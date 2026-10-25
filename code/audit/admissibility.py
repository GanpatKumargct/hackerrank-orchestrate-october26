"""Evidence admissibility at a case cutoff (plan C.7, A.4.4; A.8.1 Q-LATE-LINK).

Capture time and observation time are kept distinct. A late-captured file whose
inner observation time is at or before the cutoff may support identity/scope
linking only (when late_inner_linking is on) — never state or citation.
"""


def time_of(obs):
    """Observation time used for cutoff checks: inner time if present, else file capture."""
    return obs.observed_at if obs.observed_at is not None else obs.file_captured_at


def admissible_for_state(obs, audit_at):
    if obs.file_captured_at is None:                 # manifest guarantees presence; defensive
        return False
    if obs.file_captured_at > audit_at:              # post-cutoff file: never proves state
        return False
    if "observed_after_capture" in obs.anomalies:    # inconsistent provenance: not state proof
        return False
    if time_of(obs) > audit_at:                      # observation itself after cutoff
        return False
    return True


def admissible_for_citation(obs, audit_at):
    return admissible_for_state(obs, audit_at)        # identical by design (A.2)


def admissible_for_link(obs, audit_at, late_inner_linking):
    if admissible_for_state(obs, audit_at):
        return True
    if not late_inner_linking:
        return False
    if obs.observed_at is None:                      # no inner time -> cannot pre-date the cutoff
        return False
    if obs.observed_at > audit_at:
        return False
    if "observed_after_capture" in obs.anomalies:
        return False
    return obs.file_captured_at > audit_at           # late file, inner time <= cutoff: link only


def is_late_link_only(obs, audit_at, late_inner_linking):
    """True when the observation is usable for linking only through the late-inner path."""
    return (admissible_for_link(obs, audit_at, late_inner_linking)
            and not admissible_for_state(obs, audit_at))


def admissible_claim(activity, audit_at):
    """Activities are claims; admissible as claims only if they happened by the cutoff."""
    return activity["_event_time"] <= audit_at


def admissibility_set(obs, audit_at, late_inner_linking):
    """The B.4.1 EvidenceRef.admissible set for this case's cutoff."""
    out = set()
    if admissible_for_state(obs, audit_at):
        out.update({"state", "citation", "link"})
    elif admissible_for_link(obs, audit_at, late_inner_linking):
        out.add("link")
    return frozenset(out)
