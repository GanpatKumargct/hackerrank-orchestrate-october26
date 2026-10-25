import unittest

from audit.evidence.pdf_parser import parse_pdf
from tests.fixtures import TempDir, manifest_row
from tests.pdf_fixtures import build_pdf


class TestPdfParser(unittest.TestCase):
    def parse(self, data, captured="2026-05-10T12:00:00Z"):
        with TempDir() as d:
            p = d / "x.pdf"
            p.write_bytes(data)
            return parse_pdf(manifest_row(p, captured=captured))

    def test_text_pages_and_page_level_provenance(self):
        pdf = build_pdf([["SUPPORT EXTRACT", "Reference support_90060", "Contact a.b@example.org",
                          "captured 09 May 2026 07", "30 UTC"],
                         ["Continued", "account_90061 referenced", "recorded 01 May 2026 04 03 UTC"]])
        obs, rep = self.parse(pdf)
        self.assertEqual(rep.status, "OK")
        self.assertEqual([n for n, _ in rep.pages], [1, 2])
        by = {o.resource_id: o for o in obs}
        self.assertEqual(set(by), {"support_90060", "account_90061"})
        self.assertEqual((by["support_90060"].locator, by["support_90060"].fields["page"]), ("page1#support_90060", 1))
        self.assertEqual(by["account_90061"].context["page"], 2)
        # document capture time = observation time; event time stays a field
        self.assertEqual(by["support_90060"].observed_raw, "2026-05-09T07:30:00Z")
        self.assertEqual(by["support_90060"].time_basis, "inner")
        self.assertEqual(by["support_90060"].fields["event_time.recorded"], ["2026-05-01T04:03:00Z"])
        self.assertEqual(by["support_90060"].file_captured_raw, "2026-05-10T12:00:00Z")
        hits = {(h.kind, h.relationship) for h in by["support_90060"].identifiers}
        self.assertIn(("email", "FREE_TEXT_MENTION"), hits)
        self.assertEqual(by["support_90060"].fields["page_heading"], "SUPPORT EXTRACT")

    def test_tounicode_cmap_applied(self):
        obs, rep = self.parse(build_pdf([[b"fingerprint 8f0c\x0131ad support_90062"]]))
        self.assertIn("8f0c…31ad", rep.pages[0][1])

    def test_winansi_fallback_without_cmap(self):
        obs, rep = self.parse(build_pdf([["plain text export_90063"]], to_unicode=False))
        self.assertEqual(rep.status, "OK")
        self.assertEqual([o.resource_id for o in obs], ["export_90063"])

    def test_no_document_time_uses_file_basis(self):
        obs, _ = self.parse(build_pdf([["record backup_90064 only"]]))
        self.assertIsNone(obs[0].observed_raw)
        self.assertEqual(obs[0].time_basis, "file")

    def test_conflicting_capture_times_left_to_file_basis(self):
        obs, rep = self.parse(build_pdf([["captured 01 May 2026 01 00 UTC", "captured 02 May 2026 01 00 UTC",
                                          "search_90065"]]))
        self.assertIsNone(obs[0].observed_raw)
        self.assertTrue(any("multiple 'captured'" in w for w in rep.warnings))

    def test_no_resource_ids_is_context_only(self):
        obs, rep = self.parse(build_pdf([["Register user_9001 | ORD-1 | retain"]]))
        self.assertEqual((obs, rep.status), ([], "OK"))
        self.assertTrue(rep.pages)
        self.assertTrue(any("context only" in r for r in rep.reasons))

    def test_encrypted_fails(self):
        obs, rep = self.parse(build_pdf([["support_90066"]], encrypt=True))
        self.assertEqual((obs, rep.status), ([], "FAILED"))
        self.assertIn("encrypted", rep.reasons[0])

    def test_malformed_fails(self):
        obs, rep = self.parse(build_pdf([["support_90067"]], header=False))
        self.assertEqual(rep.status, "FAILED")
        self.assertIn("malformed", rep.reasons[0])
        obs, rep = self.parse(b"%PDF-1.4\nnothing here\n")
        self.assertEqual(rep.status, "FAILED")

    def test_unsupported_filter_fails(self):
        obs, rep = self.parse(build_pdf([["support_90068"]], content_filter="DCTDecode"))
        self.assertEqual(rep.status, "FAILED")
        self.assertIn("unsupported stream filter", rep.reasons[0])

    def test_image_only_page_fails_not_empty(self):
        obs, rep = self.parse(build_pdf([["ignored"]], image_pages=(0,)))
        self.assertEqual((obs, rep.status), ([], "FAILED"))
        self.assertIn("image-only", rep.reasons[0])

    def test_corrupt_stream_fails(self):
        obs, rep = self.parse(build_pdf([["x"]], content_filter="flate", raw_content=b"BT (a) Tj ET")
                              .replace(b"x\x9c", b"zz"))
        self.assertEqual(rep.status, "FAILED")


if __name__ == "__main__":
    unittest.main()
