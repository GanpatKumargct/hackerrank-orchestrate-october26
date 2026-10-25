"""M1 — input loader and schema validation (plan A.1.4, B.5 M1).

Every check runs before any case is processed. Errors abort with file/row/column;
warnings are returned for the run summary. Only files on config.INPUT_FILES can be
opened: the public reference answers are not reachable from here (A.1.2).
"""
import csv
import hashlib
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from . import config
from .errors import SchemaError
from .timeutil import is_strict_ts, parse_ts

CASE_ID_RE = re.compile(r"^case_\d+$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")

TIME_COLUMNS = {
    "deletion_requests.csv": ("requested_at", "reported_at", "audit_at"),
    "sample_deletion_requests.csv": ("requested_at", "reported_at", "audit_at"),
    "user_identities.csv": ("updated_at",),
    "user_audit_log.csv": ("event_time",),
    "system_activity.csv": ("event_time",),
    "evidence_files.csv": ("captured_at",),
}


@dataclass
class Dataset:
    dataset_dir: Path
    requests: list            # deletion_requests.csv rows (+ parsed times)
    sample_requests: list     # sample_deletion_requests.csv rows — unlabeled inputs
    identities: list
    audit_log: list
    activities: list
    rules: list
    manifest: list
    warnings: list = field(default_factory=list)

    def all_requests(self):
        return self.requests + self.sample_requests


def open_input(dataset_dir, name):
    """Open an allow-listed input file; anything else is refused."""
    if name not in config.INPUT_FILES:
        raise PermissionError(f"{name!r} is not on the input allow-list")
    return open(Path(dataset_dir) / name, "rb")


def _read_csv(dataset_dir, name, errors):
    with open_input(dataset_dir, name) as fh:
        raw = fh.read()
    if b"\x00" in raw:
        errors.append(f"{name}: contains NUL bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"{name}: not valid UTF-8 ({exc})")
        return []
    reader = csv.DictReader(io.StringIO(text))
    expected = config.INPUT_FILES[name]
    if tuple(reader.fieldnames or ()) != expected:
        errors.append(f"{name}: header {reader.fieldnames} != expected {list(expected)}")
        return []
    rows = []
    for n, row in enumerate(reader, start=2):
        if None in row or any(v is None for v in row.values()):
            errors.append(f"{name}:{n}: wrong number of columns")
            continue
        row["_line"] = n
        rows.append(row)
    return rows


def _check_times(name, rows, errors):
    for row in rows:
        for col in TIME_COLUMNS.get(name, ()):
            if not is_strict_ts(row[col]):
                errors.append(f"{name}:{row['_line']}:{col}: bad timestamp {row[col]!r}")
            else:
                row["_" + col] = parse_ts(row[col])


def _check_unique(name, rows, key, errors, transform=lambda v: v):
    seen = {}
    for row in rows:
        k = transform(row[key])
        if k in seen:
            errors.append(f"{name}:{row['_line']}:{key}: duplicate {row[key]!r} (first at line {seen[k]})")
        else:
            seen[k] = row["_line"]


def _check_enum(name, rows, col, allowed, errors):
    for row in rows:
        if row[col] not in allowed:
            errors.append(f"{name}:{row['_line']}:{col}: unexpected value {row[col]!r}")


def _sha(email):
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def load_dataset(dataset_dir=None):
    dataset_dir = Path(dataset_dir or config.DATASET_DIR)
    errors, warnings = [], []
    data = {name: _read_csv(dataset_dir, name, errors) for name in config.INPUT_FILES}
    if errors:                                   # header/encoding problems: stop early
        raise SchemaError(errors)
    for name, rows in data.items():
        _check_times(name, rows, errors)

    # ---- requests ----
    for name in ("deletion_requests.csv", "sample_deletion_requests.csv"):
        rows = data[name]
        _check_unique(name, rows, "case_id", errors)
        _check_enum(name, rows, "reported_status", config.REPORTED_STATUSES, errors)
        for row in rows:
            if not CASE_ID_RE.match(row["case_id"]):
                errors.append(f"{name}:{row['_line']}:case_id: bad format {row['case_id']!r}")
            if all("_" + c in row for c in ("requested_at", "reported_at", "audit_at")):
                if not (row["_requested_at"] <= row["_reported_at"] <= row["_audit_at"]):
                    errors.append(f"{name}:{row['_line']}: requested_at <= reported_at <= audit_at violated")
            row["_source"] = name

    # ---- identities ----
    ids = data["user_identities.csv"]
    _check_unique("user_identities.csv", ids, "user_id", errors)
    _check_unique("user_identities.csv", ids, "email", errors, transform=lambda v: v.strip().lower())
    user_ids = {r["user_id"] for r in ids}
    for row in ids:
        if not HASH_RE.match(row["email_hash"]):
            errors.append(f"user_identities.csv:{row['_line']}:email_hash: not 64 lowercase hex")
        elif _sha(row["email"]) != row["email_hash"]:
            row["_hash_unverified"] = True
            warnings.append(f"HASH_UNVERIFIED user_identities.csv:{row['_line']} ({row['user_id']})")

    # ---- audit log: referential + chain consistency + historical hash pairing ----
    audit = data["user_audit_log.csv"]
    _check_unique("user_audit_log.csv", audit, "audit_id", errors)
    _check_enum("user_audit_log.csv", audit, "field_name", config.AUDIT_FIELDS, errors)
    for row in audit:
        if row["user_id"] not in user_ids:
            errors.append(f"user_audit_log.csv:{row['_line']}:user_id: unknown {row['user_id']!r}")
    snapshot = {r["user_id"]: r for r in ids}
    chains = defaultdict(list)
    for row in audit:
        if "_event_time" in row:
            chains[(row["user_id"], row["field_name"])].append(row)
    norm = lambda f, v: v.strip().lower() if f != "phone" else v.strip()
    for (uid, fld), rows in chains.items():
        rows.sort(key=lambda r: r["_event_time"])
        for prev, cur in zip(rows, rows[1:]):
            if norm(fld, prev["new_value"]) != norm(fld, cur["old_value"]):
                errors.append(f"user_audit_log.csv:{cur['_line']}: chain break for {uid}/{fld}")
        if uid in snapshot and norm(fld, rows[-1]["new_value"]) != norm(fld, snapshot[uid][fld]):
            errors.append(f"user_audit_log.csv:{rows[-1]['_line']}: last {fld} change != snapshot for {uid}")
        if uid in snapshot and rows[-1]["_event_time"] > snapshot[uid]["_updated_at"]:
            warnings.append(f"user_audit_log.csv:{rows[-1]['_line']}: change after snapshot updated_at ({uid})")
    by_event = defaultdict(dict)
    for row in audit:
        by_event[(row["user_id"], row["event_time"])][row["field_name"]] = row
    for key, fields in by_event.items():
        em, hs = fields.get("email"), fields.get("email_hash")
        if em and hs:
            ok = _sha(em["old_value"]) == hs["old_value"].lower() and _sha(em["new_value"]) == hs["new_value"].lower()
            if not ok:
                for r in (em, hs):
                    r["_hash_unverified"] = True
                warnings.append(f"HASH_UNVERIFIED user_audit_log.csv:{hs['_line']} historical pair mismatch")
        elif em or hs:
            warnings.append(f"user_audit_log.csv:{(em or hs)['_line']}: email/email_hash change not paired")

    # ---- activities ----
    acts = data["system_activity.csv"]
    _check_unique("system_activity.csv", acts, "activity_id", errors)
    _check_enum("system_activity.csv", acts, "reported_result", config.REPORTED_RESULTS, errors)
    for row in acts:
        if row["event_type"] not in config.KNOWN_EVENT_TYPES:
            warnings.append(f"system_activity.csv:{row['_line']}: unknown event_type {row['event_type']!r} (uninterpreted claim)")

    # ---- rules ----
    rules = data["deletion_rules.csv"]
    _check_unique("deletion_rules.csv", rules, "rule_id", errors)
    _check_enum("deletion_rules.csv", rules, "required_action", config.REQUIRED_ACTIONS, errors)
    for row in rules:
        if row["data_category"] not in config.TREATMENTS:
            errors.append(f"deletion_rules.csv:{row['_line']}: category {row['data_category']!r} has no TREATMENTS entry")
        else:
            t = config.TREATMENTS[row["data_category"]]
            if t.source != row["rule_id"] or not t.action.startswith(row["required_action"]):
                errors.append(f"deletion_rules.csv:{row['_line']}: TREATMENTS entry for {row['data_category']} "
                              f"does not match rule {row['rule_id']}/{row['required_action']}")

    # ---- evidence manifest ----
    manifest = data["evidence_files.csv"]
    _check_unique("evidence_files.csv", manifest, "file_id", errors)
    _check_unique("evidence_files.csv", manifest, "file_path", errors)
    evidence_root = (dataset_dir / "evidence").resolve()
    listed = set()
    for row in manifest:
        rel = row["file_path"]
        if rel.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", rel):
            errors.append(f"evidence_files.csv:{row['_line']}: absolute path {rel!r}")
            continue
        full = (dataset_dir / rel).resolve()
        if evidence_root not in full.parents:
            errors.append(f"evidence_files.csv:{row['_line']}: path outside evidence/: {rel!r}")
            continue
        if not full.is_file():
            errors.append(f"evidence_files.csv:{row['_line']}: missing file {rel!r}")
            continue
        row["_path"] = full
        listed.add(full)
    if evidence_root.is_dir():
        for p in sorted(evidence_root.rglob("*")):
            if p.is_file() and p.resolve() not in listed:
                errors.append(f"evidence file not in manifest: {p.relative_to(dataset_dir).as_posix()}")
    req_times = [r["_audit_at"] for n in ("deletion_requests.csv", "sample_deletion_requests.csv")
                 for r in data[n] if "_audit_at" in r]
    req_times += [r["_requested_at"] for n in ("deletion_requests.csv", "sample_deletion_requests.csv")
                  for r in data[n] if "_requested_at" in r]
    if req_times:
        margin = timedelta(days=config.EVIDENCE_CAPTURE_MARGIN_DAYS)
        lo, hi = min(req_times) - margin, max(req_times) + margin
        for row in manifest:
            t = row.get("_captured_at")
            if t and not (lo <= t <= hi):
                warnings.append(f"evidence_files.csv:{row['_line']}: captured_at outside request window ± margin")

    if errors:
        raise SchemaError(errors)
    return Dataset(dataset_dir=dataset_dir,
                   requests=data["deletion_requests.csv"],
                   sample_requests=data["sample_deletion_requests.csv"],
                   identities=ids, audit_log=audit, activities=acts, rules=rules,
                   manifest=manifest, warnings=warnings)
