"""Command-line entry point.

Stages 0–4 only: `python code/main.py inspect` validates the inputs, parses all
evidence into an ObservationIndex and prints a coverage summary (counts and file
IDs only, no personal values). No predictions and no output.csv are produced.
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit import config                          # noqa: E402
from audit.errors import ReportNote, SchemaError, ScopeCode  # noqa: E402
from audit.scope import ScopeBuilder              # noqa: E402
from audit.state import assess                    # noqa: E402
from audit.evidence.extract import build_index    # noqa: E402
from audit.identity import IdentityResolver, Subject  # noqa: E402
from audit.loader import load_dataset             # noqa: E402


def cmd_inspect(args):
    try:
        ds = load_dataset(args.dataset)
    except SchemaError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"inputs: requests={len(ds.requests)} sample_requests={len(ds.sample_requests)} "
          f"identities={len(ds.identities)} audit_log={len(ds.audit_log)} "
          f"activities={len(ds.activities)} rules={len(ds.rules)} evidence_files={len(ds.manifest)}")
    print(f"loader warnings: {len(ds.warnings)}")
    index = build_index(ds)
    reports = index.reports
    status = Counter((r.fmt, r.status) for r in reports.values())
    print("extraction status by format:", dict(sorted(status.items())))
    print(f"observations: {len(index)}  resources: {len(index.resources())}  "
          f"coverage units: {sum(len(r.coverage) for r in reports.values())}")
    print("observations by format:", dict(sorted(Counter(o.source_format for o in index.all()).items())))
    for r in sorted(reports.values(), key=lambda r: r.file_id):
        if r.status != "OK" or r.warnings or r.fmt == "pdf":
            print(f"  {r.file_id} {r.fmt} {r.status} pages={len(r.pages)} obs={r.observations} "
                  f"reasons={r.reasons} warnings={r.warnings}")
    print("anomalies:", dict(Counter(a for o in index.all() for a in o.anomalies)))
    owners = Counter(index.owner(rid).basis for rid in index.resources())
    print("owner resolution by basis:", dict(sorted(owners.items())))

    # ---- identity (Stage 5): counts and IDs only ----
    resolver = IdentityResolver(ds)
    outcomes = Counter()
    unresolved = []
    for req in sorted(ds.all_requests(), key=lambda r: config.ROW_SORT_KEY(r["case_id"])):
        subj = resolver.resolve(req["email"], as_of=req["_audit_at"])
        if isinstance(subj, Subject):
            outcomes[f"{req['_source']}:{subj.request_email_kind}"] += 1
        else:
            outcomes[f"{req['_source']}:{type(subj).__name__}"] += 1
            unresolved.append((req["case_id"], type(subj).__name__))
    print("subject resolution (as_of=audit_at):", dict(sorted(outcomes.items())))
    print("unresolved/ambiguous subjects:", unresolved or "none")
    links, unparsed = resolver.catalog_links(ds.activities)
    print("catalog identity claims:", dict(sorted(Counter(l.status for l in links).items())),
          "unparsed:", list(unparsed))
    for l in links:
        if l.status != "CONSISTENT":
            print(f"  claim {l.activity_id} on {l.resource_id}: {l.status}")
    attributions = Counter()
    for o in index.all():
        for h in o.identifiers:
            attributions[resolver.attribute(h, o.observed_at or o.file_captured_at).status] += 1
    print("identifier-hit attribution:", dict(sorted(attributions.items())))
    conflicts = resolver.record_conflicts(index.all())
    print("record-level identity conflicts:", [(c.obs_id, c.users) for c in conflicts] or "none")

    # ---- scope (Stage 6): counts and IDs only; no state, no outcomes ----
    builder = ScopeBuilder(ds, index, resolver)
    inc, exc, rel_only = Counter(), Counter(), Counter()
    late_only, no_scope, episode = 0, [], []
    for req in sorted(ds.all_requests(), key=lambda r: (r["_source"], config.ROW_SORT_KEY(r["case_id"]))):
        sc = builder.build(req)
        for d in sc.included.values():
            inc[d.code.value] += 1
            rels = {l.relationship for l in d.subject_links}
            if len(rels) == 1:
                rel_only[next(iter(rels))] += 1
            if all(ReportNote.LINK_EVIDENCE_POST_CUTOFF in l.notes for l in d.subject_links):
                late_only += 1
        for d in sc.excluded.values():
            exc[d.code.value] += 1
        if not sc.included:
            no_scope.append(req["case_id"])
        if sc.episode_start is not None:
            episode.append((req["case_id"], sorted(r for r, d in sc.excluded.items()
                                                   if d.code == ScopeCode.EARLIER_EPISODE)))
    print("scope included by code:", dict(sorted(inc.items())))
    print("scope excluded by code:", dict(sorted(exc.items())))
    print("included resources supported by a single relationship type:", dict(sorted(rel_only.items())))
    print(f"included resources whose links are all late-captured (link-only, no state proof): {late_only}")
    print(f"cases with no in-scope resource: {len(no_scope)} {no_scope}")
    print("episode-bounded cases (prior_request) and excluded resources:", episode)
    claim_sizes = Counter("unique" if len(v) == 1 else "shared" for v in builder._claimants.values())
    print("workflow-claimed resources (candidates only):", dict(claim_sizes))

    # ---- resource state and policy (Stage 7): per in-scope resource; no case decisions ----
    capture = {m["file_id"]: m["_captured_at"] for m in ds.manifest}
    acts = {}
    for a in ds.activities:
        acts.setdefault(a["resource_id"], []).append(a)
    verdicts, reasons, cats, by_cat, conds, owners_amb = Counter(), Counter(), Counter(), Counter(), Counter(), 0
    unexpressible, scope_cache = 0, {}
    for req in sorted(ds.all_requests(), key=lambda r: (r["_source"], config.ROW_SORT_KEY(r["case_id"]))):
        sc = builder.build(req)
        for rid in sorted(sc.included):
            a = assess(rid, req["_audit_at"], sc.subject.user_id, index, resolver, acts.get(rid, []),
                       capture, scope_cache)
            verdicts[a.verdict] += 1
            cats[a.category.value or f"UNKNOWN({a.category.reason.value})"] += 1
            by_cat[(a.category.value or "-", a.verdict)] += 1
            for r in a.reasons:
                reasons[getattr(r, "value", r)] += 1
            if a.condition is not None:
                conds[(a.condition.rule, a.condition.value)] += 1
            if a.owner.system_id is None:
                owners_amb += 1
            if a.verdict == "VIOLATION_PROVEN" and not a.expressible:
                unexpressible += 1
    print(f"resource assessments (in-scope, all 550 inputs): {sum(verdicts.values())}  copy scope: {config.COPY_SCOPE}")
    print("verdicts:", dict(sorted(verdicts.items())))
    print("categories:", dict(sorted(cats.items())))
    print("verdict by category:", {f"{c}/{v}": n for (c, v), n in sorted(by_cat.items())})
    print("unknown / special reasons:", dict(sorted(reasons.items())))
    print("conditions (rule, value):", {f"{r}:{v}": n for (r, v), n in sorted(conds.items())})
    print(f"violations with no output operation (RETAINED_RECORD_MISSING): {unexpressible}")
    print(f"in-scope resources with ambiguous owner system: {owners_amb}")
    print("evidence gaps admissible-by-capture are not readable:", [g[0] for g in index.gaps()])
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ghost Data Still Exists — deletion audit (Stages 0–4)")
    parser.add_argument("command", choices=["inspect"])
    parser.add_argument("--dataset", default=str(config.DATASET_DIR))
    args = parser.parse_args(argv)
    return cmd_inspect(args)


if __name__ == "__main__":
    sys.exit(main())
