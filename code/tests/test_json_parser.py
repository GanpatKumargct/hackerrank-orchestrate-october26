import json
import unittest

from audit.evidence.json_parser import parse_json
from tests.fixtures import TempDir, manifest_row, write_file


class TestJsonParser(unittest.TestCase):
    def parse(self, doc, captured="2026-05-10T12:00:00Z"):
        with TempDir() as d:
            p = write_file(d, "x.json", json.dumps(doc))
            return parse_json(manifest_row(p, captured=captured))

    def test_bundle_snapshots_inner_time_and_coverage(self):
        doc = {"exported_at": "2026-05-10T12:00:00Z", "snapshots": [
            {"captured_at": "2026-05-09T08:00:00Z", "data_store": "account_service",
             "collection": "customer_profiles", "records": []},
            {"captured_at": "2026-05-09T09:00:00Z", "data_store": "search_service",
             "collection": "customer_search_documents",
             "records": [{"resource_id": "search_90003", "index_name": "dir",
                          "document": {"email": "e@example.org", "customer_reference": None}}]},
        ]}
        obs, rep = self.parse(doc)
        self.assertEqual(rep.status, "OK")
        cov = {(c.system, c.collection): c.resource_ids for c in rep.coverage}
        self.assertEqual(cov[("account_service", "customer_profiles")], frozenset())
        o = obs[0]
        self.assertEqual((o.observed_raw, o.time_basis, o.system_id, o.system_field),
                         ("2026-05-09T09:00:00Z", "inner", "search_service", "data_store"))
        self.assertEqual([(h.field, h.normalised) for h in o.identifiers], [("document.email", "e@example.org")])

    def test_service_export_owner_observed_at_and_nested_hits(self):
        doc = {"exported_at": "2026-05-10T12:00:00Z", "service_exports": {"search_service": {"index_queries": [
            {"observed_at": "2026-05-10T10:00:00Z", "query": "q@example.org", "resource_id": "search_90004",
             "hits": {"total": 1, "documents": [{"resource_id": "search_90004", "email": "other@example.org"}]}}]}}}
        obs, _ = self.parse(doc)
        self.assertEqual(len(obs), 2)
        item, hit = obs
        self.assertEqual((item.system_id, item.system_field, item.collection),
                         ("search_service", "service_exports", "index_queries"))
        self.assertEqual([h.relationship for h in item.keys], ["QUERY_KEY"])
        self.assertNotIn("hits.documents[0].email", item.fields)
        self.assertEqual([h.normalised for h in hit.identifiers], ["other@example.org"])
        self.assertEqual([(h.relationship, h.normalised) for h in hit.keys], [("QUERY_KEY", "q@example.org")])
        self.assertEqual(hit.context["parent_query"], "q@example.org")
        self.assertEqual(hit.observed_raw, "2026-05-10T10:00:00Z")   # observed by the parent query
        self.assertEqual(hit.time_basis, "inner")

    def test_ledger_recorded_at_and_explicit_system(self):
        doc = {"exported_at": "2026-05-10T12:00:00Z", "records": [
            {"recorded_at": "2026-05-08T09:00:00Z", "system": "account_service", "resource_id": "account_90006",
             "record_type": "USER_PROFILE", "result": "NOT_FOUND", "subject_reference": "u@example.org"}]}
        obs, _ = self.parse(doc)
        o = obs[0]
        self.assertEqual((o.system_id, o.record_type, o.observed_raw), ("account_service", "USER_PROFILE",
                                                                      "2026-05-08T09:00:00Z"))
        self.assertEqual(o.identifiers[0].field, "subject_reference")

    def test_collection_owner_and_top_level_capture(self):
        doc = {"captured_at": "2026-05-09T09:45:00Z", "collection": "customer_analytics_reports",
               "records": [{"resource_id": "analytics_90007", "user_id": None, "email": None}]}
        obs, _ = self.parse(doc)
        self.assertEqual((obs[0].system_id, obs[0].system_field, obs[0].observed_raw),
                         ("analytics_platform", "collection", "2026-05-09T09:45:00Z"))
        self.assertEqual(obs[0].identifiers, ())

    def test_observed_after_capture_anomaly(self):
        doc = {"records": [{"recorded_at": "2026-05-12T09:00:00Z", "system": "account_service",
                            "resource_id": "account_90008", "result": "FOUND"}]}
        obs, _ = self.parse(doc, captured="2026-05-10T12:00:00Z")
        self.assertEqual(obs[0].anomalies, ("observed_after_capture",))

    def test_invalid_json_fails(self):
        with TempDir() as d:
            p = write_file(d, "x.json", "{not json")
            obs, rep = parse_json(manifest_row(p))
        self.assertEqual((obs, rep.status), ([], "FAILED"))


if __name__ == "__main__":
    unittest.main()
