import unittest

from audit.evidence import normalize as n


class TestNormalize(unittest.TestCase):
    def test_email_lowercased_raw_kept(self):
        self.assertEqual(n.classify_value("Mixed.Case@Example.org"), ("email", "mixed.case@example.org"))

    def test_hash_and_user(self):
        self.assertEqual(n.classify_value("A" * 64), ("hash", "a" * 64))
        self.assertEqual(n.classify_value("user_9001"), ("user", "user_9001"))

    def test_phone_canonical_exact_digits_only(self):
        self.assertEqual(n.classify_value("+44 20 (0000) 0001"), ("phone", "+442000000001"))
        self.assertEqual(n.classify_value("020 0000 0001"), ("phone_uncanonical", None))

    def test_cleared_values_are_not_identifiers(self):
        for v in (None, "", "null", "NULL", "[REDACTED]", "None"):
            self.assertTrue(n.is_cleared(v))
            self.assertIsNone(n.classify_value(v))

    def test_resource_ids_and_free_words_not_identifiers(self):
        for v in ("analytics_9001", "no direct identifier", "customer_directory_v3"):
            self.assertIsNone(n.classify_value(v))

    def test_free_text_word_boundaries(self):
        found = n.extract_free_text("ref user_43 and user_430; mail a.b@example.org, call +44 20 0000 0001")
        users = [r for k, r, _ in found if k == "user"]
        self.assertEqual(users, ["user_43", "user_430"])
        self.assertIn(("email", "a.b@example.org", "a.b@example.org"), found)
        self.assertIn("+442000000001", [x for k, _, x in found if k == "phone"])

    def test_identifier_hits_relationships(self):
        fields = {"document.email": "X@Example.org", "message_text": "contact y@example.org",
                  "index_name": "z@example.org"}
        hits = n.identifier_hits(fields, "loc")
        rel = {(h.field, h.relationship, h.normalised) for h in hits}
        self.assertIn(("document.email", "RECORD_FIELD", "x@example.org"), rel)
        self.assertIn(("message_text", "FREE_TEXT_MENTION", "y@example.org"), rel)
        self.assertNotIn("index_name", {h.field for h in hits})
        self.assertEqual([h.raw for h in hits if h.field == "document.email"], ["X@Example.org"])

    def test_flatten_excludes_nested_records(self):
        obj = {"resource_id": "r", "hits": {"documents": [{"resource_id": "d", "email": "e@example.org"}]},
               "document": {"email": "f@example.org"}, "tags": ["a", "b"]}
        flat = n.flatten(obj, stop=lambda d: isinstance(d, dict) and "resource_id" in d)
        self.assertIn("document.email", flat)
        self.assertNotIn("hits.documents[0].email", flat)
        self.assertEqual(flat["tags"], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
