"""Core data model for parsed evidence (plan B.4.1, C.2, C.5.1, C.8.1).

Raw values and timestamps are kept alongside normalised values; nothing here
interprets state — that is Stage 7 (M6).
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class IdentifierHit:
    kind: str                    # email | hash | user | phone | phone_uncanonical
    raw: str                     # exactly as it appeared in the evidence
    normalised: Optional[str]    # None when no safe canonical form exists
    field: str                   # source field name ("" for free text without a field)
    relationship: str            # RECORD_FIELD | FREE_TEXT_MENTION | TRACE_KEY | QUERY_KEY
    locator: str                 # where in the file the value was found


@dataclass(frozen=True)
class CoverageUnit:
    """A declared snapshot coverage (C.8.1); the only basis for absence by omission."""
    file_id: str
    level: str                   # COLLECTION | SYSTEM
    system: str
    collection: str
    copy: str
    observed_raw: Optional[str]  # inner snapshot time, None => file capture time
    resource_ids: frozenset
    locator: str


@dataclass(frozen=True)
class Observation:
    obs_id: str
    file_id: str
    file_captured_at: datetime
    file_captured_raw: str
    observed_at: Optional[datetime]
    observed_raw: Optional[str]
    time_basis: str              # "inner" | "file"
    source_format: str           # sql | json | log | text | pdf | image
    locator: str
    resource_id: str
    system_id: Optional[str]     # explicit owner only (F.1.3 rule 1); None otherwise
    system_field: Optional[str]  # which field / table supplied system_id
    reporter_service: Optional[str]
    record_type: Optional[str]
    collection: Optional[str]
    copy_location: Optional[str]
    fields: dict                 # raw field values (nested values flattened with dotted keys)
    context: dict                # parent context: data_store, query, parent resource, trace id …
    identifiers: tuple           # IdentifierHit with RECORD_FIELD / FREE_TEXT_MENTION
    keys: tuple                  # IdentifierHit with TRACE_KEY / QUERY_KEY
    related_ids: tuple           # ((relationship, resource_id), …)
    anomalies: tuple = ()


@dataclass
class FileExtraction:
    """Per-file coverage report (B.3.2). A FAILED file never means 'no data'."""
    file_id: str
    path: str
    fmt: str
    status: str = "OK"           # OK | PARTIAL | FAILED
    observations: int = 0
    unparsed_units: int = 0
    unparsed_samples: list = field(default_factory=list)
    noise_units: int = 0
    reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    coverage: list = field(default_factory=list)
    pages: list = field(default_factory=list)      # [(page_no, text)] for documents (PDF)

    def finalize(self):
        if self.status != "FAILED" and self.unparsed_units:
            self.status = "PARTIAL"
        return self
