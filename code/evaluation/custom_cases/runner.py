"""Run the G.5 custom cases through the production pipeline and check their expected results."""
import shutil
import tempfile
from pathlib import Path

from audit.decision import EMIT, CaseAnalyzer
from audit.evidence.extract import build_index
from audit.identity import IdentityResolver
from audit.loader import load_dataset
from audit.scope import ScopeBuilder
from audit.serializer import RunContext, validate_case
from audit.decision import validate_steps

from .builders import CASES


def run_case(name):
    spec = CASES[name]
    root = Path(tempfile.mkdtemp(prefix="audit_cc_"))
    try:
        ds = load_dataset(spec["builder"](root))
        index = build_index(ds)
        resolver = IdentityResolver(ds)
        an = CaseAnalyzer(ds, index, resolver, ScopeBuilder(ds, index, resolver))
        r = an.analyze(ds.requests[0])
        problems = []
        if r.outcome == EMIT:
            problems += validate_steps(r.status, list(r.steps), set(an.capture), r.audit_at, an.capture)
            problems += validate_case(r, RunContext(index, an.capture, ds.activities))[0]
        got = [(s["operation"], s["system_id"], s["resource_id"], s["evidence_id"]) for s in r.steps]
        checks = {"outcome": r.outcome == spec["outcome"],
                  "steps": got == spec["steps"],
                  "validation": not problems}
        if spec["outcome"] == "EMIT":
            checks["status"] = r.status == spec["status"]
        else:
            checks["held_reason"] = [getattr(h, "value", h) for h in r.held] == [spec["held"]]
        if spec.get("held_detail"):
            want = spec["held_detail"]
            checks["held_detail"] = any(isinstance(d, tuple) and d[0] == want[0] and getattr(d[1], "value", d[1]) == want[1]
                                        for d in r.detail)
        if spec.get("never_cited"):
            checks["late_file_never_cited"] = spec["never_cited"] not in {s["evidence_id"] for s in r.steps}
        if spec.get("intent_clauses"):
            types = {c.type for c in r.intent.clauses}
            checks["intent_clauses"] = set(spec["intent_clauses"]) <= types
        result = {"name": name, "case_id": spec["case_id"], "title": spec["title"], "rules": spec["rules"],
                  "expected": {k: spec[k] for k in ("outcome", "status", "held") if k in spec},
                  "got": {"outcome": r.outcome, "status": r.status,
                          "held": [getattr(h, "value", h) for h in r.held],
                          "detail": [list(map(lambda x: getattr(x, "value", x), d)) if isinstance(d, tuple) else str(d)
                                     for d in r.detail],
                          "steps": got,
                          "intent_clauses": sorted({c.type for c in r.intent.clauses})},
                  "checks": checks, "validation_errors": problems, "passed": all(checks.values())}
        if spec.get("plan_clauses"):
            missing = sorted(set(spec["plan_clauses"]) - {c.type for c in r.intent.clauses})
            result["plan_clause_deviation"] = missing
        return result
    finally:
        shutil.rmtree(root, ignore_errors=True)


def run_all():
    return [run_case(n) for n in CASES]
