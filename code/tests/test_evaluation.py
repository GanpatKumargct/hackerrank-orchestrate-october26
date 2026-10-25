"""Stage 10 — evaluator metrics (G.3), custom cases (G.5) and remaining edge cases (G.4 E-3, E-11). Synthetic."""
import unittest

from audit import config
from audit.evidence.common import make_observation
from audit.models import IdentifierHit
from evaluation.custom_cases.builders import CASES
from evaluation.custom_cases.runner import run_case
from evaluation.metrics import aggregate, align, case_metrics, key_k, lcs
from tests.fixtures import manifest_row
from tests.test_state import StateCase


def step(op, rid, ev="", system="search_service"):
    return {"step_no": 0, "phase": config.OP_PHASE[op], "system_id": system, "resource_id": rid, "operation": op,
            "state": config.OP_STATE[op], "evidence_id": ev}


class TestMetrics(unittest.TestCase):
    EXP = [step("REPORT_REMAINING_RECORD", "search_1", "evidence_a"), step("DELETE_RECORD", "search_1"),
           step("VERIFY_RECORD_ABSENT", "search_1")]

    def test_exact_match(self):
        m = case_metrics("INCOMPLETE", self.EXP, "INCOMPLETE", self.EXP)
        self.assertEqual((m["strict_matches"], m["sequence_exact"], m["sequence_lcs_ratio"], m["citation_hits"]),
                         (3, True, 1.0, 1))

    def test_held_counts_as_wrong_with_no_predicted_steps(self):
        m = case_metrics(None, self.EXP, "INCOMPLETE", self.EXP)
        self.assertEqual((m["predicted_status"], m["status_correct"], m["pred_steps"], m["strict_matches"]),
                         ("HELD", False, 0, 0))

    def test_citation_and_field_differences(self):
        pred = [dict(self.EXP[0], evidence_id="evidence_b")] + self.EXP[1:]
        m = case_metrics("INCOMPLETE", pred, "INCOMPLETE", self.EXP)
        self.assertEqual((m["strict_matches"], m["citation_hits"], m["field_hits"]["evidence_id"]), (2, 0, 2))

    def test_duplicate_keys_pair_by_occurrence(self):
        pred = [self.EXP[0], self.EXP[0]]
        self.assertEqual(len(align(pred, self.EXP[:1], key_k)), 1)

    def test_lcs_and_false_complete(self):
        self.assertEqual(lcs([1, 2, 3, 4], [1, 3, 4]), 3)
        agg = aggregate({"a": case_metrics("COMPLETE", [], "INCOMPLETE", self.EXP),
                         "b": case_metrics("INCOMPLETE", self.EXP, "INCOMPLETE", self.EXP)})
        self.assertEqual((agg["false_complete"], agg["status_accuracy"]), (1, 0.5))
        self.assertEqual(agg["step_recall"], 0.5)


class TestCustomCases(unittest.TestCase):
    def test_every_custom_case_matches_its_rule_derived_expectation(self):
        for name in CASES:
            r = run_case(name)
            self.assertTrue(r["passed"], (name, r["checks"], r["got"]))
            self.assertEqual(r["validation_errors"], [], name)

    def test_cc4_scope_limit_deviation_is_reported_not_hidden(self):
        r = run_case("CC4")
        self.assertEqual(r["got"]["status"], "NOT_APPLICABLE")
        self.assertIn("plan_clause_deviation", r)


class TestEdgeCases(StateCase):
    def test_e3_lookalike_emails_never_attribute(self):            # G.4 E-3
        for raw in ("new.fx.jr@example.org", "new.fx1@example.org", "new.fx@example.org.evil"):
            h = IdentifierHit("email", raw, raw.lower(), "email", "RECORD_FIELD", "")
            self.assertNotEqual(self.resolver.attribute(h, None).status, "ATTRIBUTED", raw)

    def test_e11_log_level_never_changes_restore_state(self):      # G.4 E-11
        verdicts = set()
        for level in ("ERROR", "INFO"):
            o = make_observation(manifest_row=manifest_row("x.log", file_id="evidence_e11", captured="2026-05-10T00:00:00Z"),
                                 fmt="log", locator=f"l-{level}", resource_id="backup_90430",
                                 fields={"eligible": "true", "deletion_block": "false"},
                                 collection="backup_restore_entries", system_id="backup_service", system_field="system",
                                 context={"level": level})
            verdicts.add(self.run_assess("backup_90430", [o]).verdict)
        self.assertEqual(verdicts, {"VIOLATION_PROVEN"})


class TestEvaluatorGuards(unittest.TestCase):
    def test_refuses_repository_root_as_output(self):
        from evaluation import main as ev
        with self.assertRaises(SystemExit):
            ev.main(["--out-dir", str(config.REPO_ROOT)])


if __name__ == "__main__":
    unittest.main()
