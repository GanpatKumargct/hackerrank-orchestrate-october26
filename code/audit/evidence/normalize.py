"""Identifier normalisation and extraction (plan C.3).

Normalisation only *adds* a normalised value next to the raw one. A match here is
a candidate (IdentifierHit), never proof that a record belongs to a subject —
linkage is decided in Stage 6 (C.5).
"""
import re

from .. import config
from ..models import IdentifierHit

EMAIL_FULL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
HASH_FULL = re.compile(r"^[0-9A-Fa-f]{64}$")
USER_FULL = re.compile(r"^user_\d+$")
PHONE_FULL = re.compile(r"^\+\d[\d ()\-]{5,}\d$")
PHONE_LIKE = re.compile(r"^[\d ()\-]{7,}$")

EMAIL_IN_TEXT = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w-])")
HASH_IN_TEXT = re.compile(r"(?<![0-9A-Za-z])[0-9A-Fa-f]{64}(?![0-9A-Za-z])")
USER_IN_TEXT = re.compile(r"(?<![\w])user_\d+(?![\w])")
PHONE_IN_TEXT = re.compile(r"(?<![\w+])\+\d[\d ()\-]{5,}\d(?![\d])")


def is_cleared(value):
    """True for explicit null / empty / redacted values (D.3.3 'CLEARED')."""
    return value is None or (isinstance(value, str) and value.strip().lower() in config.CLEARED_VALUES)


def canonical_phone(raw):
    """Exact digit sequence including the leading '+' (C.3). No inference."""
    return "+" + re.sub(r"\D", "", raw)


def classify_value(value):
    """Classify a whole field value. Returns (kind, normalised) or None."""
    if not isinstance(value, str) or is_cleared(value):
        return None
    v = value.strip()
    if EMAIL_FULL.match(v):
        return ("email", v.lower())
    if HASH_FULL.match(v):
        return ("hash", v.lower())
    if USER_FULL.match(v):
        return ("user", v)
    if PHONE_FULL.match(v):
        return ("phone", canonical_phone(v))
    if PHONE_LIKE.match(v) and sum(c.isdigit() for c in v) >= 7:
        return ("phone_uncanonical", None)          # no '+': never matched (PHONE_UNCANONICAL)
    return None


def extract_free_text(text):
    """Bounded identifier matches inside free text. Returns [(kind, raw, normalised)]."""
    if not isinstance(text, str) or not text:
        return []
    out = []
    for m in EMAIL_IN_TEXT.finditer(text):
        out.append(("email", m.group(0), m.group(0).lower()))
    for m in HASH_IN_TEXT.finditer(text):
        out.append(("hash", m.group(0), m.group(0).lower()))
    for m in USER_IN_TEXT.finditer(text):
        out.append(("user", m.group(0), m.group(0)))
    for m in PHONE_IN_TEXT.finditer(text):
        out.append(("phone", m.group(0), canonical_phone(m.group(0))))
    return out


def leaf_name(key):
    """'document.email' -> 'email'."""
    return key.rsplit(".", 1)[-1]


def identifier_hits(fields, locator):
    """RECORD_FIELD hits from identifying fields + FREE_TEXT_MENTION hits from free text."""
    hits = []
    for key in sorted(fields):
        value = fields[key]
        name = leaf_name(key)
        if name in config.IDENTIFYING_FIELDS:
            c = classify_value(value)
            if c:
                hits.append(IdentifierHit(c[0], value, c[1], key, "RECORD_FIELD", locator))
        elif name in config.FREE_TEXT_FIELDS:
            for kind, raw, normed in extract_free_text(value):
                hits.append(IdentifierHit(kind, raw, normed, key, "FREE_TEXT_MENTION", locator))
    return tuple(hits)


def key_hits(fields, locator, names, relationship):
    """TRACE_KEY / QUERY_KEY hits: identifier-shaped values of lookup/query fields."""
    hits = []
    for key in sorted(fields):
        if leaf_name(key) in names:
            c = classify_value(fields[key])
            if c:
                hits.append(IdentifierHit(c[0], fields[key], c[1], key, relationship, locator))
    return tuple(hits)


def flatten(obj, prefix="", stop=lambda d: False):
    """Flatten nested dicts to dotted keys. Lists of scalars are kept as lists.

    `stop(d)` marks nested dicts that are separate records (e.g. search hits that
    carry their own resource_id); they are excluded here and parsed on their own.
    """
    out = {}
    for k, v in obj.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            if stop(v):
                continue
            out.update(flatten(v, key + ".", stop))
        elif isinstance(v, list):
            if any(isinstance(i, dict) and stop(i) for i in v):
                continue
            if all(not isinstance(i, (dict, list)) for i in v):
                out[key] = v
            else:
                for i, item in enumerate(v):
                    if isinstance(item, dict):
                        out.update(flatten(item, f"{key}[{i}].", stop))
                    else:
                        out[f"{key}[{i}]"] = item
        else:
            out[key] = v
    return out
