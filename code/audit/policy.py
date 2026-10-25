"""M4 — category classification and policy conditions (plan D.1, D.2; Stage 7).

Classification uses tiered signals from observations admissible for state:
T1 explicit record_type, T2 specific collection/event/document semantics,
T3 generic containers. Workflow operations are claims and may only break a tie
between grounded signals (D.1.3). Prefixes never decide. There is no default
category: unresolved → UNKNOWN with a reason (D.1.4).
"""
import re
from dataclasses import dataclass
from typing import Optional

from . import config
from .errors import UncertaintyReason as U


@dataclass(frozen=True)
class Signal:
    category: str
    tier: str                    # T1 | T2 | T3 | T-WF | T-PFX
    source: str                  # obs_id or activity_id
    detail: str


@dataclass(frozen=True)
class CategoryConclusion:
    value: Optional[str]
    basis: str                   # tier or TIE_BREAK_WORKFLOW_CLAIM / TREATMENT_EQUIVALENT
    confidence: str              # HIGH | MEDIUM | LOW | NONE
    reason: Optional[str]        # UncertaintyReason when value is None
    signals: tuple
    conflicts: tuple


@dataclass(frozen=True)
class ConditionResult:
    value: str                   # TRUE | FALSE | UNKNOWN | PREDICATE (rule is the violation test itself)
    rule: str
    evidence: tuple              # obs_ids
    detail: str
    assumption: bool = False


TIER_ORDER = ("T1", "T2", "T3")


def observation_signals(o):
    out = []
    if o.record_type in config.TREATMENTS:
        out.append(Signal(o.record_type, "T1", o.obs_id, "record_type"))
    coll, event = o.collection, o.context.get("event")
    if coll in config.COLLECTION_CATEGORY_T2:
        out.append(Signal(config.COLLECTION_CATEGORY_T2[coll], "T2", o.obs_id, f"collection:{coll}"))
    elif coll in config.COLLECTION_CATEGORY_T3:
        out.append(Signal(config.COLLECTION_CATEGORY_T3[coll], "T3", o.obs_id, f"collection:{coll}"))
    if event in config.EVENT_CATEGORY_T2:
        out.append(Signal(config.EVENT_CATEGORY_T2[event], "T2", o.obs_id, f"event:{event}"))
    text = str(o.fields.get("document_text") or o.fields.get("visible_text", "")).lower()
    if any(m in text for m in config.DOCUMENT_ATTACHMENT_MARKERS):
        out.append(Signal("SUPPORT_ATTACHMENT", "T2", o.obs_id, "document:customer-uploaded file"))
    return out


def _same_chain(categories):
    chains = {config.TREATMENTS[c][:4] for c in categories}
    return len(chains) == 1


def classify(resource_id, observations, claims):
    """observations: admissible for state; claims: activity rows on this resource (<= cutoff)."""
    signals = [s for o in observations for s in observation_signals(o)]
    wf = [Signal(a["event_type"], "T-WF", a["activity_id"], a["event_type"]) for a in claims
          if a["source_system"] == config.WORKFLOW_SOURCE_SYSTEM
          and a["event_type"] in config.WORKFLOW_OP_CATEGORY_ACTION]
    prefix = re.sub(r"_\d+$", "", resource_id)
    pfx = [Signal(prefix, "T-PFX", resource_id, "prefix (consistency check only)")]
    grounded = [s for s in signals if s.tier in TIER_ORDER]
    if not grounded:
        return CategoryConclusion(None, "NONE", "NONE", U.CATEGORY_UNGROUNDED, tuple(signals),
                                  tuple(wf + pfx))
    top = min(TIER_ORDER.index(s.tier) for s in grounded)
    top_tier = TIER_ORDER[top]
    cats = sorted({s.category for s in grounded if s.tier == top_tier})
    if len(cats) == 1:
        value, basis = cats[0], top_tier
        conf = "HIGH" if top_tier in ("T1", "T2") else "MEDIUM"
    elif _same_chain(cats):
        value, basis, conf = cats[0], "TREATMENT_EQUIVALENT", "MEDIUM"
    else:
        value, basis, conf = _tie_break(cats, wf)
        if value is None:
            return CategoryConclusion(None, "AMBIGUOUS", "NONE", U.CATEGORY_AMBIGUOUS, tuple(signals),
                                      tuple(s for s in grounded if s.tier == top_tier) + tuple(wf))
    conflicts = tuple(s for s in grounded + wf if s.category != value
                      and not (s.tier == "T-WF" and config.TREATMENTS[value].action.startswith(
                          config.WORKFLOW_OP_CATEGORY_ACTION[s.category])))
    return CategoryConclusion(value, basis, conf, None, tuple(signals + wf + pfx), conflicts)


def _tie_break(cats, wf):
    """D.1.3: one admissible workflow claim whose action matches exactly one tied category."""
    if len(wf) != 1:
        return None, None, None
    action = config.WORKFLOW_OP_CATEGORY_ACTION[wf[0].category]
    match = [c for c in cats if config.TREATMENTS[c].action.startswith(action)]
    if len(match) == 1:
        return match[0], "TIE_BREAK_WORKFLOW_CLAIM", "LOW"
    return None, None, None


# --------------------------------------------------------------------------- #
# Conditions (D.2.3). Retention (rules 12/13) is evaluated with presence in the
# same observation in state.py (Q-SPLIT-PROOF); rules 07/08/11 are violation
# predicates evaluated as PII exposure.
# --------------------------------------------------------------------------- #
ALWAYS = {"USER_PROFILE", "SECONDARY_IDENTIFIER", "SEARCH_INDEX_ENTRY", "CACHE_ENTRY",
          "USER_EXPORT", "MARKETING_PROFILE", "DATA_FLOW"}
PREDICATE = {"ANALYTICS_PROFILE", "PRODUCT_TELEMETRY", "EMAIL_DELIVERY_LOG"}
OWNER_FIELDS = ("uploaded_by", "owner_email", "requester_email", "subject", "subject_reference")


def evaluate_condition(category, observations, subject_user, resolver):
    rule = config.TREATMENTS[category].source
    if category in ALWAYS:
        return ConditionResult("TRUE", rule, (), "Always" if rule != "SUPPLEMENTAL" else "supplemental DATA_FLOW")
    if category in PREDICATE or category in ("SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD"):
        return ConditionResult("PREDICATE", rule, (), "evaluated with the record state")
    if category == "BACKUP_ARCHIVE":
        return ConditionResult("TRUE", rule, (), "restore access can be blocked: default TRUE, no "
                               "admissible evidence that blocking is impossible", assumption=True)
    if category == "SUPPORT_MESSAGE":
        for o in observations:
            f = o.fields
            if any(f.get(k) not in (None, "", "null") for k in config.SHARED_CONTEXT_FIELDS):
                return ConditionResult("TRUE", rule, (o.obs_id,), "ticket context present", True)
            for k in ("message_text", "message_excerpt", "visible_text"):
                text = str(f.get(k) or "").lower()
                if any(w in text for w in config.SHARED_CONTEXT_WORDS):
                    return ConditionResult("TRUE", rule, (o.obs_id,), f"shared context words in {k}", True)
            for h in o.identifiers:
                att = resolver.attribute(h, o.observed_at or o.file_captured_at)
                if att.status == "ATTRIBUTED" and att.user_id != subject_user:
                    return ConditionResult("TRUE", rule, (o.obs_id,), "another subject in the record", True)
        return ConditionResult("UNKNOWN", rule, (), "no shared-context evidence observed", True)
    if category == "SUPPORT_ATTACHMENT":
        mine, others, ev = False, False, []
        for o in observations:
            for h in o.identifiers:
                if h.relationship != "RECORD_FIELD" or h.field.rsplit(".", 1)[-1] not in OWNER_FIELDS:
                    continue
                att = resolver.attribute(h, o.observed_at or o.file_captured_at)
                if att.status != "ATTRIBUTED":
                    continue
                ev.append(o.obs_id)
                if att.user_id == subject_user:
                    mine = True
                else:
                    others = True
        if others:
            return ConditionResult("FALSE", rule, tuple(ev), "owner field names another subject")
        if mine:
            return ConditionResult("TRUE", rule, tuple(ev), "owner field names only the subject")
        return ConditionResult("UNKNOWN", rule, (), "no owner field observed")
    if category == "ACCOUNT_TOMBSTONE":
        statuses = {(o.obs_id, str(o.fields.get("account_status", "")).upper()) for o in observations
                    if o.fields.get("account_status")}
        if any(s == "DELETED" for _, s in statuses):
            return ConditionResult("TRUE", rule, tuple(i for i, s in statuses if s == "DELETED"), "account_status DELETED")
        if statuses:
            return ConditionResult("FALSE", rule, tuple(i for i, _ in statuses), "account not deleted")
        return ConditionResult("UNKNOWN", rule, (), "account_status not observed")
    return ConditionResult("UNKNOWN", rule, (), "no condition definition")
