"""Anti-leakage checks (plan A.1.2, G.3.3). The allow-list test is the primary
control; the grep checks are supplementary."""
import re
import unittest
from pathlib import Path

from audit import config
from audit.loader import open_input

CODE = Path(__file__).resolve().parents[1]
PRODUCTION = [CODE / "main.py"] + sorted((CODE / "audit").rglob("*.py"))
LITERALS = re.compile(
    r"sample_output|\bcase_\d+\b|\bevidence_\d+\b|\bactivity_\d+\b|\baudit_\d+\b|"
    r"\b(?:account|search|analytics|support|export|data_flow|backup|audit_record|tombstone|"
    r"legal_hold|marketing|object|cache|email_delivery)_\d+\b")
IMPORTS = re.compile(r"^\s*(?:from|import)\s+(?:\.\.?)?(?:evaluation|tests|tools)\b", re.M)


class TestLeakage(unittest.TestCase):
    def test_production_sources_exist(self):
        self.assertGreater(len(PRODUCTION), 5)

    def test_loader_refuses_reference_answers(self):
        with self.assertRaises(PermissionError):
            open_input(config.DATASET_DIR, "sample_output.csv")
        with self.assertRaises(PermissionError):
            open_input(config.DATASET_DIR, "output.csv")

    def test_no_case_or_evidence_literals_in_production(self):
        for p in PRODUCTION:
            hits = LITERALS.findall(p.read_text(encoding="utf-8"))
            self.assertEqual(hits, [], f"{p.name}: {hits}")

    def test_production_does_not_import_evaluation_tests_or_tools(self):
        for p in PRODUCTION:
            self.assertIsNone(IMPORTS.search(p.read_text(encoding="utf-8")), p.name)


if __name__ == "__main__":
    unittest.main()
