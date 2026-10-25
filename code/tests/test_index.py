import unittest

from audit.evidence.common import make_observation
from audit.evidence.index import ObservationIndex
from audit.models import CoverageUnit, FileExtraction
from tests.fixtures import manifest_row


def o(file_id, locator, rid, fields=None, observed=None, related=(), trace=None):
    return make_observation(manifest_row=manifest_row("x.log", file_id=file_id), fmt="log",
                            locator=locator, resource_id=rid, fields=fields or {}, observed_raw=observed,
                            related_ids=related, context={"trace_id": trace} if trace else None)


class TestObservationIndex(unittest.TestCase):
    def setUp(self):
        self.a = o("evidence_b", "l2", "search_90090", {"email": "e@example.org"}, "2026-05-09T10:00:00Z")
        self.b = o("evidence_a", "l1", "search_90090", {"email": "e@example.org"}, "2026-05-08T10:00:00Z")
        self.c = o("evidence_a", "l3", "account_90090", {"lookup_key": "e@example.org"}, trace="t1")
        self.d = o("evidence_c", "l4", "search_90091", {"query": "e@example.org"},
                   related=(("DERIVED_FROM", "account_90090"),))
        rep = FileExtraction("evidence_c", "p", "sql")
        rep.coverage.append(CoverageUnit("evidence_c", "COLLECTION", "account_service", "customer_profiles",
                                         "primary", None, frozenset(), "t"))
        gap = FileExtraction("evidence_z", "p", "png", status="FAILED", reasons=["gap"])
        self.idx = ObservationIndex([self.a, self.b, self.c, self.d], {"evidence_c": rep, "evidence_z": gap})

    def test_deterministic_order_and_no_merge(self):
        self.assertEqual([x.obs_id for x in self.idx.all()],
                         [self.b.obs_id, self.c.obs_id, self.a.obs_id, self.d.obs_id])
        same = self.idx.by_resource("search_90090")
        self.assertEqual(len(same), 2)                                   # two times kept separately
        self.assertEqual([x.observed_raw for x in same], ["2026-05-08T10:00:00Z", "2026-05-09T10:00:00Z"])
        self.assertIs(same[0], self.b)                                   # original object, provenance intact
        rebuilt = ObservationIndex([self.d, self.c, self.b, self.a])
        self.assertEqual([x.obs_id for x in rebuilt.all()], [x.obs_id for x in self.idx.all()])

    def test_duplicate_observation_id_rejected(self):
        with self.assertRaises(ValueError):
            ObservationIndex([self.a, o("evidence_b", "l2", "search_90099")])

    def test_identifier_lookup_excludes_trace_and_query_keys(self):
        ids = self.idx.by_identifier("email", "e@example.org")
        self.assertEqual({x.obs_id for x in ids}, {self.a.obs_id, self.b.obs_id})
        keys = self.idx.by_key("email", "e@example.org")
        self.assertEqual({x.obs_id for x in keys}, {self.c.obs_id, self.d.obs_id})
        self.assertEqual(self.idx.by_key("email", "e@example.org", relationships=("QUERY_KEY",)), (self.d,))
        self.assertEqual(self.idx.by_identifier("email", "missing@example.org"), ())

    def test_trace_related_coverage_and_gaps(self):
        self.assertEqual(self.idx.by_trace("evidence_a", "t1"), (self.c,))
        self.assertEqual(self.idx.referencing("account_90090"), (("DERIVED_FROM", self.d),))
        self.assertEqual(len(self.idx.coverage("account_service", "customer_profiles")), 1)
        self.assertEqual(self.idx.gaps(), (("evidence_z", "png", "FAILED", ("gap",)),))
        self.assertEqual(self.idx.file_status("evidence_z"), "FAILED")

    def test_lookups_are_immutable_tuples(self):
        self.assertIsInstance(self.idx.by_resource("search_90090"), tuple)
        self.assertEqual(self.idx.by_resource("unknown_90000"), ())


if __name__ == "__main__":
    unittest.main()
