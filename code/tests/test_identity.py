"""Stage 5 — identity resolution tests (plan C.3, C.4). Synthetic, fictional data."""
import unittest

from audit.errors import HeldReason, ReportNote
from audit.evidence.common import make_observation
from audit.identity import AmbiguousSubject, IdentityResolver, Subject, UnresolvedSubject
from audit.loader import load_dataset
from audit.models import IdentifierHit
from audit.timeutil import parse_ts
from tests.fixtures import TempDir, manifest_row, minimal_dataset, sha

OLD, NEW = "old.fx@example.org", "new.fx@example.org"
CHANGE = parse_ts("2026-01-10T00:00:00Z")


def hit(kind, value, normalised=None):
    return IdentifierHit(kind, value, normalised if normalised is not None else value.lower(),
                         "email", "RECORD_FIELD", "loc")


def act(aid, details, rid, when="2026-04-01T00:00:00Z"):
    return {"activity_id": aid, "event_type": "LINK_RESOURCE_IDENTITY", "details": details,
            "resource_id": rid, "_event_time": parse_ts(when)}


class IdentityCase(unittest.TestCase):
    def resolver(self, mutate=None):
        with TempDir() as d:
            return IdentityResolver(load_dataset(minimal_dataset(d, mutate)))


class TestSubjectResolution(IdentityCase):
    def test_current_and_historical_emails(self):
        r = self.resolver()
        cur = r.resolve("NEW.fx@Example.org")
        self.assertIsInstance(cur, Subject)
        self.assertEqual((cur.user_id, cur.request_email_kind), ("user_9001", "current"))
        hist = r.resolve(OLD)
        self.assertEqual((hist.user_id, hist.request_email_kind), ("user_9001", "historical"))
        for ident in (("email", OLD), ("email", NEW), ("hash", sha(OLD)), ("hash", sha(NEW)),
                      ("user", "user_9001"), ("phone", "+442000000001")):
            self.assertIn(ident, hist.identifiers)

    def test_association_windows_and_provenance(self):
        r = self.resolver()
        emails = {a.normalised: a for a in r.associations_of("user_9001") if a.kind == "email"}
        self.assertEqual((emails[OLD].valid_from, emails[OLD].valid_to, emails[OLD].source), (None, CHANGE, "audit_9001"))
        self.assertEqual((emails[NEW].valid_from, emails[NEW].valid_to, emails[NEW].source), (CHANGE, None, "audit_9001"))

    def test_cutoff_excludes_values_that_started_later(self):
        r = self.resolver()
        before = r.resolve(OLD, as_of=parse_ts("2026-01-05T00:00:00Z"))
        self.assertIn(("email", OLD), before.identifiers)
        self.assertNotIn(("email", NEW), before.identifiers)          # not known yet at the cutoff
        self.assertIsInstance(r.resolve(NEW, as_of=parse_ts("2026-01-05T00:00:00Z")), UnresolvedSubject)

    def test_unknown_email_is_unresolved_with_own_identifiers_only(self):
        s = self.resolver().resolve("nobody@example.org")
        self.assertIsInstance(s, UnresolvedSubject)
        self.assertEqual(s.reason, HeldReason.IDENTITY_UNRESOLVED)
        self.assertEqual(s.identifiers, frozenset({("email", "nobody@example.org"), ("hash", sha("nobody@example.org"))}))

    def test_reused_identifier_is_ambiguous(self):
        def mutate(t):
            t["user_identities.csv"].append(dict(user_id="user_9002", name="Other Person", email=OLD,
                                                 phone="+44 20 0000 0002", email_hash=sha(OLD),
                                                 updated_at="2026-03-01T00:00:00Z"))
        r = self.resolver(mutate)
        s = r.resolve(OLD)
        self.assertIsInstance(s, AmbiguousSubject)
        self.assertEqual((s.candidates, s.reason), (("user_9001", "user_9002"), HeldReason.IDENTITY_AMBIGUOUS))
        # attribution by time window: before the change both held it, after only user_9002
        early = r.attribute(hit("email", OLD), parse_ts("2026-01-01T00:00:00Z"))
        late = r.attribute(hit("email", OLD), parse_ts("2026-02-01T00:00:00Z"))
        self.assertEqual((early.status, early.notes), ("AMBIGUOUS_IDENTIFIER", (ReportNote.AMBIGUOUS_IDENTIFIER,)))
        self.assertEqual((late.status, late.user_id), ("ATTRIBUTED", "user_9002"))
        self.assertEqual(r.attribute(hit("email", OLD)).status, "AMBIGUOUS_IDENTIFIER")   # no time

    def test_unverified_hash_pair_gets_no_computed_hash(self):
        bogus = "0" * 64
        def mutate(t):
            t["user_audit_log.csv"][1].update(old_value=bogus)
        r = self.resolver(mutate)
        hashes = {a.normalised: a for a in r.associations_of("user_9001") if a.kind == "hash"}
        self.assertFalse(hashes[bogus].hash_verified)
        self.assertNotIn(sha(OLD), hashes)                      # not computed from an unverified pair
        self.assertFalse(any(a.source.startswith("computed:") for a in hashes.values()))

    def test_phone_without_plus_is_unmatchable(self):
        r = self.resolver(lambda t: t["user_identities.csv"][0].update(phone="020 0000 0001"))
        phones = [a for a in r.associations_of("user_9001") if a.kind == "phone"]
        self.assertEqual([p.normalised for p in phones], [None])
        att = r.attribute(IdentifierHit("phone_uncanonical", "020 0000 0001", None, "phone", "RECORD_FIELD", "l"))
        self.assertEqual((att.status, att.notes), ("UNMATCHABLE", (ReportNote.PHONE_UNCANONICAL,)))


class TestAttribution(IdentityCase):
    def test_unknown_and_historical_after_change(self):
        r = self.resolver()
        self.assertEqual(r.attribute(hit("email", "decoy.jr@example.org")).status, "UNKNOWN_IDENTIFIER")
        a = r.attribute(hit("email", OLD), parse_ts("2026-05-01T00:00:00Z"))
        self.assertEqual((a.status, a.user_id, a.notes),
                         ("ATTRIBUTED", "user_9001", (ReportNote.HISTORICAL_VALUE_AFTER_CHANGE,)))
        b = r.attribute(hit("email", NEW), parse_ts("2025-12-01T00:00:00Z"))
        self.assertEqual(b.notes, (ReportNote.PRE_ASSOCIATION_HIT,))

    def test_record_conflicts(self):
        def mutate(t):
            t["user_identities.csv"].append(dict(user_id="user_9003", name="Third", email="third@example.org",
                                                 phone="+44 20 0000 0003", email_hash=sha("third@example.org"),
                                                 updated_at="2026-03-01T00:00:00Z"))
        r = self.resolver(mutate)
        row = manifest_row("x.json")
        shared = make_observation(manifest_row=row, fmt="json", locator="a", resource_id="support_90100",
                                  fields={"requester_email": NEW, "message_text": "cc third@example.org"})
        single = make_observation(manifest_row=row, fmt="json", locator="b", resource_id="support_90101",
                                  fields={"requester_email": NEW})
        conflicts = r.record_conflicts([shared, single])
        self.assertEqual([(c.resource_id, c.users) for c in conflicts], [("support_90100", ("user_9001", "user_9003"))])


class TestCatalogClaims(IdentityCase):
    def test_statuses(self):
        r = self.resolver()
        acts = [
            act("activity_9101", f"Data catalog linked search_90110 (search_90110) to {NEW} and user_9001.", "search_90110"),
            act("activity_9102", f"Data catalog linked search_90111 (x) to {NEW} and user_9999.", "search_90111"),
            act("activity_9103", "Data catalog linked search_90112 (x) to ghost@example.org and user_9001.", "search_90112"),
            act("activity_9104", f"Attachment catalog confirmed object_90113 (file.pdf) belongs only to {OLD} "
                                 f"and user_9001; no other subject is linked.", "object_90113"),
            act("activity_9105", f"Data catalog linked search_90114 (x) to {NEW} and user_9001.", "search_99999"),
            act("activity_9106", "Free-form note that does not match a template.", "search_90115"),
            act("activity_9107", f"Data catalog linked search_90116 (x) to {NEW} and user_9001.", "search_90116",
                when="2026-06-01T00:00:00Z"),
        ]
        links, unparsed = r.catalog_links(acts, as_of=parse_ts("2026-05-01T00:00:00Z"))
        status = {l.activity_id: l.status for l in links}
        self.assertEqual(status, {"activity_9101": "CONSISTENT", "activity_9102": "UNKNOWN_USER",
                                  "activity_9103": "UNKNOWN_EMAIL", "activity_9104": "CONSISTENT",
                                  "activity_9105": "CONFLICTING"})
        self.assertEqual(unparsed, ("activity_9106",))                # recorded, not guessed
        self.assertTrue(next(l for l in links if l.activity_id == "activity_9104").exclusive)
        self.assertNotIn("activity_9107", status)                     # after the cutoff

    def test_claim_conflicting_with_email_owner(self):
        def mutate(t):
            t["user_identities.csv"].append(dict(user_id="user_9004", name="Fourth", email="fourth@example.org",
                                                 phone="+44 20 0000 0004", email_hash=sha("fourth@example.org"),
                                                 updated_at="2026-03-01T00:00:00Z"))
        r = self.resolver(mutate)
        links, _ = r.catalog_links([act("activity_9110",
                                        "Data catalog linked search_90120 (x) to fourth@example.org and user_9001.",
                                        "search_90120")])
        self.assertEqual((links[0].status, links[0].email_owners), ("CONFLICTING", ("user_9004",)))


class TestRealIdentityData(unittest.TestCase):
    """Data metrics on the real inputs (G.1.2): recorded, not decision rules."""

    def test_counts(self):
        ds = load_dataset()
        r = IdentityResolver(ds)
        kinds = [type(r.resolve(q["email"], as_of=q["_audit_at"])).__name__ for q in ds.all_requests()]
        self.assertEqual(kinds.count("Subject"), 550)
        links, unparsed = r.catalog_links(ds.activities)
        self.assertEqual((len(links), unparsed), (12, ()))
        self.assertTrue(all(l.status == "CONSISTENT" for l in links))


if __name__ == "__main__":
    unittest.main()
