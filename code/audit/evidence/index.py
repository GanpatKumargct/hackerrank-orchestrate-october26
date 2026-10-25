"""ObservationIndex (plan B.5 M2, Stage 4).

Deterministic lookups over parsed observations. The index only *finds* evidence;
it never merges observations, never decides state, and never turns a key match
into an identity link:
  * by_identifier  — RECORD_FIELD / FREE_TEXT_MENTION hits (candidates for C.5 links)
  * by_key         — TRACE_KEY / QUERY_KEY hits, kept separate; their linkage
                     meaning is decided by C.5.2 (QUERY_KEY alone never links)
Every lookup returns a tuple ordered by (file_id, locator); each element is the
original Observation with its provenance and timestamps untouched.
"""
from collections import defaultdict

from ..ownership import resolve_owner

IDENTITY_RELATIONSHIPS = ("RECORD_FIELD", "FREE_TEXT_MENTION")
KEY_RELATIONSHIPS = ("TRACE_KEY", "QUERY_KEY")


def _order(o):
    return (o.file_id, o.locator)


class ObservationIndex:
    def __init__(self, observations, reports=None):
        obs = sorted(observations, key=_order)
        seen = {}
        for o in obs:
            if o.obs_id in seen:
                raise ValueError(f"duplicate observation id {o.obs_id!r}: parser produced the same locator twice")
            seen[o.obs_id] = o
        self._by_id = seen
        self._all = tuple(obs)
        self.reports = dict(reports or {})
        by_resource, by_file, by_trace, related = (defaultdict(list) for _ in range(4))
        by_identifier, by_key = defaultdict(list), defaultdict(list)
        for o in obs:
            by_resource[o.resource_id].append(o)
            by_file[o.file_id].append(o)
            trace = o.context.get("trace_id")
            if trace:
                by_trace[(o.file_id, trace)].append(o)
            for rel, target in o.related_ids:
                related[target].append((rel, o))
            for h in o.identifiers:
                if h.normalised is not None:
                    by_identifier[(h.kind, h.normalised)].append((h.relationship, o))
            for h in o.keys:
                if h.normalised is not None:
                    by_key[(h.kind, h.normalised)].append((h.relationship, o))
        freeze = lambda d: {k: tuple(v) for k, v in d.items()}
        self._by_resource, self._by_file, self._by_trace = freeze(by_resource), freeze(by_file), freeze(by_trace)
        self._related, self._by_identifier, self._by_key = freeze(related), freeze(by_identifier), freeze(by_key)
        cov = defaultdict(list)
        for rep in self.reports.values():
            for unit in rep.coverage:
                cov[(unit.system, unit.collection)].append(unit)
        self._coverage = {k: tuple(sorted(v, key=lambda u: (u.file_id, u.locator))) for k, v in cov.items()}

    # ---- basic lookups -------------------------------------------------------
    def __len__(self):
        return len(self._all)

    def all(self):
        return self._all

    def get(self, obs_id):
        return self._by_id[obs_id]

    def resources(self):
        return tuple(sorted(self._by_resource))

    def by_resource(self, resource_id):
        return self._by_resource.get(resource_id, ())

    def by_file(self, file_id):
        return self._by_file.get(file_id, ())

    def by_trace(self, file_id, trace_id):
        return self._by_trace.get((file_id, trace_id), ())

    def referencing(self, resource_id):
        """Observations whose related_ids point at resource_id: ((relationship, obs), …)."""
        return self._related.get(resource_id, ())

    # ---- identifier lookups (candidates only) -------------------------------
    def by_identifier(self, kind, normalised, relationships=IDENTITY_RELATIONSHIPS):
        return tuple(o for rel, o in self._by_identifier.get((kind, normalised), ()) if rel in relationships)

    def by_key(self, kind, normalised, relationships=KEY_RELATIONSHIPS):
        return tuple(o for rel, o in self._by_key.get((kind, normalised), ()) if rel in relationships)

    # ---- coverage and status ------------------------------------------------
    def coverage(self, system, collection):
        return self._coverage.get((system, collection), ())

    def file_status(self, file_id):
        rep = self.reports.get(file_id)
        return rep.status if rep else None

    def gaps(self):
        return tuple(sorted((r.file_id, r.fmt, r.status, tuple(r.reasons))
                            for r in self.reports.values() if r.status != "OK"))

    # ---- owner resolution (F.1.3) -------------------------------------------
    def owner(self, resource_id):
        return resolve_owner(self.by_resource(resource_id))
