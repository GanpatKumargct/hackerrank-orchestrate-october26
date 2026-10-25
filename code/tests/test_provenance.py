"""C.2 provenance tests: normalisation never alters raw values, timestamps or locators."""
import json
import unittest

from audit.evidence.json_parser import parse_json
from audit.evidence.log_parser import parse_log
from tests.fixtures import TempDir, manifest_row, write_file


class TestProvenance(unittest.TestCase):
    def test_raw_timestamps_and_file_capture_preserved(self):
        doc = {"records": [{"recorded_at": "2026-05-08T09:00:00Z", "system": "account_service",
                            "resource_id": "account_90050", "subject_reference": "Mixed@Example.org"}]}
        with TempDir() as d:
            row = manifest_row(write_file(d, "x.json", json.dumps(doc)), file_id="evidence_x",
                               captured="2026-05-10T12:00:00Z")
            o = parse_json(row)[0][0]
        self.assertEqual(o.observed_raw, "2026-05-08T09:00:00Z")
        self.assertEqual(o.file_captured_raw, "2026-05-10T12:00:00Z")
        self.assertEqual(o.file_captured_at, row["_captured_at"])
        self.assertEqual(o.fields["subject_reference"], "Mixed@Example.org")       # raw kept
        self.assertEqual(o.identifiers[0].raw, "Mixed@Example.org")
        self.assertEqual(o.identifiers[0].normalised, "mixed@example.org")
        self.assertTrue(o.obs_id.startswith("evidence_x#"))

    def test_missing_inner_time_is_not_filled_with_file_time(self):
        doc = {"records": [{"system": "account_service", "resource_id": "account_90051"}]}
        with TempDir() as d:
            o = parse_json(manifest_row(write_file(d, "x.json", json.dumps(doc))))[0][0]
        self.assertIsNone(o.observed_at)
        self.assertIsNone(o.observed_raw)
        self.assertEqual(o.time_basis, "file")

    def test_trace_keys_stored_separately_from_record_identifiers(self):
        text = ("2026-05-09T10:00:00Z level=DEBUG service=s trace_id=t event=x_started lookup_key=a@example.org\n"
                "2026-05-09T10:00:01Z level=INFO service=s trace_id=t event=x_completed resource_id=account_90052 "
                "email=b@example.org\n")
        with TempDir() as d:
            o = parse_log(manifest_row(write_file(d, "x.log", text)))[0][0]
        self.assertEqual({h.normalised for h in o.identifiers}, {"b@example.org"})
        self.assertEqual({(h.relationship, h.normalised) for h in o.keys}, {("TRACE_KEY", "a@example.org")})
        self.assertNotIn("lookup_key", o.fields)
        self.assertTrue(o.locator.startswith("t@line"))


if __name__ == "__main__":
    unittest.main()
