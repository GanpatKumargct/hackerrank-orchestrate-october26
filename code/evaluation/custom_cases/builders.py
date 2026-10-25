"""Builders for the G.5 custom evaluation cases CC1–CC5 (and the CC2-n negative variant).

Each builder writes a self-contained, fictional mini-dataset (example.org, user_9xxx,
resource IDs 9xxxx) in the participant format, with exactly one evaluation request.
Expected outcomes are derived from the cited plan rules (G.5), not from any run.
"""
import csv
import hashlib
import json
from pathlib import Path

from audit import config

REQUESTED, REPORTED, AUDIT = "2026-05-01T10:00:00Z", "2026-05-02T10:00:00Z", "2026-05-10T12:00:00Z"


def sha(email):
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def _write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        for r in rows:
            w.writerow([r.get(h, "") for h in header])


def _rules():
    return [dict(rule_id=t.source, data_category=c, condition="Always", required_action=t.action.split("_")[0])
            for c, t in config.TREATMENTS.items() if t.source != "SUPPLEMENTAL"]


def write_dataset(root, *, case_id, email, text, users, audit_log=(), activities=(), evidence=()):
    """evidence: [(file_id, relative path under evidence/, captured_at, content)]."""
    ds = Path(root) / "dataset"
    (ds / "evidence").mkdir(parents=True)
    manifest = []
    for fid, rel, captured, content in evidence:
        p = ds / "evidence" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        manifest.append(dict(file_id=fid, file_path=f"evidence/{rel}", origin="custom_case", captured_at=captured))
    req = dict(case_id=case_id, email=email, requested_at=REQUESTED, reported_status="COMPLETE",
               reported_at=REPORTED, audit_at=AUDIT, request_text=text)
    tables = {
        "deletion_requests.csv": [req],
        "sample_deletion_requests.csv": [],
        "user_identities.csv": list(users),
        "user_audit_log.csv": list(audit_log),
        "system_activity.csv": list(activities),
        "deletion_rules.csv": _rules(),
        "evidence_files.csv": manifest,
    }
    for name, rows in tables.items():
        _write_csv(ds / name, config.INPUT_FILES[name], rows)
    return ds


def _user(uid, email, phone):
    return dict(user_id=uid, name="Custom Case Person", email=email, phone=phone, email_hash=sha(email),
                updated_at="2026-02-01T00:00:00Z")


def _readback(trace, key, rid, result="rows=0 http_status=404", day="2026-05-08"):
    return (f"{day}T09:00:00Z level=DEBUG service=account_service trace_id={trace} event=profile_lookup_started "
            f"resource_id={rid} lookup_key={key}\n"
            f"{day}T09:00:02Z level=INFO service=account_service trace_id={trace} event=profile_lookup_completed "
            f"resource_id={rid} {result}\n")


def _ledger(rid, uid, retention, recorded="2026-05-08T07:00:00Z", exported="2026-05-08T12:00:00Z"):
    return json.dumps({"exported_at": exported, "records": [
        {"recorded_at": recorded, "system": "security_service", "resource_id": rid,
         "record_type": "SECURITY_AUDIT_LOG", "result": "FOUND", "subject_reference": uid,
         "retention_until": retention}]}, indent=2)


# --------------------------------------------------------------------------- #
def cc1(root):
    old, new = "old.cc1@example.org", "new.cc1@example.org"
    bundle = {"exported_at": "2026-05-08T12:00:00Z", "snapshots": [
        {"captured_at": "2026-05-08T08:00:00Z", "data_store": "search_service",
         "collection": "customer_search_documents",
         "records": [{"resource_id": "search_90001", "index_name": "customer_directory",
                      "document": {"email": old, "customer_reference": None}}]}]}
    return write_dataset(
        root, case_id="case_9101", email=old, text="Please permanently delete my account.",
        users=[_user("user_9001", new, "+44 20 0000 0101")],
        audit_log=[dict(audit_id="audit_9101", user_id="user_9001", event_time="2026-01-10T00:00:00Z",
                        field_name="email", old_value=old, new_value=new),
                   dict(audit_id="audit_9102", user_id="user_9001", event_time="2026-01-10T00:00:00Z",
                        field_name="email_hash", old_value=sha(old), new_value=sha(new))],
        evidence=[("evidence_9101", "logs/cc1_readback.log", "2026-05-08T12:00:00Z",
                   _readback("rb-cc1", new, "account_90001")),
                  ("evidence_9102", "records/cc1_search_bundle.json", "2026-05-08T12:00:00Z", json.dumps(bundle, indent=2)),
                  ("evidence_9103", "records/cc1_audit_ledger.json", "2026-05-08T12:00:00Z",
                   _ledger("audit_record_90001", "user_9001", "2030-12-31T23:59:59Z"))])


def _cc2_export(with_hash=True):
    analytics = {"observed_at": "2026-05-10T11:00:00Z", "resource_id": "analytics_90002", "customer_reference": None,
                 "email": None, "phone": None, "audience_cohort": "returning_buyers"}
    if with_hash:
        analytics["email_hash"] = None
    return json.dumps({"exported_at": "2026-05-10T12:00:00Z", "region": "global", "service_exports": {
        "account_service": {"profile_lookups": [{"observed_at": "2026-05-10T11:00:00Z", "profile": None,
                                                 "resource_id": "account_90002", "status_code": 404}]},
        "analytics_platform": {"profiles": [analytics]}}}, indent=2)


def cc2(root, with_hash=True):
    email = "cc2@example.org"
    case_id = "case_9201" if with_hash else "case_9211"
    return write_dataset(
        root, case_id=case_id, email=email, text="Please erase my account and personal data.",
        users=[_user("user_9002", email, "+44 20 0000 0102")],
        activities=[dict(activity_id="activity_9201", event_time="2026-05-02T09:00:00Z", event_type="DELETE_RECORD",
                         source_system="deletion_worker", target_system="account_service",
                         resource_id="account_90002", reported_result="FAILED", details="Deletion worker failed."),
                    dict(activity_id="activity_9202", event_time="2026-05-01T12:00:00Z",
                         event_type="LINK_RESOURCE_IDENTITY", source_system="data_catalog",
                         target_system="analytics_platform", resource_id="analytics_90002", reported_result="SUCCESS",
                         details=f"Data catalog linked analytics_90002 (analytics_90002) to {email} and user_9002.")],
        evidence=[("evidence_9201", "records/cc2_service_export.json", AUDIT, _cc2_export(with_hash)),
                  ("evidence_9202", "records/cc2_audit_ledger.json", "2026-05-09T12:00:00Z",
                   _ledger("audit_record_90002", "user_9002", "2031-12-31T23:59:59Z",
                           recorded="2026-05-09T07:00:00Z", exported="2026-05-09T12:00:00Z")),
                  ("evidence_9203", "logs/cc2_readback.log", "2026-05-09T12:00:00Z",
                   _readback("rb-cc2", email, "account_90002", day="2026-05-09"))])


def cc2n(root):
    return cc2(root, with_hash=False)


def cc3(root):
    email = "cc3@example.org"
    late = ("2026-05-09T09:00:00Z level=DEBUG service=search_service trace_id=ix-cc3 event=index_query_started "
            f"resource_id=search_90003 lookup_key={email}\n"
            "2026-05-09T09:00:02Z level=INFO service=search_service trace_id=ix-cc3 event=index_query_completed "
            "resource_id=search_90003 result=hit\n")
    return write_dataset(
        root, case_id="case_9301", email=email, text="Please delete my account.",
        users=[_user("user_9003", email, "+44 20 0000 0103")],
        evidence=[("evidence_9301", "logs/cc3_readback.log", "2026-05-08T12:00:00Z",
                   _readback("rb-cc3", email, "account_90003")),
                  ("evidence_9302", "logs/cc3_late_index.log", "2026-05-12T12:00:00Z", late)])


def cc4(root):
    email = "cc4@example.org"
    marketing = {"captured_at": "2026-05-08T08:00:00Z", "collection": "marketing_profiles",
                 "records": [{"resource_id": "marketing_90004", "email": email, "segment": "newsletter"}]}
    return write_dataset(
        root, case_id="case_9401", email=email,
        text="Please remove me from marketing lists only. I still want order receipts.",
        users=[_user("user_9004", email, "+44 20 0000 0104")],
        evidence=[("evidence_9401", "logs/cc4_readback.log", "2026-05-08T12:00:00Z",
                   _readback("rb-cc4", email, "account_90004", result="rows=1 http_status=200")),
                  ("evidence_9402", "records/cc4_marketing.json", "2026-05-08T12:00:00Z", json.dumps(marketing, indent=2))])


def cc5(root):
    email = "cc5@example.org"
    sql = ("-- point-in-time database snapshot\n-- Captured at: 2026-05-09T12:00:00Z\n"
           "CREATE TABLE customer_profiles_primary (resource_id TEXT, user_id TEXT, email TEXT, account_status TEXT);\n"
           "CREATE TABLE customer_profiles_failover_replica (resource_id TEXT, user_id TEXT, email TEXT, "
           "account_status TEXT);\n"
           f"INSERT INTO customer_profiles_failover_replica VALUES ('account_90005','user_9005','{email}','ACTIVE');\n")
    return write_dataset(
        root, case_id="case_9501", email=email, text="Please close my account and delete my data.",
        users=[_user("user_9005", email, "+44 20 0000 0105")],
        evidence=[("evidence_9501", "databases/cc5_profiles_dump.sql", "2026-05-09T12:00:00Z", sql)])


def _s(op, system, rid, ev=""):
    return (op, system, rid, ev)


# Expected results (G.5). steps: (operation, system_id, resource_id, evidence_id) in output order.
CASES = {
    "CC1": dict(builder=cc1, case_id="case_9101", title="Historical-email-only remaining search entry",
                outcome="EMIT", status="INCOMPLETE", steps=[
                    _s("REPORT_REMAINING_RECORD", "search_service", "search_90001", "evidence_9102"),
                    _s("DELETE_RECORD", "search_service", "search_90001"),
                    _s("VERIFY_RECORD_ABSENT", "account_service", "account_90001"),
                    _s("VERIFY_RECORD_ABSENT", "search_service", "search_90001"),
                    _s("VERIFY_RECORD_PRESENT", "security_service", "audit_record_90001")],
                rules="C.4, C.5.2, D.2.3, E.4.2, E.5, F.2"),
    "CC2": dict(builder=cc2, case_id="case_9201", title="Fully proven compliant case with a misleading FAILED claim",
                outcome="EMIT", status="COMPLETE", steps=[
                    _s("VERIFY_RECORD_ABSENT", "account_service", "account_90002", "evidence_9201"),
                    _s("VERIFY_RECORD_PRESENT", "security_service", "audit_record_90002", "evidence_9202"),
                    _s("VERIFY_RECORD_ANONYMIZED", "analytics_platform", "analytics_90002", "evidence_9201")],
                rules="A.4.5, C.7, D.3.3, E.4.2, F.2.1–F.2.3"),
    "CC2-n": dict(builder=cc2n, case_id="case_9211", title="CC2 with the analytics email_hash slot not observed",
                  outcome="HOLD", held="REQUIRED_RESOURCE_UNRESOLVED", steps=[],
                  held_detail=("analytics_90002", "FIELD_COVERAGE_INCOMPLETE"), rules="D.3.3, E.4.2"),
    "CC3": dict(builder=cc3, case_id="case_9301", title="Late-captured evidence cannot create a finding or citation",
                outcome="HOLD", held="REQUIRED_RESOURCE_UNRESOLVED", steps=[], never_cited="evidence_9302",
                held_detail=("search_90003", "POST_CUTOFF_ONLY"),
                rules="C.7, A.8.1 Q-LATE-LINK, E.4.2, F.2.1 check 2"),
    "CC4": dict(builder=cc4, case_id="case_9401", title="Marketing-only request", outcome="EMIT",
                status="NOT_APPLICABLE", steps=[], intent_clauses=("MARKETING_ONLY",),
                plan_clauses=("MARKETING_ONLY", "SCOPE_LIMIT"), rules="E.1.1–E.1.2"),
    "CC5": dict(builder=cc5, case_id="case_9501", title="Replica-only copy of the profile", outcome="EMIT",
                status="INCOMPLETE", steps=[
                    _s("REPORT_REMAINING_RECORD", "account_service", "account_90005", "evidence_9501"),
                    _s("DELETE_RECORD", "account_service", "account_90005"),
                    _s("VERIFY_RECORD_ABSENT", "account_service", "account_90005")],
                rules="C.8.2, D.2.2, E.4.2"),
}
