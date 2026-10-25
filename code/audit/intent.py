"""M2b — request intent, three-way and clause-scoped (plan B.1.4, E.1; Stage 8).

The text is split into sentences and clauses. Each clause gets at most one type
(E.1.1); the E.1.2 table combines them. A negation or "only" applies to the
object of its own clause. No single word decides alone, and an unmatched or
contradictory text is UNSURE (held; the LLM fallback is off by default,
Q-INTENT-LLM). CLASSIFY_REQUEST activities are claims and are never read here.
"""
import re
from dataclasses import dataclass

DELETION, NON_DELETION, UNSURE = "DELETION", "NON_DELETION", "UNSURE"

# Clause types (E.1.1)
DELETE_REQUEST = "DELETE_REQUEST"
DELETION_FOLLOWUP = "DELETION_FOLLOWUP"
SCOPE_LIMIT = "SCOPE_LIMIT"
DELETION_NEGATION = "DELETION_NEGATION"
OTHER_PURPOSE = "OTHER_PURPOSE"
MARKETING_ONLY = "MARKETING_ONLY"

_SENTENCE = re.compile(r"(?<=[.!?。！？])\s*|\n+")
_CLAUSE = re.compile(r"[,;，、；]|\s[—–-]\s|\b(?:but|and|so|except|however)\b|\s(?:pero|mas|mais|et|y|e)\s"
                     r"|けど|が、|하지만", re.I)

# Deletion triggers (verbs and nouns), English and the five observed languages.
_DELETE = re.compile(
    r"\b(?:delet\w*|eras\w*|remov\w*|clos\w*|wip\w*)\b|account-deletion"
    r"|\b(?:exclu\w*|apag\w*|elimin\w*|borr\w*|suppr\w*|effac\w*|fermer|fermeture|cerrar|encerrar)\b"
    r"|削除|消去|삭제|탈퇴", re.I)
# Objects that make a deletion trigger a request about the subject's account or data.
_OBJECT = re.compile(
    r"\b(?:account|profile|personal|details|data|information|records?|copies|copy|export\w*|archive|"
    r"search result|traces|document|me|everything|all|it|them|this|that|rest)\b"
    r"|\b(?:conta|cuenta|compte|dados|datos|données|perfil|profil)\b|アカウント|データ|계정|데이터", re.I)
_NEGATION = re.compile(r"\bnot\b|n['’]t\b|\bnever\b|\bwithout\b|\bno\s+(?:quiero|deseo|quero)\b"
                       r"|\bne\b.*\bpas\b|\bnão\b|しないで|ないで|하지\s*마", re.I)
_NEG_IGNORED = re.compile(r"\bno longer\b|\bnot\s+(?:be able|able)\b", re.I)
# Objects that make a negated/kept clause a subset limit rather than a negation of deletion.
_SUBSET = re.compile(r"\b(?:orders?|order history|invoices?|receipts?|backups?|statistics|security|"
                     r"reference|conversations?|messages?|record\b|purchase|treat)\w*", re.I)
_WHOLE = re.compile(r"\b(?:the account|my account|this account|account itself|deletion|anything|any of|"
                    r"all of|everything|it)\b", re.I)
_KEEP_ACCOUNT = re.compile(
    r"keep the account|leave the account|leave my profile|continue using|still need the account|"
    r"still use it|account as it is|not asking for deletion", re.I)
_KEEP = re.compile(r"\b(?:keep\w*|retain\w*|may stay|can stay|stay if|only)\b", re.I)
_MARKETING = re.compile(r"\b(?:marketing|promotional|newsletter)\b", re.I)
_OTHER = re.compile(
    r"\b(?:correct|fix|change|update|replace|misspelled|out of date|copy of|download|portable format|"
    r"what (?:personal )?information|hold about me|reset\w*|login|invoices|stop the promotional|"
    r"information request)\b", re.I)
_FOLLOW_ACTION = re.compile(
    r"\b(?:verify|check|confirm\w*|audit|inspect|investigate|tell me whether|finish|complete|handle|"
    r"remove|delete|disable|switch off|make sure)\b|comprob\w*|complet\w*|vérifi\w*|verifi\w*", re.I)
_PRIOR_DELETION = re.compile(
    r"\b(?:i deleted|i closed|i(?:['’]m| am) deleting|deleted (?:my|this|the) account|was deleted|"
    r"been (?:deleted|removed)|was fully removed|deletion was complete|is gone|are gone|request failed|"
    r"had been deleted|i disconnected|deleted-account|(?:audit|finish|complete) the deletion)\b"
    r"|intent\w* eliminar", re.I)


@dataclass(frozen=True)
class Clause:
    sentence: int
    text: str
    type: str


@dataclass(frozen=True)
class IntentResult:
    value: str                   # DELETION | NON_DELETION | UNSURE
    clauses: tuple               # typed clauses (Clause)
    scope_limits: tuple          # SCOPE_LIMIT clause texts, recorded as case notes only
    reason: str                  # short explanation for the trace


def _sentences(text):
    return [s.strip() for s in _SENTENCE.split(text or "") if s and s.strip()]


def _clause_type(clause, sentence):
    neg = bool(_NEGATION.search(_NEG_IGNORED.sub("", clause)))
    deletes = bool(_DELETE.search(clause))
    if _MARKETING.search(clause):
        if re.search(r"\bonly\b", clause, re.I) and deletes:
            return MARKETING_ONLY
        if _OTHER.search(clause) or re.search(r"\b(?:stop|unsubscribe)\b", clause, re.I):
            return OTHER_PURPOSE
    if _KEEP_ACCOUNT.search(clause):
        return DELETION_NEGATION
    if neg and deletes:
        if _SUBSET.search(clause) and not _WHOLE.search(_SUBSET.sub("", clause)):
            return SCOPE_LIMIT
        return DELETION_NEGATION
    if deletes and (_OBJECT.search(clause) or _OBJECT.search(sentence)):
        if _KEEP.search(clause) and _SUBSET.search(clause):
            return SCOPE_LIMIT
        return DELETE_REQUEST
    if _KEEP.search(clause) and _SUBSET.search(clause):
        return SCOPE_LIMIT
    if neg and _SUBSET.search(clause):
        return SCOPE_LIMIT
    if _OTHER.search(clause):
        return OTHER_PURPOSE
    return None


def classify_intent(text):
    """Return an IntentResult for one request_text (E.1.2 decision table)."""
    clauses = []
    sentences = _sentences(text)
    for i, s in enumerate(sentences):
        for part in _CLAUSE.split(s):
            part = (part or "").strip()
            if not part:
                continue
            t = _clause_type(part, s)
            if t:
                clauses.append(Clause(i, part, t))
    whole = " ".join(sentences)
    if _PRIOR_DELETION.search(whole) and _FOLLOW_ACTION.search(whole) \
            and not any(c.type == DELETION_NEGATION for c in clauses):
        clauses.append(Clause(-1, "prior or in-progress deletion referenced", DELETION_FOLLOWUP))
    types = {c.type for c in clauses}
    limits = tuple(c.text for c in clauses if c.type == SCOPE_LIMIT)
    wants = bool(types & {DELETE_REQUEST, DELETION_FOLLOWUP})
    if wants and DELETION_NEGATION in types:
        return IntentResult(UNSURE, tuple(clauses), limits, "deletion request and deletion negation together")
    if wants:
        return IntentResult(DELETION, tuple(clauses), limits, "deletion request clause")
    if types & {DELETION_NEGATION, OTHER_PURPOSE, MARKETING_ONLY}:
        return IntentResult(NON_DELETION, tuple(clauses), limits,
                            "explicit non-deletion clause: " + ",".join(sorted(types)))
    return IntentResult(UNSURE, tuple(clauses), limits, "no typed clause or unsupported language")
