# Sample Case Analysis — Ghost Data Still Exists

Analysis of the 32 public sample cases (`dataset/sample_deletion_requests.csv` vs `dataset/sample_output.csv`) against participant-visible evidence. Purpose: derive general decision rules for the agent. The expected answers are used **only as a reference to test hypotheses**; nothing here is a per-case lookup to be hardcoded.

Legend used throughout:

- **[C] Confirmed** — holds for every applicable sample case, verified by script or direct inspection.
- **[H] Hypothesis** — consistent with all samples but not uniquely implied; may fail on evaluation cases.
- **[U] Unresolved** — cannot be determined from public data.

Personal data is minimised: users are referred to by `user_id`, historical identifiers by `audit_id`. Evidence IDs are participant-visible `file_id` / `activity_id` / `audit_id` values.

## 1. Method

1. Built a throw-away, read-only index of all text evidence (24 SQL dumps executed in in-memory SQLite, 29 JSON/TXT records flattened to resource-level objects, 26 logs grouped by `trace_id` / `requestId`). 3,338 resource-level observations.
2. Inspected all 4 PDFs and 11 PNG screenshots visually (they are few and not machine-extractable with installed libraries).
3. For every sample case: resolved identity (current snapshot + `user_audit_log.csv`), found every observation containing any identifier (word-boundary match — plain substring matching wrongly maps `user_43` to `user_430…439`), found every observation of each expected resource, separated observations by file `captured_at` vs `audit_at`, and listed `system_activity.csv` rows on those resources.
4. Checked candidate rules programmatically across all 32 cases (ordering, phase structure, citation choice, scope windows).

Analysis scripts lived in a scratch directory and are not part of the solution.

## 2. Rules supported by the samples

### 2.1 Output structure and ordering — [C] (scripted check, 0 violations / 32 cases)

| # | Rule |
|---|---|
| S1 | Steps are sorted by (operation index in the problem-statement table, `system_id`, `resource_id`). Phase order falls out of the operation index. |
| S2 | `step_no` is consecutive from 1. |
| S3 | `COMPLETE` ⇒ only VERIFICATION steps, each with a non-empty `evidence_id`. |
| S4 | `INCOMPLETE` ⇒ ≥1 FINDING; every FINDING cites evidence; every REMEDIATION and VERIFICATION step has `evidence_id = ""`. |
| S5 | The set of resources in FINDING equals the set in REMEDIATION. |
| S6 | Finding → remediation → verification mapping: `REMAINING_RECORD → DELETE_RECORD → VERIFY_RECORD_ABSENT`; `EXPOSED_PII → REDACT_RECORD → VERIFY_RECORD_REDACTED` or `→ ANONYMIZE_RECORD → VERIFY_RECORD_ANONYMIZED`; `ACTIVE_DATA_FLOW → DISABLE_DATA_FLOW → VERIFY_DATA_FLOW_DISABLED`; `RESTORE_RISK → BLOCK_RESTORE → VERIFY_RESTORE_BLOCKED`. |
| S7 | Every case (COMPLETE or INCOMPLETE) verifies **exactly one** primary `account_*` as `VERIFY_RECORD_ABSENT`. |
| S8 | `VERIFY_RECORD_PRESENT` is used only for `audit_record_*` (security audit logs, rule_12 RETAIN). |
| S9 | Remediation order is the operation-table order: DISABLE_DATA_FLOW, BLOCK_RESTORE, DELETE, REDACT, ANONYMIZE. This satisfies "stop recreation paths before changing dependent records". |

### 2.2 Policy mapping — [C] for observed categories

| Resource / category evidence | Required action | Finding when violated | Verification |
|---|---|---|---|
| `account_*` USER_PROFILE (any copy, incl. replica) | DELETE (rule_01) | REMAINING_RECORD | ABSENT |
| `search_*` SEARCH_INDEX_ENTRY | DELETE (rule_03) | REMAINING_RECORD | ABSENT |
| `export_*` USER_EXPORT | DELETE (rule_09) | REMAINING_RECORD | ABSENT |
| `support_*` explicitly SUPPORT_ATTACHMENT / customer-uploaded file / legacy contact copy | DELETE (rule_06) | REMAINING_RECORD | ABSENT |
| `support_*` SUPPORT_MESSAGE (ticket/conversation) | REDACT (rule_05) | EXPOSED_PII | REDACTED |
| `analytics_*` ANALYTICS_PROFILE still identifiable | ANONYMIZE (rule_07) | EXPOSED_PII | ANONYMIZED |
| `tombstone_*` ACCOUNT_TOMBSTONE | REDACT (rule_15) | EXPOSED_PII | REDACTED |
| `audit_record_*` SECURITY_AUDIT_LOG within retention | RETAIN (rule_12) | — | PRESENT |
| `backup_*` BACKUP_ARCHIVE | RETAIN + block restore (rule_14) | RESTORE_RISK if restorable | RESTORE_BLOCKED |
| `data_flow_*` connector | (no rule row) disable | ACTIVE_DATA_FLOW if enabled | DATA_FLOW_DISABLED |

### 2.3 State reading — [C]

| State | Evidence signals observed |
|---|---|
| Account ABSENT | `rows=0` / `http_status=404` / `status_code: 404` / `result=NOT_FOUND`; or omitted from a captured profile table (§3.4) |
| Account PRESENT | `status_code: 200` with profile fields (case_24); a row in any replica table, even if the primary is clean (case_05, case_16) |
| Search PRESENT | `result=hit`, `FOUND`, or row in a search table |
| Analytics ANONYMIZED | `user_id/customer_reference/email/phone/email_hash` all null, or `ANONYMIZED` |
| Analytics / support EXPOSED | any direct identifier non-null, `IDENTIFIABLE`, or `message_pii_scan … detector=direct_identifier` |
| Support REDACTED | `requester_*` null; a retained `customer_reference=user_NN` is acceptable (case_26–28) |
| Tombstone REDACTED | email/phone/email_hash null, `subject_reference` retained (case_31) |
| Data flow ACTIVE / DISABLED | `enabled=true` / `enabled=false`, `ACTIVE`, `connector_heartbeat enabled=true` |
| Backup restorable / blocked | `restore_allowed=1/true`, `eligible=true deletion_block=false`, `ACTIVE` vs `restore_allowed=false` |
| Support copy recreated | `deletion_marker_check marker_found=false` with `last_write` after the reported deletion (case_10) |

Log level words (`WARN`, `ERROR`) and `reported_result` are noise. State always comes from fields.

### 2.4 Claims vs evidence — [C]

- `reported_status` is not predictive. COMPLETE outcomes include reported NOT_STARTED (case_25, 26, 28) and PARTIALLY_COMPLETE (case_02). INCOMPLETE outcomes include reported COMPLETE (case_05, 07, 10, 11, 12, 14, 15, 22, 24, 30).
- `reported_result` is not proof. A FAILED account delete with 404 evidence counts as ABSENT (case_25, 26, 28). A SUCCESS delete followed by a replica row or recreation counts as REMAINING (case_05, 10, 24).

### 2.5 Findings require positive evidence — [H] (no counter-example)

A resource is reported as a finding only when a pre-cutoff observation shows the violation. Resources whose state is unobserved still appear in verification, with no finding. Examples: case_20 `account_5037` (delete FAILED, never observed) and case_09 `account_3960`.

## 3. The five investigated questions

### 3.1 Identifier-free records (case_03 and similar)

Facts [C]:

- Every expected `analytics_*` in COMPLETE cases is identifier-free at audit time: case_03 `analytics_9406`, case_21 `analytics_5335`, case_25 `analytics_1895`, case_26 `analytics_4566`, case_27 `analytics_4574`, case_28 `analytics_6077`, case_04 `analytics_901`.
- None of these resources occurs with any subject identifier in any evidence file, at any time. Their only participant-visible connection is a `deletion_worker` ANONYMIZE_RECORD activity.
- For the six generated cases, that activity is at **reported_at − 29 min (minute-floored)**. Other per-type offsets also cluster: account DELETE −46…−75 min, BLOCK_RESTORE −8, DISABLE_DATA_FLOW −15, support REDACT −22.
- Readback-log adjacency is **misleading**. In evidence_94 the trace immediately after case_03's `account_7566` lookup is `analytics_5589`, not the expected `analytics_9406`. Adjacency must not be used.
- Time-window attribution alone is **ambiguous**. Windows of [requested_at, reported_at+3h] contain 1–46 `deletion_worker` actions belonging to other users. In case_03, eval case_44 (user_42) has the identical `reported_at`, and its ANONYMIZE on `analytics_5589` is 15 s after `analytics_9406`. Both sit at −29 min. Nothing participant-visible separates them.

Conclusion:

- **[U]** No grounded identity link exists for these records.
- **[H]** The candidate rule that reproduces all 7 samples is: "an identifier-free `analytics_*` whose deletion-workflow action falls at the case's characteristic offset from `reported_at`". It is a workflow-correlation inference, not an identity link. It cannot disambiguate when two cases share a `reported_at` (case_03 vs case_44).
- **Recommendation:** treat workflow correlation as a low-confidence link. Accept it only when exactly one candidate matches. Record it as an inference in run logs. Accept the risk of a missed or extra verification step; status is unaffected because the record is already compliant.

### 3.2 When primary account and audit records are verified (case_05–08 vs others)

- **[C]** The primary account is **always** verified ABSENT, exactly once, in every COMPLETE and INCOMPLETE case (S7). In case_06/07/08 it is verified even though the finding concerns a different resource.
- **[C]** An account found PRESENT gets a finding, DELETE and verify (case_05, 16, 24). The verification step is not duplicated.
- **[C]** `audit_record_*` VERIFY_PRESENT appears iff a security-audit record for the subject exists in the dataset. Users 01, 02, 04–08 and 10 (cases 01, 02, 04–08, 10) have no such record anywhere, and none is expected. All 22 other cases include exactly one.
- **[U]** Two expected audit records (`audit_record_6645` case_18, `audit_record_5569` case_20) appear in **no** participant-visible file. They are undiscoverable; expect to miss them.
- **[H] Inner vs file timestamps.** Five expected audit records (case_09, 23, 24, 29, 30) and `account_3960` (case_09) are linked only by files whose `captured_at` is **after** `audit_at` (evidence_02 at 09-17, evidence_06 at 09-18). The relevant inner observations are timestamped at or before `audit_at`: evidence_02 inner snapshot `captured_at=2026-09-15T12:00:00Z`, and evidence_06 log lines at 2026-09-16T08:52–08:57.

  Working rule, consistent with all samples:
  - **scope and identity linking** may use observations whose own inner timestamp is ≤ `audit_at`;
  - **cited `evidence_id`s** must be files with `captured_at ≤ audit_at`. No sample cites a late file.

  This needs owner confirmation; see §5.

### 3.3 Why case_12 is DELETE, not ANONYMIZE

Evidence (evidence_01, 2026-09-15): `analytics_9914 event=contact_lookup_completed rows=1 email_opt_in=true correlation_key=<email_hash>`. The `correlation_key` equals the user's **historical** email hash (`audit_283` old value). It does not match the current one.

- **[C]** The record is a contact/opt-in lookup keyed by an obsolete identifier. It is not an analytics profile with behavioural metrics: there are no `metrics`, `audience_cohort` or `reporting_window` fields, which all real ANALYTICS_PROFILE rows carry.
- **[C]** The deletion workflow itself attempted `DELETE_RECORD` on it (activity_3435, FAILED), not ANONYMIZE.
- **[H]** The category is SECONDARY_IDENTIFIER (rule_02) or MARKETING_PROFILE (rule_10). Both require DELETE. **Policy is decided per record from its content/type, not from the `system_id` prefix.**
- **[H]** Across all 32 samples, the expected remediation for a resource equals the operation type of the deletion workflow's own action on it (DELETE / REDACT / ANONYMIZE; CHECK_DATA_FLOW → DISABLE; CHECK_RESTORE_ACCESS → BLOCK). This is a useful secondary signal for category, but it is a workflow claim. Prefer an explicit `record_type`; fall back to content features, then to the workflow operation.

### 3.4 Evidence citation pattern

- **[C]** 70 of 75 cited steps cite the **latest file with `captured_at ≤ audit_at` that mentions the resource**. Examples:
  - case_15 cites evidence_01 (09-15), not the earlier connector screenshot evidence_14 (08-07).
  - case_09 cites evidence_93 (09-16 08:37), not the late evidence_06.
- **[C]** The other 5 citations are explained, not contradictory:
  - **support_001 (case_07):** cites evidence_58, a PDF that contains the resource and was not in the text index.
  - **Absence by omission (4 steps).** The file is a profile snapshot in which the account does **not** appear:
    - account_001/002/004 → evidence_54 (failover-replica dump with `customer_profiles_primary` + `customer_profiles_failover_replica`)
    - account_4857 → evidence_51 (bundle with an empty `account_service/customer_profiles` snapshot at audit time)
- **[U]** Which snapshot proves an omission. For case_04, evidence_90 (09-05, scope `account_service`, zero profile rows) is later than evidence_54 (09-02) but evidence_54 is expected. The selection rule for omission-based proofs is not determinable. Candidate heuristic: prefer the latest pre-cutoff snapshot that contains a **populated** profile table (primary/replica rows present, target absent) over an empty scoped table. This fits case_01/02/04, but case_31 cites an empty snapshot, so it is unconfirmed.
- **[H]** When one file supports several steps, the same file is cited for all of them (case_21–30 all cite evidence_92; case_11/13/14 all cite evidence_03).

### 3.5 Request intent

- **[C]** All 32 public samples are deletion requests. **There is no NOT_APPLICABLE example in the public answers**, so no labelled public example distinguishes access/export/correction/marketing requests.
- Several deletion requests contain **limiting clauses that must not flip intent**:
  - case_04: keep anonymous stats
  - case_17: may retain backups
  - case_23: security records can stay
  - case_31: keep a deleted-account reference
  - case_19: conversation may need to stay
  - case_28: "a similar email belongs to someone else, do not treat that record as mine". This is a decoy-exclusion instruction; the expected answer excludes the look-alike search document.
- Participant-visible evaluation **inputs** (not labels) contain 10 single-occurrence non-deletion texts (case_533–542):
  - profile/phone/surname/email correction
  - stop promotional emails / marketing lists only
  - data portability download / copy of information
  - "what information do you hold"
  - invoice copy
  - login help

  Each explicitly says it is *not* a deletion request ("leave the account active", "not asking for deletion", "please don't delete"). Ten `CLASSIFY_REQUEST` activities classify ten accounts as non-deletion; they are claims and consistent with this count.
- **[H]** Keyword matching is unsafe. Non-deletion texts contain "remove", "delete", "erase", "removing" inside negations or "only" clauses. Intent should come from a classifier that handles negation and "only" scoping. The other 508 eval texts are built from 17 fixed opening sentences (5 non-English) plus 40 boilerplate follow-ups, so a deterministic classifier with an LLM fallback for unseen text is adequate.

## 4. Scope: which resources belong to a case

- **[C]** Every expected non-audit resource has a `deletion_worker` action (or CHECK_*) inside [requested_at, reported_at + 3 h]. The exceptions are `account_004` and `support_001`, which come from handcrafted cases.
- **[C]** Grounded links found, in order of strength:
  1. A record containing a current or historical identifier (email in any case, phone, `email_hash`, `user_id`) together with the `resource_id`.
  2. Same `trace_id` across log lines (`lookup_key` / `subject_key` on the started line, `resource_id` and state on the completed line).
  3. `LINK_RESOURCE_IDENTITY` activities.
  4. Foreign keys such as `search_documents_primary.source_resource_id = account_006` (case_06).
- **[C] Earlier deletion episodes are out of scope.** In case_17, `account_6523` (looked up by the same email on 2026-03-10) and `tombstone_17` (linked 2026-03-10) are **not** expected; they belong to the same person's earlier request (eval case_46, audit 2026-03-11). In case_07, `object_19` (linked 2026-02-13) is not expected; it belongs to eval case_61 (audit 2026-02-14).
- **[H]** Scope rule: resources linked to the subject by observations made at or after `requested_at` (and with inner time ≤ `audit_at`), plus the resources acted on by this request's deletion workflow. Older links belong to earlier episodes.
- **[C]** Look-alike identifiers are decoys. Examples: `.jr` suffixes and different digits (case_28 `search_8168`); same-surname users in other files. Only exact, case-insensitive identifier matches are valid.

## 5. Unresolved questions

| # | Question | Impact |
|---|---|---|
| U1 | Attribution of identifier-free analytics records when two cases share `reported_at` (case_03 vs eval case_44). | ±1 verification step on affected cases |
| U2 | Whether inner observation timestamps ≤ `audit_at` inside a late-captured file may be used for linking. Needed to reproduce 6 expected resources (case_09, 23, 24, 29, 30). | Missed audit/account verification steps |
| U3 | Which snapshot is cited for absence-by-omission (evidence_54 vs evidence_90 for case_04). | Wrong `evidence_id` on 1 step per affected case |
| U4 | Two expected audit records (case_18, case_20) exist in no participant file. | Unavoidable step miss |
| U5 | Support record category when no `record_type` is given. Replica "legacy contact" copy (case_10) and customer-uploaded PDF (case_07) → DELETE; ticket with `message_excerpt` → REDACT. Rule inferred from 9 examples. | REDACT vs DELETE errors |
| U6 | Account linkage in handcrafted-style cases (01, 02, 04, 07, 08, 10). The only link is a workflow DELETE with "Target resource" wording within ±8 min of `reported_at`; no identifier links the account. | Account verification step |
| U7 | No public NOT_APPLICABLE examples; the intent classifier is unvalidated against labels. | 10 eval cases at risk |

## 6. Case-by-case analysis

Notation: `R=` request email is current or historical; `rep`/`audit` = `reported_status` / `audit_at` date. "Cites" lists the expected evidence. "Steps" uses `F:` / `R:` / `V:` for phases.

### case_01 — COMPLETE (rep COMPLETE, audit 09-03)
- Identity: user_01, R=current, no history.
- Resources: `account_001`, absent from both profile tables in evidence_54 (09-02 23:00). Linked only via activity_3342 (DELETE, "Target resource", −1 min from `reported_at`).
- Steps: V: ABSENT account_001 [evidence_54].
- Uncertainty: U3, U6.

### case_02 — COMPLETE (rep PARTIALLY_COMPLETE, audit 09-04)
- Identity: user_02, current. Request is in Spanish.
- Resources: `account_002` absent in evidence_54. Activity_3376 reports PARTIAL, but evidence of absence wins.
- Steps: V: ABSENT account_002 [evidence_54].
- Uncertainty: U3, U6.

### case_03 — COMPLETE (rep COMPLETE, audit 09-26)
- Identity: user_43, current. Request is in French.
- Resources (all from evidence_94, 09-26 10:38):
  - `account_7566`: lookup by email → rows=0/404
  - `audit_record_2016`: lookup user_43, rows=1, retained to 2034
  - `analytics_9406`: lookup_key=null, all identifiers null
- Steps: V: ABSENT account_7566; PRESENT audit_record_2016; ANONYMIZED analytics_9406 — all [evidence_94].
- Uncertainty: **U1**. `analytics_9406` vs `analytics_5589` cannot be distinguished; readback adjacency points to the wrong one.

### case_04 — COMPLETE (rep COMPLETE, audit 09-07)
- Identity: user_04, current. "Keep anonymous statistics".
- Resources:
  - `account_004`: absent (evidence_54)
  - `analytics_901`: identifiers null in evidence_56 (09-07 09:45); linked by activity_3463 only
- Steps: V: ABSENT account_004 [evidence_54]; ANONYMIZED analytics_901 [evidence_56].
- Uncertainty: U3 (evidence_90 is later and also shows no account rows), U6, U1-type link.

### case_05 — INCOMPLETE (rep COMPLETE, audit 09-08)
- Identity: user_05, current.
- Resources: `account_005` is present (ACTIVE, full PII, `user_id=user_05`) in `customer_profiles_failover_replica` but absent from `customer_profiles_primary` in evidence_54. This is replication drift; activity_3483 SYNC_RECORD follows the delete.
- Steps: F: REMAINING account_005 [evidence_54]; R: DELETE account_005; V: ABSENT account_005.
- Note: no audit record exists for user_05 → no PRESENT step.

### case_06 — INCOMPLETE (rep PARTIALLY_COMPLETE, audit 09-10)
- Identity: user_06, current.
- Resources:
  - `search_001`: present in `search_documents_primary` (evidence_57, 09-10 08:45) with the subject email and `source_resource_id=account_006` (grounded link to the account)
  - `account_006`: unobserved (activity_3545 DELETE SUCCESS)
- Steps: F: REMAINING search_001 [evidence_57]; R: DELETE search_001; V: ABSENT account_006, search_001.

### case_07 — INCOMPLETE (rep COMPLETE, audit 09-12)
- Identity: user_07, current.
- Resources:
  - `support_001`: evidence_58 PDF (captured 09-12 07:30) shows a customer-uploaded delivery-correction attachment with name, email and phone → SUPPORT_ATTACHMENT, DELETE
  - `account_007`: activity_3590 only
- Excluded: `object_19` (linked 2026-02-13, earlier episode).
- Steps: F: REMAINING support_001 [evidence_58]; R: DELETE; V: ABSENT account_007, support_001.
- Uncertainty: U6.

### case_08 — INCOMPLETE (rep PARTIALLY_COMPLETE, audit 09-14)
- Identity: user_08, current.
- Resources:
  - `export_001`: owner email = subject, `download_available=true`, expires 10-04 (evidence_59, 09-14 15:40); activity_3555 DELETE FAILED
  - `account_008`: activity_3554 only
- Steps: F: REMAINING export_001 [evidence_59]; R: DELETE; V: ABSENT account_008, export_001.
- Note: evidence_27 lists a legal-hold order row for user_08. It has no `resource_id`, so it produces no step.

### case_09 — INCOMPLETE (rep NOT_STARTED, audit 09-16 09:00)
- Identity: user_61, current.
- Resources:
  - `backup_4978`: `customer_email`=subject, `restore_allowed=1` (evidence_93, 09-16 08:37)
  - `account_3960`, `audit_record_4902`: linked only in evidence_06 (captured 09-18; lines 09-16 08:52–08:57)
- Steps: F: RESTORE_RISK backup_4978 [evidence_93]; R: BLOCK_RESTORE; V: ABSENT account_3960, PRESENT audit_record_4902, RESTORE_BLOCKED backup_4978.
- Uncertainty: **U2**.

### case_10 — INCOMPLETE (rep COMPLETE, audit 09-18)
- Identity: user_10, R=**historical** (email changed twice: audit_121, audit_238; hashes audit_122, audit_239).
- Resources:
  - `support_002`: found in `support_replica` by the **old** email (evidence_61, 09-17); `marker_found=false`, `last_write=2026-09-07` after the 09-02 SUCCESS delete claim (activity_3596) → recreated or never deleted
  - `account_010`: activity_3595 only
- Steps: F: REMAINING support_002 [evidence_61]; R: DELETE; V: ABSENT account_010, support_002.
- Uncertainty: U5, U6.

### case_11 — INCOMPLETE (rep COMPLETE, audit 10-01)
- Identity: user_32, current.
- Resources (evidence_03 handover, 10-01 12:00, explicit `record_type` + state):
  - `account_4248` NOT_FOUND
  - `search_052` FOUND
  - `analytics_2034` IDENTIFIABLE
  - `support_864` SUPPORT_MESSAGE IDENTIFIABLE
  - `data_flow_9522` ACTIVE
  - `audit_record_9394` FOUND
- Steps: F: REMAINING search_052; EXPOSED analytics_2034, support_864; ACTIVE data_flow_9522 [all evidence_03]. R: DISABLE → DELETE → REDACT → ANONYMIZE. V: six checks.

### case_12 — INCOMPLETE (rep COMPLETE, audit 09-15)
- Identity: user_12, current; previous email/hash audit_282/audit_283.
- Resources (evidence_01, 09-15):
  - `account_9797` 404
  - `audit_record_2945` rows=1
  - `analytics_9914`: contact lookup, `email_opt_in=true`, keyed by the **old email hash**
- Steps: F: REMAINING analytics_9914 [evidence_01]; R: DELETE; V: ABSENT account_9797, analytics_9914; PRESENT audit_record_2945.
- See §3.3.

### case_13 — INCOMPLETE (rep NOT_STARTED, audit 10-01)
- Identity: user_33, current.
- Resources (evidence_03):
  - `account_9335` NOT_FOUND
  - `search_1308` FOUND
  - `support_4218` **SUPPORT_ATTACHMENT** FOUND → DELETE
  - `audit_record_4816` FOUND
- Steps: F: REMAINING search_1308, support_4218; R: DELETE ×2; V: ABSENT ×3, PRESENT audit.

### case_14 — INCOMPLETE (rep COMPLETE, audit 10-01)
- Identity: user_37, current. Request is in Japanese.
- Resources (evidence_03): `account_3677` NOT_FOUND; `backup_3870` BACKUP_ARCHIVE ACTIVE; `audit_record_987` FOUND.
- Steps: F: RESTORE_RISK backup_3870; R: BLOCK; V: ABSENT, PRESENT, RESTORE_BLOCKED.

### case_15 — INCOMPLETE (rep COMPLETE, audit 09-15)
- Identity: user_15, current; old phone audit_50.
- Resources (evidence_01):
  - `account_4745` 404
  - `data_flow_9846`: heartbeat `enabled=true`, trace joined via `subject_key`
  - `audit_record_1596` rows=1
- Earlier screenshot evidence_14 (08-07) shows the same connector, but the latest pre-cutoff file is cited.
- Steps: F: ACTIVE data_flow_9846 [evidence_01]; R: DISABLE; V: ABSENT, PRESENT, DISABLED.

### case_16 — INCOMPLETE (rep NOT_STARTED, audit 09-21)
- Identity: user_53, current.
- Resources (evidence_05, 09-21 10:00, primary + read replica):
  - `account_994`: in **read replica only**
  - `search_1007`: in both
  - `audit_record_9528` present
- Steps: F: REMAINING account_994, search_1007 [evidence_05]; R: DELETE ×2; V: ABSENT ×2, PRESENT.

### case_17 — INCOMPLETE (rep NOT_STARTED, audit 09-15)
- Identity: user_17, current.
- Resources (evidence_01):
  - `account_4092` 404
  - `backup_3245`: `eligible=true deletion_block=false`
  - `audit_record_1797` rows=1
- Excluded: `account_6523`, `tombstone_17` (March episode).
- Steps: F: RESTORE_RISK backup_3245; R: BLOCK; V: ABSENT, PRESENT, RESTORE_BLOCKED.

### case_18 — INCOMPLETE (rep COMPLETE, audit 09-26)
- Identity: user_50, current; old phone audit_169.
- Resources (evidence_94):
  - `search_4013` hit
  - `analytics_037` email set
  - `support_5569` requester_email set (ticket → REDACT)
  - `data_flow_4890` enabled=true
  - `account_5521`: activity only
  - `audit_record_6645`: in **no** file
- Steps: 4 findings, 4 remediations, 6 verifications.
- Uncertainty: **U4**.

### case_19 — INCOMPLETE (rep PARTIALLY_COMPLETE, audit 09-15)
- Identity: user_19, current. Request asks to keep shared conversations.
- Resources (evidence_01):
  - `search_6083` hit
  - `support_9553`: `message_pii_scan detector=direct_identifier` → REDACT
  - `account_9102` 404
  - `audit_record_6793` rows=1
- Steps: F: REMAINING search_6083, EXPOSED support_9553; R: DELETE, REDACT; V: ABSENT ×2, PRESENT, REDACTED.

### case_20 — INCOMPLETE (rep NOT_STARTED, audit 09-26)
- Identity: user_48, current.
- Resources (evidence_94): `search_4262` hit; `data_flow_1770` enabled=true. `account_5037`: activity_3734 DELETE FAILED, never observed → no finding (§2.5). `audit_record_5569`: in no file.
- Steps: F: REMAINING search_4262, ACTIVE data_flow_1770; R: DISABLE, DELETE; V: four checks.
- Uncertainty: **U4**.

### case_21 — COMPLETE (rep COMPLETE, audit 09-15)
- Identity: user_21, current.
- Resources (evidence_92, 09-15 11:44):
  - `account_6440` 404
  - `audit_record_3737` subject user_21, retained to 2034
  - `analytics_5335` all identifiers null; linked by workflow only
- Steps: V: ABSENT, PRESENT, ANONYMIZED [evidence_92].
- Uncertainty: U1-type link.

### case_22 — INCOMPLETE (rep COMPLETE, audit 09-21)
- Identity: user_51, current.
- Resources (evidence_05): `search_8911` and `analytics_4440` (`user_id` + email) present in primary and replica; `audit_record_3482` present; `account_4990` activity only.
- Steps: F: REMAINING search_8911, EXPOSED analytics_4440; R: DELETE, ANONYMIZE; V: four checks.

### case_23 — INCOMPLETE (rep NOT_STARTED, audit 09-15)
- Identity: user_23, current. "Security records can stay."
- Resources (evidence_92): `export_7364` owner email; `search_898` hit. `account_410`: activity only. `audit_record_4128`: only in late evidence_02 (inner 09-15 12:00).
- Steps: F: REMAINING export_7364, search_898; R: DELETE ×2; V: ABSENT ×3, PRESENT.
- Uncertainty: U2.

### case_24 — INCOMPLETE (rep COMPLETE, audit 09-15)
- Identity: user_24, current.
- Resources (evidence_92): `account_5334` **status 200** with email (deletion claimed SUCCESS); `search_5577` hit. `audit_record_7095`: late evidence_02 only.
- Steps: F: REMAINING account_5334, search_5577; R: DELETE ×2; V: ABSENT ×2, PRESENT.
- Uncertainty: U2.

### case_25 — COMPLETE (rep NOT_STARTED, audit 09-15)
- Identity: user_25, current; old phone audit_220.
- Resources (evidence_92): `account_3136` 404 (despite activity_3597 FAILED); `audit_record_451`; `analytics_1895` null identifiers.
- Steps: V: ABSENT, PRESENT, ANONYMIZED [evidence_92].

### case_26 — COMPLETE (rep NOT_STARTED, audit 09-15)
- Identity: user_26, current.
- Resources (evidence_92):
  - `account_5684` 404
  - `audit_record_5416`
  - `support_4715`: requester_* null, `customer_reference=user_26` kept
  - `analytics_4566` null
  - `data_flow_6244` enabled=false
  - `backup_3120` restore_allowed=false
- Steps: V: six checks [evidence_92].

### case_27 — COMPLETE (rep COMPLETE, audit 09-15)
- Identity: user_27, current. Asks to audit "as it stood".
- Resources: same pattern as case_26 (`account_3866`, `audit_record_3830`, `support_4707`, `analytics_4574`, `data_flow_2295`, `backup_5970`).
- Steps: V: six checks [evidence_92].

### case_28 — COMPLETE (rep NOT_STARTED, audit 09-15)
- Identity: user_28, current.
- Resources: same pattern (`account_5482`, `audit_record_9265`, `support_2351`, `analytics_6077`, `data_flow_2337`, `backup_838`). The look-alike search doc (`search_8168`, a different email with a `.jr` suffix) is correctly **excluded**.
- Steps: V: six checks [evidence_92].

### case_29 — INCOMPLETE (rep NOT_STARTED, audit 09-15)
- Identity: user_29, R=**historical** (audit_284/285).
- Resources (evidence_92, matched by the **historical** request email, not the current snapshot email):
  - `search_1993` hit
  - `analytics_5208` email set
  - `support_5281` requester_email set
  - `data_flow_3827` enabled=true (`analytics_identity_bridge`)
  - `account_7012`: activity only
  - `audit_record_3954`: late evidence_02 only
- Steps: 4 findings, 4 remediations, 6 verifications.
- Uncertainty: U2.

### case_30 — INCOMPLETE (rep COMPLETE, audit 09-15)
- Identity: user_30, R=**historical** (audit_280/281).
- Resources (evidence_92, matched by the historical email): `search_9359`, `analytics_3697`, `support_6477`, `data_flow_8524`, same states as case_29. `account_4163`: activity only. `audit_record_1707`: late evidence_02 only.
- Steps: 4/4/6 as case_29.
- Uncertainty: U2.

### case_31 — COMPLETE (rep COMPLETE, audit 09-15)
- Identity: user_541, current.
- Resources (evidence_51, 09-15 12:00): `tombstone_440` (subject_reference kept, email/phone/hash null, DELETED); `audit_record_6909`; `account_4857` absent by omission (empty profile snapshot).
- Steps: V: ABSENT account_4857, PRESENT audit_record_6909, REDACTED tombstone_440 [evidence_51].
- Uncertainty: U3.

### case_32 — INCOMPLETE (rep PARTIALLY_COMPLETE, audit 09-15)
- Identity: user_542, current.
- Resources (evidence_51): `tombstone_9178` still carries email/phone/email_hash; `audit_record_7068`; `account_8858` activity only (PARTIAL).
- Steps: F: EXPOSED tombstone_9178; R: REDACT; V: ABSENT account_8858, PRESENT audit_record_7068, REDACTED tombstone_9178.

## 7. Recommended implementation order

1. **Evidence normaliser.** SQL via sqlite3; JSON walker emitting resource-level objects with inner `observed_at`/`captured_at`; log parsers for 4 formats with `trace_id` joins; handover TXT. Every observation carries `file_id`, file `captured_at`, inner time, system, `resource_id`, `record_type`, field states, identifiers.
2. **Identity resolver.** Current + historical emails (lowercased), phones, email hashes, `user_id`; exact word-boundary matching only.
3. **Linker and scope.** Grounded links (identifier co-occurrence, trace join, `LINK_RESOURCE_IDENTITY`, foreign keys) restricted to the current episode (≥ `requested_at`); workflow-correlation links as low-confidence fallback for identifier-free records; exclude look-alikes.
4. **State reconstruction.** Latest observation per resource with inner time ≤ `audit_at`; replica-aware (any copy present ⇒ PRESENT); omission-based absence from profile snapshots.
5. **Policy engine.** Category from `record_type` → content features → workflow operation; map to required action per §2.2.
6. **Step generator and serialiser.** Rules S1–S9; citations = latest pre-cutoff file (§3.4).
7. **Evaluator** on the 32 samples: status, step, field and sequence accuracy. Iterate on U-items without per-case special-casing.
8. **Intent classifier.** Deterministic template + negation handling, LLM fallback with cache; validate on the 10 non-deletion inputs by reading, since no labels exist.
9. **Media.** PDFs via text extraction; the 11 PNGs via a one-time cached vision/OCR pass.
10. Full run, usage report, evaluation report, packaging.
