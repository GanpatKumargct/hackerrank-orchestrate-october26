"""M9 — serializer, run-level validator (L1–L4) and staged writer (plan F.3–F.4, E.4.3; Stage 9).

Only emitted results are serialized; a held result reaching the serializer raises.
Everything is written under a run directory in `runs/`. This stage never writes the
root output.csv: with held cases the staging file is explicitly partial, and the
run exits non-zero (A.8.3, F.3.2). Reports carry case, resource and file IDs and
reason codes only — no personal values (A.7.3).
"""
import csv
import hashlib
import io
import json
from collections import Counter
from pathlib import Path

from . import config
from .admissibility import admissible_for_citation
from .decision import EMIT, HOLD, _proof_is_absence, citation_file, validate_steps
from .dependencies import build_edges, check_order
from .errors import HeldReason as H
from .intent import NON_DELETION
from .state import COMPLIANT, VIOLATION


class SerializationError(Exception):
    """A held result reached the serializer (E.7 serialization guard)."""


# --------------------------------------------------------------------------- #
# Serialization (F.3.3)
# --------------------------------------------------------------------------- #
def serialize_steps(steps):
    return json.dumps([{k: s[k] for k in config.STEP_KEYS} for s in steps], ensure_ascii=False,
                      separators=(",", ":"))


def to_row(result):
    if result.outcome != EMIT or result.status not in config.STATUSES:
        raise SerializationError(f"{result.case_id}: held result cannot be serialized")
    return result.case_id, result.status, serialize_steps(result.steps)


def render_csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writerow(config.OUTPUT_HEADER)
    for r in sorted(rows, key=lambda r: config.ROW_SORT_KEY(r[0])):
        w.writerow(r)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# L1 / L2 — file-only re-read (independent of internal state, F.4 caveat)
# --------------------------------------------------------------------------- #
def validate_file(text, expected_ids, file_ids, audit_at=None, capture_map=None):
    """Return (errors, missing_ids, parsed {case_id: (status, steps)})."""
    errs, parsed = [], {}
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or tuple(rows[0]) != config.OUTPUT_HEADER:
        return [f"L1.1 header must be exactly {','.join(config.OUTPUT_HEADER)}"], sorted(expected_ids), {}
    data = rows[1:]
    ids = [r[0] if r else "" for r in data]
    for n, r in enumerate(data, 2):
        if len(r) != 3:
            errs.append(f"L1 line {n}: expected 3 columns, found {len(r)}")
            continue
        cid, status, cell = r
        if cid in parsed:
            errs.append(f"L1.3 duplicate case_id {cid}")
            continue
        if cid not in expected_ids:
            errs.append(f"L1.3 unexpected case_id {cid}")
        if status not in config.STATUSES:
            errs.append(f"L1.5 {cid}: status {status!r} not permitted")
        try:
            steps = json.loads(cell)
        except ValueError:
            errs.append(f"L1.6 {cid}: steps_json is not valid JSON")
            continue
        if not isinstance(steps, list):
            errs.append(f"L1.6 {cid}: steps_json is not a JSON array")
            continue
        parsed[cid] = (status, steps)
        when = audit_at.get(cid) if audit_at else None
        errs += [f"L1/L2 {cid}: {e}" for e in validate_steps(status, steps, file_ids, when, capture_map)]
    try:
        keys = [config.ROW_SORT_KEY(c) for c in ids]
        if keys != sorted(keys):
            errs.append("L1.4 rows are not in ROW_SORT_KEY order")
    except (ValueError, IndexError):
        errs.append("L1.4 a case_id has no numeric suffix")
    missing = sorted(set(expected_ids) - set(parsed), key=config.ROW_SORT_KEY)
    if len(data) != len(expected_ids):
        errs.append(f"L1.2 {len(data)} data rows; the contract requires {len(expected_ids)}")
    return errs, missing, parsed


# --------------------------------------------------------------------------- #
# L3 citation meaning and L4 policy completeness — per emitted case
# --------------------------------------------------------------------------- #
def validate_case(result, ctx):
    """Return (errors, dependency_conflicts) for one emitted result. ctx: RunContext."""
    errs, conflicts = [], []
    steps = list(result.steps)
    if result.status == "NOT_APPLICABLE":
        if steps:
            errs.append("L2.4 NOT_APPLICABLE with steps")
        if result.intent is None or result.intent.value != NON_DELETION:
            errs.append("L4 NOT_APPLICABLE without an explicit NON_DELETION intent")
        return errs, conflicts
    sets, a_by, scope = result.sets, result.assessments, result.scope
    included = set(scope.included) if scope is not None else set()
    wf_only = set(scope.workflow_candidates) if scope is not None else set()
    by_phase = {p: [s for s in steps if s["phase"] == p] for p in config.PHASES}
    for s in steps:
        rid = s["resource_id"]
        if rid not in included or rid in wf_only:
            errs.append(f"L4.7 {rid}: step for a resource that is not in scope")
            continue
        a = a_by.get(rid)
        if a is None or a.category.value is None:
            errs.append(f"L4 {rid}: no assessment/category behind the step")
            continue
        treat = config.TREATMENTS[a.category.value]
        if s["system_id"] != a.owner.system_id:
            errs.append(f"L4 {rid}: system_id {s['system_id']} differs from resolved owner")
        if s["operation"] == "DELETE_RECORD" and a.category.value in config.NEVER_DELETE:
            errs.append(f"L4.5 {rid}: DELETE prohibited for {a.category.value}")
        if s["evidence_id"]:
            errs += _l3(s, a, treat, result, ctx)
    # L4.1 / L4.2 / L4.3 / L4.4
    find = {s["resource_id"] for s in by_phase["FINDING"]}
    rem = {s["resource_id"] for s in by_phase["REMEDIATION"]}
    ver = {s["resource_id"] for s in by_phase["VERIFICATION"]}
    if find != set(sets.violating) or rem != set(sets.violating):
        errs.append("L4.1 FINDING/REMEDIATION sets differ from the violating set")
    if ver != set(sets.req):
        errs.append("L4.2 VERIFICATION set differs from REQ")
    for s in steps:
        a = a_by.get(s["resource_id"])
        if a is None or a.category.value is None:
            continue
        treat = config.TREATMENTS[a.category.value]
        expected = {"FINDING": treat.finding, "REMEDIATION": treat.remediation,
                    "VERIFICATION": treat.verification}[s["phase"]]
        if s["operation"] != expected:
            errs.append(f"L4.1/L4.2 {s['resource_id']}: {s['operation']} is not the {a.category.value} chain")
        if s["operation"] == "VERIFY_RECORD_PRESENT" and treat.action != "RETAIN":
            errs.append(f"L4.2 {s['resource_id']}: VERIFY_RECORD_PRESENT outside a retained category")
    if result.status == "COMPLETE":
        if set(sets.req) != set(sets.proven_ok) or sets.unresolved or sets.unexpressible or sets.wf_violating:
            errs.append("L4.3 COMPLETE without every REQ member proven and nothing unresolved")
        if by_phase["FINDING"] or by_phase["REMEDIATION"]:
            errs.append("L2.5 COMPLETE with non-verification steps")
    if result.status == "INCOMPLETE":
        if not sets.violating or sets.unresolved:
            errs.append("L4.4 INCOMPLETE needs a violation and an empty unresolved set")
        for rid in sets.violating:
            if a_by[rid].verdict != VIOLATION or not a_by[rid].proof:
                errs.append(f"L4.4 {rid}: finding without an observed violation proof")
    # L4.6 dependencies (D.4)
    owners = {rid: a.owner.system_id for rid, a in a_by.items()}
    edges = build_edges(included, owners, ctx.index, ctx.activities, result.audit_at)
    d1, d2 = check_order(steps, edges)
    errs += [f"L4.6 {e}" for e in d1]
    conflicts += d2
    return errs, conflicts


def _l3(step, a, treat, result, ctx):
    """F.2.1 checks 1–6 for one cited step."""
    rid, ev, errs = step["resource_id"], step["evidence_id"], []
    if ev not in ctx.capture:
        return [f"L3.1 {rid}: {ev} is not a manifest file_id"]
    if ctx.capture[ev] > result.audit_at:
        errs.append(f"L3.2 {rid}: {ev} captured after audit_at")
    if len(a.proof) != 1 or citation_file(a.proof[0], ctx.index) != ev:
        errs.append(f"L3.6 {rid}: {ev} is not the single PROOF ref of the verdict")
        return errs
    src = a.proof[0]
    if src.startswith("coverage:"):
        pass                                             # C.8.2-selected omission snapshot (check 3)
    else:
        o = ctx.index.get(src)
        if o.resource_id != rid:
            errs.append(f"L3.3 {rid}: cited observation names another resource")
        if not admissible_for_citation(o, result.audit_at):
            errs.append(f"L3.2 {rid}: cited observation not admissible at audit_at")
    if step["phase"] == "FINDING" and (a.verdict != VIOLATION or step["operation"] != treat.finding):
        errs.append(f"L3.5 {rid}: finding does not match an observed violation")
    if step["phase"] == "VERIFICATION":
        if a.verdict != COMPLIANT or step["operation"] != treat.verification:
            errs.append(f"L3.5 {rid}: verification does not match a proven compliant state")
        elif (step["operation"] == "VERIFY_RECORD_ABSENT") != _proof_is_absence(a):
            errs.append(f"L3.5 {rid}: citation state does not match {step['operation']}")
    return errs


# --------------------------------------------------------------------------- #
# Staged run (F.3.2, E.4.3)
# --------------------------------------------------------------------------- #
class RunContext:
    def __init__(self, index, capture, activities, gaps=()):
        self.index, self.capture, self.activities, self.gaps = index, capture, activities, tuple(gaps)


def _demote(result, errors):
    result.outcome, result.held, result.detail = HOLD, (H.VALIDATION_FAILED,), tuple(errors)
    result.status, result.steps = None, ()
    return result


def stage_run(results, expected_ids, ctx, run_dir):
    """Validate, stage and report one run. Returns (exit_code, summary). Never touches root output.csv."""
    run_dir = Path(run_dir).resolve()
    if run_dir == config.REPO_ROOT.resolve():
        raise ValueError("the staging directory may not be the repository root")
    run_dir.mkdir(parents=True, exist_ok=True)
    results = sorted(results, key=lambda r: config.ROW_SORT_KEY(r.case_id))
    seen = Counter(r.case_id for r in results)
    run_errors = [f"duplicate result for {c}" for c, n in seen.items() if n > 1]
    run_errors += [f"no result for {c}" for c in sorted(set(expected_ids) - set(seen), key=config.ROW_SORT_KEY)]
    run_errors += [f"result for unexpected case {c}" for c in seen if c not in expected_ids]
    conflicts, case_errors = {}, {}
    for r in results:
        if r.outcome != EMIT:
            continue
        errs = validate_steps(r.status, list(r.steps), set(ctx.capture), r.audit_at, ctx.capture)
        more, conf = validate_case(r, ctx)
        errs += more
        if conf:
            conflicts[r.case_id] = conf
        if errs:
            case_errors[r.case_id] = errs
            _demote(r, errs)                             # never staged; reported as held
    emitted = [r for r in results if r.outcome == EMIT]
    held = [r for r in results if r.outcome == HOLD]
    partial = bool(held) or len(emitted) != len(expected_ids)
    name = "staging_output.partial.csv" if partial else "staging_output.csv"
    text = render_csv([to_row(r) for r in emitted])
    (run_dir / name).write_text(text, encoding="utf-8", newline="")
    # independent re-read of the written file (L1/L2) plus a round-trip check
    audit = {r.case_id: r.audit_at for r in results}
    file_errs, missing, parsed = validate_file(text, set(expected_ids), set(ctx.capture), audit, ctx.capture)
    held_ids = {r.case_id for r in held}
    file_errs = [e for e in file_errs if not (partial and e.startswith("L1.2"))]   # partial by design; below
    if set(missing) != held_ids:
        file_errs.append("staged rows + held cases do not cover every expected case exactly once")
    for r in emitted:
        if parsed.get(r.case_id) != (r.status, [dict(s) for s in r.steps]):
            file_errs.append(f"round-trip mismatch for {r.case_id}")
    run_level = {
        "held_count_is_zero": not held,
        "emitted_plus_held_equals_inputs": len(emitted) + len(held) == len(expected_ids),
        "evidence_gaps_accepted": not ctx.gaps,
    }
    invalid = bool(run_errors or file_errs or case_errors)
    code = config.EXIT_INVALID if invalid else (config.EXIT_HELD if held or not all(run_level.values())
                                                else config.EXIT_OK)
    summary = {
        "run_dir": run_dir.name,
        "inputs": len(expected_ids),
        "emitted": dict(sorted(Counter(r.status for r in emitted).items())),
        "held": len(held),
        "held_by_reason": dict(sorted(Counter(_v(h) for r in held for h in r.held).items())),
        "staging_file": name,
        "staging_rows": len(emitted),
        "staging_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "partial": partial,
        "run_level_checks": run_level,
        "evidence_gaps": [g[0] for g in ctx.gaps],
        "run_errors": run_errors,
        "file_errors": file_errs,
        "cases_failing_validation": {c: e for c, e in sorted(case_errors.items())},
        "dependency_order_conflicts": conflicts,
        "exit_code": code,
        "status": ("COMPLETE_AND_VALID — eligible for promotion in Stage 13 (root output.csv not written)"
                   if code == config.EXIT_OK else
                   "INVALID — validation errors" if code == config.EXIT_INVALID else
                   "NOT COMPLETE — held cases remain; root output.csv not written"),
    }
    (run_dir / "run_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                                              encoding="utf-8", newline="\n")
    (run_dir / "held_cases.json").write_text(json.dumps([_held_entry(r) for r in held], indent=2,
                                                        ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    (run_dir / "held_report.md").write_text(held_report(summary, held), encoding="utf-8", newline="\n")
    (run_dir / "validation_report.md").write_text(validation_report(summary), encoding="utf-8", newline="\n")
    return code, summary


def _v(x):
    return getattr(x, "value", x)


def _unresolved(r):
    out = {}
    if r.sets is None:
        return out
    for rid, codes in sorted(r.sets.unresolved.items()):
        a = r.assessments.get(rid)
        out[rid] = {"reasons": [_v(c) for c in codes],
                    "category": (a.category.value if a else None),
                    "category_reason": (_v(a.category.reason) if a and a.category.reason else None),
                    "owner_system": (a.owner.system_id if a else None)}
    for rid in r.sets.unexpressible:
        out[rid] = {"reasons": [H.RETAINED_RECORD_MISSING.value], "category": r.assessments[rid].category.value,
                    "category_reason": None, "owner_system": r.assessments[rid].owner.system_id}
    for rid in r.sets.wf_violating:
        out[rid] = {"reasons": ["WORKFLOW_CANDIDATE_VIOLATION"], "category": None, "category_reason": None,
                    "owner_system": None}
    return out


def _held_entry(r):
    s = r.sets
    return {"case_id": r.case_id,
            "held": [_v(h) for h in r.held],
            "intent": r.intent.value if r.intent else None,
            "detail": [list(map(_v, d)) if isinstance(d, tuple) else str(d) for d in r.detail],
            "unresolved": _unresolved(r),
            "sets": None if s is None else {"req": len(s.req), "proven_ok": len(s.proven_ok),
                                            "violating": len(s.violating), "unresolved": len(s.unresolved),
                                            "unexpressible": len(s.unexpressible),
                                            "workflow_violating": len(s.wf_violating)}}


def held_report(summary, held):
    lines = ["# Held-case report", "",
             f"Run `{summary['run_dir']}` — {summary['status']}.", "",
             "Identifiers only (case, resource, file IDs and reason codes); no personal values.", "",
             "## Totals", "",
             "| Item | Count |", "|---|---|",
             f"| Evaluation inputs | {summary['inputs']} |"]
    lines += [f"| Emitted {k} | {v} |" for k, v in summary["emitted"].items()]
    lines += [f"| **Held** | **{summary['held']}** |", "",
              "## Held by reason", "", "| Reason | Cases |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in summary["held_by_reason"].items()]
    member = Counter(c for r in held for m in _unresolved(r).values() for c in m["reasons"])
    lines += ["", "## Unresolved members behind the holds", "", "| Reason | Members |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(member.items())]
    lines += ["", "## Held cases", "",
              "| case_id | Hold reason | REQ / proven / violating | Unresolved members (resource: reason [category, owner]) |",
              "|---|---|---|---|"]
    for r in held:
        s = r.sets
        counts = "-" if s is None else f"{len(s.req)} / {len(s.proven_ok)} / {len(s.violating)}"
        um = _unresolved(r)
        cells = "; ".join(f"{rid}: {','.join(m['reasons'])} [{m['category'] or m['category_reason'] or '-'}, "
                          f"{m['owner_system'] or '-'}]" for rid, m in um.items())
        if not cells:
            cells = "; ".join(str(d) if not isinstance(d, tuple) else f"{d[0]}: {_v(d[1])}" for d in r.detail) or "-"
        lines.append(f"| {r.case_id} | {', '.join(_v(h) for h in r.held)} | {counts} | {cells} |")
    return "\n".join(lines) + "\n"


def validation_report(summary):
    rl = summary["run_level_checks"]
    lines = ["# Run validation report", "", f"Run `{summary['run_dir']}` — exit code {summary['exit_code']}: "
             f"{summary['status']}.", "",
             f"- Staging file: `{summary['staging_file']}` ({summary['staging_rows']} rows, "
             f"partial={summary['partial']}, sha256 `{summary['staging_sha256']}`)",
             "- Root `output.csv`: not written by this stage.", "", "## Run-level checks", ""]
    lines += [f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in rl.items()]
    lines += ["", f"Evidence gaps not accepted: {', '.join(summary['evidence_gaps']) or 'none'}", "",
              "## L1/L2 file re-read errors", ""]
    lines += [f"- {e}" for e in summary["file_errors"]] or ["- none"]
    lines += ["", "## Run errors (coverage, duplicates)", ""]
    lines += [f"- {e}" for e in summary["run_errors"]] or ["- none"]
    lines += ["", "## Cases failing L1–L4 (demoted to held VALIDATION_FAILED)", ""]
    lines += [f"- {c}: {'; '.join(e)}" for c, e in summary["cases_failing_validation"].items()] or ["- none"]
    lines += ["", "## D.4 dependency-order conflicts (reported; contract order kept, Q-DEP)", ""]
    lines += [f"- {c}: {'; '.join(e)}" for c, e in summary["dependency_order_conflicts"].items()] or ["- none"]
    return "\n".join(lines) + "\n"
