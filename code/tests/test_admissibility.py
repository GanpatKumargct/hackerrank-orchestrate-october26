"""C.7 admissibility table (plan rows 1–10) for state, citation and link (flag off / on)."""
import unittest
from datetime import timedelta

from audit.admissibility import (admissibility_set, admissible_claim, admissible_for_citation,
                                 admissible_for_link, admissible_for_state, is_late_link_only)
from audit.evidence.common import make_observation
from audit.timeutil import parse_ts
from tests.fixtures import manifest_row

AUDIT = parse_ts("2026-05-10T12:00:00Z")


def obs(captured, inner=None):
    return make_observation(manifest_row=manifest_row("x.log", captured=captured), fmt="log",
                            locator="l", resource_id="account_90200", fields={}, observed_raw=inner)


CASES = [  # (name, captured, inner, state, citation, link_off, link_on)
    ("1 both before", "2026-05-09T00:00:00Z", "2026-05-08T00:00:00Z", True, True, True, True),
    ("2 boundary equal", "2026-05-10T12:00:00Z", "2026-05-10T12:00:00Z", True, True, True, True),
    ("3 inner after cutoff", "2026-05-09T00:00:00Z", "2026-05-11T00:00:00Z", False, False, False, False),
    ("4 late file early inner", "2026-05-12T00:00:00Z", "2026-05-10T08:00:00Z", False, False, False, True),
    ("5 late file late inner", "2026-05-12T00:00:00Z", "2026-05-11T00:00:00Z", False, False, False, False),
    ("6 late file no inner", "2026-05-12T00:00:00Z", None, False, False, False, False),
    ("7 early file no inner", "2026-05-09T00:00:00Z", None, True, True, True, True),
    ("8 anomaly both before", "2026-05-08T00:00:00Z", "2026-05-09T00:00:00Z", False, False, False, False),
    ("9 anomaly crossing", "2026-05-09T00:00:00Z", "2026-05-11T00:00:00Z", False, False, False, False),
    ("10 file 1s after", "2026-05-10T12:00:01Z", "2026-05-10T11:00:00Z", False, False, False, True),
]


class TestAdmissibilityTable(unittest.TestCase):
    def test_rows(self):
        for name, cap, inner, state, cite, link_off, link_on in CASES:
            o = obs(cap, inner)
            with self.subTest(name):
                self.assertEqual(admissible_for_state(o, AUDIT), state)
                self.assertEqual(admissible_for_citation(o, AUDIT), cite)
                self.assertEqual(admissible_for_link(o, AUDIT, False), link_off)
                self.assertEqual(admissible_for_link(o, AUDIT, True), link_on)

    def test_late_link_never_grants_state_or_citation(self):
        o = obs("2026-05-12T00:00:00Z", "2026-05-10T08:00:00Z")
        self.assertTrue(is_late_link_only(o, AUDIT, True))
        self.assertEqual(admissibility_set(o, AUDIT, True), frozenset({"link"}))
        self.assertEqual(admissibility_set(obs("2026-05-09T00:00:00Z"), AUDIT, True),
                         frozenset({"state", "citation", "link"}))

    def test_claims_by_event_time(self):
        self.assertTrue(admissible_claim({"_event_time": AUDIT}, AUDIT))
        self.assertFalse(admissible_claim({"_event_time": AUDIT + timedelta(seconds=1)}, AUDIT))


if __name__ == "__main__":
    unittest.main()
