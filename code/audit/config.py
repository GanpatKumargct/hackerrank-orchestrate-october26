"""Canonical configuration: the single source of truth for enums, policy chains,
decided flags and input allow-lists (plan A.3, A.8.1, B.2, F.1.3, F.3.3).

No other module may restate these tables; tests and the validator import them.
"""
import os
from collections import namedtuple
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset"
RUNS_DIR = REPO_ROOT / "runs"

# --------------------------------------------------------------------------- #
# Output enums (A.3.1). Row order IS the within-phase sort order.
# --------------------------------------------------------------------------- #
OPERATIONS = (
    ("REPORT_REMAINING_RECORD", "FINDING", "PRESENT"),
    ("REPORT_EXPOSED_PII", "FINDING", "PRESENT"),
    ("REPORT_ACTIVE_DATA_FLOW", "FINDING", "ACTIVE"),
    ("REPORT_RESTORE_RISK", "FINDING", "ACTIVE"),
    ("DISABLE_DATA_FLOW", "REMEDIATION", "DISABLED"),
    ("BLOCK_RESTORE", "REMEDIATION", "BLOCKED"),
    ("DELETE_RECORD", "REMEDIATION", "ABSENT"),
    ("REDACT_RECORD", "REMEDIATION", "REDACTED"),
    ("ANONYMIZE_RECORD", "REMEDIATION", "ANONYMIZED"),
    ("VERIFY_RECORD_ABSENT", "VERIFICATION", "ABSENT"),
    ("VERIFY_RECORD_PRESENT", "VERIFICATION", "PRESENT"),
    ("VERIFY_RECORD_REDACTED", "VERIFICATION", "REDACTED"),
    ("VERIFY_RECORD_ANONYMIZED", "VERIFICATION", "ANONYMIZED"),
    ("VERIFY_DATA_FLOW_DISABLED", "VERIFICATION", "DISABLED"),
    ("VERIFY_RESTORE_BLOCKED", "VERIFICATION", "BLOCKED"),
)
OP_INDEX = {op: i for i, (op, _, _) in enumerate(OPERATIONS)}
OP_PHASE = {op: phase for op, phase, _ in OPERATIONS}
OP_STATE = {op: state for op, _, state in OPERATIONS}
PHASES = ("FINDING", "REMEDIATION", "VERIFICATION")
STATUSES = ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")
STEP_KEYS = ("step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id")
OUTPUT_HEADER = ("case_id", "deletion_status", "steps_json")
REQUIRED_OUTPUT_ROWS = 518  # [REQ] AGENTS §6.3


def ROW_SORT_KEY(case_id):
    """Q-SORT (A.8.1): ascending integer suffix of case_id."""
    return int(case_id.rsplit("_", 1)[1])


# --------------------------------------------------------------------------- #
# Treatments (A.3.2, D.2.2). `source` is the deletion_rules.csv rule id, or
# "SUPPLEMENTAL" for the challenge-specific DATA_FLOW mapping.
# --------------------------------------------------------------------------- #
Treatment = namedtuple(
    "Treatment", "action finding remediation verification source dependency_class")

_DELETE = ("DELETE", "REPORT_REMAINING_RECORD", "DELETE_RECORD", "VERIFY_RECORD_ABSENT")
_REDACT = ("REDACT", "REPORT_EXPOSED_PII", "REDACT_RECORD", "VERIFY_RECORD_REDACTED")
_ANON = ("ANONYMIZE", "REPORT_EXPOSED_PII", "ANONYMIZE_RECORD", "VERIFY_RECORD_ANONYMIZED")
_RETAIN = ("RETAIN", None, None, "VERIFY_RECORD_PRESENT")

TREATMENTS = {
    "USER_PROFILE": Treatment(*_DELETE, "rule_01", "record_change"),
    "SECONDARY_IDENTIFIER": Treatment(*_DELETE, "rule_02", "record_change"),
    "SEARCH_INDEX_ENTRY": Treatment(*_DELETE, "rule_03", "record_change"),
    "CACHE_ENTRY": Treatment(*_DELETE, "rule_04", "record_change"),
    "SUPPORT_MESSAGE": Treatment(*_REDACT, "rule_05", "record_change"),
    "SUPPORT_ATTACHMENT": Treatment(*_DELETE, "rule_06", "record_change"),
    "ANALYTICS_PROFILE": Treatment(*_ANON, "rule_07", "record_change"),
    "PRODUCT_TELEMETRY": Treatment(*_ANON, "rule_08", "record_change"),
    "USER_EXPORT": Treatment(*_DELETE, "rule_09", "record_change"),
    "MARKETING_PROFILE": Treatment(*_DELETE, "rule_10", "record_change"),
    "EMAIL_DELIVERY_LOG": Treatment(*_REDACT, "rule_11", "record_change"),
    "SECURITY_AUDIT_LOG": Treatment(*_RETAIN, "rule_12", "none"),
    "LEGAL_HOLD_RECORD": Treatment(*_RETAIN, "rule_13", "none"),
    "BACKUP_ARCHIVE": Treatment("RETAIN_BLOCK_RESTORE", "REPORT_RESTORE_RISK", "BLOCK_RESTORE",
                                "VERIFY_RESTORE_BLOCKED", "rule_14", "recreation_path"),
    "ACCOUNT_TOMBSTONE": Treatment(*_REDACT, "rule_15", "record_change"),
    "DATA_FLOW": Treatment("DISABLE", "REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW",
                           "VERIFY_DATA_FLOW_DISABLED", "SUPPLEMENTAL", "recreation_path"),
}
# Categories for which DELETE_RECORD is a prohibited remediation (D.3.6, F.4 L4.5).
NEVER_DELETE = frozenset({"BACKUP_ARCHIVE", "SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD"})

# --------------------------------------------------------------------------- #
# Decided flags (A.8.1). Changing any of these needs a register entry.
# --------------------------------------------------------------------------- #
EPISODE_MODE = "prior_request"            # Q-EPISODE
LATE_INNER_LINKING = True                 # Q-LATE-LINK: link-only, never state/citation
WORKFLOW_LINK_MODE = "unique_only"        # C.6: candidates only, never steps (Q-WEAK-VERIFY = No)
WORKFLOW_WINDOW_HOURS = 3                 # C.6 heuristic
WORKFLOW_EVENT_TYPES = frozenset({        # C.6 candidate generation (claims only)
    "DELETE_RECORD", "REDACT_RECORD", "ANONYMIZE_RECORD", "DISABLE_DATA_FLOW", "BLOCK_RESTORE",
    "CHECK_DATA_FLOW", "CHECK_RESTORE_ACCESS",
})
WORKFLOW_SOURCE_SYSTEM = "deletion_worker"
# C.5.2 TRACE_KEY relationship (plan-authorized, conditional). A trace key alone is
# never identity proof: it links only when the trace's request key attributes to
# the subject AND the state line names the resource AND that line's own identifier
# fields do not attribute to someone else. Switchable for review (Stage 6 report).
TRACE_KEY_LINKS = True
AUDIT_LLM_ENABLED = os.environ.get("AUDIT_LLM_ENABLED", "0") == "1"   # Q-INTENT-LLM, default off
MEDIA_TRANSMISSION_AUTHORIZED = False     # Q-MEDIA-PROVIDER: not authorized; not overridable by env

# --------------------------------------------------------------------------- #
# Input contract (A.1.1, A.1.4). Allow-list: the loader can open nothing else.
# The public reference answers are deliberately NOT listed (A.1.2).
# --------------------------------------------------------------------------- #
REQUEST_HEADER = ("case_id", "email", "requested_at", "reported_status", "reported_at",
                  "audit_at", "request_text")
INPUT_FILES = {
    "deletion_requests.csv": REQUEST_HEADER,
    "sample_deletion_requests.csv": REQUEST_HEADER,
    "user_identities.csv": ("user_id", "name", "email", "phone", "email_hash", "updated_at"),
    "user_audit_log.csv": ("audit_id", "user_id", "event_time", "field_name", "old_value",
                           "new_value"),
    "system_activity.csv": ("activity_id", "event_time", "event_type", "source_system",
                            "target_system", "resource_id", "reported_result", "details"),
    "deletion_rules.csv": ("rule_id", "data_category", "condition", "required_action"),
    "evidence_files.csv": ("file_id", "file_path", "origin", "captured_at"),
}
REPORTED_STATUSES = frozenset({"COMPLETE", "PARTIALLY_COMPLETE", "NOT_STARTED"})
REPORTED_RESULTS = frozenset({"SUCCESS", "FAILED", "PARTIAL"})
AUDIT_FIELDS = frozenset({"email", "email_hash", "phone"})
REQUIRED_ACTIONS = frozenset({"DELETE", "REDACT", "ANONYMIZE", "RETAIN"})
KNOWN_EVENT_TYPES = frozenset({
    "DELETE_RECORD", "UPDATE_RECORD", "SYNC_RECORD", "INDEX_RECORD", "SEND_EMAIL",
    "REFRESH_CACHE", "RETAIN_RECORD", "ANONYMIZE_RECORD", "REDACT_RECORD", "CREATE_EXPORT",
    "CHECK_DATA_FLOW", "DISABLE_DATA_FLOW", "BLOCK_RESTORE", "CHECK_RESTORE_ACCESS",
    "LINK_RESOURCE_IDENTITY", "CLASSIFY_REQUEST", "RESTORE_BACKUP",
})
EVIDENCE_CAPTURE_MARGIN_DAYS = 30   # warning only (B.5 M1)

# --------------------------------------------------------------------------- #
# System ownership (F.1.3). Explicit owner fields beat reporter aliases.
# --------------------------------------------------------------------------- #
OWNER_FIELDS = ("system", "data_store", "origin_system")
# Q-OWNER-RESOLUTION: values seen as explicit owner fields in participant evidence
# (Stage 4 survey). Activity target_system values are claims and are not added.
CANONICAL_SYSTEMS = frozenset({
    "account_service", "analytics_platform", "backup_service", "export_service",
    "identity_service", "integration_service", "legal_service", "search_service",
    "security_service", "support_platform",
})
SYSTEM_ALIASES = {                         # Q-SYSTEM-ALIASES (A.8.1) [ASSUMPTION]
    "profile_service": "account_service",
    "support_replica": "support_platform",
}

# --------------------------------------------------------------------------- #
# Media (B.1.3). Local, hash-pinned cache only; nothing is ever transmitted.
# --------------------------------------------------------------------------- #
MEDIA_CACHE_DIR = REPO_ROOT / "code" / "media_cache"
MEDIA_PROMPT_PATH = REPO_ROOT / "code" / "prompts" / "media_extraction.md"
MEDIA_SCHEMA_VERSIONS = frozenset({"1"})

# PDF in-document time labels (C.1). Observation labels describe when the document
# itself was captured/issued; event labels describe facts inside it and are kept as
# fields only, never as observation time.
PDF_OBSERVATION_LABELS = ("captured", "issued", "generated")
PDF_EVENT_LABELS = ("recorded", "received", "submitted", "retain until", "created", "modified")

# Inventory SQL tables -> (owning system, collection) (C.1, C.8.1 SYSTEM level)
INVENTORY_TABLES = {
    "customer_profiles": "account_service",
    "customer_search_documents": "search_service",
    "customer_analytics_profiles": "analytics_platform",
    "support_records": "support_platform",
    "customer_exports": "export_service",
    "connector_subscriptions": "integration_service",
    "backup_restore_entries": "backup_service",
    "security_audit_records": "security_service",
}
# Direct SQL tables -> (owning system, collection, copy) (C.1, C.8.1 COLLECTION level)
DIRECT_TABLES = {
    "customer_profiles_primary": ("account_service", "customer_profiles", "primary"),
    "customer_profiles_failover_replica": ("account_service", "customer_profiles", "failover_replica"),
    "search_documents_primary": ("search_service", "customer_search_documents", "primary"),
}
# Topology extract tables (prefix) -> copy location. No coverage (C.1).
TOPOLOGY_TABLE_PREFIX = "customer_data_"
# JSON collections whose owner is implied only by the collection name (C.1).
COLLECTION_OWNERS = {
    "customer_analytics_reports": "analytics_platform",
    "customer_export_jobs": "export_service",
}

# --------------------------------------------------------------------------- #
# Log parsing vocabulary (C.1, B.3.2)
# --------------------------------------------------------------------------- #
NOISE_EVENTS = frozenset({
    "connection_acquired", "dependency_retry", "dependency_recovered", "cache_lookup",
    "timer_tick", "disk_latency", "lease_extended", "consumer_lag", "slow_call_rate",
    "certificate_checked", "flag_snapshot_loaded", "checkpoint_saved", "cache_refresh",
    "delivery_abandoned", "thumbnail_failed", "export_started", "export_completed",
    "batch_started",
})
TRACE_KEY_FIELDS = ("lookup_key", "subject_key", "subject_ref", "match_key", "scan_key",
                    "correlation_key")
QUERY_KEY_FIELDS = ("query",)

# --------------------------------------------------------------------------- #
# Identifier extraction (C.3, C.5.2)
# --------------------------------------------------------------------------- #
IDENTIFYING_FIELDS = frozenset({
    "email", "requester_email", "owner_email", "customer_email", "uploaded_by", "user_id",
    "customer_reference", "subject_reference", "lookup_value", "email_hash", "phone",
    "requester_phone", "owner_phone", "subject",
})
FREE_TEXT_FIELDS = frozenset({"message_text", "message_excerpt", "visible_text"})
CLEARED_VALUES = frozenset({"", "null", "none", "[redacted]"})
