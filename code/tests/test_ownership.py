"""F.1.3 / Q-OWNER-RESOLUTION tests."""
import unittest

from audit.errors import HeldReason
from audit.evidence.common import make_observation
from audit.ownership import resolve_owner
from tests.fixtures import manifest_row


def obs(locator, rid="account_90080", system=None, reporter=None, fields=None):
    return make_observation(manifest_row=manifest_row("x.log"), fmt="log", locator=locator,
                            resource_id=rid, fields=fields or {}, system_id=system,
                            system_field="system" if system else None, reporter_service=reporter)


class TestOwnerResolution(unittest.TestCase):
    def test_explicit_owner_wins_over_reporters(self):
        r = resolve_owner([obs("a", system="account_service"), obs("b", reporter="search_service"),
                           obs("c", reporter="search_index_service")])
        self.assertEqual((r.system_id, r.basis, r.reason), ("account_service", "EXPLICIT", None))
        self.assertTrue(any("overridden" in n for n in r.notes))

    def test_exact_canonical_reporter(self):
        r = resolve_owner([obs("a", reporter="security_service")])
        self.assertEqual((r.system_id, r.basis), ("security_service", "REPORTER_EXACT"))

    def test_alias_reporter(self):
        r = resolve_owner([obs("a", reporter="profile_service")])
        self.assertEqual((r.system_id, r.basis), ("account_service", "ALIAS"))

    def test_alias_and_exact_agreeing(self):
        r = resolve_owner([obs("a", reporter="profile_service"), obs("b", reporter="account_service")])
        self.assertEqual((r.system_id, r.basis), ("account_service", "ALIAS"))

    def test_unknown_service_is_ambiguous(self):
        r = resolve_owner([obs("a", reporter="search_index_service")])
        self.assertEqual((r.system_id, r.reason), (None, HeldReason.SYSTEM_AMBIGUOUS))

    def test_partial_or_similar_name_does_not_match(self):
        for svc in ("account", "account_service_v2", "Account_Service", "accounts_service"):
            self.assertIsNone(resolve_owner([obs("a", reporter=svc)]).system_id, svc)

    def test_prefix_only_is_ambiguous(self):
        r = resolve_owner([obs("a", rid="account_90081")])           # resource prefix only, no owner evidence
        self.assertEqual((r.system_id, r.basis), (None, "AMBIGUOUS"))

    def test_conflicting_explicit_owners(self):
        r = resolve_owner([obs("a", system="account_service"), obs("b", system="search_service")])
        self.assertEqual((r.system_id, r.reason), (None, HeldReason.SYSTEM_AMBIGUOUS))
        self.assertEqual(r.candidates, ("account_service", "search_service"))

    def test_conflicting_reporters(self):
        r = resolve_owner([obs("a", reporter="account_service"), obs("b", reporter="search_service")])
        self.assertEqual((r.system_id, r.reason), (None, HeldReason.SYSTEM_AMBIGUOUS))

    def test_non_canonical_explicit_owner_ignored(self):
        r = resolve_owner([obs("a", system="privacy_treatment_service"), obs("b", reporter="account_service")])
        self.assertEqual((r.system_id, r.basis), ("account_service", "REPORTER_EXACT"))
        self.assertTrue(any("non-canonical" in n for n in r.notes))

    def test_reporter_is_not_an_identity_link(self):
        o = obs("a", reporter="account_service", fields={"rows": "0"})
        self.assertEqual((o.identifiers, o.keys), ((), ()))


if __name__ == "__main__":
    unittest.main()
