"""Stage 9 — staged writer, held report, L1–L4 run validation and D.4 dependencies (plan F.3–F.4, D.4). Synthetic."""
import json
import unittest

from audit import config
from audit.decision import EMIT, HOLD, CaseResult, build_sets, build_steps, decide
from audit.dependencies import DependencyEdge, build_edges, check_order
from audit.errors import HeldReason as H
from audit.evidence.common import make_observation
from audit.evidence.index import ObservationIndex
from audit.intent import classify_intent
from audit.scope import CaseScope
from audit.serializer import (RunContext, SerializationError, render_csv, stage_run, to_row, validate_file)
from audit.state import assess
from tests.fixtures import TempDir, manifest_row
from tests.test_decision import acct_gone, audit_no_date, flow_off, search_gone, search_present
from tests.test_state import AUDIT, SUBJ, USER, StateCase, ob

DELETE_TEXT = "Please delete my account and personal data."


class RunCase(StateCase):
    def result(self, case_id, observations, text=DELETE_TEXT):
        """A CaseResult built through the real assessment, gate and step builder."""
        idx = ObservationIndex(observations, {})
        cap = {o.file_id: o.file_captured_at for o in observations}
        rids = sorted({o.resource_id for o in observations})
        a = {r: assess(r, AUDIT, USER, idx, self.resolver, [], cap, {}) for r in rids}
        sets = build_sets(a, {})
        intent = classify_intent(text)
        verdict = decide(intent.value, sets)
        scope = CaseScope(case_id, None, AUDIT, None, included={r: None for r in rids})
        r = CaseResult(case_id, "test", HOLD, intent=intent, sets=sets, assessments=a, scope=scope, audit_at=AUDIT)
        if verdict[0] == EMIT:
            r.outcome, r.status = EMIT, verdict[1]
            r.steps = tuple(build_steps(verdict[1], sets, a, idx, AUDIT, cap))
        else:
            r.held, r.detail = (verdict[1],), verdict[2]
        return r, idx, cap

    def run_stage(self, specs, expected=None):
        results, obs = [], []
        for cid, observations, *text in specs:
            r, _, _ = self.result(cid, observations, *text)
            results.append(r)
            obs += observations
        obs = list({o.obs_id: o for o in obs}.values())          # cases may share fixture observations
        idx = ObservationIndex(obs, {})
        cap = {o.file_id: o.file_captured_at for o in obs}
        ctx = RunContext(idx, cap, [])
        self._dir = TempDir()
        d = self._dir.__enter__()
        self.addCleanup(self._dir.__exit__, None, None, None)
        expected = expected if expected is not None else {r.case_id for r in results}
        code, summary = stage_run(results, expected, ctx, d / "run")
        return code, summary, d / "run"


class TestStagedRun(RunCase):
    def test_all_emitted_valid_is_complete_staging_without_root_output(self):
        root_before = (config.REPO_ROOT / "output.csv").exists()
        code, s, d = self.run_stage([("case_9201", [acct_gone()]),
                               ("case_9202", [acct_gone(), search_present()]),
                               ("case_9203", [acct_gone()], "Please fix my surname. Do not close the account.")])
        self.assertEqual((code, s["partial"], s["staging_file"]), (config.EXIT_OK, False, "staging_output.csv"))
        self.assertEqual(s["emitted"], {"COMPLETE": 1, "INCOMPLETE": 1, "NOT_APPLICABLE": 1})
        self.assertEqual((config.REPO_ROOT / "output.csv").exists(), root_before)
        text = (d / "staging_output.csv").read_text(encoding="utf-8")
        self.assertEqual(text.splitlines()[0], "case_id,deletion_status,steps_json")
        self.assertIn("case_9203,NOT_APPLICABLE,[]", text)

    def test_partial_staging_with_held_cases(self):
        code, s, d = self.run_stage([("case_9210", [acct_gone()]),
                               ("case_9204", [acct_gone(), audit_no_date()]),           # held
                               ("case_9205", [search_gone()])])                         # held: no account
        self.assertEqual((code, s["held"], s["partial"]), (config.EXIT_HELD, 2, True))
        self.assertFalse((d / "staging_output.csv").exists())
        rows = (d / "staging_output.partial.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual([r.split(",")[0] for r in rows[1:]], ["case_9210"])           # nothing padded
        self.assertFalse(s["run_level_checks"]["held_count_is_zero"])
        self.assertTrue(s["run_level_checks"]["emitted_plus_held_equals_inputs"])
        self.assertIn("NOT COMPLETE", s["status"])
        report = (d / "held_report.md").read_text(encoding="utf-8")
        self.assertIn("| case_9204 | REQUIRED_RESOURCE_UNRESOLVED |", report)
        self.assertIn("audit_record_91003: CONDITION_UNKNOWN", report)
        self.assertIn("PRIMARY_ACCOUNT_SLOT: NO_IN_SCOPE_USER_PROFILE", report)
        held = json.loads((d / "held_cases.json").read_text(encoding="utf-8"))
        self.assertEqual([h["case_id"] for h in held], ["case_9204", "case_9205"])     # numeric order
        self.assertNotIn("@", report + json.dumps(held))                                # no personal values

    def test_missing_and_duplicate_cases_are_invalid(self):
        code, s, _ = self.run_stage([("case_9206", [acct_gone()])], expected={"case_9206", "case_9207"})
        self.assertEqual(code, config.EXIT_INVALID)
        self.assertIn("no result for case_9207", s["run_errors"])
        code, s, _ = self.run_stage([("case_9206", [acct_gone()]), ("case_9206", [acct_gone()])])
        self.assertEqual(code, config.EXIT_INVALID)
        self.assertIn("duplicate result for case_9206", s["run_errors"])

    def test_tampered_citation_is_demoted_and_run_invalid(self):
        r, _, _ = self.result("case_9208", [acct_gone(), search_present()])
        steps = [dict(s) for s in r.steps]
        steps[0]["evidence_id"] = "evidence_s2"                       # not the proof file of the finding
        r.steps = tuple(steps)
        obs = [acct_gone(), search_present(), search_gone()]
        idx = ObservationIndex(obs, {})
        cap = {o.file_id: o.file_captured_at for o in obs}
        with TempDir() as d:
            code, s = stage_run([r], {"case_9208"}, RunContext(idx, cap, []), d / "run")
            self.assertEqual((code, r.outcome, r.held), (config.EXIT_INVALID, HOLD, (H.VALIDATION_FAILED,)))
            self.assertTrue(any("L3.6" in e for e in s["cases_failing_validation"]["case_9208"]))
            self.assertEqual(s["staging_rows"], 0)

    def test_repo_root_refused_and_held_never_serialized(self):
        r, _, _ = self.result("case_9209", [acct_gone(), audit_no_date()])
        with self.assertRaises(SerializationError):
            to_row(r)
        with self.assertRaises(ValueError):
            stage_run([], set(), RunContext(ObservationIndex([], {}), {}, []), config.REPO_ROOT)


class TestStageCommand(unittest.TestCase):
    def test_cli_stage_exits_nonzero_with_held_case_and_writes_only_the_run_dir(self):
        import contextlib
        import io
        import main
        from tests.fixtures import minimal_dataset
        root_before = (config.REPO_ROOT / "output.csv").exists()
        with TempDir() as d:
            ds = minimal_dataset(d)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = main.main(["stage", "--dataset", str(ds), "--run-dir", str(d / "run")])
            self.assertEqual(code, config.EXIT_HELD)
            self.assertEqual(sorted(p.name for p in (d / "run").iterdir()),
                             ["held_cases.json", "held_report.md", "run_summary.json", "staging_output.partial.csv",
                              "validation_report.md"])
            self.assertIn("root output.csv not written", out.getvalue())
        self.assertEqual((config.REPO_ROOT / "output.csv").exists(), root_before)


class TestFileValidator(unittest.TestCase):
    STEP = {"step_no": 1, "phase": "VERIFICATION", "system_id": "account_service", "resource_id": "account_1",
            "operation": "VERIFY_RECORD_ABSENT", "state": "ABSENT", "evidence_id": "evidence_a"}

    def text(self, rows, header="case_id,deletion_status,steps_json"):
        return header + "\n" + "".join(f"{r}\n" for r in rows)

    def good_rows(self):
        return [r for r in render_csv([("case_2", "COMPLETE", json.dumps([self.STEP])),
                                       ("case_10", "NOT_APPLICABLE", "[]")]).splitlines()[1:]]

    def test_valid_round_trip_with_quotes_and_numeric_order(self):
        rows = self.good_rows()
        self.assertEqual([r.split(",")[0] for r in rows], ["case_2", "case_10"])      # numeric, not lexicographic
        errs, missing, parsed = validate_file(self.text(rows), {"case_2", "case_10"}, {"evidence_a"})
        self.assertEqual((errs, missing), ([], []))
        self.assertEqual(parsed["case_2"], ("COMPLETE", [self.STEP]))

    def test_each_file_violation(self):
        ids, files = {"case_2", "case_10"}, {"evidence_a"}
        rows = self.good_rows()
        cases = {
            "L1.1": self.text(rows, header="id,status,steps"),
            "L1.3 duplicate": self.text(rows + [rows[0]]),
            "L1.3 unexpected": self.text(rows + ["case_11,NOT_APPLICABLE,[]"]),
            "L1.4": self.text(list(reversed(rows))),
            "L1.5": self.text([rows[0], "case_10,DONE,[]"]),
            "L1.6 json": self.text([rows[0], "case_10,NOT_APPLICABLE,[oops"]),
            "L1.6 array": self.text([rows[0], 'case_10,NOT_APPLICABLE,"{}"']),
            "NOT_APPLICABLE must have []": self.text([rows[0], "case_10,NOT_APPLICABLE," + rows[0].split(",", 2)[2]]),
        }
        for name, text in cases.items():
            errs, _, _ = validate_file(text, ids, files)
            self.assertTrue(any(e.startswith(name.split()[0]) or name.split()[0] in e for e in errs), (name, errs))
        errs, missing, _ = validate_file(self.text(rows[:1]), ids, files)
        self.assertEqual(missing, ["case_10"])
        self.assertTrue(any(e.startswith("L1.2") for e in errs))


class TestDependencies(unittest.TestCase):
    def step(self, op, rid, system="s"):
        return {"step_no": 0, "phase": config.OP_PHASE[op], "system_id": system, "resource_id": rid,
                "operation": op, "state": config.OP_STATE[op], "evidence_id": ""}

    def test_d1_holds_by_contract_order_and_crafted_violation_fails(self):
        edge = DependencyEdge("data_flow_1", "search_1", "RECREATES", "obs", "D1")
        ok = [self.step("DISABLE_DATA_FLOW", "data_flow_1"), self.step("DELETE_RECORD", "search_1")]
        self.assertEqual(check_order(ok, [edge]), ([], []))
        bad = list(reversed(ok))
        errors, _ = check_order(bad, [edge])
        self.assertEqual(len(errors), 1)

    def test_d2_conflict_reported_order_unchanged(self):
        edge = DependencyEdge("account_1", "search_1", "DERIVED_FROM", "obs", "D2")
        steps = [self.step("DELETE_RECORD", "account_1", "account_service"),
                 self.step("DELETE_RECORD", "search_1", "search_service")]
        before = [dict(s) for s in steps]
        errors, conflicts = check_order(steps, [edge])
        self.assertEqual((errors, len(conflicts), steps), ([], 1, before))
        self.assertIn("DEPENDENCY_ORDER_CONFLICT", conflicts[0])

    def test_edges_from_evidence_and_claims_only_within_scope(self):
        mk = lambda rid, fields, related=(): make_observation(
            manifest_row=manifest_row("x.json", file_id="evidence_d", captured="2026-05-09T00:00:00Z"), fmt="json",
            locator=rid, resource_id=rid, fields=fields, related_ids=related)
        obs = [mk("data_flow_1", {"connector_name": "search_profile_indexer", "enabled": "true"}),
               mk("search_2", {"email": SUBJ}, (("DERIVED_FROM", "account_3"),)),
               mk("account_3", {"email": SUBJ})]
        idx = ObservationIndex(obs, {})
        restore = {"activity_id": "activity_1", "event_type": "RESTORE_BACKUP", "resource_id": "backup_4",
                   "source_system": "backup_service", "details": "Restore job repopulated downstream resource search_2.",
                   "_event_time": AUDIT.replace(hour=1)}
        late = dict(restore, activity_id="activity_2", _event_time=AUDIT.replace(day=11))
        owners = {"data_flow_1": "integration_service", "search_2": "search_service", "account_3": "account_service",
                  "backup_4": "backup_service"}
        edges = build_edges({"data_flow_1", "search_2", "account_3", "backup_4"}, owners, idx, [restore, late], AUDIT)
        self.assertEqual({(e.upstream, e.downstream, e.type) for e in edges},
                         {("data_flow_1", "search_2", "RECREATES"), ("account_3", "search_2", "DERIVED_FROM"),
                          ("backup_4", "search_2", "RESTORES")})
        narrow = build_edges({"search_2"}, owners, idx, [restore], AUDIT)
        self.assertEqual(narrow, ())                                     # edges never pull resources into scope


if __name__ == "__main__":
    unittest.main()
