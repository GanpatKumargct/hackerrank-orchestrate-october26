"""Owner (`system_id`) resolution — plan F.1.3, A.8.1 Q-OWNER-RESOLUTION.

Order: (1) explicit, valid owner field; (2) evidence-backed reporter alias;
(3) reporter_service exactly equal to a canonical system ID. Prefixes, partial or
similar names and timing never decide. Absent or conflicting → SYSTEM_AMBIGUOUS.
This is owner resolution only: reporter_service never creates an identity link.
"""
from dataclasses import dataclass

from . import config
from .errors import HeldReason


@dataclass(frozen=True)
class OwnerResolution:
    system_id: object           # str or None
    basis: str                  # EXPLICIT | ALIAS | REPORTER_EXACT | AMBIGUOUS
    reason: object              # HeldReason.SYSTEM_AMBIGUOUS or None
    candidates: tuple           # sorted candidate systems considered at the deciding rule
    notes: tuple                # e.g. ignored non-canonical owners, overridden reporter readings
    evidence: tuple             # obs_ids that supplied the deciding values


def _reporter_candidate(service):
    if service in config.SYSTEM_ALIASES:
        return config.SYSTEM_ALIASES[service], "ALIAS"
    if service in config.CANONICAL_SYSTEMS:
        return service, "REPORTER_EXACT"
    return None, None


def resolve_owner(observations):
    """Resolve the owner of one resource from all its observations."""
    observations = sorted(observations, key=lambda o: o.obs_id)
    explicit, notes = {}, []
    for o in observations:
        if o.system_id is None:
            continue
        if o.system_id in config.CANONICAL_SYSTEMS:
            explicit.setdefault(o.system_id, []).append(o.obs_id)
        else:
            notes.append(f"non-canonical explicit owner {o.system_id!r} ignored ({o.obs_id})")
    reporter = {}
    for o in observations:
        if o.reporter_service:
            system, basis = _reporter_candidate(o.reporter_service)
            if system:
                reporter.setdefault((system, basis), []).append(o.obs_id)
            elif not explicit:
                notes.append(f"reporter {o.reporter_service!r} is not canonical/aliased ({o.obs_id})")

    if explicit:
        if len(explicit) == 1:
            system = next(iter(explicit))
            for (other, _), ids in sorted(reporter.items()):
                if other != system:
                    notes.append(f"reporter-derived {other!r} overridden by explicit owner ({ids[0]})")
            return OwnerResolution(system, "EXPLICIT", None, (system,), tuple(notes), tuple(explicit[system]))
        return OwnerResolution(None, "AMBIGUOUS", HeldReason.SYSTEM_AMBIGUOUS, tuple(sorted(explicit)),
                               tuple(notes + ["conflicting explicit owners"]),
                               tuple(i for ids in explicit.values() for i in ids))

    systems = sorted({s for s, _ in reporter})
    if len(systems) == 1:
        bases = sorted({b for s, b in reporter})
        basis = "ALIAS" if "ALIAS" in bases else "REPORTER_EXACT"
        ids = tuple(i for (s, _), v in sorted(reporter.items()) for i in v)
        return OwnerResolution(systems[0], basis, None, tuple(systems), tuple(notes), ids)
    why = "conflicting reporter-derived owners" if systems else "no explicit owner, alias or canonical reporter"
    return OwnerResolution(None, "AMBIGUOUS", HeldReason.SYSTEM_AMBIGUOUS, tuple(systems),
                           tuple(notes + [why]), ())
