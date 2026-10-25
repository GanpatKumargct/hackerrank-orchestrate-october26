"""Regression checks of Stages 2–3 against the real participant evidence.

Asserts parser coverage only (file statuses, anomalies, coverage units, resource
reach). It does not use or compare against any reference answer.
"""
import re
import unittest
from collections import Counter

from audit.evidence.extract import extract_all
from audit.loader import load_dataset

RID = re.compile(r"\b(?:account|search|analytics|support|export|data_flow|backup|audit_record|tombstone|"
                 r"cache|email_delivery|marketing|object|legal_hold|telemetry)_\d+\b")


class TestRealEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = load_dataset()
        cls.obs, cls.reports = extract_all(cls.ds)

    def test_all_text_formats_parse_ok(self):
        status = Counter((r.fmt, r.status) for r in self.reports.values())
        self.assertEqual(status[("sql", "OK")], 24)
        self.assertEqual(status[("json", "OK")], 28)
        self.assertEqual(status[("log", "OK")], 26)
        self.assertEqual(status[("text", "OK")], 1)

    def test_png_reported_as_gaps_not_empty(self):
        pngs = [r for r in self.reports.values() if r.fmt == "png"]
        self.assertEqual(len(pngs), 11)
        self.assertTrue(all(r.status == "FAILED" and "EVIDENCE_GAP" in r.reasons[0] for r in pngs))

    def test_pdfs_extract_with_page_provenance(self):
        pdfs = {r.file_id: r for r in self.reports.values() if r.fmt == "pdf"}
        self.assertEqual(sorted(pdfs), ["evidence_18", "evidence_27", "evidence_55", "evidence_58"])
        self.assertTrue(all(r.status == "OK" and r.pages for r in pdfs.values()))
        self.assertEqual({fid: len(r.pages) for fid, r in pdfs.items()},
                         {"evidence_18": 2, "evidence_27": 2, "evidence_55": 1, "evidence_58": 2})
        pdf_obs = {o.file_id: o for o in self.obs if o.source_format == "pdf"}
        self.assertEqual(sorted(pdf_obs), ["evidence_55", "evidence_58"])
        self.assertEqual(pdf_obs["evidence_55"].observed_raw, "2026-09-05T06:30:00Z")   # 'issued'
        self.assertEqual(pdf_obs["evidence_58"].observed_raw, "2026-09-12T07:30:00Z")   # 'captured'
        self.assertIn("event_time.recorded", pdf_obs["evidence_55"].fields)

    def test_sql_headers_match_manifest(self):
        for r in self.reports.values():
            if r.fmt == "sql":
                self.assertEqual(r.warnings, [], r.file_id)

    def test_observed_after_capture_anomalies(self):
        files = Counter(o.file_id for o in self.obs if "observed_after_capture" in o.anomalies)
        self.assertEqual(dict(files), {"evidence_13": 1, "evidence_36": 1})

    def test_coverage_units(self):
        cov = [c for r in self.reports.values() for c in r.coverage]
        e51 = [c for c in cov if c.file_id == "evidence_51" and c.collection == "customer_profiles"]
        self.assertEqual(len(e51), 1)
        self.assertEqual(e51[0].resource_ids, frozenset())
        e54 = {(c.copy, c.level) for c in cov if c.file_id == "evidence_54"}
        self.assertEqual(e54, {("primary", "COLLECTION"), ("failover_replica", "COLLECTION")})
        self.assertFalse([c for c in cov if c.file_id == "evidence_05"])        # topology: no coverage
        self.assertTrue(all(c.level == "SYSTEM" for c in cov if c.file_id == "evidence_90"))

    def test_every_resource_mention_reaches_an_observation_or_is_warned(self):
        reached = {}
        for o in self.obs:
            reached.setdefault(o.file_id, set()).add(o.resource_id)
            reached[o.file_id].update(r for _, r in o.related_ids)
        for r in self.reports.values():
            for c in r.coverage:
                reached.setdefault(r.file_id, set()).update(c.resource_ids)
        missed = {}
        for row in self.ds.manifest:
            if row["_path"].suffix in (".pdf", ".png"):
                continue
            found = set(RID.findall(row["_path"].read_text(encoding="utf-8")))
            m = found - reached.get(row["file_id"], set())
            if m:
                missed[row["file_id"]] = m
        self.assertEqual(list(missed), ["evidence_61"])                 # one noise-event mention
        self.assertEqual(len(missed["evidence_61"]), 1)
        self.assertTrue(self.reports["evidence_61"].warnings)

    def test_trace_keys_and_identifiers_extracted(self):
        trace = sum(1 for o in self.obs for h in o.keys if h.relationship == "TRACE_KEY")
        free = sum(1 for o in self.obs for h in o.identifiers if h.relationship == "FREE_TEXT_MENTION")
        self.assertGreater(trace, 0)
        self.assertGreater(free, 0)


if __name__ == "__main__":
    unittest.main()
