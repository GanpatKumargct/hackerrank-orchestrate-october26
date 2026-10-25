"""Stage 6 — links and scope (plan C.5, C.6, C.7, E.2). Synthetic, fictional data."""
import unittest
from unittest import mock

from audit import config
from audit.errors import ReportNote, ScopeCode
from audit.evidence.common import make_observation
from audit.evidence.index import ObservationIndex
from audit.identity import IdentityResolver
from audit.loader import load_dataset
from audit.scope import ScopeBuilder
from tests.fixtures import TempDir, manifest_row, minimal_dataset, sha

SUBJ = "new.fx@example.org"           # user_9001 (request email is the historical old.fx@...)
OTHER = "other.fx@example.org"        # user_9002


def add_other_user(t):
    t["user_identities.csv"].append(dict(user_id="user_9002", name="Other", email=OTHER,
                                         phone="+44 20 0000 0009", email_hash=sha(OTHER),
                                         updated_at="2026-03-01T00:00:00Z"))


def activity(aid, when, etype, rid, details="x", source="deletion_worker"):
    return dict(activity_id=aid, event_time=when, event_type=etype, source_system=source,
                target_system="t", resource_id=rid, reported_result="SUCCESS", details=details)


def ob(locator, rid, fields=None, captured="2026-05-09T00:00:00Z", inner=None, related=(), file_id="evidence_9201"):
    return make_observation(manifest_row=manifest_row("x.log", file_id=file_id, captured=captured), fmt="log",
                            locator=locator, resource_id=rid, fields=fields or {}, observed_raw=inner,
                            related_ids=related)


class ScopeCase(unittest.TestCase):
    def build(self, observations, mutate=None, case="case_900"):
        def m(t):
            add_other_user(t)
            if mutate:
                mutate(t)
        with TempDir() as d:
            ds = load_dataset(minimal_dataset(d, m))
        idx = ObservationIndex(observations)
        sb = ScopeBuilder(ds, idx, IdentityResolver(ds))
        req = next(r for r in ds.all_requests() if r["case_id"] == case)
        return sb, sb.build(req)


class TestLinksAndRules(ScopeCase):
    def test_record_field_link_is_grounded_direct(self):
        _, sc = self.build([ob("a", "search_90201", {"email": SUBJ})])
        d = sc.included["search_90201"]
        self.assertEqual(d.code, ScopeCode.GROUNDED_DIRECT)
        self.assertEqual([(l.relationship, l.confidence, l.source) for l in d.subject_links],
                         [("RECORD_FIELD", "STRONG", "evidence_9201#a")])

    def test_historical_identifier_links(self):
        _, sc = self.build([ob("a", "search_90202", {"email": "old.fx@example.org"}, inner="2026-04-01T00:00:00Z")])
        notes = sc.included["search_90202"].subject_links[0].notes
        self.assertIn(ReportNote.HISTORICAL_VALUE_AFTER_CHANGE, notes)

    def test_trace_key_link_conditional_and_switchable(self):
        o = ob("a", "account_90203", {"rows": "0"})
        o = o.__class__(**{**o.__dict__, "keys": (self._trace_hit(SUBJ),)})
        _, sc = self.build([o])
        self.assertEqual(sc.included["account_90203"].code, ScopeCode.GROUNDED_TRACE)
        with mock.patch.object(config, "TRACE_KEY_LINKS", False):
            _, sc = self.build([o])
        self.assertNotIn("account_90203", sc.included)

    def test_trace_key_refused_when_record_names_someone_else(self):
        o = ob("a", "search_90204", {"email": OTHER})
        o = o.__class__(**{**o.__dict__, "keys": (self._trace_hit(SUBJ),)})
        _, sc = self.build([o])
        self.assertNotIn("search_90204", sc.included)

    def test_query_key_alone_never_links(self):
        _, sc = self.build([ob("a", "search_90205", {"query": SUBJ})])
        self.assertNotIn("search_90205", sc.included)
        self.assertNotIn("search_90205", sc.excluded)

    def test_reporter_prefix_origin_never_link(self):
        o = make_observation(manifest_row=dict(manifest_row("x.log"), origin="account_service"), fmt="log",
                             locator="a", resource_id="account_90206", fields={"rows": "1"},
                             reporter_service="account_service")
        _, sc = self.build([o])
        self.assertEqual((sc.included, {k: v for k, v in sc.excluded.items() if k == "account_90206"}), ({}, {}))

    def test_free_text_mention_and_fk(self):
        _, sc = self.build([ob("a", "support_90207", {"message_text": f"contact {SUBJ}"}),
                            ob("b", "search_90208", {"email": SUBJ}, related=(("DERIVED_FROM", "account_90208"),))])
        self.assertEqual(sc.included["support_90207"].code, ScopeCode.CONTAINS_SUBJECT_PII)
        self.assertEqual(sc.included["account_90208"].code, ScopeCode.GROUNDED_FK)

    def test_shared_and_ownership_changed(self):
        shared = ob("a", "support_90209", {"requester_email": SUBJ, "message_text": f"cc {OTHER}"})
        before = ob("b", "search_90210", {"email": OTHER}, inner="2026-04-01T00:00:00Z")
        after = ob("c", "search_90210", {"email": SUBJ}, inner="2026-05-01T00:00:00Z")
        _, sc = self.build([shared, before, after])
        self.assertEqual(sc.included["support_90209"].code, ScopeCode.SHARED_RESOURCE)
        d = sc.included["search_90210"]
        self.assertEqual(d.code, ScopeCode.OWNERSHIP_CHANGED)
        self.assertEqual([l.subject for l in d.other_links], ["user_9002"])

    def _trace_hit(self, value):
        from audit.models import IdentifierHit
        return IdentifierHit("email", value, value, "lookup_key", "TRACE_KEY", "line1")


class TestCatalogClaims(ScopeCase):
    def claim(self, aid, rid, email, user, when="2026-05-05T00:00:00Z"):
        return activity(aid, when, "LINK_RESOURCE_IDENTITY", rid,
                        f"Data catalog linked {rid} ({rid}) to {email} and {user}.", source="data_catalog")

    def test_consistent_claim_is_catalog_link_and_cutoff_applies(self):
        def m(t):
            t["system_activity.csv"] += [self.claim("activity_9201", "object_90211", SUBJ, "user_9001"),
                                         self.claim("activity_9202", "object_90212", SUBJ, "user_9001",
                                                    when="2026-05-11T00:00:00Z")]
        _, sc = self.build([], m)
        self.assertEqual(sc.included["object_90211"].code, ScopeCode.CATALOG)
        self.assertNotIn("object_90212", sc.included)             # claim after audit_at

    def test_claim_contradicted_by_record_field(self):
        def m(t):
            t["system_activity.csv"].append(self.claim("activity_9203", "search_90213", SUBJ, "user_9001"))
        _, sc = self.build([ob("a", "search_90213", {"email": OTHER})], m)
        self.assertEqual(sc.excluded["search_90213"].code, ScopeCode.CATALOG_CONTRADICTED)


class TestCutoffAndAnomalies(ScopeCase):
    def test_late_file_links_only_with_note(self):
        late = ob("a", "search_90214", {"email": SUBJ}, captured="2026-05-12T00:00:00Z", inner="2026-05-10T08:00:00Z")
        _, sc = self.build([late])
        self.assertIn(ReportNote.LINK_EVIDENCE_POST_CUTOFF, sc.included["search_90214"].subject_links[0].notes)
        with mock.patch.object(config, "LATE_INNER_LINKING", False):
            _, sc = self.build([late])
        self.assertNotIn("search_90214", sc.included)

    def test_post_cutoff_and_anomalous_observations_do_not_link(self):
        after = ob("a", "search_90215", {"email": SUBJ}, captured="2026-05-12T00:00:00Z", inner="2026-05-11T00:00:00Z")
        anomaly = ob("b", "search_90216", {"email": SUBJ}, captured="2026-05-08T00:00:00Z", inner="2026-05-09T00:00:00Z")
        _, sc = self.build([after, anomaly])
        self.assertNotIn("search_90215", sc.included)
        self.assertNotIn("search_90216", sc.included)

    def test_unresolved_subject_builds_no_scope(self):
        _, sc = self.build([ob("a", "search_90217", {"email": SUBJ})],
                           lambda t: t["deletion_requests.csv"][0].update(email="nobody@example.org"))
        self.assertEqual(sc.included, {})
        self.assertTrue(any("not resolved" in n for n in sc.notes))


class TestEpisode(ScopeCase):
    def test_prior_request_boundary(self):
        def m(t):   # earlier request (case_901) by the same user, audited 2026-03-10
            t["sample_deletion_requests.csv"][0].update(requested_at="2026-03-01T10:00:00Z",
                                                        reported_at="2026-03-02T10:00:00Z",
                                                        audit_at="2026-03-10T12:00:00Z")
        old = ob("a", "search_90218", {"email": SUBJ}, captured="2026-03-05T00:00:00Z")
        new = ob("b", "search_90219", {"email": SUBJ}, captured="2026-04-01T00:00:00Z")
        between = ob("c", "export_90220", {"owner_email": SUBJ}, captured="2026-03-20T00:00:00Z")
        _, sc = self.build([old, new, between], m)
        self.assertEqual(str(sc.episode_start), "2026-03-10 12:00:00+00:00")
        self.assertEqual(sc.excluded["search_90218"].code, ScopeCode.EARLIER_EPISODE)
        self.assertIn("search_90219", sc.included)
        self.assertIn("export_90220", sc.included)       # observed before requested_at but after prior audit
        _, earlier = self.build([old, new, between], m, case="case_901")
        self.assertIsNone(earlier.episode_start)


class TestWorkflowCandidates(ScopeCase):
    def test_unique_shared_and_grounded(self):
        def m(t):
            t["system_activity.csv"] += [
                activity("activity_9210", "2026-05-02T08:00:00Z", "ANONYMIZE_RECORD", "analytics_90221"),
                activity("activity_9211", "2026-05-02T09:00:00Z", "DELETE_RECORD", "search_90222"),
                activity("activity_9212", "2026-05-11T00:00:00Z", "DELETE_RECORD", "cache_90223"),
            ]
            t["deletion_requests.csv"].append(dict(t["deletion_requests.csv"][0], case_id="case_902",
                                                   email=OTHER, requested_at="2026-05-02T08:30:00Z",
                                                   reported_at="2026-05-02T10:00:00Z"))
            # move the fixture's sample request out of the window so case_900 is the only claimant
            t["sample_deletion_requests.csv"][0].update(requested_at="2026-03-01T10:00:00Z",
                                                        reported_at="2026-03-02T10:00:00Z",
                                                        audit_at="2026-03-10T12:00:00Z")
        grounded = ob("a", "search_90222", {"email": OTHER})
        _, sc = self.build([grounded], m)
        self.assertEqual(sc.excluded["analytics_90221"].code, ScopeCode.WEAK_LINK_ONLY)
        self.assertEqual(sc.workflow_candidates["analytics_90221"], ("activity_9210",))
        self.assertNotIn("analytics_90221", sc.included)             # never in scope
        self.assertNotIn("search_90222", sc.workflow_candidates)     # grounded to someone: not a candidate
        self.assertNotIn("cache_90223", sc.workflow_candidates)      # after audit_at

    def test_shared_window_is_ambiguous(self):
        def m(t):
            t["system_activity.csv"].append(activity("activity_9213", "2026-05-02T09:00:00Z", "DELETE_RECORD",
                                                     "account_90224"))
            t["deletion_requests.csv"].append(dict(t["deletion_requests.csv"][0], case_id="case_903",
                                                   email=OTHER))
        _, sc = self.build([], m)
        self.assertEqual(sc.excluded["account_90224"].code, ScopeCode.AMBIGUOUS_WORKFLOW)
        self.assertIn("account_90224", sc.ambiguous_workflow)


if __name__ == "__main__":
    unittest.main()
