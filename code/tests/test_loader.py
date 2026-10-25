import unittest

from audit import config
from audit.errors import SchemaError
from audit.loader import load_dataset
from tests.fixtures import TempDir, minimal_dataset, sha, write_file


class TestRealDatasetLoads(unittest.TestCase):
    def test_real_dataset_loads_without_errors(self):
        ds = load_dataset(config.DATASET_DIR)
        counts = (len(ds.requests), len(ds.sample_requests), len(ds.identities), len(ds.audit_log),
                  len(ds.activities), len(ds.rules), len(ds.manifest))
        self.assertEqual(counts, (518, 32, 850, 306, 4011, 15, 94))
        self.assertEqual(ds.warnings, [])
        self.assertTrue(all("_path" in m for m in ds.manifest))


class TestLoaderChecks(unittest.TestCase):
    def assert_error(self, mutate, needle, files=None):
        with TempDir() as d:
            root = minimal_dataset(d, mutate)
            if files:
                files(root)
            with self.assertRaises(SchemaError) as cm:
                load_dataset(root)
            self.assertTrue(any(needle in e for e in cm.exception.errors), cm.exception.errors)

    def test_minimal_dataset_is_valid(self):
        with TempDir() as d:
            ds = load_dataset(minimal_dataset(d))
            self.assertEqual(len(ds.requests), 1)
            self.assertEqual(ds.warnings, [])

    def test_header_mismatch(self):
        def files(root):
            p = root / "deletion_rules.csv"
            p.write_text(p.read_text(encoding="utf-8").replace("rule_id,", "rule,", 1), encoding="utf-8")
        self.assert_error(None, "header", files)

    def test_bad_timestamp(self):
        self.assert_error(lambda t: t["deletion_requests.csv"][0].update(audit_at="2026-05-10 12:00"),
                          "bad timestamp")

    def test_request_time_order(self):
        self.assert_error(lambda t: t["deletion_requests.csv"][0].update(reported_at="2026-05-11T00:00:00Z"),
                          "requested_at <= reported_at <= audit_at")

    def test_duplicate_case_id(self):
        self.assert_error(lambda t: t["deletion_requests.csv"].append(dict(t["deletion_requests.csv"][0])),
                          "duplicate")

    def test_enum_violation(self):
        self.assert_error(lambda t: t["system_activity.csv"][0].update(reported_result="DONE"),
                          "unexpected value")

    def test_unknown_audit_user(self):
        self.assert_error(lambda t: t["user_audit_log.csv"][0].update(user_id="user_9999"), "unknown")

    def test_audit_chain_break(self):
        def mutate(t):
            t["user_audit_log.csv"][0].update(new_value="other.fx@example.org")
        self.assert_error(mutate, "last email change != snapshot")

    def test_rule_without_treatment(self):
        self.assert_error(lambda t: t["deletion_rules.csv"][0].update(data_category="UNKNOWN_CATEGORY"),
                          "no TREATMENTS entry")

    def test_manifest_missing_file(self):
        self.assert_error(lambda t: t["evidence_files.csv"][0].update(file_path="evidence/logs/none.log"),
                          "missing file")

    def test_manifest_path_outside_evidence(self):
        self.assert_error(lambda t: t["evidence_files.csv"][0].update(file_path="deletion_rules.csv"),
                          "outside evidence")

    def test_file_not_in_manifest(self):
        self.assert_error(None, "not in manifest",
                          lambda root: write_file(root / "evidence" / "logs", "extra.log", "x\n"))

    def test_hash_mismatch_is_warning_not_error(self):
        with TempDir() as d:
            def mutate(t):
                bogus = sha("x@example.org")            # consistent chain, wrong hash value
                t["user_identities.csv"][0].update(email_hash=bogus)
                t["user_audit_log.csv"][1].update(new_value=bogus)
            root = minimal_dataset(d, mutate)
            ds = load_dataset(root)
            self.assertTrue(any(w.startswith("HASH_UNVERIFIED") for w in ds.warnings))
            self.assertTrue(ds.identities[0].get("_hash_unverified"))


if __name__ == "__main__":
    unittest.main()
