"""Synthetic, fictional fixtures (example.org, user_9xxx). Never copies dataset rows."""
import csv
import hashlib
import shutil
import tempfile
from pathlib import Path

from audit import config
from audit.timeutil import parse_ts


def sha(email):
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def manifest_row(path, file_id="evidence_x", captured="2026-05-10T12:00:00Z"):
    path = Path(path)
    return {"file_id": file_id, "file_path": f"evidence/{path.name}", "origin": "test",
            "captured_at": captured, "_captured_at": parse_ts(captured), "_path": path}


class TempDir:
    def __enter__(self):
        self.path = Path(tempfile.mkdtemp(prefix="audit_test_"))
        return self.path

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)


def write_file(directory, name, text):
    p = Path(directory) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        for r in rows:
            w.writerow([r[h] for h in header])


def minimal_dataset(root, mutate=None):
    """A small valid dataset; `mutate(tables)` may alter rows before writing."""
    ds = Path(root) / "dataset"
    (ds / "evidence" / "logs").mkdir(parents=True)
    write_file(ds / "evidence" / "logs", "a.log",
               "2026-05-09T10:00:00Z level=INFO service=account_service trace_id=t1 "
               "event=profile_lookup_completed resource_id=account_90001 rows=0\n")
    old, new = "old.fx@example.org", "new.fx@example.org"
    req = dict(case_id="case_900", email=old, requested_at="2026-05-01T10:00:00Z",
               reported_status="COMPLETE", reported_at="2026-05-02T10:00:00Z",
               audit_at="2026-05-10T12:00:00Z", request_text="Please delete my account.")
    tables = {
        "deletion_requests.csv": [req],
        "sample_deletion_requests.csv": [dict(req, case_id="case_901")],
        "user_identities.csv": [dict(user_id="user_9001", name="Fx Person", email=new,
                                     phone="+44 20 0000 0001", email_hash=sha(new),
                                     updated_at="2026-02-01T00:00:00Z")],
        "user_audit_log.csv": [
            dict(audit_id="audit_9001", user_id="user_9001", event_time="2026-01-10T00:00:00Z",
                 field_name="email", old_value=old, new_value=new),
            dict(audit_id="audit_9002", user_id="user_9001", event_time="2026-01-10T00:00:00Z",
                 field_name="email_hash", old_value=sha(old), new_value=sha(new)),
        ],
        "system_activity.csv": [dict(activity_id="activity_9001", event_time="2026-05-02T09:00:00Z",
                                     event_type="DELETE_RECORD", source_system="deletion_worker",
                                     target_system="account_service", resource_id="account_90001",
                                     reported_result="FAILED", details="test")],
        "deletion_rules.csv": [dict(rule_id=t.source, data_category=c, condition="Always",
                                    required_action=t.action.split("_")[0])
                               for c, t in config.TREATMENTS.items() if t.source != "SUPPLEMENTAL"],
        "evidence_files.csv": [dict(file_id="evidence_9001", file_path="evidence/logs/a.log",
                                    origin="test", captured_at="2026-05-09T12:00:00Z")],
    }
    if mutate:
        mutate(tables)
    for name, rows in tables.items():
        _write_csv(ds / name, config.INPUT_FILES[name], rows)
    return ds
