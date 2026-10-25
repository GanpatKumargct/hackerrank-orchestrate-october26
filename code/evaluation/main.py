"""Stage 10 evaluator (plan G.3–G.5, A.6). Offline and deterministic; evaluation only.

    python code/evaluation/main.py [--stage-run runs/<ts>] [--out-dir runs/<ts>_evaluation]

(A) Runs the production pipeline in memory on the 32 public samples and compares the
    emitted results with dataset/sample_output.csv (read here only; production never
    opens it, A.1.2).
(B) Runs the G.5 custom cases CC1–CC5 (+ CC2-n) through the same pipeline.
(C) Evaluates the existing Stage 9 staged run read-only: re-validates its staging file
    from text (L1/L2), summarises held reasons, re-runs the evaluation requests in
    memory to confirm the staged rows are reproduced byte-for-byte, and re-checks the
    L3/L4 invariants. Nothing in the Stage 9 run directory is written.

Writes metrics.json and evaluation_metrics.md to a NEW directory (default
runs/<UTC ts>_evaluation). Never writes root output.csv. Exit 0 when false-COMPLETE = 0,
invalid citations = 0, every custom case passes and the staged run is reproduced; else 1.
"""
import argparse
import csv
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audit import config                                       # noqa: E402
from audit.decision import EMIT, CaseAnalyzer, validate_steps  # noqa: E402
from audit.evidence.extract import build_index                 # noqa: E402
from audit.identity import IdentityResolver                    # noqa: E402
from audit.loader import load_dataset                          # noqa: E402
from audit.scope import ScopeBuilder                           # noqa: E402
from audit.serializer import RunContext, render_csv, to_row, validate_case, validate_file  # noqa: E402
from evaluation.custom_cases.runner import run_all             # noqa: E402
from evaluation.metrics import aggregate, case_metrics         # noqa: E402


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _latest_stage_run():
    runs = sorted(p for p in config.RUNS_DIR.glob("*") if p.is_dir() and (p / "run_summary.json").is_file()
                  and not p.name.endswith("_evaluation"))
    return runs[-1] if runs else None


def _git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=config.REPO_ROOT, capture_output=True,
                              text=True, timeout=20).stdout.strip() or "not available"
    except (OSError, subprocess.SubprocessError):
        return "not available"


def _git_dirty_paths():
    """Uncommitted changes under code/ (A.6 provenance). None when git is unavailable."""
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--", "code"], cwd=config.REPO_ROOT,
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    paths = (line[3:].strip() for line in out.stdout.splitlines() if line.strip())
    return sorted(p for p in paths if "__pycache__" not in p)      # bytecode caches are not code


def _code_fingerprint():
    """SHA-256 over every code/**/*.py (relative path + content): identifies the executed code."""
    code = config.REPO_ROOT / "code"
    h = hashlib.sha256()
    for p in sorted(code.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        h.update(p.relative_to(code).as_posix().encode("utf-8") + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def _check(results, ctx):
    """L1/L2 per case + L3/L4 for emitted results: (invalid citations, COMPLETE invariant failures, errors)."""
    invalid, bad_complete, errors = 0, 0, {}
    for r in results:
        if r.outcome != EMIT:
            continue
        errs = validate_steps(r.status, list(r.steps), set(ctx.capture), r.audit_at, ctx.capture)
        errs += validate_case(r, ctx)[0]
        if errs:
            errors[r.case_id] = errs
        invalid += sum(1 for e in errs if e.startswith("L3") or "captured after audit_at" in e)
        if r.status == "COMPLETE" and errs:
            bad_complete += 1
    return invalid, bad_complete, errors


def evaluate(dataset_dir, stage_run):
    ds = load_dataset(dataset_dir)
    index = build_index(ds)
    resolver = IdentityResolver(ds)
    an = CaseAnalyzer(ds, index, resolver, ScopeBuilder(ds, index, resolver))
    ctx = RunContext(index, an.capture, ds.activities, index.gaps())
    out = {}

    # ---- (A) public samples ----
    expected = {r["case_id"]: r for r in csv.DictReader(open(Path(dataset_dir) / "sample_output.csv",
                                                             encoding="utf-8", newline=""))}
    samples = sorted(ds.sample_requests, key=lambda r: config.ROW_SORT_KEY(r["case_id"]))
    sres = [an.analyze(r) for r in samples]
    per_case, held_reasons, unresolved = {}, Counter(), Counter()
    for r in sres:
        e = expected[r.case_id]
        per_case[r.case_id] = case_metrics(r.status if r.outcome == EMIT else None, r.steps,
                                           e["deletion_status"], json.loads(e["steps_json"]))
        for h in r.held:
            held_reasons[getattr(h, "value", h)] += 1
        if r.sets is not None:
            for codes in r.sets.unresolved.values():
                for c in codes:
                    unresolved[getattr(c, "value", c)] += 1
    s_invalid, s_bad_complete, s_errors = _check(sres, ctx)
    agg = aggregate(per_case)
    agg.update(invalid_citations=s_invalid, complete_invariant_failures=s_bad_complete,
               held_by_reason=dict(sorted(held_reasons.items())), unresolved_members_by_reason=dict(sorted(unresolved.items())),
               validation_errors=s_errors)
    req_ratio = [len(r.sets.proven_ok) + len(r.sets.violating) + len(r.sets.unexpressible) for r in sres if r.sets]
    req_total = [len(r.sets.req) for r in sres if r.sets]
    agg["internal_req_decided_ratio"] = round(sum(req_ratio) / sum(req_total), 4) if sum(req_total) else None
    out["samples"] = {"aggregate": agg, "per_case": per_case}

    # ---- (B) custom cases ----
    out["custom_cases"] = run_all()

    # ---- (C) Stage 9 staged run, read-only ----
    st = {"run_dir": None}
    if stage_run is not None:
        stage_run = Path(stage_run)
        files = sorted(p for p in stage_run.iterdir() if p.is_file())
        before = {p.name: _sha(p) for p in files}
        summary = json.loads((stage_run / "run_summary.json").read_text(encoding="utf-8"))
        held = json.loads((stage_run / "held_cases.json").read_text(encoding="utf-8"))
        staged_text = (stage_run / summary["staging_file"]).read_text(encoding="utf-8")
        requests = sorted(ds.requests, key=lambda r: config.ROW_SORT_KEY(r["case_id"]))
        audit = {r["case_id"]: r["_audit_at"] for r in requests}
        file_errs, missing, parsed = validate_file(staged_text, set(audit), set(an.capture), audit, an.capture)
        held_ids = {h["case_id"] for h in held}
        eres = [an.analyze(r) for r in requests]
        e_invalid, e_bad_complete, e_errors = _check(eres, ctx)
        reproduced_text = render_csv([to_row(r) for r in eres if r.outcome == EMIT and r.case_id not in e_errors])
        after = {p.name: _sha(p) for p in sorted(p for p in stage_run.iterdir() if p.is_file())}
        st = {
            "run_dir": stage_run.name,
            "summary_status": summary["status"], "exit_code": summary["exit_code"],
            "inputs": summary["inputs"], "emitted": summary["emitted"], "held": summary["held"],
            "held_by_reason": summary["held_by_reason"],
            "staging_file": summary["staging_file"], "staging_rows": len(parsed),
            "file_errors_excluding_partial_row_count": [e for e in file_errs if not e.startswith("L1.2")],
            "missing_rows_equal_held_cases": set(missing) == held_ids,
            "staged_rows_reproduced_in_memory": reproduced_text == staged_text,
            "staging_sha256_recorded": summary["staging_sha256"],
            "staging_sha256_reproduced": hashlib.sha256(reproduced_text.encode("utf-8")).hexdigest(),
            "in_memory_held": sum(1 for r in eres if r.outcome != EMIT),
            "invalid_citations": e_invalid, "complete_invariant_failures": e_bad_complete,
            "validation_errors": e_errors,
            "artifact_sha256_before": before, "artifact_sha256_after": after,
            "artifacts_unchanged": before == after,
            "evidence_gaps": [g[0] for g in index.gaps()],
        }
    out["stage_run"] = st
    acceptance = {
        "false_complete_zero": agg["false_complete"] == 0 and agg["complete_invariant_failures"] == 0
        and st.get("complete_invariant_failures", 0) == 0,
        "invalid_citations_zero": agg["invalid_citations"] == 0 and st.get("invalid_citations", 0) == 0,
        "custom_cases_pass": all(c["passed"] for c in out["custom_cases"]),
        "stage_run_reproduced": bool(st.get("staged_rows_reproduced_in_memory", False)),
        "stage_run_artifacts_unchanged": bool(st.get("artifacts_unchanged", False)),
    }
    out["acceptance"] = acceptance
    return out


def _provenance_note(meta):
    if meta["git_dirty"] is None:
        return "git status not available — the recorded commit may not identify the executed code."
    if meta["git_dirty"]:
        return (f"**Uncommitted changes under code/ ({len(meta['dirty_paths'])} paths) — the recorded commit does "
                "not identify the executed code; use the code fingerprint.**")
    return "Working tree clean under code/: the recorded commit identifies the executed code."


def _md(res, meta):
    a, st = res["samples"]["aggregate"], res["stage_run"]
    prov = _provenance_note(meta)
    L = ["# Stage 10 evaluation metrics", "",
         f"Generated {meta['generated_at']} by `{meta['command']}` at git commit `{meta['git_commit']}`.",
         f"Code fingerprint (SHA-256 of code/**/*.py): `{meta['code_fingerprint']}`. {prov}", "",
         "Offline, deterministic, no model calls. **Public-sample metrics only**; no hidden-test score is "
         "estimated. Held cases count as incorrect and contribute no predicted steps.", "",
         "## Acceptance", ""]
    L += [f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in res["acceptance"].items()]
    L += ["", "## (A) Public samples (32)", "", "| Metric | Value |", "|---|---|"]
    for k in ("status_accuracy", "false_complete", "complete_invariant_failures", "invalid_citations", "held_rate",
              "step_precision", "step_recall", "step_f1", "predicted_steps", "expected_steps", "strict_matches",
              "field_aligned_pairs", "sequence_exact", "sequence_lcs_mean", "citation_accuracy",
              "resource_coverage_mean", "internal_req_decided_ratio", "unexpected_resources"):
        L.append(f"| {k} | {a[k] if a[k] is not None else 'not available (no denominator)'} |")
    L += ["", "Field accuracy (over (resource_id, phase)-aligned pairs): " +
          ", ".join(f"{f} {v}" for f, v in a["field_accuracy"].items()), "",
          "Status confusion (expected -> predicted): " + ", ".join(f"{k} {v}" for k, v in a["confusion"].items()), "",
          "Held by reason: " + (", ".join(f"{k} {v}" for k, v in a["held_by_reason"].items()) or "none"), "",
          "Unresolved members by reason: " +
          (", ".join(f"{k} {v}" for k, v in a["unresolved_members_by_reason"].items()) or "none"), "",
          "| case | expected | predicted | strict / expected steps | LCS | coverage |", "|---|---|---|---|---|---|"]
    for cid, c in res["samples"]["per_case"].items():
        L.append(f"| {cid} | {c['expected_status']} | {c['predicted_status']} | {c['strict_matches']} / "
                 f"{c['exp_steps']} | {round(c['sequence_lcs_ratio'], 3)} | {round(c['resource_coverage'], 3)} |")
    L += ["", "## (B) Custom cases (G.5)", "", "| Case | Title | Expected | Got | Result |", "|---|---|---|---|---|"]
    for c in res["custom_cases"]:
        exp = c["expected"].get("status") or f"HOLD {c['expected'].get('held')}"
        got = c["got"]["status"] or f"HOLD {','.join(c['got']['held'])}"
        note = f" (plan clause not detected: {', '.join(c['plan_clause_deviation'])})" if c.get("plan_clause_deviation") else ""
        L.append(f"| {c['name']} ({c['case_id']}) | {c['title']} | {exp} | {got} | "
                 f"{'PASS' if c['passed'] else 'FAIL'}{note} |")
    L += ["", "## (C) Stage 9 staged run (read-only)", ""]
    if st.get("run_dir"):
        L += [f"- Run `{st['run_dir']}`: {st['summary_status']} (exit {st['exit_code']}).",
              f"- Inputs {st['inputs']}; emitted {st['emitted']}; held {st['held']} {st['held_by_reason']}.",
              f"- Staging file `{st['staging_file']}`: {st['staging_rows']} rows; L1/L2 re-read errors "
              f"(excluding the by-design partial row count): {len(st['file_errors_excluding_partial_row_count'])}; "
              f"missing rows equal held cases: {st['missing_rows_equal_held_cases']}.",
              f"- Reproduced in memory: {st['staged_rows_reproduced_in_memory']} "
              f"(sha256 recorded {st['staging_sha256_recorded'][:16]}…, reproduced {st['staging_sha256_reproduced'][:16]}…); "
              f"in-memory held {st['in_memory_held']}.",
              f"- Invalid citations {st['invalid_citations']}; COMPLETE invariant failures "
              f"{st['complete_invariant_failures']}; artifacts unchanged: {st['artifacts_unchanged']}.",
              f"- Evidence gaps (not accepted): {', '.join(st['evidence_gaps'])}."]
    else:
        L.append("- No Stage 9 run found: not available.")
    return "\n".join(L) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description="Stage 10 evaluator (offline, evaluation only)")
    p.add_argument("--dataset", default=str(config.DATASET_DIR))
    p.add_argument("--stage-run", default=None, help="Stage 9 run directory (default: latest under runs/)")
    p.add_argument("--out-dir", default=None, help="new output directory (default: runs/<UTC ts>_evaluation)")
    args = p.parse_args(argv)
    stage_run = Path(args.stage_run) if args.stage_run else _latest_stage_run()
    now = datetime.now(timezone.utc)
    out_dir = Path(args.out_dir) if args.out_dir else config.RUNS_DIR / (now.strftime("%Y%m%dT%H%M%SZ") + "_evaluation")
    out_dir = out_dir.resolve()
    if out_dir == config.REPO_ROOT.resolve() or (stage_run is not None and out_dir == Path(stage_run).resolve()):
        raise SystemExit("refusing to write into the repository root or the Stage 9 run directory")
    dirty, fingerprint = _git_dirty_paths(), _code_fingerprint()   # taken before the run, describes the code it uses
    res = evaluate(args.dataset, stage_run)
    meta = {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "git_commit": _git_commit(),
            "git_dirty": None if dirty is None else bool(dirty), "dirty_paths": dirty or [],
            "code_fingerprint": fingerprint,
            "command": "python code/evaluation/main.py" + (" " + " ".join(argv) if argv else ""),
            "inputs": sorted(config.INPUT_FILES) + ["sample_output.csv (evaluation only)"],
            "stage_run": res["stage_run"].get("run_dir")}
    out_dir.mkdir(parents=True, exist_ok=False)
    (out_dir / "metrics.json").write_text(json.dumps({"meta": meta, **res}, indent=2, ensure_ascii=False,
                                                     default=list) + "\n", encoding="utf-8", newline="\n")
    (out_dir / "evaluation_metrics.md").write_text(_md(res, meta), encoding="utf-8", newline="\n")
    a = res["samples"]["aggregate"]
    print(f"output directory: {out_dir}")
    print(f"provenance: commit {meta['git_commit']} dirty={meta['git_dirty']} "
          f"fingerprint={meta['code_fingerprint'][:16]}…")
    print(f"samples: status_accuracy={a['status_accuracy']} false_complete={a['false_complete']} "
          f"invalid_citations={a['invalid_citations']} held_rate={a['held_rate']} step_f1={a['step_f1']} "
          f"confusion={a['confusion']}")
    print("custom cases:", {c["name"]: "PASS" if c["passed"] else "FAIL" for c in res["custom_cases"]})
    st = res["stage_run"]
    if st.get("run_dir"):
        print(f"stage run {st['run_dir']}: held={st['held']} reproduced={st['staged_rows_reproduced_in_memory']} "
              f"invalid_citations={st['invalid_citations']} artifacts_unchanged={st['artifacts_unchanged']}")
    print("acceptance:", res["acceptance"])
    return 0 if all(res["acceptance"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
