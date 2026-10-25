"""Stage 7 — category classification (D.1) and conditions (D.2.3)."""
import unittest

from audit.errors import UncertaintyReason as U
from audit.evidence.common import make_observation
from audit.identity import IdentityResolver
from audit.loader import load_dataset
from audit.policy import classify, evaluate_condition
from tests.fixtures import TempDir, manifest_row, minimal_dataset, sha

SUBJ, OTHER = "new.fx@example.org", "other.fx@example.org"


def ob(locator, rid, fields=None, collection=None, record_type=None, event=None):
    return make_observation(manifest_row=manifest_row("x.json"), fmt="json", locator=locator, resource_id=rid,
                            fields=fields or {}, collection=collection, record_type=record_type,
                            context={"event": event} if event else None)


def wf(aid, etype, rid):
    return {"activity_id": aid, "event_type": etype, "source_system": "deletion_worker", "resource_id": rid}


def resolver():
    def m(t):
        t["user_identities.csv"].append(dict(user_id="user_9002", name="Other", email=OTHER, phone="+44 20 0000 0009",
                                             email_hash=sha(OTHER), updated_at="2026-03-01T00:00:00Z"))
    with TempDir() as d:
        return IdentityResolver(load_dataset(minimal_dataset(d, m)))


class TestClassify(unittest.TestCase):
    def test_tier_precedence_and_conflict_recorded(self):
        c = classify("support_90300", [ob("a", "support_90300", collection="support_records"),
                                       ob("b", "support_90300", collection="ticket_attachments")], [])
        self.assertEqual((c.value, c.basis, c.confidence), ("SUPPORT_ATTACHMENT", "T2", "HIGH"))
        self.assertIn("SUPPORT_MESSAGE", {s.category for s in c.conflicts})

    def test_record_type_beats_collection(self):
        c = classify("x_90301", [ob("a", "x_90301", record_type="USER_EXPORT", collection="customer_profiles")], [])
        self.assertEqual((c.value, c.basis), ("USER_EXPORT", "T1"))

    def test_prefix_and_workflow_alone_never_decide(self):
        c = classify("account_90302", [ob("a", "account_90302")], [wf("activity_9300", "DELETE_RECORD", "account_90302")])
        self.assertEqual((c.value, c.reason), (None, U.CATEGORY_UNGROUNDED))

    def test_same_tier_conflict_tie_break_and_ambiguity(self):
        obs = [ob("a", "r_90303", collection="support_conversations"), ob("b", "r_90303", collection="ticket_attachments")]
        self.assertEqual(classify("r_90303", obs, []).reason, U.CATEGORY_AMBIGUOUS)
        tb = classify("r_90303", obs, [wf("activity_9301", "REDACT_RECORD", "r_90303")])
        self.assertEqual((tb.value, tb.basis, tb.confidence), ("SUPPORT_MESSAGE", "TIE_BREAK_WORKFLOW_CLAIM", "LOW"))
        two = classify("r_90303", obs, [wf("activity_9302", "REDACT_RECORD", "r_90303"),
                                        wf("activity_9303", "DELETE_RECORD", "r_90303")])
        self.assertEqual(two.reason, U.CATEGORY_AMBIGUOUS)

    def test_treatment_equivalent_categories(self):
        c = classify("r_90304", [ob("a", "r_90304", collection="customer_exports"),
                                 ob("b", "r_90304", event="contact_lookup_completed")], [])
        self.assertEqual((c.value, c.basis), ("SECONDARY_IDENTIFIER", "TREATMENT_EQUIVALENT"))

    def test_contact_lookup_is_secondary_identifier_assumption(self):
        c = classify("analytics_90305", [ob("a", "analytics_90305", event="contact_lookup_completed")], [])
        self.assertEqual(c.value, "SECONDARY_IDENTIFIER")
        self.assertIn(("analytics", "T-PFX"), {(s.category, s.tier) for s in c.signals})   # recorded, never decides


class TestConditions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = resolver()

    def test_support_message_shared_context(self):
        for fields in ({"ticket_id": "CS-1"}, {"message_excerpt": "Asked about a delivery"},
                       {"message_text": f"cc {OTHER}"}):
            c = evaluate_condition("SUPPORT_MESSAGE", [ob("a", "support_90306", fields)], "user_9001", self.r)
            self.assertEqual(c.value, "TRUE", fields)
            self.assertTrue(c.assumption)
        unknown = evaluate_condition("SUPPORT_MESSAGE", [ob("a", "support_90306", {"requester_email": SUBJ})],
                                     "user_9001", self.r)
        self.assertEqual(unknown.value, "UNKNOWN")

    def test_attachment_owner(self):
        mine = evaluate_condition("SUPPORT_ATTACHMENT", [ob("a", "s", {"uploaded_by": SUBJ})], "user_9001", self.r)
        other = evaluate_condition("SUPPORT_ATTACHMENT", [ob("a", "s", {"uploaded_by": OTHER})], "user_9001", self.r)
        none = evaluate_condition("SUPPORT_ATTACHMENT", [ob("a", "s", {"file": "x.pdf"})], "user_9001", self.r)
        self.assertEqual((mine.value, other.value, none.value), ("TRUE", "FALSE", "UNKNOWN"))

    def test_tombstone_backup_always(self):
        t = lambda st: evaluate_condition("ACCOUNT_TOMBSTONE", [ob("a", "t", {"account_status": st})], "u", self.r).value
        self.assertEqual((t("DELETED"), t("ACTIVE")), ("TRUE", "FALSE"))
        self.assertEqual(evaluate_condition("ACCOUNT_TOMBSTONE", [ob("a", "t")], "u", self.r).value, "UNKNOWN")
        b = evaluate_condition("BACKUP_ARCHIVE", [], "u", self.r)
        self.assertEqual((b.value, b.assumption), ("TRUE", True))
        self.assertEqual(evaluate_condition("DATA_FLOW", [], "u", self.r).rule, "SUPPLEMENTAL")
        self.assertEqual(evaluate_condition("USER_PROFILE", [], "u", self.r).value, "TRUE")


if __name__ == "__main__":
    unittest.main()
