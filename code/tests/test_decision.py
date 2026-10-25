"""Stage 8 — sets, completeness gate and step construction (plan E.4–E.6, F.1–F.2, G.1.1). Synthetic data.

Sets are built from observations through the Stage 7 assessment, never injected.
"""
import copy
import unittest
from types import SimpleNamespace

from audit import config
from audit.decision import (EMIT, HOLD, PRIMARY_ACCOUNT_SLOT, CaseAnalyzer, StepBuildError, build_sets,
                            build_steps, decide, validate_steps)
from audit.errors import HeldReason as H
from audit.evidence.index import ObservationIndex
from audit.identity import Subject, UnresolvedSubject
from audit.scope import CaseScope
from audit.state import assess
from tests.test_state import AUDIT, OTHER, SUBJ, USER, StateCase, ob

DELETE_TEXT = "Please delete my account and personal data."


# Fixture observations (fictional IDs 91xxx); each proves one state by itself.
def acct_gone():
    return ob("evidence_a", "l1", "account_91001", {"rows": "0", "http_status": "404"},
              event="profile_lookup_completed", fmt="log")


def acct_present():
    return ob("evidence_a", "l2", "account_91001", {"email": SUBJ}, collection="customer_profiles",
              inner="2026-05-09T12:00:00Z")


def search_present():
    return ob("evidence_s", "l1", "search_91002", {"email": SUBJ}, collection="customer_search_documents",
              system="search_service")


def audit_retained():
    return ob("evidence_r", "l1", "audit_record_91003", {"subject_reference": USER,
                                                          "retention_until": "2031-01-01T00:00:00Z"},
              collection="security_audit_records", system="security_service")


def audit_no_date():
    return ob("evidence_r", "l1", "audit_record_91003", {"subject_reference": USER},
              collection="security_audit_records", system="security_service")


def flow_off():
    return ob("evidence_f", "l1", "data_flow_91004", {"enabled": "false"}, collection="connector_subscriptions",
              system="integration_service")


def backup_blocked():
    return ob("evidence_b", "l1", "backup_91005", {"restore_allowed": "false"}, collection="backup_restore_entries",
              system="backup_service")


def search_gone():
    return ob("evidence_s2", "l1", "search_91006", {"result": "NOT_FOUND"}, record_type="SEARCH_INDEX_ENTRY",
              system="search_service")


class GateCase(StateCase):
    def run_case(self, observations, rids=None, wf=(), intent="DELETION", activities=()):
        idx = ObservationIndex(observations, {})
        cap = {o.file_id: o.file_captured_at for o in observations}
        rids = rids or sorted({o.resource_id for o in observations})
        acts = list(activities)
        a = {r: assess(r, AUDIT, USER, idx, self.resolver, acts, cap, {}) for r in rids}
        w = {r: assess(r, AUDIT, USER, idx, self.resolver, acts, cap, {}) for r in wf}
        sets = build_sets(a, w)
        verdict = decide(intent, sets)
        steps = None
        if verdict[0] == EMIT:
            try:
                steps = build_steps(verdict[1], sets, a, idx, AUDIT, cap)
            except StepBuildError as e:
                verdict = (HOLD, e.reason, (e.detail,))
        return verdict, sets, steps


class TestGate(GateCase):
    def test_d1_all_compliant_complete_with_one_citation_each(self):
        obs = [acct_gone(), audit_retained(), flow_off(), backup_blocked(), search_gone()]
        (kind, status, _), sets, steps = self.run_case(obs)
        self.assertEqual((kind, status), (EMIT, "COMPLETE"))
        self.assertEqual(len(steps), len(sets.req))
        self.assertTrue(all(s["phase"] == "VERIFICATION" and s["evidence_id"] for s in steps))
        self.assertEqual({(s["operation"], s["resource_id"], s["evidence_id"]) for s in steps}, {
            ("VERIFY_RECORD_ABSENT", "account_91001", "evidence_a"),
            ("VERIFY_RECORD_PRESENT", "audit_record_91003", "evidence_r"),
            ("VERIFY_DATA_FLOW_DISABLED", "data_flow_91004", "evidence_f"),
            ("VERIFY_RESTORE_BLOCKED", "backup_91005", "evidence_b"),
            ("VERIFY_RECORD_ABSENT", "search_91006", "evidence_s2")})

    def test_d2_one_unknown_member_holds_not_complete(self):
        obs = [acct_gone(), audit_no_date(), flow_off(), backup_blocked(), search_gone()]
        (kind, reason, detail), _, _ = self.run_case(obs)
        self.assertEqual((kind, reason), (HOLD, H.REQUIRED_RESOURCE_UNRESOLVED))
        self.assertIn(("audit_record_91003", "CONDITION_UNKNOWN"), detail)

    def test_d3_every_member_unknown(self):
        (kind, reason, _), _, _ = self.run_case([audit_no_date()], rids=["audit_record_91003", "export_91099"])
        self.assertEqual((kind, reason), (HOLD, H.REQUIRED_RESOURCE_UNRESOLVED))

    def test_d4_violation_incomplete_with_full_verification_set(self):
        obs = [acct_gone(), search_present(), audit_retained(), flow_off()]
        (kind, status, _), sets, steps = self.run_case(obs)
        self.assertEqual((kind, status), (EMIT, "INCOMPLETE"))
        phases = [s["phase"] for s in steps]
        self.assertEqual(phases, sorted(phases, key=config.PHASES.index))
        self.assertEqual([s["operation"] for s in steps if s["phase"] != "VERIFICATION"],
                         ["REPORT_REMAINING_RECORD", "DELETE_RECORD"])
        finding = steps[0]
        self.assertEqual((finding["resource_id"], finding["evidence_id"]), ("search_91002", "evidence_s"))
        verify = [s for s in steps if s["phase"] == "VERIFICATION"]
        self.assertEqual(len(verify), len(sets.req))
        self.assertTrue(all(s["evidence_id"] == "" for s in steps[1:]))
        self.assertIn(("VERIFY_RECORD_PRESENT", "audit_record_91003"),
                      {(s["operation"], s["resource_id"]) for s in verify})
        self.assertEqual([s["step_no"] for s in steps], list(range(1, len(steps) + 1)))

    def test_d5_violation_plus_unknown(self):
        (kind, reason, _), _, _ = self.run_case([acct_gone(), search_present(), audit_no_date()])
        self.assertEqual((kind, reason), (HOLD, H.VERIFICATION_SET_INCOMPLETE))

    def test_d6_retained_record_missing_always_held(self):
        tomb = ob("evidence_t", "l1", "tombstone_91007", {"subject_reference": None, "name": None, "email": None,
                                                          "phone": None, "email_hash": None,
                                                          "account_status": "DELETED"},
                  collection="deleted_customer_references", system="identity_service")
        for extra in ([], [search_present()]):
            (kind, reason, _), _, _ = self.run_case([acct_gone(), tomb] + extra)
            self.assertEqual((kind, reason), (HOLD, H.RETAINED_RECORD_MISSING))

    def test_d7_primary_account_slot_empty(self):
        (kind, reason, detail), sets, _ = self.run_case([search_gone(), flow_off()])
        self.assertEqual((kind, reason), (HOLD, H.REQUIRED_RESOURCE_UNRESOLVED))
        self.assertIn(PRIMARY_ACCOUNT_SLOT, sets.unresolved)

    def test_d8_category_ambiguous_member(self):
        amb = [ob("evidence_x", "l1", "record_91008", {"file": "a"}, collection="support_conversations",
                  system="support_platform"),
               ob("evidence_x", "l2", "record_91008", {"file": "b"}, collection="ticket_attachments",
                  system="support_platform")]
        (kind, reason, detail), _, _ = self.run_case([acct_gone()] + amb)
        self.assertEqual((kind, reason), (HOLD, H.REQUIRED_RESOURCE_UNRESOLVED))
        self.assertIn(("record_91008", "CATEGORY_AMBIGUOUS"), detail)

    def test_d9_equal_time_conflict(self):
        t = "2026-05-09T00:00:00Z"
        a1 = ob("evidence_a", "l1", "account_91001", {"result": "FOUND"}, record_type="USER_PROFILE", inner=t)
        a2 = ob("evidence_c", "l2", "account_91001", {"result": "NOT_FOUND"}, record_type="USER_PROFILE", inner=t)
        (kind, reason, detail), _, _ = self.run_case([a1, a2])
        self.assertEqual(kind, HOLD)
        self.assertIn(("account_91001", "CONFLICTING_OBSERVATIONS"), detail)

    def test_d12_unsure_intent_held_and_non_deletion_not_applicable(self):
        obs = [acct_gone()]
        self.assertEqual(self.run_case(obs, intent="UNSURE")[0][:2], (HOLD, H.UNSURE_INTENT))
        verdict, _, steps = self.run_case([acct_present()], intent="NON_DELETION")
        self.assertEqual((verdict[:2], steps), ((EMIT, "NOT_APPLICABLE"), []))

    def test_workflow_candidate_with_observed_violation_holds(self):
        wf = ob("evidence_w", "l1", "search_91009", {"email": OTHER, "result": "FOUND"},
                record_type="SEARCH_INDEX_ENTRY", system="search_service")
        (kind, reason, detail), _, _ = self.run_case([acct_gone(), wf], rids=["account_91001"], wf=["search_91009"])
        self.assertEqual((kind, reason), (HOLD, H.REQUIRED_RESOURCE_UNRESOLVED))
        compliant_wf = ob("evidence_w", "l1", "search_91009", {"result": "NOT_FOUND"},
                          record_type="SEARCH_INDEX_ENTRY", system="search_service")
        verdict, _, steps = self.run_case([acct_gone(), compliant_wf], rids=["account_91001"], wf=["search_91009"])
        self.assertEqual(verdict[:2], (EMIT, "COMPLETE"))
        self.assertNotIn("search_91009", {s["resource_id"] for s in steps})   # candidates never produce steps


class TestStepRules(GateCase):
    def test_claims_never_add_or_remove_steps(self):
        claim = {"activity_id": "activity_9101", "resource_id": "search_91002", "event_type": "DELETE_RECORD",
                 "source_system": "deletion_worker", "reported_result": "SUCCESS",
                 "_event_time": AUDIT.replace(hour=1)}
        base = self.run_case([acct_gone(), search_present()])[2]
        with_claim = self.run_case([acct_gone(), search_present()], activities=[claim])[2]
        self.assertEqual(base, with_claim)
        self.assertNotIn("activity_9101", {s["evidence_id"] for s in with_claim})

    def test_system_ambiguous_holds(self):
        orphan = ob("evidence_s", "l1", "search_91002", {"email": SUBJ}, collection="customer_search_documents",
                    system=None)
        (kind, reason, _), _, _ = self.run_case([acct_gone(), orphan])
        self.assertEqual((kind, reason), (HOLD, H.SYSTEM_AMBIGUOUS))

    def test_absence_cannot_prove_a_redacted_state(self):
        # Q-ABSENT-NONDELETE-VERIFY: a support message proven absent is not compliant (policy requires REDACT)
        gone = ob("evidence_m", "l1", "support_91010", {"result": "NOT_FOUND", "ticket_id": "CS-9"},
                  collection="support_conversations", system="support_platform")
        (kind, reason, detail), _, _ = self.run_case([acct_gone(), gone])
        self.assertEqual((kind, reason), (HOLD, H.REQUIRED_RESOURCE_UNRESOLVED))
        self.assertIn(("support_91010", "POLICY_GAP"), detail)

    def test_verify_absent_positive_single_resource_specific_negative(self):
        (kind, status, _), _, steps = self.run_case([acct_gone(), search_gone()])
        self.assertEqual((kind, status), (EMIT, "COMPLETE"))
        self.assertEqual({(s["operation"], s["resource_id"], s["evidence_id"]) for s in steps},
                         {("VERIFY_RECORD_ABSENT", "account_91001", "evidence_a"),
                          ("VERIFY_RECORD_ABSENT", "search_91006", "evidence_s2")})

    def test_absence_proof_never_cited_for_another_end_state(self):
        # defence in depth: even a (wrongly) compliant non-DELETE assessment with an absence proof is refused
        gone = ob("evidence_m", "l1", "support_91010", {"result": "NOT_FOUND", "ticket_id": "CS-9"},
                  collection="support_conversations", system="support_platform")
        idx = ObservationIndex([acct_gone(), gone], {})
        cap = {"evidence_a": AUDIT.replace(hour=0), "evidence_m": AUDIT.replace(hour=0)}
        a = {r: assess(r, AUDIT, USER, idx, self.resolver, [], cap, {}) for r in ("account_91001", "support_91010")}
        a["support_91010"].verdict, a["support_91010"].proof = "COMPLIANT_PROVEN", (gone.obs_id,)
        a["support_91010"].reasons = ()
        sets = build_sets(a, {})
        with self.assertRaises(StepBuildError) as e:
            build_steps("COMPLETE", sets, a, idx, AUDIT, cap)
        self.assertIn("CITATION_STATE_MISMATCH", e.exception.detail)

    def test_order_independent_of_input_order(self):
        obs = [flow_off(), search_present(), acct_present(), audit_retained()]
        a = self.run_case(obs)[2]
        b = self.run_case(list(reversed(obs)))[2]
        self.assertEqual(a, b)
        keys = [(config.OP_INDEX[s["operation"]], s["system_id"], s["resource_id"]) for s in a]
        self.assertEqual(keys, sorted(keys))


class TestValidator(unittest.TestCase):
    FILES = {"evidence_a"}

    def good(self):
        mk = lambda n, op, ev: {"step_no": n, "phase": config.OP_PHASE[op], "system_id": "search_service",
                                "resource_id": "search_1", "operation": op, "state": config.OP_STATE[op],
                                "evidence_id": ev}
        return [mk(1, "REPORT_REMAINING_RECORD", "evidence_a"), mk(2, "DELETE_RECORD", ""),
                mk(3, "VERIFY_RECORD_ABSENT", "")]

    def test_valid_and_each_violation(self):
        self.assertEqual(validate_steps("INCOMPLETE", self.good(), self.FILES), [])
        broken = {
            "phase/state": lambda s: s[0].update(state="ACTIVE"),
            "not consecutive": lambda s: s[1].update(step_no=5),
            "order": lambda s: s.reverse(),
            "duplicate": lambda s: s.append(dict(s[2], step_no=4)),
            "empty evidence_id": lambda s: s[1].update(evidence_id="evidence_a"),
            "FINDING without evidence": lambda s: s[0].update(evidence_id=""),
            "manifest file_id": lambda s: s[0].update(evidence_id="activity_1"),
            "keys": lambda s: s[0].pop("state"),
            "unknown operation": lambda s: s[0].update(operation="PURGE"),
        }
        for name, mutate in broken.items():
            steps = copy.deepcopy(self.good())
            mutate(steps)
            self.assertTrue(validate_steps("INCOMPLETE", steps, self.FILES), name)

    def test_status_rules(self):
        self.assertEqual(validate_steps("NOT_APPLICABLE", [], self.FILES), [])
        self.assertTrue(validate_steps("NOT_APPLICABLE", self.good(), self.FILES))
        self.assertTrue(validate_steps("COMPLETE", self.good(), self.FILES))       # non-verification steps
        self.assertTrue(validate_steps("INCOMPLETE", self.good()[1:], self.FILES))  # no finding
        self.assertTrue(validate_steps("HELD", [], self.FILES))
        late = {"evidence_a": AUDIT.replace(day=11)}
        self.assertTrue(validate_steps("INCOMPLETE", self.good(), self.FILES, AUDIT, late))


class TestAnalyzer(StateCase):
    """E.2.1 identity branch and F.3.1 errors through the per-case procedure."""

    def analyzer(self, scope_fn, observations=()):
        idx = ObservationIndex(list(observations), {})
        ds = SimpleNamespace(manifest=[], activities=[])
        return CaseAnalyzer(ds, idx, self.resolver, SimpleNamespace(build=scope_fn))

    def req(self, text):
        return {"case_id": "case_9100", "_source": "test", "request_text": text, "_audit_at": AUDIT}

    def test_d10_d11_unresolved_identity(self):
        unresolved = lambda req: CaseScope(req["case_id"], UnresolvedSubject("x@example.org", frozenset()), AUDIT,
                                           None)
        an = self.analyzer(unresolved)
        held = an.analyze(self.req(DELETE_TEXT))
        self.assertEqual((held.outcome, held.held), (HOLD, (H.IDENTITY_UNRESOLVED,)))
        na = an.analyze(self.req("Please fix my surname. Do not close the account."))
        self.assertEqual((na.outcome, na.status, na.steps), (EMIT, "NOT_APPLICABLE", ()))

    def test_d13_exception_is_held_error_never_a_row(self):
        def boom(req):
            raise RuntimeError("synthetic failure")
        r = self.analyzer(boom).analyze(self.req(DELETE_TEXT))
        self.assertEqual((r.outcome, r.held, r.status, r.steps), (HOLD, (H.ERROR,), None, ()))

    def test_end_to_end_emit(self):
        o = acct_gone()
        subject = Subject(USER, SUBJ, "current", AUDIT, (), frozenset())
        scope = lambda req: CaseScope(req["case_id"], subject, AUDIT, None,
                                      included={"account_91001": None})
        an = self.analyzer(scope, [o])
        an.capture = {o.file_id: o.file_captured_at}
        r = an.analyze(self.req(DELETE_TEXT))
        self.assertEqual((r.outcome, r.status, [s["evidence_id"] for s in r.steps]), (EMIT, "COMPLETE", ["evidence_a"]))


if __name__ == "__main__":
    unittest.main()
