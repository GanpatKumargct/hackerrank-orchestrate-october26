"""Public-sample metrics and step alignment (plan G.3.1–G.3.2). Evaluation only.

A held case is never correct and contributes no predicted steps. All numbers are
computed from results; nothing here estimates a hidden-test score.
"""
from collections import Counter, defaultdict

FIELDS = ("operation", "system_id", "state", "evidence_id")


def key_k(s):
    return (s["operation"], s["system_id"], s["resource_id"])


def key_k2(s):
    return (s["resource_id"], s["phase"])


def align(pred, exp, keyf):
    """Pair the k-th occurrence of a key on one side with the k-th on the other (G.3.1 rule 2)."""
    by_p, by_e = defaultdict(list), defaultdict(list)
    for s in pred:
        by_p[keyf(s)].append(s)
    for s in exp:
        by_e[keyf(s)].append(s)
    pairs = []
    for k in by_e:
        for p, e in zip(by_p.get(k, []), by_e[k]):
            pairs.append((p, e))
    return pairs


def strict(p, e):
    return key_k(p) == key_k(e) and all(p[f] == e[f] for f in ("phase", "state", "evidence_id"))


def lcs(a, b):
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[-1]))
        prev = cur
    return prev[-1]


def _tuple(s):
    return (s["phase"], s["system_id"], s["resource_id"], s["operation"], s["state"], s["evidence_id"])


def case_metrics(pred_status, pred_steps, exp_status, exp_steps):
    """pred_status is None for a held case."""
    pred_steps = list(pred_steps) if pred_status is not None else []
    k_pairs = align(pred_steps, exp_steps, key_k)
    strict_matches = sum(1 for p, e in k_pairs if strict(p, e))
    k2_pairs = align(pred_steps, exp_steps, key_k2)
    field_hits = {f: sum(1 for p, e in k2_pairs if p[f] == e[f]) for f in FIELDS}
    cite_pairs = [(p, e) for p, e in k_pairs
                  if e["phase"] == "FINDING" or (exp_status == "COMPLETE" and e["phase"] == "VERIFICATION")]
    exp_res = {s["resource_id"] for s in exp_steps}
    pred_res = {s["resource_id"] for s in pred_steps}
    pt, et = [_tuple(s) for s in pred_steps], [_tuple(s) for s in exp_steps]
    denom = max(len(pt), len(et))
    return {
        "expected_status": exp_status,
        "predicted_status": pred_status or "HELD",
        "status_correct": pred_status == exp_status,
        "pred_steps": len(pred_steps), "exp_steps": len(exp_steps), "strict_matches": strict_matches,
        "k2_pairs": len(k2_pairs), "field_hits": field_hits,
        "citation_pairs": len(cite_pairs), "citation_hits": sum(1 for p, e in cite_pairs
                                                               if p["evidence_id"] == e["evidence_id"]),
        "sequence_exact": pt == et,
        "sequence_lcs_ratio": (lcs(pt, et) / denom) if denom else 1.0,
        "resource_coverage": (len(pred_res & exp_res) / len(exp_res)) if exp_res else 1.0,
        "unexpected_resources": sorted(pred_res - exp_res),
    }


def _ratio(n, d):
    return round(n / d, 4) if d else None


def aggregate(per_case):
    cases = list(per_case.values())
    n = len(cases)
    tp = sum(c["strict_matches"] for c in cases)
    pp = sum(c["pred_steps"] for c in cases)
    ep = sum(c["exp_steps"] for c in cases)
    prec, rec = _ratio(tp, pp), _ratio(tp, ep)
    f1 = round(2 * prec * rec / (prec + rec), 4) if prec and rec else (0.0 if pp or ep else None)
    k2 = sum(c["k2_pairs"] for c in cases)
    confusion = Counter((c["expected_status"], c["predicted_status"]) for c in cases)
    return {
        "cases": n,
        "status_accuracy": _ratio(sum(c["status_correct"] for c in cases), n),
        "confusion": {f"{e}->{p}": v for (e, p), v in sorted(confusion.items())},
        "false_complete": sum(1 for c in cases if c["predicted_status"] == "COMPLETE"
                              and c["expected_status"] != "COMPLETE"),
        "held_rate": _ratio(sum(1 for c in cases if c["predicted_status"] == "HELD"), n),
        "step_precision": prec, "step_recall": rec, "step_f1": f1,
        "predicted_steps": pp, "expected_steps": ep, "strict_matches": tp,
        "field_accuracy": {f: _ratio(sum(c["field_hits"][f] for c in cases), k2) for f in FIELDS},
        "field_aligned_pairs": k2,
        "sequence_exact": _ratio(sum(c["sequence_exact"] for c in cases), n),
        "sequence_lcs_mean": _ratio(sum(c["sequence_lcs_ratio"] for c in cases), n),
        "citation_accuracy": _ratio(sum(c["citation_hits"] for c in cases), sum(c["citation_pairs"] for c in cases)),
        "resource_coverage_mean": _ratio(sum(c["resource_coverage"] for c in cases), n),
        "unexpected_resources": sum(len(c["unexpected_resources"]) for c in cases),
    }
