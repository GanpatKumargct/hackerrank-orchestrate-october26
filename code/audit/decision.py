"""M7/M8 — case sets, completeness gate and step construction (plan E.4–E.6, F.1–F.2; Stage 8).

Consumes the Stage 6 scope and Stage 7 assessments; adds no evidence rules.
A case is either emitted (COMPLETE / INCOMPLETE / NOT_APPLICABLE with steps) or
held with a reason (E.4.3). Held cases are never turned into rows; writing
output.csv, the held report and the full L1–L4 validator are Stage 9.
"""
from dataclasses import dataclass, field

from . import config
from .errors import HeldReason as H
from .identity import Subject
from .intent import DELETION, NON_DELETION, classify_intent
from .state import COMPLIANT, UNKNOWN, VIOLATION, assess

EMIT, HOLD = "EMIT", "HOLD"
PRIMARY_ACCOUNT_SLOT = "PRIMARY_ACCOUNT_SLOT"
CITATION_STATE_MISMATCH = "CITATION_STATE_MISMATCH"


class StepBuildError(Exception):
    """F.1.1 invariant broken; the case is held (VALIDATION_FAILED or SYSTEM_AMBIGUOUS)."""

    def __init__(self, reason, detail):
        self.reason, self.detail = reason, detail
        super().__init__(f"{reason}: {detail}")


@dataclass
class CaseSets:
    req: tuple = ()                                   # resources with a required final state (E.4.1)
    proven_ok: tuple = ()
    violating: tuple = ()
    unexpressible: tuple = ()
    unresolved: dict = field(default_factory=dict)    # rid (or PRIMARY_ACCOUNT_SLOT) -> reason codes
    wf_violating: tuple = ()
    primary: tuple = ()                               # in-scope USER_PROFILE resources of the subject


@dataclass
class CaseResult:
    case_id: str
    source: str
    outcome: str                                      # EMIT | HOLD
    status: object = None                             # COMPLETE | INCOMPLETE | NOT_APPLICABLE (EMIT only)
    steps: tuple = ()
    held: tuple = ()                                  # HeldReason codes (HOLD only)
    detail: tuple = ()                                # (resource_id, reason) pairs or messages
    intent: object = None
    sets: object = None
    assessments: dict = field(default_factory=dict)
    notes: tuple = ()
    scope: object = None                              # CaseScope (L3/L4 run-level validation, Stage 9)
    audit_at: object = None


# --------------------------------------------------------------------------- #
# Sets (E.4.1)
# --------------------------------------------------------------------------- #
def build_sets(assessments, wf_assessments):
    s = CaseSets()
    req, ok, bad, unexp, unres, primary = [], [], [], [], {}, []
    for rid in sorted(assessments):
        a = assessments[rid]
        if a.category.value is None:
            unres[rid] = tuple(_codes(a.reasons) or (a.category.reason,))
            continue
        req.append(rid)
        if a.category.value == "USER_PROFILE":
            primary.append(rid)
        if a.verdict == COMPLIANT and a.proof:
            ok.append(rid)
        elif a.verdict == VIOLATION and a.expressible:
            bad.append(rid)
        elif a.verdict == VIOLATION:
            unexp.append(rid)
        else:
            unres[rid] = tuple(_codes(a.reasons)) or (UNKNOWN,)
    if not primary:
        unres[PRIMARY_ACCOUNT_SLOT] = ("NO_IN_SCOPE_USER_PROFILE",)
    s.req, s.proven_ok, s.violating, s.unexpressible = tuple(req), tuple(ok), tuple(bad), tuple(unexp)
    s.unresolved, s.primary = unres, tuple(primary)
    s.wf_violating = tuple(sorted(r for r, a in wf_assessments.items() if a.verdict == VIOLATION))
    return s


def _codes(reasons):
    return tuple(getattr(r, "value", r) for r in reasons)


# --------------------------------------------------------------------------- #
# Gate (E.4.2)
# --------------------------------------------------------------------------- #
def decide(intent_value, sets):
    """Return (EMIT, status) or (HOLD, HeldReason, detail)."""
    if intent_value == NON_DELETION:
        return EMIT, "NOT_APPLICABLE", ()
    if intent_value != DELETION:
        return HOLD, H.UNSURE_INTENT, ()
    if sets.unexpressible:
        return HOLD, H.RETAINED_RECORD_MISSING, tuple((r, H.RETAINED_RECORD_MISSING.value) for r in sets.unexpressible)
    unresolved = tuple((r, c) for r, cs in sorted(sets.unresolved.items()) for c in cs)
    if sets.violating:
        if sets.unresolved:
            return HOLD, H.VERIFICATION_SET_INCOMPLETE, unresolved
        return EMIT, "INCOMPLETE", ()
    if sets.wf_violating:
        return HOLD, H.REQUIRED_RESOURCE_UNRESOLVED, tuple((r, "WORKFLOW_CANDIDATE_VIOLATION")
                                                           for r in sets.wf_violating)
    if sets.unresolved:
        return HOLD, H.REQUIRED_RESOURCE_UNRESOLVED, unresolved
    if set(sets.req) == set(sets.proven_ok) and sets.req:
        return EMIT, "COMPLETE", ()
    return HOLD, H.INTERNAL_INCONSISTENCY, ()


# --------------------------------------------------------------------------- #
# Steps (F.1–F.2)
# --------------------------------------------------------------------------- #
def citation_file(source, index):
    """file_id of a proof source: an obs_id or a C.8 omission coverage reference."""
    if source.startswith("coverage:"):
        return source.split(":", 2)[1]
    return index.get(source).file_id


def _step(op, system_id, resource_id, evidence_id):
    return {"step_no": 0, "phase": config.OP_PHASE[op], "system_id": system_id, "resource_id": resource_id,
            "operation": op, "state": config.OP_STATE[op], "evidence_id": evidence_id}


def _cite(a, index, audit_at, capture_map):
    if len(a.proof) != 1:
        raise StepBuildError(H.VALIDATION_FAILED, f"{a.resource_id}: proof is not a single observation")
    fid = citation_file(a.proof[0], index)
    cap = capture_map.get(fid)
    if cap is None or cap > audit_at:
        raise StepBuildError(H.VALIDATION_FAILED, f"{a.resource_id}: citation {fid} not admissible at cutoff")
    return fid


def _proof_is_absence(a):
    ex = a.dimensions.get("existence")
    return ex is not None and ex.value == "ABSENT" and tuple(a.proof) == tuple(
        p.source if hasattr(p, "source") else p for p in ex.proof)


def build_steps(status, sets, assessments, index, audit_at, capture_map):
    """Ordered, numbered steps for an emitted COMPLETE / INCOMPLETE case (F.1.1–F.1.4)."""
    if status == "NOT_APPLICABLE":
        return []
    steps = []
    for rid in sets.req:
        a = assessments[rid]
        if a.owner.system_id is None:
            raise StepBuildError(H.SYSTEM_AMBIGUOUS, rid)
    for rid in sets.req:
        a = assessments[rid]
        treat = config.TREATMENTS[a.category.value]
        system = a.owner.system_id
        if status == "COMPLETE":
            if a.verdict != COMPLIANT:
                raise StepBuildError(H.VALIDATION_FAILED, f"{rid}: COMPLETE member not proven compliant")
            # Q-ABSENT-NONDELETE-VERIFY: VERIFY_RECORD_ABSENT only for a DELETE end state proven by
            # one absence observation; an absence proof never stands for another end state (F.2.1 check 5)
            if (treat.verification == "VERIFY_RECORD_ABSENT") != _proof_is_absence(a):
                raise StepBuildError(H.VALIDATION_FAILED, f"{rid}: {CITATION_STATE_MISMATCH}")
            steps.append(_step(treat.verification, system, rid, _cite(a, index, audit_at, capture_map)))
            continue
        if rid in sets.violating:
            if treat.finding is None or treat.remediation is None:
                raise StepBuildError(H.VALIDATION_FAILED, f"{rid}: no finding/remediation for {a.category.value}")
            if treat.remediation == "DELETE_RECORD" and a.category.value in config.NEVER_DELETE:
                raise StepBuildError(H.VALIDATION_FAILED, f"{rid}: DELETE prohibited for {a.category.value}")
            steps.append(_step(treat.finding, system, rid, _cite(a, index, audit_at, capture_map)))
            steps.append(_step(treat.remediation, system, rid, ""))
        steps.append(_step(treat.verification, system, rid, ""))
    steps.sort(key=lambda s: (config.OP_INDEX[s["operation"]], s["system_id"], s["resource_id"]))
    for i, s in enumerate(steps, 1):
        s["step_no"] = i
    errors = validate_steps(status, steps, set(capture_map), audit_at, capture_map)
    if errors:
        raise StepBuildError(H.VALIDATION_FAILED, "; ".join(errors))
    return steps


def validate_steps(status, steps, file_ids, audit_at=None, capture_map=None):
    """Per-case output schema checks (F.4 L1.5–L1.8, L2.1–L2.6). Returns a list of errors."""
    errs = []
    if status not in config.STATUSES:
        errs.append(f"status {status!r} not permitted")
    if status == "NOT_APPLICABLE":
        return errs + (["NOT_APPLICABLE must have []"] if steps else [])
    if not steps:
        errs.append(f"{status} with no steps")
    keys_seen = set()
    for i, s in enumerate(steps, 1):
        if not isinstance(s, dict) or tuple(sorted(s)) != tuple(sorted(config.STEP_KEYS)):
            errs.append(f"step {i}: keys must be exactly {config.STEP_KEYS}")
            continue
        if type(s["step_no"]) is not int or s["step_no"] != i:
            errs.append(f"step {i}: step_no {s['step_no']!r} not consecutive")
        if any(not isinstance(s[k], str) for k in config.STEP_KEYS if k != "step_no"):
            errs.append(f"step {i}: non-string field")
            continue
        op = s["operation"]
        if op not in config.OP_INDEX:
            errs.append(f"step {i}: unknown operation {op}")
            continue
        if s["phase"] != config.OP_PHASE[op] or s["state"] != config.OP_STATE[op]:
            errs.append(f"step {i}: phase/state do not match {op}")
        k = (op, s["system_id"], s["resource_id"])
        if k in keys_seen:
            errs.append(f"step {i}: duplicate {k}")
        keys_seen.add(k)
        ev = s["evidence_id"]
        if status == "COMPLETE":
            if s["phase"] != "VERIFICATION":
                errs.append(f"step {i}: COMPLETE may contain only VERIFICATION")
            if not ev:
                errs.append(f"step {i}: COMPLETE verification without evidence")
        if status == "INCOMPLETE":
            if s["phase"] == "FINDING" and not ev:
                errs.append(f"step {i}: FINDING without evidence")
            if s["phase"] != "FINDING" and ev:
                errs.append(f"step {i}: {s['phase']} must have empty evidence_id")
        if ev:
            if ev not in file_ids:
                errs.append(f"step {i}: evidence_id {ev} is not a manifest file_id")
            elif capture_map is not None and audit_at is not None and capture_map[ev] > audit_at:
                errs.append(f"step {i}: evidence {ev} captured after audit_at")
    order = [(config.OP_INDEX.get(s.get("operation"), -1), s.get("system_id"), s.get("resource_id"))
             for s in steps if isinstance(s, dict)]
    if order != sorted(order):
        errs.append("steps not in (operation, system_id, resource_id) order")
    if status == "INCOMPLETE" and not any(isinstance(s, dict) and s.get("phase") == "FINDING" for s in steps):
        errs.append("INCOMPLETE without a FINDING")
    return errs


# --------------------------------------------------------------------------- #
# Per-case procedure (E.6)
# --------------------------------------------------------------------------- #
class CaseAnalyzer:
    def __init__(self, dataset, index, resolver, builder):
        self.ds, self.index, self.resolver, self.builder = dataset, index, resolver, builder
        self.capture = {m["file_id"]: m["_captured_at"] for m in dataset.manifest}
        self.acts = {}
        for a in dataset.activities:
            self.acts.setdefault(a["resource_id"], []).append(a)
        self.scope_cache = {}

    def _assess(self, rid, req, user_id):
        return assess(rid, req["_audit_at"], user_id, self.index, self.resolver, self.acts.get(rid, []),
                      self.capture, self.scope_cache)

    def analyze(self, req):
        intent = classify_intent(req["request_text"])
        base = dict(case_id=req["case_id"], source=req["_source"], intent=intent, audit_at=req["_audit_at"])
        try:
            scope = self.builder.build(req)
            base["scope"] = scope
            if not isinstance(scope.subject, Subject):                  # E.2.1
                if intent.value == NON_DELETION:
                    return CaseResult(outcome=EMIT, status="NOT_APPLICABLE", **base)
                return CaseResult(outcome=HOLD, held=(scope.subject.reason,), **base)
            user = scope.subject.user_id
            assessments = {rid: self._assess(rid, req, user) for rid in sorted(scope.included)}
            wf = {rid: self._assess(rid, req, user) for rid in sorted(scope.workflow_candidates)}
            sets = build_sets(assessments, wf)
            verdict = decide(intent.value, sets)
            base.update(sets=sets, assessments=assessments,
                        notes=tuple(f"scope limit: {t}" for t in intent.scope_limits))
            if verdict[0] == HOLD:
                return CaseResult(outcome=HOLD, held=(verdict[1],), detail=verdict[2], **base)
            status = verdict[1]
            try:
                steps = build_steps(status, sets, assessments, self.index, req["_audit_at"], self.capture)
            except StepBuildError as e:
                return CaseResult(outcome=HOLD, held=(e.reason,), detail=(e.detail,), **base)
            return CaseResult(outcome=EMIT, status=status, steps=tuple(steps), **base)
        except Exception as e:                                           # F.3.1: never a row
            return CaseResult(outcome=HOLD, held=(H.ERROR,), detail=(f"{type(e).__name__}: {e}",), **base)
