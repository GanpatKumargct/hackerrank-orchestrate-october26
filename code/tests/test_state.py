"""Stage 7 — resource state interpretation and verdicts (B.4, C.8, D.3, E.3.1). Synthetic data."""
import unittest
from unittest import mock

from audit import config
from audit.errors import HeldReason, ReportNote, UncertaintyReason as U
from audit.evidence.common import make_observation
from audit.evidence.index import ObservationIndex
from audit.identity import IdentityResolver
from audit.loader import load_dataset
from audit.models import CoverageUnit, FileExtraction
from audit.state import assess, existence_reading
from audit.timeutil import parse_ts
from tests.fixtures import TempDir, manifest_row, minimal_dataset, sha

SUBJ, OTHER, USER = "new.fx@example.org", "other.fx@example.org", "user_9001"
AUDIT = parse_ts("2026-05-10T12:00:00Z")


def ob(fid, loc, rid, fields=None, *, captured="2026-05-10T00:00:00Z", inner=None, collection=None,
       record_type=None, event=None, copy=None, system="account_service", fmt="json"):
    return make_observation(manifest_row=manifest_row("x", file_id=fid, captured=captured), fmt=fmt, locator=loc,
                            resource_id=rid, fields=fields or {}, observed_raw=inner, collection=collection,
                            record_type=record_type, copy_location=copy, system_id=system,
                            system_field="system" if system else None,
                            context={"event": event} if event else None)


class StateCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def m(t):
            t["user_identities.csv"].append(dict(user_id="user_9002", name="Other", email=OTHER,
                                                 phone="+44 20 0000 0009", email_hash=sha(OTHER),
                                                 updated_at="2026-03-01T00:00:00Z"))
        with TempDir() as d:
            cls.resolver = IdentityResolver(load_dataset(minimal_dataset(d, m)))

    def run_assess(self, rid, observations, reports=None, activities=(), captures=None):
        idx = ObservationIndex(observations, reports or {})
        cap = {o.file_id: o.file_captured_at for o in observations}
        cap.update(captures or {})
        return assess(rid, AUDIT, USER, idx, self.resolver, list(activities), cap, {})


class TestExistence(StateCase):
    def test_named_negative_absent_single_proof_claims_ignored(self):
        o = ob("evidence_a", "l1", "account_90400", {"rows": "0", "http_status": "404"},
               event="profile_lookup_completed", fmt="log")
        claim = {"activity_id": "activity_9400", "resource_id": "account_90400", "event_type": "DELETE_RECORD",
                 "source_system": "deletion_worker", "_event_time": parse_ts("2026-05-02T00:00:00Z")}
        a = self.run_assess("account_90400", [o], activities=[claim])
        self.assertEqual((a.verdict, a.proof, a.claims), ("COMPLIANT_PROVEN", (o.obs_id,), ("activity_9400",)))

    def test_latest_observation_wins(self):
        present = ob("evidence_a", "l1", "account_90401", {"status_code": "200"}, collection="profile_lookups",
                     inner="2026-05-08T00:00:00Z")
        absent = ob("evidence_b", "l2", "account_90401", {"status_code": "404"}, collection="profile_lookups",
                    inner="2026-05-09T00:00:00Z")
        self.assertEqual(self.run_assess("account_90401", [present, absent]).verdict, "COMPLIANT_PROVEN")
        later = ob("evidence_c", "l3", "account_90401", {"status_code": "200"}, collection="profile_lookups",
                   inner="2026-05-09T06:00:00Z")
        a = self.run_assess("account_90401", [present, absent, later])
        self.assertEqual((a.verdict, a.proof), ("VIOLATION_PROVEN", (later.obs_id,)))

    def test_same_time_conflict_and_quality_resolution(self):
        t = "2026-05-09T00:00:00Z"
        a1 = ob("evidence_a", "l1", "account_90402", {"result": "FOUND"}, record_type="USER_PROFILE", inner=t)
        a2 = ob("evidence_b", "l2", "account_90402", {"result": "NOT_FOUND"}, record_type="USER_PROFILE", inner=t)
        self.assertEqual(self.run_assess("account_90402", [a1, a2]).reasons, (U.CONFLICTING_OBSERVATIONS,))
        row = ob("evidence_c", "l3", "account_90403", {"email": SUBJ}, collection="customer_profiles", inner=t)
        neg = ob("evidence_d", "l4", "account_90403", {"result": "NOT_FOUND"}, record_type="USER_PROFILE", inner=t)
        a = self.run_assess("account_90403", [row, neg])
        self.assertEqual(a.verdict, "VIOLATION_PROVEN")
        self.assertIn(ReportNote.RESOLVED_BY_QUALITY, a.dimensions["existence"].notes)

    def test_cutoff_and_late_files(self):
        after = ob("evidence_a", "l1", "account_90404", {"rows": "1"}, captured="2026-05-12T00:00:00Z",
                   inner="2026-05-11T00:00:00Z", event="profile_lookup_completed", fmt="log")
        late_link = ob("evidence_b", "l2", "account_90404", {"rows": "1"}, captured="2026-05-12T00:00:00Z",
                       inner="2026-05-10T08:00:00Z", event="profile_lookup_completed", fmt="log")
        a = self.run_assess("account_90404", [after, late_link])
        self.assertEqual((a.verdict, a.reasons), ("UNKNOWN", (U.POST_CUTOFF_ONLY,)))

    def test_replica_presence_beats_primary_absence(self):
        prim = ob("evidence_a", "l1", "account_90405", {"rows": "0"}, event="profile_lookup_completed", fmt="log",
                  inner="2026-05-09T10:00:00Z")
        rep = ob("evidence_b", "l2", "account_90405", {"email": SUBJ}, collection="customer_profiles",
                 copy="read_replica", fmt="sql")
        a = self.run_assess("account_90405", [prim, rep])
        self.assertEqual((a.verdict, a.proof), ("VIOLATION_PROVEN", (rep.obs_id,)))

    def _omission_case(self, locator, subject_in_file):
        anchor_fields = {"email": SUBJ} if subject_in_file else {"email": OTHER}
        anchor = ob("evidence_snap", "anchor", "search_90499", anchor_fields, collection="customer_search_documents",
                    system="search_service")
        target = ob("evidence_old", "l1", "account_90406", {"email": SUBJ}, collection="customer_profiles",
                    captured="2026-05-01T00:00:00Z")
        unit = CoverageUnit("evidence_snap", "COLLECTION", "account_service", "customer_profiles", "primary",
                            "2026-05-09T00:00:00Z", frozenset(), locator)
        rep = FileExtraction("evidence_snap", "p", "json")
        rep.coverage.append(unit)
        return self.run_assess("account_90406", [anchor, target], {"evidence_snap": rep})

    def test_omission_direct_table_and_subject_scoped_bundle(self):
        self.assertEqual(self._omission_case("table:customer_profiles_primary", False).verdict, "COMPLIANT_PROVEN")
        self.assertEqual(self._omission_case("snapshots[0]", True).verdict, "COMPLIANT_PROVEN")
        self.assertEqual(self._omission_case("snapshots[0]", False).verdict, "VIOLATION_PROVEN")  # not this subject

    def test_copy_scope_single_observation_rule(self):
        neg = ob("evidence_a", "l1", "account_90407", {"rows": "0"}, event="profile_lookup_completed", fmt="log",
                 inner="2026-05-09T10:00:00Z")
        unit = lambda copy: CoverageUnit("evidence_dump", "COLLECTION", "account_service", "customer_profiles", copy,
                                         None, frozenset(), f"table:customer_profiles_{copy}")
        rep = FileExtraction("evidence_dump", "p", "sql")
        rep.coverage += [unit("primary"), unit("failover_replica")]
        other = ob("evidence_dump", "row", "account_90499", {"email": OTHER}, collection="customer_profiles", fmt="sql")
        caps = {"evidence_dump": parse_ts("2026-05-08T00:00:00Z")}
        with mock.patch.object(config, "COPY_SCOPE", "collection"):
            a = self.run_assess("account_90407", [neg, other], {"evidence_dump": rep}, captures=caps)
        self.assertEqual(a.reasons, (U.PROOF_NOT_SINGLE_OBSERVATION,))
        with mock.patch.object(config, "COPY_SCOPE", "resource"):
            a = self.run_assess("account_90407", [neg, other], {"evidence_dump": rep}, captures=caps)
        self.assertEqual((a.verdict, a.proof), ("COMPLIANT_PROVEN", (neg.obs_id,)))

    def test_no_observation_and_ungrounded(self):
        a = self.run_assess("account_90408", [])
        self.assertEqual(a.reasons, (U.NO_ADMISSIBLE_OBSERVATION,))
        b = self.run_assess("account_90409", [ob("evidence_a", "l1", "account_90409", {"x": "1"}, system=None)])
        self.assertEqual(b.reasons, (U.CATEGORY_UNGROUNDED,))

    def test_existence_reading_values(self):
        r = existence_reading(ob("e", "l", "s", {"result": "hit"}, fmt="log", event="index_query_completed"))
        self.assertEqual((r.value, r.quality), ("PRESENT", 2))


class TestPii(StateCase):
    def analytics(self, loc, fields, inner="2026-05-09T00:00:00Z", fid="evidence_a", **kw):
        return ob(fid, loc, "analytics_90410", fields, collection="customer_analytics_reports",
                  system="analytics_platform", inner=inner, **kw)

    def test_single_observation_clean_vs_split(self):
        clean = self.analytics("l1", {"user_id": None, "email": None, "phone": None, "email_hash": None})
        self.assertEqual(self.run_assess("analytics_90410", [clean]).verdict, "COMPLIANT_PROVEN")
        part1 = ob("evidence_a", "l1", "analytics_90410", {"email": None, "phone": None},
                   event="analytics_profile_read", fmt="log", system="analytics_platform")
        part2 = ob("evidence_b", "l2", "analytics_90410", {"customer_reference": None, "email_hash": None},
                   event="analytics_profile_read_completed", fmt="log", system="analytics_platform")
        self.assertEqual(self.run_assess("analytics_90410", [part1, part2]).reasons, (U.PROOF_NOT_SINGLE_OBSERVATION,))
        self.assertEqual(self.run_assess("analytics_90410", [part1]).reasons, (U.FIELD_COVERAGE_INCOMPLETE,))

    def test_exposed_and_label_contradiction(self):
        exposed = self.analytics("l1", {"user_id": None, "email": SUBJ, "phone": None, "email_hash": None,
                                        "result": "ANONYMIZED"})
        self.assertEqual(self.run_assess("analytics_90410", [exposed]).verdict, "VIOLATION_PROVEN")

    def test_handover_labels(self):
        label = lambda result, subject: ob("evidence_h", "l1", "analytics_90411",
                                           {"result": result, "subject": subject, "system": "analytics_platform"},
                                           record_type="ANALYTICS_PROFILE", system="analytics_platform", fmt="text")
        self.assertEqual(self.run_assess("analytics_90411", [label("ANONYMIZED", "no direct identifier")]).verdict,
                         "COMPLIANT_PROVEN")
        self.assertEqual(self.run_assess("analytics_90411", [label("IDENTIFIABLE", SUBJ)]).verdict, "VIOLATION_PROVEN")
        self.assertEqual(self.run_assess("analytics_90411", [label("ANONYMIZED", "")]).reasons, (U.LABEL_ONLY,))

    def test_support_message_redaction_and_condition(self):
        sup = lambda fields: ob("evidence_s", "l1", "support_90412", fields, collection="tickets",
                                system="support_platform")
        ok = sup({"message_excerpt": "Delivery query", "requester_email": None, "requester_phone": None,
                  "requester_name": None, "customer_reference": USER})
        self.assertEqual(self.run_assess("support_90412", [ok]).verdict, "COMPLIANT_PROVEN")
        bad = sup({"message_excerpt": "Delivery query", "requester_email": SUBJ, "requester_phone": None,
                   "requester_name": None})
        self.assertEqual(self.run_assess("support_90412", [bad]).verdict, "VIOLATION_PROVEN")
        no_ctx = sup({"requester_email": SUBJ, "requester_phone": None, "requester_name": None})
        self.assertEqual(self.run_assess("support_90412", [no_ctx]).reasons, (U.CONDITION_UNKNOWN,))

    def test_tombstone(self):
        tomb = lambda **f: ob("evidence_t", "l1", "tombstone_90413",
                              dict({"subject_reference": USER, "name": None, "email": None, "phone": None,
                                    "email_hash": None, "account_status": "DELETED"}, **f),
                              collection="deleted_customer_references", system="identity_service")
        self.assertEqual(self.run_assess("tombstone_90413", [tomb()]).verdict, "COMPLIANT_PROVEN")
        self.assertEqual(self.run_assess("tombstone_90413", [tomb(email=SUBJ)]).verdict, "VIOLATION_PROVEN")
        missing = self.run_assess("tombstone_90413", [tomb(subject_reference=None)])
        self.assertEqual((missing.verdict, missing.reasons, missing.expressible),
                         ("VIOLATION_PROVEN", (HeldReason.RETAINED_RECORD_MISSING,), False))
        self.assertEqual(self.run_assess("tombstone_90413", [tomb(account_status="ACTIVE")]).reasons, (U.POLICY_GAP,))


class TestRetainedFlowsBackups(StateCase):
    def audit(self, fields, **kw):
        return ob("evidence_r", "l1", "audit_record_90414", fields, collection="security_audit_records",
                  system="security_service", **kw)

    def test_retention_same_observation(self):
        ok = self.audit({"subject_reference": USER, "retention_until": "2031-12-31T23:59:59Z"})
        self.assertEqual(self.run_assess("audit_record_90414", [ok]).verdict, "COMPLIANT_PROVEN")
        expired = self.audit({"subject_reference": USER, "retention_until": "2026-05-01T00:00:00Z"})
        self.assertEqual(self.run_assess("audit_record_90414", [expired]).reasons, (U.POLICY_GAP,))
        no_date = self.audit({"subject_reference": USER})
        self.assertEqual(self.run_assess("audit_record_90414", [no_date]).reasons, (U.CONDITION_UNKNOWN,))
        gone = ob("evidence_r2", "l2", "audit_record_90414", {"rows": "0"}, event="audit_record_read_completed",
                  fmt="log", system="security_service", captured="2026-05-10T08:00:00Z",
                  inner="2026-05-10T06:00:00Z")      # later than the row snapshot (file time 05-10 00:00)
        a = self.run_assess("audit_record_90414", [ok, gone])
        self.assertEqual((a.reasons, a.expressible), ((HeldReason.RETAINED_RECORD_MISSING,), False))

    def test_legal_hold(self):
        hold = ob("evidence_l", "l1", "legal_hold_90415", {"subject_reference": USER,
                                                            "retained_until": "2033-12-31T23:59:59Z"},
                  collection="retained_order_records", system="legal_service")
        self.assertEqual(self.run_assess("legal_hold_90415", [hold]).verdict, "COMPLIANT_PROVEN")

    def test_backup_signals(self):
        b = lambda fields, loc="l1", inner=None: ob("evidence_b", loc, "backup_90416", fields,
                                                    collection="backup_restore_entries", system="backup_service",
                                                    inner=inner)
        self.assertEqual(self.run_assess("backup_90416", [b({"restore_allowed": "1"})]).verdict, "VIOLATION_PROVEN")
        self.assertEqual(self.run_assess("backup_90416", [b({"restore_allowed": "false"})]).verdict, "COMPLIANT_PROVEN")
        both = b({"restore_allowed": "false", "eligible": "true", "deletion_block": "false"})
        self.assertEqual(self.run_assess("backup_90416", [both]).reasons, (U.CONFLICTING_OBSERVATIONS,))
        gone = ob("evidence_g", "l9", "backup_90416", {"result": "NOT_FOUND"}, record_type="BACKUP_ARCHIVE",
                  system="backup_service", inner="2026-05-09T12:00:00Z")
        a = self.run_assess("backup_90416", [b({"restore_allowed": "false"}, inner="2026-05-08T00:00:00Z"), gone])
        self.assertEqual(a.reasons, (HeldReason.RETAINED_RECORD_MISSING,))

    def test_flows(self):
        f = lambda v, loc, inner: ob("evidence_f", loc, "data_flow_90417", {"enabled": v},
                                     collection="connector_subscriptions", system="integration_service", inner=inner)
        self.assertEqual(self.run_assess("data_flow_90417", [f("true", "l1", None)]).verdict, "VIOLATION_PROVEN")
        later = [f("false", "l1", "2026-05-08T00:00:00Z"), f("true", "l2", "2026-05-09T00:00:00Z")]
        self.assertEqual(self.run_assess("data_flow_90417", later).verdict, "VIOLATION_PROVEN")
        self.assertEqual(self.run_assess("data_flow_90417", [f("0", "l1", None)]).verdict, "COMPLIANT_PROVEN")


class TestApprovedDecisions(StateCase):
    """Regression locks for the Stage 7 review decisions (A.8.1)."""

    def test_restore_deny_alone_is_not_blocked(self):           # Q-RESTORE-AUTH-SIGNAL
        deny = ob("evidence_r", "l1", "backup_90418", {"decision": "deny", "policy": "privacy_deletion"},
                  event="restore_authorization_completed", system="backup_service", fmt="log")
        a = self.run_assess("backup_90418", [deny])
        self.assertNotEqual(a.verdict, "COMPLIANT_PROVEN")
        self.assertNotIn(deny.obs_id, a.proof)

    def test_unlisted_phrase_keeps_shared_context_unknown(self):  # shared-context word list stays conservative
        msg = ob("evidence_s", "l1", "support_90419", {"message_excerpt": "Question about account access",
                                                       "requester_email": SUBJ, "requester_phone": None,
                                                       "requester_name": None},
                 collection="tickets", system="support_platform")
        self.assertEqual(self.run_assess("support_90419", [msg]).reasons, (U.CONDITION_UNKNOWN,))

    def test_absence_is_compliant_only_for_a_delete_end_state(self):  # Q-ABSENT-NONDELETE-VERIFY
        gone = lambda rid, **kw: ob("evidence_n", "l1", rid, {"result": "NOT_FOUND", "ticket_id": "CS-7"}, **kw)
        self.assertEqual(self.run_assess("search_90420", [gone("search_90420", record_type="SEARCH_INDEX_ENTRY",
                                                                system="search_service")]).verdict,
                         "COMPLIANT_PROVEN")
        for rid, kw in (("support_90421", dict(collection="support_conversations", system="support_platform")),
                        ("analytics_90422", dict(record_type="ANALYTICS_PROFILE", system="analytics_platform")),
                        ("data_flow_90423", dict(collection="connector_subscriptions",
                                                 system="integration_service"))):
            a = self.run_assess(rid, [gone(rid, **kw)])
            self.assertEqual((a.verdict, a.reasons), ("UNKNOWN", (U.POLICY_GAP,)), rid)
        tomb = self.run_assess("tombstone_90424", [ob("evidence_n", "l1", "tombstone_90424",
                                                      {"result": "NOT_FOUND", "account_status": "DELETED"},
                                                      collection="deleted_customer_references",
                                                      system="identity_service")])
        self.assertEqual((tomb.verdict, tomb.reasons, tomb.expressible),
                         ("VIOLATION_PROVEN", (HeldReason.RETAINED_RECORD_MISSING,), False))

    def test_claims_and_failures_never_prove_absence(self):  # Q-ABSENT-NONDELETE-VERIFY
        claims = [{"activity_id": f"activity_942{i}", "resource_id": "search_90425", "event_type": "DELETE_RECORD",
                   "source_system": "deletion_worker", "reported_result": r, "_event_time": parse_ts(t)}
                  for i, (r, t) in enumerate((("SUCCESS", "2026-05-02T00:00:00Z"),
                                              ("FAILED", "2026-05-03T00:00:00Z")))]
        a = self.run_assess("search_90425", [], activities=claims)
        self.assertNotEqual(a.verdict, "COMPLIANT_PROVEN")
        self.assertEqual(a.proof, ())

    def test_selector_and_scan_fields_are_not_link_fields(self):  # Q-IDENTIFYING-FIELDS
        self.assertFalse({"subject_selector", "matched_value"} & config.IDENTIFYING_FIELDS)


if __name__ == "__main__":
    unittest.main()
