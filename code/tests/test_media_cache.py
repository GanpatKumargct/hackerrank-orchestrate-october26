import hashlib
import json
import socket
import unittest
from unittest import mock

from audit.evidence.media_cache import parse_png
from tests.fixtures import TempDir, manifest_row, write_file

PNG_BYTES = b"\x89PNG\r\n\x1a\nfixture-image-bytes"


def _no_network(*a, **k):
    raise AssertionError("network access attempted")


class TestMediaCache(unittest.TestCase):
    def setUp(self):
        self.patch = mock.patch.object(socket, "socket", _no_network)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def run_case(self, entry_mutator=None, write_entry=True, write_prompt=True, prompt_text="prompt v1"):
        with TempDir() as d:
            img = d / "shot.png"
            img.write_bytes(PNG_BYTES)
            row = manifest_row(img, file_id="evidence_9100", captured="2026-05-10T12:00:00Z")
            prompt = d / "media_extraction.md"
            if write_prompt:
                prompt.write_text(prompt_text, encoding="utf-8")
            cache = d / "media_cache"
            cache.mkdir()
            entry = {"file_id": "evidence_9100", "file_path": row["file_path"],
                     "sha256": hashlib.sha256(PNG_BYTES).hexdigest(),
                     "prompt_sha256": hashlib.sha256(b"prompt v1").hexdigest(),
                     "extractor": {"provider": "test", "model": "fixture"},
                     "extracted_at": "2026-05-11T00:00:00Z", "schema_version": "1",
                     "review_status": "unreviewed",
                     "records": [{"resource_id": "data_flow_90070", "fields": {"selector": "s@example.org",
                                                                                "enabled": "true"},
                                  "visible_text": "Connector data_flow_90070 s@example.org",
                                  "observed_at": "2026-05-09T08:00:00Z"}]}
            if entry_mutator:
                entry_mutator(entry)
            if write_entry:
                write_file(cache, "evidence_9100.json", json.dumps(entry))
            return parse_png(row, cache_dir=cache, prompt_path=prompt)

    def test_missing_entry_is_explicit_gap(self):
        obs, rep = self.run_case(write_entry=False)
        self.assertEqual((obs, rep.status), ([], "FAILED"))
        self.assertIn("EVIDENCE_GAP", rep.reasons[0])
        self.assertIn("not authorized", rep.reasons[0])

    def test_valid_entry_produces_observations_with_provenance(self):
        obs, rep = self.run_case()
        self.assertEqual(rep.status, "OK")
        o = obs[0]
        self.assertEqual((o.source_format, o.resource_id, o.locator),
                         ("image", "data_flow_90070", "cache:evidence_9100#records[0]"))
        self.assertEqual((o.observed_raw, o.file_captured_raw), ("2026-05-09T08:00:00Z", "2026-05-10T12:00:00Z"))
        self.assertEqual(o.context["review_status"], "unreviewed")
        self.assertIn(("email", "FREE_TEXT_MENTION"), {(h.kind, h.relationship) for h in o.identifiers})

    def test_image_hash_mismatch(self):
        obs, rep = self.run_case(lambda e: e.update(sha256="0" * 64))
        self.assertEqual(rep.status, "FAILED")
        self.assertIn("SHA-256", rep.reasons[0])

    def test_prompt_hash_mismatch_and_missing_prompt(self):
        _, rep = self.run_case(prompt_text="prompt v2")
        self.assertIn("prompt SHA-256", rep.reasons[0])
        _, rep = self.run_case(write_prompt=False)
        self.assertIn("prompt file missing", rep.reasons[0])

    def test_schema_and_shape_checks(self):
        _, rep = self.run_case(lambda e: e.update(schema_version="9"))
        self.assertIn("schema_version", rep.reasons[0])
        _, rep = self.run_case(lambda e: e.pop("extractor"))
        self.assertIn("missing keys", rep.reasons[0])
        _, rep = self.run_case(lambda e: e.update(file_id="evidence_9999"))
        self.assertIn("file_id mismatch", rep.reasons[0])

    def test_record_without_resource_id_is_partial(self):
        obs, rep = self.run_case(lambda e: e["records"].append({"visible_text": "no id"}))
        self.assertEqual((len(obs), rep.status), (1, "PARTIAL"))


if __name__ == "__main__":
    unittest.main()
