"""D.4 remediation dependency edges and their validation (plan D.4, F.1.4, A.8.1 Q-DEP; Stage 9).

Edges come only from explicit evidence or admissible claims, and they affect
ordering validation only — never scope, state or step content. D1 (disable or
block before the dependent record change) is an error when violated. D2
(downstream copy before its source) is reported as DEPENDENCY_ORDER_CONFLICT;
the output keeps the contract sort order (Q-DEP).
"""
import re
from dataclasses import dataclass

from . import config
from .admissibility import admissible_claim, admissible_for_state

RECORD_CHANGE = frozenset({"DELETE_RECORD", "REDACT_RECORD", "ANONYMIZE_RECORD"})
_RESTORED = re.compile(r"downstream resource ([a-z_]+_\d+)")


@dataclass(frozen=True)
class DependencyEdge:
    upstream: str
    downstream: str
    type: str          # RECREATES | RESTORES | REPLICATES | DERIVED_FROM
    basis: str         # obs_id or activity_id
    rule: str          # D1 | D2


def build_edges(scope_ids, owners, index, activities, audit_at):
    """Edges among this case's in-scope resources.

    scope_ids: in-scope resource ids; owners: rid -> system_id (or None).
    """
    scope_ids = set(scope_ids)
    by_system = {}
    for rid in scope_ids:
        if owners.get(rid):
            by_system.setdefault(owners[rid], set()).add(rid)
    edges = set()
    for rid in sorted(scope_ids):
        for o in index.by_resource(rid):
            if not admissible_for_state(o, audit_at):
                continue
            for rel, target in o.related_ids:              # source_resource_id foreign key
                if rel == "DERIVED_FROM" and target in scope_ids and target != rid:
                    edges.add(DependencyEdge(target, rid, "DERIVED_FROM", o.obs_id, "D2"))
            target_system = (config.CONNECTOR_TARGETS.get(o.fields.get("connector_name"))
                             or config.DESTINATION_TARGETS.get(o.fields.get("destination")))
            if target_system:
                for down in sorted(by_system.get(target_system, ())):
                    if down != rid:
                        edges.add(DependencyEdge(rid, down, "RECREATES", o.obs_id, "D1"))
    for a in activities:
        if not admissible_claim(a, audit_at):
            continue
        if a["event_type"] == "RESTORE_BACKUP" and a["resource_id"] in scope_ids:
            for down in _RESTORED.findall(a.get("details", "")):
                if down in scope_ids:
                    edges.add(DependencyEdge(a["resource_id"], down, "RESTORES", a["activity_id"], "D1"))
        if a["event_type"] == "SYNC_RECORD" and a["resource_id"] in scope_ids:
            # the claim names the source system only: system-level edge to that system's in-scope resources
            for up in sorted(by_system.get(a["source_system"], ())):
                if up != a["resource_id"]:
                    edges.add(DependencyEdge(up, a["resource_id"], "REPLICATES", a["activity_id"], "D2"))
    return tuple(sorted(edges, key=lambda e: (e.upstream, e.downstream, e.type, e.basis)))


def check_order(steps, edges):
    """Return (d1_errors, d2_conflicts) for an ordered step list."""
    pos = {}
    for i, s in enumerate(steps):
        if s["phase"] == "REMEDIATION":
            pos.setdefault(s["resource_id"], []).append((i, s["operation"]))
    errors, conflicts = [], []
    for e in edges:
        if e.upstream not in pos or e.downstream not in pos:
            continue                                        # both ends must be remediated
        up = [i for i, op in pos[e.upstream]]
        down = [i for i, op in pos[e.downstream] if op in RECORD_CHANGE]
        if not down:
            continue
        if e.rule == "D1":
            if any(op not in ("DISABLE_DATA_FLOW", "BLOCK_RESTORE") for _, op in pos[e.upstream]):
                continue                                    # upstream is not a recreation path here
            if max(up) > min(down):
                errors.append(f"D1 {e.type} {e.upstream} -> {e.downstream} ({e.basis}): "
                              f"recreation path not disabled before the record change")
        elif e.rule == "D2":
            if not any(op in RECORD_CHANGE for _, op in pos[e.upstream]):
                continue
            if min(i for i, op in pos[e.upstream] if op in RECORD_CHANGE) < min(down):
                conflicts.append(f"DEPENDENCY_ORDER_CONFLICT {e.type} {e.upstream} -> {e.downstream} "
                                 f"({e.basis}): source precedes downstream copy in the contract order")
    return errors, conflicts
