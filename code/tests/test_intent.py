"""Stage 8 — clause-scoped three-way intent (plan E.1, B.1.4). Synthetic texts only."""
import unittest

from audit.intent import (DELETE_REQUEST, DELETION, DELETION_FOLLOWUP, DELETION_NEGATION, MARKETING_ONLY,
                          NON_DELETION, OTHER_PURPOSE, SCOPE_LIMIT, UNSURE, classify_intent)


def types(text):
    return {c.type for c in classify_intent(text).clauses}


class TestDeletion(unittest.TestCase):
    def test_openers_in_six_languages(self):
        for text in ("Please erase my account and the data attached to it.",
                     "I would like my profile permanently deleted.",
                     "Kindly close this account and remove my personal information.",
                     "Peço a exclusão da minha conta.",
                     "Quiero la eliminación de mi cuenta.",
                     "Merci de procéder à la suppression de mon compte.",
                     "私のアカウントを削除してください。",
                     "제 계정을 삭제해 주세요."):
            r = classify_intent(text)
            self.assertEqual(r.value, DELETION, text)
            self.assertIn(DELETE_REQUEST, types(text), text)

    def test_followups(self):
        for text in ("I deleted my profile last month. Could you verify nothing is left?",
                     "Support said the deletion was complete. Please investigate and finish it.",
                     "My account is gone, but please check the analytics data."):
            r = classify_intent(text)
            self.assertEqual(r.value, DELETION, text)
            self.assertIn(DELETION_FOLLOWUP, types(text), text)

    def test_scope_limits_are_recorded_not_decisive(self):
        for text, limit in (("Delete only my account, not my orders", "not my orders"),
                            ("Close my account but do not delete my invoices", "do not delete my invoices"),
                            ("Please delete my account. Backups may stay if policy requires them.",
                             "Backups may stay if policy requires them."),
                            ("Can you verify my account was deleted? Please do not treat that ticket record as mine.",
                             "Please do not treat that ticket record as mine.")):
            r = classify_intent(text)
            self.assertEqual(r.value, DELETION, text)
            self.assertIn(limit, r.scope_limits)

    def test_negated_keep_is_not_a_deletion_negation(self):
        r = classify_intent("I'm not asking you to keep anything; delete it all")
        self.assertEqual(r.value, DELETION)
        self.assertNotIn(DELETION_NEGATION, types("I'm not asking you to keep anything; delete it all"))

    def test_no_longer_is_not_negation(self):
        self.assertEqual(classify_intent("I no longer use this profile and want it erased.").value, DELETION)


class TestNonDeletion(unittest.TestCase):
    def test_explicit_non_deletion(self):
        cases = {
            "Please fix the postcode on my profile. Do not close the account.": {OTHER_PURPOSE, DELETION_NEGATION},
            "Send me a copy of my data. This is not a request to erase it.": {OTHER_PURPOSE, DELETION_NEGATION},
            "Please update my phone number without removing any of my records.": {DELETION_NEGATION},  # one type/clause
            "Remove me from the marketing lists only.": {MARKETING_ONLY},
            "Please stop the promotional messages.": {OTHER_PURPOSE},
            "I want to continue using the service, please reset my login.": {OTHER_PURPOSE, DELETION_NEGATION},
        }
        for text, expected in cases.items():
            r = classify_intent(text)
            self.assertEqual(r.value, NON_DELETION, text)
            self.assertTrue(expected <= types(text), (text, types(text)))

    def test_marketing_without_only_is_not_marketing_only(self):
        self.assertNotIn(MARKETING_ONLY, types("Please remove my account and any marketing profile."))
        self.assertEqual(classify_intent("Please remove my account and any marketing profile.").value, DELETION)


class TestUnsure(unittest.TestCase):
    def test_contradiction_empty_and_unsupported(self):
        for text in ("please delete everything — actually, don't close the account",
                     "", "   ", "Bitte löschen Sie mein Konto.", "Hello, thanks for your help."):
            self.assertEqual(classify_intent(text).value, UNSURE, repr(text))


if __name__ == "__main__":
    unittest.main()
