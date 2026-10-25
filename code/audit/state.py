"""M6 — resource state interpretation and policy verdicts (plan B.4, C.8, D.2–D.3, E.3; Stage 7).

Only observations admissible for state at the case cutoff are read. Activities,
reported statuses and success messages are attached as CLAIMs and never read as
state. Field values (rows, HTTP codes, result labels, flags) are interpreted only
inside an admissible observation that names the resource. A COMPLIANT verdict
needs one admissible observation that proves the whole required state
(Q-SPLIT-PROOF); otherwise the verdict is UNKNOWN with a reason. No case-level
decisions are made here.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from . import config
from .admissibility import admissible_claim, admissible_for_state, is_late_link_only, time_of
from .errors import HeldReason, ReportNote, UncertaintyReason as U
from .evidence.normalize import classify_value, extract_free_text, is_cleared
from .policy import classify, evaluate_condition
from .timeutil import try_parse_ts

COMPLIANT, VIOLATION, UNKNOWN = "COMPLIANT_PROVEN", "VIOLATION_PROVEN", "UNKNOWN"
PRESENT_RESULTS = {"found", "hit", "identifiable", "anonymized", "redacted", "active", "disabled", "blocked"}
ABSENT_RESULTS = {"not_found", "miss"}
TRUE_VALUES, FALSE_VALUES = {"true", "1"}, {"false", "0"}
Q1, Q2, Q3 = 1, 2, 3            # E.3.1 evidence quality (lower is stronger)


@dataclass(frozen=True)
class Reading:
    dimension: str              # existence | flow | restore
    value: str
    copy: str
    time: object
    quality: int
    source: str                 # obs_id, or "coverage:<file_id>:<locator>" for omission
    file_id: str
    detail: str = ""


@dataclass(frozen=True)
class DimensionResult:
    value: str                  # PRESENT/ABSENT, ENABLED/DISABLED, RESTORABLE/BLOCKED, EXPOSED/CLEAN, UNKNOWN
    proof: tuple                # readings / obs_ids that prove the value (one source when single-proof)
    reason: Optional[str] = None
    notes: tuple = ()


@dataclass
class ResourceAssessment:
    resource_id: str
    owner: object                           # OwnerResolution
    category: object                        # CategoryConclusion
    condition: object = None                # ConditionResult
    dimensions: dict = field(default_factory=dict)
    verdict: str = UNKNOWN
    reasons: tuple = ()
    proof: tuple = ()                       # sources proving the verdict (single source when COMPLIANT)
    expressible: bool = True                # a finding operation exists for a violation
    claims: tuple = ()                      # activity ids (never proof)
    admissible: tuple = ()                  # obs_ids admissible for state
    notes: tuple = ()


def _low(v):
    return str(v).strip().lower() if v is not None else ""


# --------------------------------------------------------------------------- #
# Readings from one observation
# --------------------------------------------------------------------------- #
def existence_reading(o):
    f = o.fields
    copy = o.copy_location or "primary"
    mk = lambda value, q, d: Reading("existence", value, copy, time_of(o), q, o.obs_id, o.file_id, d)
    if "rows" in f and _low(f["rows"]).isdigit():
        return mk("PRESENT" if int(f["rows"]) >= 1 else "ABSENT", Q2, f"rows={f['rows']}")
    for k in ("http_status", "status_code"):
        if k in f and _low(f[k]) in ("200", "404"):
            return mk("PRESENT" if _low(f[k]) == "200" else "ABSENT", Q2, f"{k}={f[k]}")
    if "result" in f:
        r = _low(f["result"])
        if r in PRESENT_RESULTS:
            return mk("PRESENT", Q2, f"result={f['result']}")
        if r in ABSENT_RESULTS:
            return mk("ABSENT", Q2, f"result={f['result']}")
    for k in ("hits.total", "total_hits"):
        if k in f and _low(f[k]).isdigit():
            return mk("PRESENT" if int(f[k]) > 0 else "ABSENT", Q3, f"{k}={f[k]}")
    event = o.context.get("event") or ""
    if o.source_format == "log" and event and not event.endswith("_completed"):
        return mk("PRESENT", Q3, f"event {event} names the resource")       # scans, heartbeats, checks
    return mk("PRESENT", Q1, "record content observed")                     # row / record / document


def flag_reading(o, category):
    f = o.fields
    t = time_of(o)
    out = []
    if category == "DATA_FLOW":
        if "enabled" in f and _low(f["enabled"]) in TRUE_VALUES | FALSE_VALUES:
            out.append(Reading("flow", "ENABLED" if _low(f["enabled"]) in TRUE_VALUES else "DISABLED",
                               "-", t, Q1, o.obs_id, o.file_id, f"enabled={f['enabled']}"))
        elif _low(f.get("result")) in ("active", "disabled"):
            out.append(Reading("flow", "ENABLED" if _low(f["result"]) == "active" else "DISABLED",
                               "-", t, Q2, o.obs_id, o.file_id, f"result={f['result']}"))
    if category == "BACKUP_ARCHIVE":
        vals = set()
        if "restore_allowed" in f and _low(f["restore_allowed"]) in TRUE_VALUES | FALSE_VALUES:
            vals.add("RESTORABLE" if _low(f["restore_allowed"]) in TRUE_VALUES else "BLOCKED")
        if _low(f.get("deletion_block")) == "true":
            vals.add("BLOCKED")
        elif _low(f.get("eligible")) == "true" and _low(f.get("deletion_block")) == "false":
            vals.add("RESTORABLE")
        if _low(f.get("result")) in ("active", "blocked"):
            vals.add("RESTORABLE" if _low(f["result"]) == "active" else "BLOCKED")
        if len(vals) == 1:
            out.append(Reading("restore", vals.pop(), "-", t, Q1, o.obs_id, o.file_id, "restore signals"))
        elif len(vals) > 1:
            out.append(Reading("restore", "CONFLICT", "-", t, Q1, o.obs_id, o.file_id,
                               "contradictory restore signals in one observation"))
    return out


def pii_slots(o, category, subject_user, resolver):
    """Slot states for one observation: POPULATED_SUBJECT | POPULATED_OTHER | CLEARED | NOT_OBSERVED."""
    spec = config.PII_SLOTS.get(category, {})
    when = time_of(o)
    states = {}
    for slot, names in spec.items():
        present = [n for n in names if n in o.fields]
        if not present:
            states[slot] = "NOT_OBSERVED"
            continue
        vals = [o.fields[n] for n in present]
        if all(is_cleared(v) for v in vals):
            states[slot] = "CLEARED"
            continue
        states[slot] = _attribute_values([v for v in vals if not is_cleared(v)], when, subject_user, resolver)
    extras = []                      # exposure-only evidence: free text and PII scans
    for k in ("message_text", "message_excerpt", "visible_text"):
        if k in o.fields:
            for kind, raw, norm in extract_free_text(o.fields[k]):
                if _owner_of(kind, norm, when, resolver) == subject_user:
                    extras.append(f"{k} mentions subject")
    if o.fields.get("subject") and _low(o.fields.get("result")) == "identifiable":
        # handover identifier column: field evidence of exposure, not a bare label
        if _attribute_values([o.fields["subject"]], when, subject_user, resolver) == "POPULATED_SUBJECT":
            extras.append("identifier column holds subject identifier (IDENTIFIABLE)")
    if o.fields.get("detector") and o.fields.get("matched_value"):
        if _attribute_values([o.fields["matched_value"]], when, subject_user, resolver) == "POPULATED_SUBJECT":
            extras.append("pii scan matched subject identifier")
    return states, extras


def _owner_of(kind, norm, when, resolver):
    from .models import IdentifierHit
    att = resolver.attribute(IdentifierHit(kind, norm, norm, "", "RECORD_FIELD", ""), when)
    return att.user_id if att.status == "ATTRIBUTED" else None


def _attribute_values(values, when, subject_user, resolver):
    owners = set()
    for v in values:
        c = classify_value(v)
        if c and c[1] is not None:
            owners.add(_owner_of(c[0], c[1], when, resolver))
        else:
            owners.add(None)        # populated but not attributable (e.g. a name)
    if subject_user in owners:
        return "POPULATED_SUBJECT"
    return "POPULATED_OTHER" if owners - {None} else "POPULATED_UNATTRIBUTED"


# --------------------------------------------------------------------------- #
# Dimension resolution (E.3.1)
# --------------------------------------------------------------------------- #
def _latest(readings):
    """Latest value of one copy/dimension with E.3.1 conflict handling."""
    if not readings:
        return None, (), None, ()
    t = max(r.time for r in readings)
    at = [r for r in readings if r.time == t]
    values = {r.value for r in at}
    if len(values) == 1 and "CONFLICT" not in values:
        return at[0].value, tuple(sorted(at, key=lambda r: (r.quality, r.source))), None, ()
    best_q = min(r.quality for r in at)
    best = {r.value for r in at if r.quality == best_q}
    worse = [r for r in at if r.quality > best_q]
    if len(best) == 1 and "CONFLICT" not in best and worse:
        proof = tuple(r for r in at if r.quality == best_q)
        return next(iter(best)), proof, None, (ReportNote.RESOLVED_BY_QUALITY,)
    return "CONFLICT", tuple(at), U.CONFLICTING_OBSERVATIONS, ()


def file_subjects(file_id, index, resolver, cache):
    """Users whose identifiers appear in a file (scope of a subject-scoped extract)."""
    if file_id not in cache:
        users = set()
        for o in index.by_file(file_id):
            for h in o.identifiers:
                att = resolver.attribute(h, time_of(o))
                if att.status == "ATTRIBUTED":
                    users.add(att.user_id)
        cache[file_id] = frozenset(users)
    return cache[file_id]


def omission_readings(resource_id, category, owner_system, index, audit_at, capture_map,
                      subject_user=None, resolver=None, scope_cache=None):
    """C.8.2: coverage-first, then recency; ABSENT readings for the covered copies.

    Direct SQL tables are complete table dumps. Bundle snapshots and inventory
    extracts are subject-scoped (they hold a few subjects' records), so their
    omission only speaks for subjects that appear in the same file (C.8.3).
    """
    if owner_system is None:
        return []
    units = []
    for coll in config.CATEGORY_COLLECTIONS.get(category, ()):
        for u in index.coverage(owner_system, coll):
            rep = index.reports.get(u.file_id)
            if rep is None or rep.status != "OK":
                continue                                          # incomplete files never prove absence
            cap = capture_map.get(u.file_id)                       # manifest capture time
            if cap is None:
                continue
            when = try_parse_ts(u.observed_raw) if u.observed_raw else cap
            if cap > audit_at or when > audit_at:
                continue
            if not u.locator.startswith("table:"):
                if resolver is None or subject_user not in file_subjects(u.file_id, index, resolver,
                                                                         scope_cache if scope_cache is not None else {}):
                    continue
            units.append((u, when, cap))
    if not units:
        return []
    level = "COLLECTION" if any(u.level == "COLLECTION" for u, _, _ in units) else "SYSTEM"
    cand = [x for x in units if x[0].level == level]
    best_u, when, cap = max(cand, key=lambda x: (x[1], x[2], x[0].file_id))
    same_file = [x for x in cand if x[0].file_id == best_u.file_id and x[1] == when]
    if any(resource_id in u.resource_ids for u, _, _ in same_file):
        return []                                                  # present rows are read as observations
    return [Reading("existence", "ABSENT", u.copy, w, Q3, f"coverage:{u.file_id}:{u.locator}", u.file_id,
                    f"omitted from {u.level.lower()}-level snapshot {u.collection}/{u.copy}")
            for u, w, _ in same_file]


def resolve_existence(readings):
    by_copy = defaultdict(list)
    for r in readings:
        by_copy[r.copy].append(r)
    if not by_copy:
        return DimensionResult(UNKNOWN, (), U.NO_ADMISSIBLE_OBSERVATION)
    latest, notes = {}, []
    for copy, rs in sorted(by_copy.items()):
        value, proof, reason, n = _latest(rs)
        latest[copy] = (value, proof)
        notes.extend(n)
    present = [(c, p) for c, (v, p) in latest.items() if v == "PRESENT"]
    if present:
        c, p = sorted(present)[0]
        return DimensionResult("PRESENT", (p[0],), None, tuple(notes) + tuple(f"present in copy {x}" for x, _ in present))
    if any(v == "CONFLICT" for v, _ in latest.values()):
        return DimensionResult(UNKNOWN, tuple(r for _, p in latest.values() for r in p), U.CONFLICTING_OBSERVATIONS)
    sources = {p[0].source if not p[0].source.startswith("coverage:") else p[0].file_id
               for _, p in latest.values()}
    if len(sources) == 1:
        return DimensionResult("ABSENT", tuple(p[0] for _, p in latest.values())[:1], None,
                               tuple(notes) + tuple(f"absent in copy {c}" for c in sorted(latest)))
    return DimensionResult(UNKNOWN, tuple(p[0] for _, p in latest.values()), U.PROOF_NOT_SINGLE_OBSERVATION,
                           ("each copy's absence is proven by a different observation",))


def resolve_flag(readings):
    if not readings:
        return DimensionResult(UNKNOWN, (), U.NO_ADMISSIBLE_OBSERVATION)
    value, proof, reason, notes = _latest(readings)
    if value == "CONFLICT":
        return DimensionResult(UNKNOWN, proof, U.CONFLICTING_OBSERVATIONS)
    return DimensionResult(value, proof[:1], None, notes)


def resolve_pii(observations, category, subject_user, resolver):
    """D.3.3 / D.3.8: EXPOSED, CLEAN (single observation), or UNKNOWN with a reason."""
    spec = config.PII_SLOTS.get(category, {})
    exposures, clears, partial, labels, other = [], [], [], [], []
    for o in observations:
        states, extras = pii_slots(o, category, subject_user, resolver)
        t = time_of(o)
        if any(s == "POPULATED_SUBJECT" for s in states.values()) or extras:
            exposures.append((t, o.obs_id))
            continue
        observed = {k: s for k, s in states.items() if s != "NOT_OBSERVED"}
        label = _low(o.fields.get("result"))
        subj_text = _low(o.fields.get("subject"))
        if not observed:
            if category in ("ANALYTICS_PROFILE", "PRODUCT_TELEMETRY") and label == "anonymized" \
                    and subj_text == "no direct identifier":
                clears.append((t, o.obs_id, "handover states no direct identifier [ASSUMPTION d]"))
            elif label in ("anonymized", "redacted", "identifiable"):
                labels.append((t, o.obs_id))
            continue
        if any(s in ("POPULATED_OTHER", "POPULATED_UNATTRIBUTED") for s in observed.values()):
            other.append((t, o.obs_id))
            continue
        if category == "ACCOUNT_TOMBSTONE":
            ref = o.fields.get(config.TOMBSTONE_REFERENCE_FIELD)
            if len(observed) == len(spec) and is_cleared(ref) and config.TOMBSTONE_REFERENCE_FIELD in o.fields:
                return DimensionResult("REFERENCE_MISSING", (o.obs_id,), None, ("stable reference cleared",))
        if len(observed) == len(spec):
            clears.append((t, o.obs_id, "all required slots cleared"))
        else:
            partial.append((t, o.obs_id, frozenset(observed)))
    last_exp = max(exposures) if exposures else None
    last_clear = max(clears) if clears else None
    if last_exp and (not last_clear or last_exp[0] > last_clear[0]):
        return DimensionResult("EXPOSED", (last_exp[1],))
    if last_exp and last_clear and last_exp[0] == last_clear[0]:
        return DimensionResult(UNKNOWN, (last_exp[1], last_clear[1]), U.CONFLICTING_OBSERVATIONS)
    if last_clear:
        later_other = [x for x in other if x[0] > last_clear[0]]
        if later_other:
            return DimensionResult(UNKNOWN, (later_other[-1][1],), U.CONFLICTING_OBSERVATIONS,
                                   ("later observation holds another value",))
        return DimensionResult("CLEAN", (last_clear[1],), None, (last_clear[2],))
    if partial:
        covered = frozenset().union(*(p[2] for p in partial))
        if len(covered) == len(spec):
            return DimensionResult(UNKNOWN, tuple(p[1] for p in partial), U.PROOF_NOT_SINGLE_OBSERVATION)
        return DimensionResult(UNKNOWN, tuple(p[1] for p in partial), U.FIELD_COVERAGE_INCOMPLETE,
                               (f"missing slots {sorted(set(spec) - covered)}",))
    if other:
        return DimensionResult(UNKNOWN, tuple(x[1] for x in other), U.CONFLICTING_OBSERVATIONS,
                               ("identifier slots hold values not attributable to the subject",))
    if labels:
        return DimensionResult(UNKNOWN, tuple(x[1] for x in labels), U.LABEL_ONLY)
    return DimensionResult(UNKNOWN, (), U.FIELD_COVERAGE_INCOMPLETE, ("no identifier slot observed",))


def resolve_retention(observations, existence, category, audit_at):
    """Rules 12/13: presence and the retention date must come from one observation."""
    key = "retention_until" if category == "SECURITY_AUDIT_LOG" else "retained_until"
    if existence.value == "ABSENT":
        return DimensionResult("RECORD_MISSING", existence.proof, None)
    if existence.value != "PRESENT":
        return DimensionResult(UNKNOWN, existence.proof, existence.reason)
    with_date = [o for o in observations if try_parse_ts(o.fields.get(key)) is not None
                 and existence_reading(o).value == "PRESENT"]
    if with_date:
        o = max(with_date, key=lambda o: (time_of(o), o.obs_id))
        if try_parse_ts(o.fields[key]) > audit_at:
            return DimensionResult("RETAINED", (o.obs_id,), None, (f"{key}={o.fields[key]}",))
        return DimensionResult(UNKNOWN, (o.obs_id,), U.POLICY_GAP, (f"{key} expired at cutoff",))
    if any(try_parse_ts(o.fields.get(key)) for o in observations):
        return DimensionResult(UNKNOWN, (), U.PROOF_NOT_SINGLE_OBSERVATION)
    return DimensionResult(UNKNOWN, existence.proof, U.CONDITION_UNKNOWN, (f"{key} not observed",))


# --------------------------------------------------------------------------- #
# Assessment
# --------------------------------------------------------------------------- #
def assess(resource_id, audit_at, subject_user, index, resolver, activities, capture_map, scope_cache=None):
    all_obs = index.by_resource(resource_id)
    obs = [o for o in all_obs if admissible_for_state(o, audit_at)]
    claims = [a for a in activities if a["resource_id"] == resource_id and admissible_claim(a, audit_at)]
    owner = index.owner(resource_id)
    cat = classify(resource_id, obs, claims)
    a = ResourceAssessment(resource_id, owner, cat, claims=tuple(x["activity_id"] for x in claims),
                           admissible=tuple(o.obs_id for o in obs))
    if not obs:
        reason = U.NO_ADMISSIBLE_OBSERVATION
        if any(is_late_link_only(o, audit_at, True) or o.file_captured_at > audit_at for o in all_obs):
            reason = U.POST_CUTOFF_ONLY
        elif any("observed_after_capture" in o.anomalies for o in all_obs):
            reason = U.OBSERVED_AFTER_CAPTURE
        notes = (U.CLAIMS_ONLY.value,) if claims else ()
        a.reasons, a.notes = (reason,), notes
        return a
    if cat.value is None:
        a.reasons = (cat.reason,)
        return a
    category = cat.value
    treat = config.TREATMENTS[category]
    a.condition = evaluate_condition(category, obs, subject_user, resolver)
    ex_readings = [existence_reading(o) for o in obs]
    omitted = omission_readings(resource_id, category, owner.system_id, index, audit_at, capture_map,
                                subject_user, resolver, scope_cache)
    if config.COPY_SCOPE == "resource":
        # only copies this resource was observed in (plus primary) — C.8.2 Stage 7 proposal
        known = {r.copy for r in ex_readings} | {"primary"}
        omitted = [r for r in omitted if r.copy in known]
    ex_readings += omitted
    existence = resolve_existence(ex_readings)
    a.dimensions["existence"] = existence

    if a.condition.value == "FALSE":
        a.reasons = (U.POLICY_GAP,)
        return a
    if a.condition.value == "UNKNOWN":
        a.reasons = (U.CONDITION_UNKNOWN,)
        return a

    action = treat.action
    if action == "DELETE":
        _from_dimension(a, existence, violation="PRESENT", compliant="ABSENT")
    elif action in ("REDACT", "ANONYMIZE"):
        if existence.value == "ABSENT":
            _set(a, COMPLIANT, existence.proof)
        else:
            pii = resolve_pii(obs, category, subject_user, resolver)
            a.dimensions["pii_exposure"] = pii
            if pii.value == "REFERENCE_MISSING":
                _set(a, VIOLATION, pii.proof, (HeldReason.RETAINED_RECORD_MISSING,), expressible=False)
            elif pii.value == "EXPOSED":
                _set(a, VIOLATION, pii.proof)
            elif pii.value == "CLEAN":
                _set(a, COMPLIANT, pii.proof)
            else:
                a.reasons = (pii.reason,)
    elif action == "RETAIN":
        ret = resolve_retention(obs, existence, category, audit_at)
        a.dimensions["retention"] = ret
        if ret.value == "RETAINED":
            _set(a, COMPLIANT, ret.proof)
        elif ret.value == "RECORD_MISSING":
            _set(a, VIOLATION, ret.proof, (HeldReason.RETAINED_RECORD_MISSING,), expressible=False)
        else:
            a.reasons = (ret.reason,)
    elif action == "RETAIN_BLOCK_RESTORE":
        if existence.value == "ABSENT":
            _set(a, VIOLATION, existence.proof, (HeldReason.RETAINED_RECORD_MISSING,), expressible=False)
        else:
            restore = resolve_flag([r for o in obs for r in flag_reading(o, category)])
            a.dimensions["restore"] = restore
            _from_dimension(a, restore, violation="RESTORABLE", compliant="BLOCKED")
    elif action == "DISABLE":
        flow = resolve_flag([r for o in obs for r in flag_reading(o, category)])
        a.dimensions["flow"] = flow
        if flow.value == UNKNOWN and existence.value == "ABSENT":
            _set(a, COMPLIANT, existence.proof)
        else:
            _from_dimension(a, flow, violation="ENABLED", compliant="DISABLED")
    else:
        a.reasons = (U.POLICY_GAP,)
    return a


def _proof_ids(proof):
    return tuple(p.source if isinstance(p, Reading) else p for p in proof)


def _set(a, verdict, proof, reasons=(), expressible=True):
    a.verdict, a.proof, a.reasons, a.expressible = verdict, _proof_ids(proof), tuple(reasons), expressible


def _from_dimension(a, dim, violation, compliant):
    if dim.value == violation:
        _set(a, VIOLATION, dim.proof)
    elif dim.value == compliant:
        _set(a, COMPLIANT, dim.proof)
    else:
        a.reasons = (dim.reason or U.NO_ADMISSIBLE_OBSERVATION,)
