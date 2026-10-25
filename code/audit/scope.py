"""M5 — resource links and case scope (plan C.5, C.6, C.7, E.2; Stage 6).

Produces, for one request, a CaseScope: every candidate resource gets an explicit
include/exclude decision with reason code and the links behind it. Links keep
their source, time, relationship and confidence. Nothing here decides state.

Never identity proof here: reporter_service, manifest origin, resource prefixes,
timing, or a query key on its own. Trace keys link only under the C.5.2 condition
(config.TRACE_KEY_LINKS). Catalog claims are MEDIUM claims. Workflow correlations
are candidates and never enter scope (A.8.1 Q-WEAK-VERIFY = No).
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from . import config
from .admissibility import admissible_claim, admissible_for_link, is_late_link_only, time_of
from .errors import ReportNote, ScopeCode
from .identity import Subject

STRONG, MEDIUM, CANDIDATE = "STRONG", "MEDIUM", "CANDIDATE"


@dataclass(frozen=True)
class Link:
    resource_id: str
    subject: str
    relationship: str            # RECORD_FIELD | TRACE_KEY | FREE_TEXT_MENTION | DERIVED_FROM | CATALOG_CLAIM
    confidence: str              # STRONG | MEDIUM
    source: str                  # obs_id or activity_id
    file_id: Optional[str]
    observed_at: object          # observation time (or claim event time)
    identifier: Optional[str]    # "kind:normalised" that carried the link
    notes: tuple = ()


@dataclass(frozen=True)
class ScopeDecision:
    resource_id: str
    included: bool
    code: str                    # ScopeCode value
    subject_links: tuple
    other_links: tuple
    notes: tuple = ()


@dataclass
class CaseScope:
    case_id: str
    subject: object
    audit_at: object
    episode_start: object
    included: dict = field(default_factory=dict)     # rid -> ScopeDecision
    excluded: dict = field(default_factory=dict)     # rid -> ScopeDecision
    workflow_candidates: dict = field(default_factory=dict)   # rid -> (activity ids)
    ambiguous_workflow: dict = field(default_factory=dict)    # rid -> claimant case ids
    claims: tuple = ()                                # catalog claims considered (any status)
    notes: list = field(default_factory=list)


def _ident(h):
    return f"{h.kind}:{h.normalised}"


class ScopeBuilder:
    def __init__(self, dataset, index, resolver):
        self.ds, self.index, self.resolver = dataset, index, resolver
        self.requests = sorted(dataset.all_requests(), key=lambda r: (r["_source"], r["case_id"]))
        self._request_user = {}
        for r in self.requests:                                   # each request's subject at its own cutoff
            s = resolver.resolve(r["email"], as_of=r["_audit_at"])
            self._request_user[(r["_source"], r["case_id"])] = s.user_id if isinstance(s, Subject) else None
        self._grounded_anyone = self._resources_grounded_to_anyone()
        self._claimants = self._workflow_claimants()

    # ---- C.6 workflow candidates (global, claims only) -----------------------
    def _resources_grounded_to_anyone(self):
        out = set()
        for o in self.index.all():
            when = time_of(o)
            for h in o.identifiers + (o.keys if config.TRACE_KEY_LINKS else ()):
                if h.relationship == "QUERY_KEY":
                    continue
                if self.resolver.attribute(h, when).status == "ATTRIBUTED":
                    out.add(o.resource_id)
                    break
            for rel, target in o.related_ids:
                out.add(target)                                   # FK target of an observed record
        links, _ = self.resolver.catalog_links(self.ds.activities)
        out.update(l.resource_id for l in links if l.status == "CONSISTENT")
        return frozenset(out)

    def _workflow_window(self, req):
        return req["_requested_at"], req["_reported_at"] + timedelta(hours=config.WORKFLOW_WINDOW_HOURS)

    def _workflow_claimants(self):
        acts = [a for a in self.ds.activities
                if a["source_system"] == config.WORKFLOW_SOURCE_SYSTEM
                and a["event_type"] in config.WORKFLOW_EVENT_TYPES
                and a["resource_id"] not in self._grounded_anyone]
        acts.sort(key=lambda a: a["_event_time"])
        claim = defaultdict(lambda: defaultdict(list))            # rid -> case_key -> [activity ids]
        for req in self.requests:
            lo, hi = self._workflow_window(req)
            key = (req["_source"], req["case_id"])
            for a in acts:
                t = a["_event_time"]
                if lo <= t <= hi and t <= req["_audit_at"]:
                    claim[a["resource_id"]][key].append(a["activity_id"])
        return {rid: dict(v) for rid, v in claim.items()}

    # ---- E.2.2 episode boundary ---------------------------------------------
    def episode_start(self, req, subject):
        if config.EPISODE_MODE != "prior_request" or not isinstance(subject, Subject):
            return None if config.EPISODE_MODE == "prior_request" else req["_requested_at"]
        prior = [other["_audit_at"] for other in self.requests
                 if other is not req
                 and self._request_user[(other["_source"], other["case_id"])] == subject.user_id
                 and other["_audit_at"] < req["_requested_at"]]
        return max(prior) if prior else None

    # ---- C.5 links -----------------------------------------------------------
    def _subject_links(self, subject, audit_at):
        links = defaultdict(list)
        late = config.LATE_INNER_LINKING
        for kind, value in sorted(subject.identifiers):
            for rel_set, rels in ((("RECORD_FIELD", "FREE_TEXT_MENTION"), "identifiers"),
                                  (("TRACE_KEY",), "keys")):
                if rels == "keys" and not config.TRACE_KEY_LINKS:
                    continue
                pool = (self.index.by_identifier(kind, value, rel_set) if rels == "identifiers"
                        else self.index.by_key(kind, value, rel_set))
                for o in pool:
                    if not admissible_for_link(o, audit_at, late):
                        continue
                    when = time_of(o)
                    hits = o.identifiers if rels == "identifiers" else o.keys
                    for h in hits:
                        if (h.kind, h.normalised) != (kind, value) or h.relationship not in rel_set:
                            continue
                        att = self.resolver.attribute(h, when)
                        if att.status != "ATTRIBUTED" or att.user_id != subject.user_id:
                            continue
                        if h.relationship == "TRACE_KEY" and self._record_names_other(o, subject.user_id, when):
                            continue                                    # own identifier wins (C.5.2)
                        notes = tuple(att.notes)
                        if is_late_link_only(o, audit_at, late):
                            notes += (ReportNote.LINK_EVIDENCE_POST_CUTOFF,)
                        conf = MEDIUM if h.relationship == "FREE_TEXT_MENTION" else STRONG
                        links[o.resource_id].append(Link(o.resource_id, subject.user_id, h.relationship, conf,
                                                         o.obs_id, o.file_id, when, _ident(h), notes))
        # DERIVED_FROM: MEDIUM link for the referenced resource of a STRONG-linked record
        for rid in list(links):
            for lk in [l for l in links[rid] if l.confidence == STRONG]:
                for rel, target in self.index.get(lk.source).related_ids:
                    if rel == "DERIVED_FROM":
                        links[target].append(Link(target, subject.user_id, "DERIVED_FROM", MEDIUM, lk.source,
                                                  lk.file_id, lk.observed_at, None, lk.notes))
        return links

    def _record_names_other(self, obs, user_id, when):
        for h in obs.identifiers:
            if h.relationship == "RECORD_FIELD":
                att = self.resolver.attribute(h, when)
                if att.status == "ATTRIBUTED" and att.user_id != user_id:
                    return True
        return False

    def _other_links(self, rid, user_id, audit_at):
        out = []
        late = config.LATE_INNER_LINKING
        for o in self.index.by_resource(rid):
            if not admissible_for_link(o, audit_at, late):
                continue
            when = time_of(o)
            hits = list(o.identifiers) + ([h for h in o.keys if h.relationship == "TRACE_KEY"]
                                          if config.TRACE_KEY_LINKS else [])
            for h in hits:
                att = self.resolver.attribute(h, when)
                if att.status != "ATTRIBUTED" or att.user_id == user_id:
                    continue
                if h.relationship == "TRACE_KEY" and self._record_names_other(o, att.user_id, when):
                    continue
                conf = MEDIUM if h.relationship == "FREE_TEXT_MENTION" else STRONG
                out.append(Link(rid, att.user_id, h.relationship, conf, o.obs_id, o.file_id, when, _ident(h)))
        return out

    # ---- C.5.3 decision -----------------------------------------------------
    @staticmethod
    def _decide(rid, ls_all, ls, lo, episode_start):
        if not ls_all:
            return ScopeDecision(rid, False, ScopeCode.LINKED_TO_OTHER_SUBJECT, (), tuple(lo))
        if not ls:
            return ScopeDecision(rid, False, ScopeCode.EARLIER_EPISODE, tuple(ls_all), tuple(lo),
                                 (f"all subject links at or before episode start {episode_start}",))
        strong = [l for l in ls if l.confidence == STRONG]
        other_strong = [l for l in lo if l.confidence == STRONG]
        if not lo:
            if strong:
                code = ScopeCode.GROUNDED_DIRECT if any(l.relationship == "RECORD_FIELD" for l in strong) \
                    else ScopeCode.GROUNDED_TRACE
            else:
                rels = {l.relationship for l in ls}
                code = (ScopeCode.GROUNDED_FK if "DERIVED_FROM" in rels else
                        ScopeCode.CONTAINS_SUBJECT_PII if "FREE_TEXT_MENTION" in rels else ScopeCode.CATALOG)
            return ScopeDecision(rid, True, code, tuple(ls), ())
        if all(l.relationship == "CATALOG_CLAIM" for l in ls) and other_strong:
            return ScopeDecision(rid, False, ScopeCode.CATALOG_CONTRADICTED, tuple(ls), tuple(lo))
        shared_sources = {l.source for l in ls} & {l.source for l in lo}
        same_times = {l.observed_at for l in ls} & {l.observed_at for l in lo}
        code = ScopeCode.SHARED_RESOURCE if (shared_sources or same_times) else ScopeCode.OWNERSHIP_CHANGED
        return ScopeDecision(rid, True, code, tuple(ls), tuple(lo))

    # ---- public --------------------------------------------------------------
    def build(self, req):
        audit_at = req["_audit_at"]
        subject = self.resolver.resolve(req["email"], as_of=audit_at)
        scope = CaseScope(req["case_id"], subject, audit_at, None)
        if not isinstance(subject, Subject):
            scope.notes.append(f"identity not resolved: {type(subject).__name__}; scope not built (E.2.1)")
            return scope
        start = self.episode_start(req, subject)
        scope.episode_start = start
        links = self._subject_links(subject, audit_at)
        claims, _ = self.resolver.catalog_links(
            [a for a in self.ds.activities if admissible_claim(a, audit_at)], as_of=audit_at)
        scope.claims = claims
        for c in claims:
            if c.status == "CONSISTENT" and c.claimed_user == subject.user_id:
                links[c.resource_id].append(Link(c.resource_id, subject.user_id, "CATALOG_CLAIM", MEDIUM,
                                                 c.activity_id, None, c.event_time, f"email:{c.email}"))
            elif c.claimed_user == subject.user_id or subject.user_id in c.email_owners:
                scope.notes.append(f"catalog claim {c.activity_id} on {c.resource_id} not used: {c.status}")
        key = (req["_source"], req["case_id"])
        candidates = set(links)
        for rid in sorted(candidates):
            ls_all = sorted(links[rid], key=lambda l: (l.source, l.relationship))
            ls = [l for l in ls_all if start is None or l.observed_at > start]
            lo = self._other_links(rid, subject.user_id, audit_at)
            # catalog claims naming another user for this resource
            lo += [Link(c.resource_id, c.claimed_user, "CATALOG_CLAIM", MEDIUM, c.activity_id, None,
                        c.event_time, f"email:{c.email}")
                   for c in claims if c.resource_id == rid and c.status == "CONSISTENT"
                   and c.claimed_user != subject.user_id]
            d = self._decide(rid, ls_all, ls, sorted(lo, key=lambda l: l.source), start)
            (scope.included if d.included else scope.excluded)[rid] = d
        for rid, claimants in sorted(self._claimants.items()):
            if key not in claimants or rid in scope.included:
                continue
            if len(claimants) == 1:
                scope.workflow_candidates[rid] = tuple(claimants[key])
                scope.excluded.setdefault(rid, ScopeDecision(rid, False, ScopeCode.WEAK_LINK_ONLY, (), (),
                                                             ("workflow correlation only (C.6)",)))
            else:
                scope.ambiguous_workflow[rid] = tuple(sorted(c for _, c in claimants))
                scope.excluded.setdefault(rid, ScopeDecision(rid, False, ScopeCode.AMBIGUOUS_WORKFLOW, (), (),
                                                             (f"{len(claimants)} claimant cases",)))
        return scope
