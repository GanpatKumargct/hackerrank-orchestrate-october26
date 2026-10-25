import json
import unittest

from audit.evidence.sql_parser import parse_sql
from tests.fixtures import TempDir, manifest_row, write_file

HEADER = "-- point-in-time database snapshot\n-- Captured at: 2026-05-10T12:00:00Z\n"


class TestSqlParser(unittest.TestCase):
    def parse(self, body, header=HEADER, captured="2026-05-10T12:00:00Z"):
        with TempDir() as d:
            p = write_file(d, "x.sql", header + body)
            return parse_sql(manifest_row(p, captured=captured))

    def test_inventory_rows_and_system_level_coverage(self):
        body = """
CREATE TABLE snapshot_scope (origin_system TEXT, captured_at TEXT);
INSERT INTO snapshot_scope VALUES ('account_service','2026-05-10T12:00:00Z');
CREATE TABLE customer_profiles (resource_id TEXT, customer_reference TEXT, email TEXT);
INSERT INTO customer_profiles VALUES ('account_90001', NULL, 'a@example.org');
CREATE TABLE customer_search_documents (resource_id TEXT, email TEXT);
INSERT INTO customer_search_documents VALUES ('search_90001', 'a@example.org');
"""
        obs, rep = self.parse(body)
        self.assertEqual(rep.status, "OK")
        self.assertEqual({o.resource_id for o in obs}, {"account_90001", "search_90001"})
        acc = next(o for o in obs if o.resource_id == "account_90001")
        self.assertEqual((acc.system_id, acc.system_field, acc.time_basis), ("account_service", "table", "file"))
        self.assertEqual([h.normalised for h in acc.identifiers], ["a@example.org"])
        cov = {(c.level, c.system, c.collection) for c in rep.coverage}
        self.assertEqual(cov, {("SYSTEM", "account_service", "customer_profiles")})  # search not in scope

    def test_direct_tables_collection_coverage_and_fk(self):
        body = """
CREATE TABLE customer_profiles_primary (resource_id TEXT, user_id TEXT, email TEXT);
CREATE TABLE customer_profiles_failover_replica (resource_id TEXT, user_id TEXT, email TEXT);
INSERT INTO customer_profiles_failover_replica VALUES ('account_90005','user_9005','c@example.org');
CREATE TABLE search_documents_primary (resource_id TEXT, email TEXT, source_resource_id TEXT);
INSERT INTO search_documents_primary VALUES ('search_90005','c@example.org','account_90005');
"""
        obs, rep = self.parse(body)
        units = {(c.collection, c.copy): c.resource_ids for c in rep.coverage}
        self.assertEqual(units[("customer_profiles", "primary")], frozenset())
        self.assertEqual(units[("customer_profiles", "failover_replica")], frozenset({"account_90005"}))
        self.assertTrue(all(c.level == "COLLECTION" for c in rep.coverage))
        s = next(o for o in obs if o.resource_id == "search_90005")
        self.assertEqual(s.related_ids, (("DERIVED_FROM", "account_90005"),))

    def test_topology_extract_parses_record_json_without_coverage(self):
        rec = json.dumps({"resource_id": "analytics_90002", "user_id": None, "email": "d@example.org",
                          "metrics": {"sessions_30d": 3}})
        body = f"""
CREATE TABLE customer_data_read_replica (resource_id TEXT, origin_system TEXT, collection_name TEXT,
  record_json TEXT, updated_at TEXT);
INSERT INTO customer_data_read_replica VALUES ('analytics_90002','analytics_platform',
  'customer_analytics_reports','{rec}','2026-05-09T00:00:00Z');
"""
        obs, rep = self.parse(body)
        self.assertEqual(rep.coverage, [])
        o = obs[0]
        self.assertEqual((o.system_id, o.copy_location, o.collection),
                         ("analytics_platform", "read_replica", "customer_analytics_reports"))
        self.assertIn("metrics.sessions_30d", o.fields)
        self.assertEqual(o.fields["_row.updated_at"], "2026-05-09T00:00:00Z")

    def test_header_mismatch_is_warning(self):
        _, rep = self.parse("CREATE TABLE t (a TEXT);", captured="2026-05-11T00:00:00Z")
        self.assertTrue(any("header capture" in w for w in rep.warnings))

    def test_broken_sql_fails_not_empty(self):
        obs, rep = self.parse("CREATE TABLE (oops;")
        self.assertEqual((obs, rep.status), ([], "FAILED"))
        self.assertTrue(rep.reasons)


if __name__ == "__main__":
    unittest.main()
