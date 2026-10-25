"""M3 — identity and historical-identifier resolution (plan C.3, C.4, Stage 5).

Three separate questions are kept apart:
  * association — did an identifier belong to a user, and in which time window;
  * attribution — whose identifier is a given evidence hit (not record ownership);
  * claims      — LINK_RESOURCE_IDENTITY activities, parsed and checked, never proof.
Resource linkage / scope (C.5) is Stage 6 and is not decided here.

Cutoff: an association whose value only started after `as_of` is not known at
`as_of` and is excluded. Nothing here reads evidence captured after a cutoff.
"""
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from .errors import HeldReason, ReportNote
from .evidence.normalize import canonical_phone

FIELD_KIND = {"email": "email", "email_hash": "hash", "phone": "phone"}


def _sha(email):
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def normalise(kind, raw):
    """Normalised value for matching; None when no safe canonical form exists (C.3)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if kind == "email":
        return raw.lower()
    if kind == "hash":
        return raw.lower()
    if kind == "phone":
        return canonical_phone(raw) if raw.startswith("+") else None
    return raw


@dataclass(frozen=True)
class Association:
    user_id: str
    kind: str                     # email | hash | phone | user
    raw: str
    normalised: Optional[str]
    valid_from: object            # datetime or None (unknown start)
    valid_to: object              # datetime or None (still current)
    source: str                   # "snapshot", an audit_id, or "computed:<source>"
    hash_verified: bool = True    # hash: verified vs email; email: its email/hash pairing verified

    def known_at(self, as_of):
        return as_of is None or self.valid_from is None or self.valid_from <= as_of

    def contains(self, when):
        return ((self.valid_from is None or self.valid_from <= when) and
                (self.valid_to is None or when < self.valid_to))


@dataclass(frozen=True)
class Subject:
    user_id: str
    request_email: str
    request_email_kind: str       # current | historical
    as_of: object
    associations: tuple
    identifiers: frozenset        # {(kind, normalised)} known at as_of and matchable


@dataclass(frozen=True)
class UnresolvedSubject:
    request_email: str
    identifiers: frozenset        # the request email and its computed hash only
    reason: str = HeldReason.IDENTITY_UNRESOLVED


@dataclass(frozen=True)
class AmbiguousSubject:
    request_email: str
    candidates: tuple
    reason: str = HeldReason.IDENTITY_AMBIGUOUS


@dataclass(frozen=True)
class HitAttribution:
    status: str                   # ATTRIBUTED | AMBIGUOUS_IDENTIFIER | UNKNOWN_IDENTIFIER | UNMATCHABLE
    user_id: Optional[str]
    candidates: tuple
    notes: tuple


@dataclass(frozen=True)
class CatalogLink:
    """Parsed LINK_RESOURCE_IDENTITY activity — a CLAIM (C.5.2 CATALOG_CLAIM)."""
    activity_id: str
    event_time: object
    resource_id: str
    label: str
    email_raw: str
    email: str
    claimed_user: str
    exclusive: bool               # "belongs only to … no other subject is linked"
    status: str                   # CONSISTENT | CONFLICTING | UNKNOWN_EMAIL | UNKNOWN_USER
    email_owners: tuple


@dataclass(frozen=True)
class IdentityConflict:
    obs_id: str
    resource_id: str
    users: tuple
    detail: str


LINK_PATTERNS = (
    (re.compile(r"^Data catalog linked (\S+) \(([^)]*)\) to (\S+@\S+) and (user_\d+)\.$"), False),
    (re.compile(r"^Attachment catalog confirmed (\S+) \(([^)]*)\) belongs only to (\S+@\S+) and "
                r"(user_\d+); no other subject is linked\.$"), True),
)


class IdentityResolver:
    def __init__(self, dataset):
        self._assoc = []
        self._current_email = {}
        known_users = set()
        for row in sorted(dataset.identities, key=lambda r: r["user_id"]):
            uid = row["user_id"]
            known_users.add(uid)
            self._current_email[uid] = row["email"].strip().lower()
            self._assoc.append(Association(uid, "user", uid, uid, None, None, "snapshot"))
        self._known_users = frozenset(known_users)
        events = defaultdict(list)
        for row in dataset.audit_log:
            events[(row["user_id"], row["field_name"])].append(row)
        for row in sorted(dataset.identities, key=lambda r: r["user_id"]):
            uid = row["user_id"]
            for field, kind in FIELD_KIND.items():
                verified = not row.get("_hash_unverified")
                rows = sorted(events.get((uid, field), []), key=lambda r: (r["_event_time"], r["audit_id"]))
                if not rows:
                    self._add(uid, kind, row[field], None, None, "snapshot", verified)
                    continue
                first = rows[0]
                self._add(uid, kind, first["old_value"], None, first["_event_time"], first["audit_id"],
                          not first.get("_hash_unverified"))
                for i, ev in enumerate(rows):
                    end = rows[i + 1]["_event_time"] if i + 1 < len(rows) else None
                    self._add(uid, kind, ev["new_value"], ev["_event_time"], end, ev["audit_id"],
                              not ev.get("_hash_unverified"))
        # computed hashes only for emails whose recorded email/hash pairing verified (C.3)
        existing = {(a.user_id, a.normalised) for a in self._assoc if a.kind == "hash"}
        for a in [a for a in self._assoc if a.kind == "email" and a.hash_verified]:
            h = _sha(a.raw)
            if (a.user_id, h) not in existing:
                self._assoc.append(Association(a.user_id, "hash", h, h, a.valid_from, a.valid_to,
                                               f"computed:{a.source}"))
                existing.add((a.user_id, h))
        self._assoc.sort(key=lambda a: (a.user_id, a.kind, a.valid_from is not None,
                                        a.valid_from or 0, a.source))
        self._by_value = defaultdict(list)
        self._by_user = defaultdict(list)
        for a in self._assoc:
            self._by_user[a.user_id].append(a)
            if a.normalised is not None:
                self._by_value[(a.kind, a.normalised)].append(a)

    def _add(self, uid, kind, raw, start, end, source, verified=True):
        # For hash associations: is the recorded hash verified against its email?
        # For email associations: is this email's recorded email/hash pairing verified?
        # (gates computed hashes, C.3). Phones and user ids carry no hash pairing.
        self._assoc.append(Association(uid, kind, raw, normalise(kind, raw), start, end, source,
                                       verified if kind in ("hash", "email") else True))

    # ---- associations -------------------------------------------------------
    def associations_of(self, user_id, as_of=None):
        return tuple(a for a in self._by_user.get(user_id, ()) if a.known_at(as_of))

    def owners_of(self, kind, normalised, as_of=None):
        return tuple(sorted({a.user_id for a in self._by_value.get((kind, normalised), ()) if a.known_at(as_of)}))

    # ---- subject resolution (C.4) -------------------------------------------
    def resolve(self, request_email, as_of=None):
        e = normalise("email", request_email)
        owners = self.owners_of("email", e, as_of)
        if len(owners) > 1:
            return AmbiguousSubject(request_email, owners)
        if not owners:
            return UnresolvedSubject(request_email, frozenset({("email", e), ("hash", _sha(e))}))
        uid = owners[0]
        assoc = self.associations_of(uid, as_of)
        kind = "current" if self._current_email.get(uid) == e else "historical"
        ids = frozenset((a.kind, a.normalised) for a in assoc if a.normalised is not None)
        return Subject(uid, request_email, kind, as_of, assoc, ids)

    # ---- hit attribution (association, not ownership) -----------------------
    def attribute(self, hit, observed_at=None):
        if hit.normalised is None:
            return HitAttribution("UNMATCHABLE", None, (), (ReportNote.PHONE_UNCANONICAL,)
                                  if hit.kind.startswith("phone") else ())
        assoc = self._by_value.get((hit.kind, hit.normalised), ())
        users = tuple(sorted({a.user_id for a in assoc}))
        if not users:
            return HitAttribution("UNKNOWN_IDENTIFIER", None, (), ())
        if len(users) == 1:
            notes = []
            if observed_at is not None and not any(a.contains(observed_at) for a in assoc):
                if all(a.valid_to is not None and observed_at >= a.valid_to for a in assoc):
                    notes.append(ReportNote.HISTORICAL_VALUE_AFTER_CHANGE)
                elif all(a.valid_from is not None and observed_at < a.valid_from for a in assoc):
                    notes.append(ReportNote.PRE_ASSOCIATION_HIT)
            return HitAttribution("ATTRIBUTED", users[0], users, tuple(notes))
        if observed_at is None:
            return HitAttribution("AMBIGUOUS_IDENTIFIER", None, users, (ReportNote.AMBIGUOUS_IDENTIFIER,))
        inside = tuple(sorted({a.user_id for a in assoc if a.contains(observed_at)}))
        if len(inside) == 1:
            return HitAttribution("ATTRIBUTED", inside[0], users, ())
        return HitAttribution("AMBIGUOUS_IDENTIFIER", None, users, (ReportNote.AMBIGUOUS_IDENTIFIER,))

    # ---- explicit identity-link claims --------------------------------------
    def catalog_links(self, activities, as_of=None):
        links, unparsed = [], []
        for act in sorted(activities, key=lambda a: a["activity_id"]):
            if act["event_type"] != "LINK_RESOURCE_IDENTITY":
                continue
            if as_of is not None and act["_event_time"] > as_of:
                continue
            for rx, exclusive in LINK_PATTERNS:
                m = rx.match(act["details"].strip())
                if m:
                    break
            else:
                unparsed.append(act["activity_id"])
                continue
            rid, label, email_raw, claimed = m.groups()
            email = normalise("email", email_raw)
            owners = self.owners_of("email", email)
            if claimed not in self._known_users:
                status = "UNKNOWN_USER"
            elif not owners:
                status = "UNKNOWN_EMAIL"
            elif owners == (claimed,):
                status = "CONSISTENT"
            else:
                status = "CONFLICTING"
            if rid != act["resource_id"]:
                status = "CONFLICTING"
            links.append(CatalogLink(act["activity_id"], act["_event_time"], act["resource_id"], label,
                                     email_raw, email, claimed, exclusive, status, owners))
        return tuple(links), tuple(unparsed)

    # ---- record-level conflicts ---------------------------------------------
    def record_conflicts(self, observations):
        """Observations whose own identifiers attribute to more than one user (C.5.3 I3/I4 input)."""
        conflicts = []
        for o in sorted(observations, key=lambda o: o.obs_id):
            when = o.observed_at or o.file_captured_at
            users = sorted({att.user_id for h in o.identifiers
                            for att in [self.attribute(h, when)] if att.status == "ATTRIBUTED"})
            if len(users) > 1:
                conflicts.append(IdentityConflict(o.obs_id, o.resource_id, tuple(users),
                                                  "identifiers of several users in one record"))
        return tuple(conflicts)
