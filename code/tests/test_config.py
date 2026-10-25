import csv
import importlib
import os
import unittest

from audit import config


class TestOperations(unittest.TestCase):
    def test_operations_match_problem_statement_table(self):
        expected = [
            ("REPORT_REMAINING_RECORD", "FINDING", "PRESENT"),
            ("REPORT_EXPOSED_PII", "FINDING", "PRESENT"),
            ("REPORT_ACTIVE_DATA_FLOW", "FINDING", "ACTIVE"),
            ("REPORT_RESTORE_RISK", "FINDING", "ACTIVE"),
            ("DISABLE_DATA_FLOW", "REMEDIATION", "DISABLED"),
            ("BLOCK_RESTORE", "REMEDIATION", "BLOCKED"),
            ("DELETE_RECORD", "REMEDIATION", "ABSENT"),
            ("REDACT_RECORD", "REMEDIATION", "REDACTED"),
            ("ANONYMIZE_RECORD", "REMEDIATION", "ANONYMIZED"),
            ("VERIFY_RECORD_ABSENT", "VERIFICATION", "ABSENT"),
            ("VERIFY_RECORD_PRESENT", "VERIFICATION", "PRESENT"),
            ("VERIFY_RECORD_REDACTED", "VERIFICATION", "REDACTED"),
            ("VERIFY_RECORD_ANONYMIZED", "VERIFICATION", "ANONYMIZED"),
            ("VERIFY_DATA_FLOW_DISABLED", "VERIFICATION", "DISABLED"),
            ("VERIFY_RESTORE_BLOCKED", "VERIFICATION", "BLOCKED"),
        ]
        self.assertEqual(list(config.OPERATIONS), expected)

    def test_phase_order_follows_operation_index(self):
        phases = [config.PHASES.index(p) for _, p, _ in config.OPERATIONS]
        self.assertEqual(phases, sorted(phases))


class TestTreatments(unittest.TestCase):
    def test_every_rule_category_has_matching_treatment(self):
        with open(config.DATASET_DIR / "deletion_rules.csv", encoding="utf-8") as fh:
            rules = list(csv.DictReader(fh))
        self.assertEqual(len(rules), 15)
        for r in rules:
            t = config.TREATMENTS[r["data_category"]]
            self.assertEqual(t.source, r["rule_id"])
            self.assertTrue(t.action.startswith(r["required_action"]))

    def test_chains_use_valid_operations_in_right_phase(self):
        for cat, t in config.TREATMENTS.items():
            for op, phase in ((t.finding, "FINDING"), (t.remediation, "REMEDIATION"),
                              (t.verification, "VERIFICATION")):
                if op is not None:
                    self.assertEqual(config.OP_PHASE[op], phase, cat)
            self.assertEqual(t.finding is None, t.remediation is None, cat)

    def test_data_flow_is_supplemental_and_retained_have_no_remediation(self):
        self.assertEqual(config.TREATMENTS["DATA_FLOW"].source, "SUPPLEMENTAL")
        for cat in ("SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD"):
            self.assertIsNone(config.TREATMENTS[cat].remediation)
            self.assertEqual(config.TREATMENTS[cat].verification, "VERIFY_RECORD_PRESENT")
        self.assertEqual(config.TREATMENTS["BACKUP_ARCHIVE"].remediation, "BLOCK_RESTORE")
        self.assertIn("BACKUP_ARCHIVE", config.NEVER_DELETE)


class TestDecidedFlags(unittest.TestCase):
    def test_flags_match_decision_register(self):
        self.assertEqual(config.EPISODE_MODE, "prior_request")
        self.assertTrue(config.LATE_INNER_LINKING)
        self.assertEqual(config.WORKFLOW_LINK_MODE, "unique_only")
        self.assertFalse(config.MEDIA_TRANSMISSION_AUTHORIZED)
        self.assertEqual(config.SYSTEM_ALIASES, {"profile_service": "account_service",
                                                 "support_replica": "support_platform"})

    def test_llm_disabled_by_default(self):
        saved = os.environ.pop("AUDIT_LLM_ENABLED", None)
        try:
            self.assertFalse(importlib.reload(config).AUDIT_LLM_ENABLED)
        finally:
            if saved is not None:
                os.environ["AUDIT_LLM_ENABLED"] = saved
            importlib.reload(config)

    def test_row_sort_key_is_numeric(self):
        ids = ["case_100", "case_99", "case_33", "case_550"]
        self.assertEqual(sorted(ids, key=config.ROW_SORT_KEY),
                         ["case_33", "case_99", "case_100", "case_550"])

    def test_reference_answers_not_on_input_allow_list(self):
        self.assertNotIn("sample_output.csv", config.INPUT_FILES)
        self.assertNotIn("output.csv", config.INPUT_FILES)


if __name__ == "__main__":
    unittest.main()
