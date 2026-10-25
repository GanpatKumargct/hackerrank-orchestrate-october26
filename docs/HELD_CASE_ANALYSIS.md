# Held-Case Analysis — Stage 9 run `runs/20261025T024207Z`

**Read-only analysis. Prepared 2026-10-25 for the project owner's review before Stage 10.**

No production code, tests, dataset, evidence, staged run files or root `output.csv` were changed. No rule was relaxed. Case and resource identifiers appear below. Email addresses, phone numbers and names do not.

**Labels used throughout:**

- **[VERIFIED]** — measured on participant data with the current pipeline.
- **[HYPOTHESIS]** — a plausible explanation that the evidence does not prove. It must not drive logic without new evidence or a decision.
- **[OPEN DECISION]** — needs an explicit decision from the owner, or an external input.

---

## 0. Bottom line

1. **[VERIFIED]** 464 of 518 evaluation cases are held. They are held only for the two reasons the gate defines: `VERIFICATION_SET_INCOMPLETE` 327 and `REQUIRED_RESOURCE_UNRESOLVED` 137. These two codes are **symptoms**. The causes are the unresolved members behind them. There are **ten member-level classes**, and four of them account for 437 of the 464 cases.
2. **[VERIFIED]** No held case can be resolved from locally available, admissible evidence under the current approved rules. The pipeline did not miss any admissible evidence it could legally use for these blockers:
   - no retention field exists for the 202 unresolved audit records;
   - no identifier-bearing observation exists for the shared-claim accounts;
   - post-cutoff resources are observed only in files captured at least 47.9 h after `audit_at`;
   - the 11 screenshots are unread.
3. **[VERIFIED]** The four large classes are each resolvable only by **new evidence**, or by an **owner decision that would change an approved rule**:
   - **P** — primary account not grounded: 333 cases.
   - **R** — audit retention not observed: 202 cases.
   - **C** — post-cutoff-only resource: 134 cases.
   - **S** — support shared-context not evidenced: 82 cases.
4. **[VERIFIED]** The public sample answers resolve the same four classes **more permissively** than the approved rules. This is a recorded fact, not a reason to change the rules (G.3.3). Section 7 gives the comparison.

---

## 1. Method and provenance

- **Inputs read:**
  - `runs/20261025T024207Z/held_cases.json`, `held_report.md` and `run_summary.json`;
  - participant files under `dataset/`, opened through the existing loader;
  - `dataset/sample_output.csv`, for the comparison in §7 only.
- **How the facts were produced.** Throw-away scripts in the session scratchpad re-ran the existing pipeline in memory (`CaseAnalyzer`, `assess`, `omission_readings`). They wrote nothing into the repository. The in-memory held set matched `held_cases.json` exactly: 464 cases with identical reasons.
- **Integrity check.** The sha256 of all five files in `runs/20261025T024207Z/` was recorded before the analysis and re-verified after it: all OK. Root `output.csv` does not exist.

---

## 2. Hold reasons are symptoms

| Gate reason | Cases | What it means |
|---|---|---|
| `VERIFICATION_SET_INCOMPLETE` | 327 | At least one proven violation, but some required member has no determinable final state. INCOMPLETE would omit a check (Q-VERIFICATION-SET-INCOMPLETE). |
| `REQUIRED_RESOURCE_UNRESOLVED` | 137 | No proven violation, and at least one required member unresolved. COMPLETE is impossible. |

Both reasons are produced by the same member-level blockers. Whether a case lands in one or the other depends only on whether it **also** has a proven violation. Root causes are therefore analysed at member level in §3–§5.

---

## 3. Root-cause classes (member level)

| Code | Root cause | Members | Cases touched | Cases where it is the **only** blocker |
|---|---|---|---|---|
| **P** | Primary-account slot empty: no in-scope `USER_PROFILE` resource | 333 | 333 | 96 |
| **R** | `SECURITY_AUDIT_LOG` rule_12 condition unknown: retention period not observed | 202 | 202 | 66 |
| **C** | `POST_CUTOFF_ONLY`: the resource is observed only in files captured after `audit_at`, so its category and state are unknown | 185 | 134 | 16 |
| **S** | `SUPPORT_MESSAGE` rule_05 condition unknown: no shared-context evidence | 83 | 82 | 12 |
| LB | Analytics `LABEL_ONLY`: a handover label without slot content | 11 | 11 | 0 |
| F | Support message `FIELD_COVERAGE_INCOMPLETE` | 6 | 6 | 0 |
| N | `NO_ADMISSIBLE_OBSERVATION` (4 catalog-claim-only resources, 1 backup) | 5 | 5 | 1 |
| A | `SUPPORT_ATTACHMENT` rule_06 condition unknown: no owner field | 3 | 3 | 0 |
| L | `LEGAL_HOLD_RECORD` rule_13 condition unknown | 1 | 1 | 0 |
| U | `CATEGORY_UNGROUNDED` (`audit_record_003`; owner ambiguity kept by instruction) | 1 | 1 | 0 |

**[VERIFIED] The "cases touched" column overlaps.** It sums to 778, against 464 held cases. Do not add the rows.

### 3.1 Exact blocker combinations (each case counted once)

| Blocker set | Cases | VSI | RRU |
|---|---|---|---|
| P | 96 | 56 | 40 |
| P+R | 96 | 63 | 33 |
| C+P | 92 | 74 | 18 |
| R | 66 | 54 | 12 |
| C+P+S | 24 | 21 | 3 |
| R+S | 18 | 14 | 4 |
| C | 16 | 16 | 0 |
| P+S | 15 | 14 | 1 |
| S | 12 | 1 | 11 |
| LB+R+S | 8 | 8 | 0 |
| F+P+R | 6 | 0 | 6 |
| LB+R | 3 | 2 | 1 |
| N+P | 3 | 0 | 3 |
| A+R | 2 | 1 | 1 |
| C+S | 2 | 2 | 0 |
| A+R+S, L+R+S, N+R+S, N, P+U | 1 each | 1, 0, 0, 0, 0 | 0, 1, 1, 1, 1 |
| **Total** | **464** | **327** | **137** |

### 3.2 Cases whose every blocker lies within a set

This is a counterfactual count for sizing decisions only. It is cumulative and not additive.

| Every blocker within | Cases |
|---|---|
| {P} | 96 |
| {R} | 66 |
| {S} | 12 |
| {C} | 16 |
| {P, R} | 258 |
| {R, S} | 96 |
| {P, R, S} | 303 |
| {P, R, S, C} | 437 |

**[VERIFIED]** The remaining 27 cases also involve LB, F, N, A, L or U.

---

## 4. Root cause by class: verified facts, available evidence, resolvability

### 4.1 P — primary account slot (333 cases)

**[VERIFIED] What the scope builder sees for these cases.** Resource-ID prefixes are used here only to *describe* candidates; they never decide anything.

| Account candidates seen by the scope builder | Cases |
|---|---|
| Only accounts reachable through **shared** workflow claims (3–14 claimant cases each), with **0 observations** | 204 |
| Shared-claim accounts, one of which has an identifier-free observation (admissible in 54 cases, late in 11) | 65 |
| An account in scope through a **late-captured** link only, so `POST_CUTOFF_ONLY` (with or without shared claims) | 61 |
| No account candidate at all (case_33, case_50, case_63) | 3 |

**[VERIFIED] Facts behind the candidates:**

- The claims are `deletion_worker` activities with the template "submitted primary profile `<id>` to account_service". There are 532 such activities, each naming one distinct resource. **Their `details` contain no identifier.**
- **Timing does not single out an account.** 355 of 518 requests have ≥ 5 such activities inside `[requested_at, reported_at]`. The median gap from `requested_at` to the nearest one is about 1 367 minutes.
- In 85 of the 333 cases, some account candidate has admissible **state** evidence: an observation or a direct-table omission. **Identity** is still missing, so this evidence cannot be attributed to the subject.

**Available local evidence that could legitimately resolve P:** none under Q-WEAK-VERIFY = No and the C.5 link rules.

**Resolvable without a decision or new evidence:** No.

- **[OPEN DECISION]** Only a change to the approved identity basis could move this class: Q-WEAK-VERIFY, or the disabled `offset_signature`. Even then, the claims are shared by 3–14 cases, so a unique attribution would still be unavailable for most accounts. **Recommendation: keep held** unless new identity evidence is supplied.

### 4.2 R — security-audit retention not observed (202 cases)

**[VERIFIED]**

- **None** of the 202 unresolved audit records has a retention field (`retention_until` or any `*until*`, `*reten*`, `*expir*`, `*policy*` name) in **any** observation, admissible or late.
- Their evidence schemas carry no such column. The most common field sets are `actor_type, event_name, integrity_seal, subject_reference` (115) and `integrity_check, rows` (34).
- By contrast, 104 observations elsewhere in the dataset do carry `retention_until`, for other audit records.

**Available local evidence that could legitimately resolve R:** none. Under Q-RETENTION-UNOBSERVED (strict), these records stay `CONDITION_UNKNOWN`.

**[HYPOTHESIS]** The screenshot `evidence_37` (named "security_audit_explorer", captured 2026-09-05) could show retention data for some records. By an upper bound, at most 42 held cases have an unresolved `security_service` member with `audit_at` on or after that capture.

**[OPEN DECISION]** Should rule_12's condition be required only for **COMPLETE** (cited proof), while an **INCOMPLETE** case may list a future `VERIFY_RECORD_PRESENT` check (with an empty `evidence_id`) for an audit record whose presence is proven but whose retention period is unobserved? This changes Q-RETENTION-UNOBSERVED and Q-VERIFICATION-SET-INCOMPLETE.

- **Size:** 66 cases are blocked only by R. With P, 258 cases are blocked only by P and/or R (§3.2).
- **Safety argument for:** a future presence check asks the operator to *keep* the record. It never deletes it.
- **Risk:** the check asserts a retention obligation that no evidence shows.

### 4.3 C — post-cutoff-only resources (134 cases, 185 members)

**[VERIFIED]**

- Every C member is in scope only through late-captured evidence. That evidence is admissible for linking (Q-LATE-LINK), never for state or category. So the category is ungrounded and the required final state is unknown.
- The earliest late file is captured **≥ 47.9 h** after `audit_at` (median 50.9 h). There are 18 distinct late files.
- In 177 members every late observation has an inner time ≤ cutoff (pure link-only). In 8, at least one does not.
- Descriptive prefix counts: `audit_record` 116, `account` 61, `legal_hold` 2, and one each of search, data_flow, analytics, export, support and backup.

**Available local evidence that could legitimately resolve C:** none. No pre-cutoff observation exists.

**Resolvable:** No. Late evidence may not prove state or category, and the resource prefix may not decide category (D.1). **Recommendation: keep held.** Only new pre-cutoff evidence would resolve these.

### 4.4 S — support-message shared context (82 cases, 83 members)

**[VERIFIED] Evidence held for the unresolved support messages** (87 distinct resources across evaluation and samples):

| What the evidence contains | Resources |
|---|---|
| Requester fields and an event, with **no message text** | 34 |
| Message excerpt, all reading "Customer contacted support about account access." | 22 |
| Other: handover rows, PII-scan lines, readback lines | 31 |

`deletion_rules.csv` has only rule_05 for `SUPPORT_MESSAGE`, with condition "shared customer, agent, or order context that must be retained".

**Available local evidence that could legitimately resolve S:** only the "account access" excerpt, and only after the meaning validation required by Q-SHARED-CONTEXT-WORDS.

- **[HYPOTHESIS]** That sentence describes a single customer's own access issue. On its face it does not show shared customer, agent or order context. So it is not, by itself, evidence for the condition.

**[OPEN DECISION]** Is rule_05 a category-level treatment (every support conversation is REDACT), or a condition that must be evidenced per record (the current rule)? If it must be evidenced, what is the treatment when it is FALSE? There is no rule for that, so the result would be `POLICY_GAP`. 12 cases are blocked only by S.

### 4.5 Small classes (27 cases in total, each with other blockers as well)

| Class | Resources (case) | Verified fact | Resolvable locally? |
|---|---|---|---|
| LB (11) | analytics_6499, 3181, 8539 (case_89–91, evidence_08); analytics_7772, 3006 (case_134/140, evidence_13); analytics_4420, 2784, 5354 (case_386/388/389, evidence_36); analytics_2354, 6172, 6528 (case_434/437/438, evidence_41) | Handover rows give an ANONYMIZED or IDENTIFIABLE label with no slot content | No: a label alone is not proof (D.3.3) |
| F (6) | support_7479 (57), 2859 (112), 7867 (155), 9505 (204), 6046 (308), 5854 (480) | Not every requester slot is observed | No |
| N (5) | export_1842 (33), tombstone_17 (46), object_19 (61), marketing_001 (63): in scope only through a catalog claim with zero observations; backup_3250 (264): its only observation is not admissible | See §5 for the media link of the first four | Only through media (§5) |
| A (3) | support_9538 (34), support_5234 (263), support_2944 (419) | Only PII-scan lines; no owner field | No |
| L (1) | legal_hold_8049 (390) | `retained_until` not observed | No |
| U (1) | audit_record_003 (45) | Owner and category ambiguous; kept unresolved by instruction | Only through media (§5) |

---

## 5. The 11 PNG evidence gaps

**[VERIFIED]** All 12 `LINK_RESOURCE_IDENTITY` (catalog) claims occur exactly **7 min 1 s after** the capture of a screenshot, or of one PDF, from the matching system. The **manifest file name** suggests the system; that suggestion is a [HYPOTHESIS].

| Media | Name suggests | Captured | Paired catalog claim (resource) | Case | Current state of that resource |
|---|---|---|---|---|---|
| evidence_04 | account admin console | 09-26 11:00 | activity_4000 (account_5762) | case_34 | account candidate only |
| evidence_09 | search index inspector | 09-01 06:00 | activity_4001 (search_428) | case_35 | POST_CUTOFF_ONLY |
| evidence_14 | connector console | 08-07 08:00 | activity_4002 (data_flow_1121) | case_39 | POST_CUTOFF_ONLY |
| evidence_19 | analytics profile view | 07-13 10:00 | activity_4003 (analytics_7438) | case_50 | POST_CUTOFF_ONLY |
| evidence_23 | export console | 06-18 12:00 | activity_4004 (export_1260) | case_52 | POST_CUTOFF_ONLY |
| evidence_28 | support ticket console | 05-24 07:00 | activity_4005 (support_1034) | case_53 | POST_CUTOFF_ONLY |
| evidence_32 | backup restore console | 04-29 09:00 | activity_4006 (backup_9287) | case_55 | POST_CUTOFF_ONLY |
| evidence_37 | security audit explorer | 09-05 07:00 | activity_4010 (audit_record_003) | case_45 | CATEGORY_UNGROUNDED |
| evidence_42 | deleted-account reference | 03-10 06:00 | activity_4011 (tombstone_17) | case_46 | NO_ADMISSIBLE_OBSERVATION |
| evidence_46 | object storage browser | 02-13 08:00 | activity_4007 (object_19) | case_61 | NO_ADMISSIBLE_OBSERVATION |
| evidence_60 | marketing profile console | 09-16 07:20 | activity_4008 (marketing_001) | case_63 | NO_ADMISSIBLE_OBSERVATION |
| evidence_18 (PDF, parsed) | customer statement | 07-18 11:00 | activity_4009 (export_1842) | case_33 | NO_ADMISSIBLE_OBSERVATION |

**[VERIFIED] Other facts:**

- `evidence_18` parses (2 pages). It holds a customer statement with direct identifiers for user_18, but **no resource ID**, so it creates no observation.
- No sample expected step cites any of the 11 PNGs.

**[HYPOTHESIS]**

- Each screenshot shows the resource of its paired claim, at its system's console, a few minutes before the claim.
- If so, reading them could ground state and category for up to 11 resources in 11 held cases: case_33–35, 39, 45, 46, 50, 52, 53, 55, 61, 63. That is 12 IDs, because the evidence_18 PDF covers case_33.
- `evidence_37` could also carry retention data (§4.2).
- **[VERIFIED]** Only **case_46** (blocker N alone) could have every blocker removed by media alone. The other 11 also have P (case_33, 35, 39, 45, 50, 52, 53, 55, 61, 63) or A+R (case_34).

**Resolvable:** only after **X-MEDIA-TRANSMISSION** is decided [OPEN DECISION]. An alternative needing its own decision is a human transcription into the hash-pinned media cache (B.1.3).

---

## 6. Resolvability summary

| Class | Cases touched | Local admissible evidence available? | What would resolve it | Type |
|---|---|---|---|---|
| P | 333 | No: identity missing; 85 cases have state evidence only | New identity evidence, or a change to Q-WEAK-VERIFY (not recommended) | New evidence / open decision |
| R | 202 | No: retention not present anywhere | Retention evidence (possibly evidence_37), or a revision of Q-RETENTION-UNOBSERVED for INCOMPLETE future checks | New evidence / open decision |
| C | 134 | No: late-only | Pre-cutoff evidence | New evidence |
| S | 82 | Only the "account access" excerpt (22 resources), not shown to mean shared context | A decision on the rule_05 interpretation | Open decision |
| LB, F, A, L | 21 | No | New evidence | New evidence |
| N, U | 6 | No | X-MEDIA-TRANSMISSION | External decision |

**[VERIFIED]** Even if P, R, S and C were all resolved, 27 cases would still be held by the small classes (§3.2).

---

## 7. Comparison with the 32 public samples (evaluation only; no tuning)

**[VERIFIED] Outcomes:**

- 3 emitted: case_05 matches exactly. case_03 and case_26 match status (COMPLETE) but omit one anonymized analytics record each, which is linked only by shared workflow claims.
- 29 held. False-COMPLETE count: 0.

| Expected | Cases held by us | Our blockers | What the sample answer does instead (VERIFIED) |
|---|---|---|---|
| COMPLETE | case_01, 02, 04, 21, 25, 28 | P only | Cites a primary account that has no C.5 link. In case_01/02/04 the citation is the `evidence_54` direct-table omission (a failover + primary dump). In case_01/02 the cited account is reachable only through shared claims (8 and 7 claimants). In case_04 the cited account is not a candidate at all; our candidates are four other shared-claim accounts. |
| COMPLETE | case_27 | P + S | The same, plus `VERIFY_RECORD_REDACTED` for support_4707 (the "account access" excerpt case). |
| COMPLETE | case_31 | P + R | Cites `audit_record_6909` from `evidence_51`, **whose observation has no `retention_until`** (6 of the 7 sample audit-record citations do include it). |
| INCOMPLETE | case_11–17, 19, 22, 32 | R (± P, S) | Lists `VERIFY_RECORD_PRESENT` (future check, empty `evidence_id`) for audit records whose retention period we cannot observe. |
| INCOMPLETE | case_07, 11, 18, 19 | S or A (± others) | Applies the REDACT chain to every support message whose shared context is unevidenced (4/4). For support_001 (attachment) it applies the DELETE chain. |
| INCOMPLETE | case_06, 09, 23, 24, 29, 30 | C or N (± P) | Lists a future `VERIFY_RECORD_ABSENT` / `_PRESENT` for resources we can see only after the cutoff, or not at all. |
| INCOMPLETE | case_08, 10, 20 | P only | Lists a future `VERIFY_RECORD_ABSENT` for an ungrounded primary account. |

**[HYPOTHESIS]** The reference answers appear to treat:

- a resource's category as known from its identity;
- retention, and rule_05 shared context, as category-level properties;
- workflow-claimed accounts as the subject's.

None of these is derivable from participant evidence under the approved rules. Per G.3.3, sample agreement alone is **not** a valid reason to adopt them.

---

## 8. Recommended next actions (ranked by impact × safety)

| # | Action | Impact (held cases affected) | Safety | Type |
|---|---|---|---|---|
| 1 | **Decide X-HELD-MAPPING in principle now.** With 464 held, no compliant `output.csv` can exist under A.8.3. The owner must choose between: (a) no root output; (b) reason-specific mappings, each recorded with its compliance risk; (c) more evidence work. | all 464 | Decision only; no code | [OPEN DECISION] |
| 2 | **Decide X-MEDIA-TRANSMISSION**, or a human-transcription alternative into the hash-pinned cache. This adds evidence without weakening any rule. | up to 12 cases directly (§5); more if `evidence_37` holds retention data (≤ 42 upper bound) | High: adds evidence; nothing is relaxed | [OPEN DECISION], external |
| 3 | **Review R for INCOMPLETE only**: allow a future `VERIFY_RECORD_PRESENT` for a proven-present audit record with unobserved retention. Keep COMPLETE strict. | 66 solely; up to 258 together with P | Medium: retains data, never deletes; but asserts an unevidenced retention obligation | [OPEN DECISION] (Q-RETENTION-UNOBSERVED / Q-VERIFICATION-SET-INCOMPLETE) |
| 4 | **Decide the rule_05 interpretation** (category-level REDACT vs a per-record condition) and the FALSE-branch treatment. | 12 solely; up to 96 together with R | Medium: REDACT keeps the record and removes identifiers | [OPEN DECISION] |
| 5 | **Keep P held** unless new identity evidence is supplied. Do not revive workflow-only linking. | 333 | Highest risk if relaxed (identity) | Keep current rule |
| 6 | **Keep C, LB, F, A, L held**; they need new pre-cutoff or field evidence. | 134 + 21 | Correct as is | Keep current rule |
| 7 | **Proceed with Stage 10** (evaluator and metrics) whatever the outcome above. It measures and does not depend on these decisions. | — | No production effect | Next stage, when authorized |

---

## 9. Case IDs by exact blocker set (evaluation inputs)

Code letters as in §3. Each case appears once.

**P** — 96 cases (VERIFICATION_SET_INCOMPLETE 56, REQUIRED_RESOURCE_UNRESOLVED 40)

case_48, case_49, case_96, case_97, case_98, case_99, case_101, case_127, case_144, case_145, case_146, case_147, case_149, case_150, case_151, case_152, case_175, case_178, case_183, case_184, case_185, case_186, case_188, case_190, case_191, case_192, case_194, case_197, case_200, case_225, case_226, case_231, case_243, case_244, case_245, case_248, case_250, case_252, case_274, case_276, case_277, case_284, case_288, case_289, case_290, case_291, case_293, case_294, case_295, case_296, case_297, case_298, case_299, case_300, case_301, case_302, case_343, case_344, case_345, case_346, case_348, case_349, case_350, case_352, case_393, case_394, case_395, case_396, case_397, case_398, case_399, case_400, case_401, case_402, case_423, case_424, case_427, case_444, case_445, case_446, case_447, case_448, case_449, case_450, case_451, case_452, case_493, case_494, case_495, case_496, case_497, case_500, case_502, case_524, case_530, case_532

**P+R** — 96 cases (VERIFICATION_SET_INCOMPLETE 63, REQUIRED_RESOURCE_UNRESOLVED 33)

case_54, case_56, case_58, case_59, case_60, case_62, case_103, case_104, case_106, case_107, case_108, case_109, case_110, case_111, case_154, case_156, case_157, case_158, case_159, case_160, case_161, case_162, case_203, case_205, case_206, case_207, case_208, case_209, case_210, case_212, case_253, case_254, case_255, case_256, case_257, case_258, case_260, case_262, case_303, case_304, case_305, case_306, case_309, case_310, case_311, case_312, case_353, case_354, case_356, case_358, case_359, case_360, case_361, case_362, case_403, case_404, case_406, case_407, case_408, case_409, case_410, case_411, case_412, case_454, case_455, case_456, case_457, case_458, case_459, case_460, case_461, case_462, case_473, case_474, case_476, case_478, case_479, case_481, case_482, case_503, case_504, case_505, case_506, case_507, case_508, case_509, case_510, case_512, case_543, case_544, case_545, case_546, case_547, case_548, case_549, case_550

**C+P** — 92 cases (VERIFICATION_SET_INCOMPLETE 74, REQUIRED_RESOURCE_UNRESOLVED 18)

case_35, case_39, case_50, case_52, case_53, case_55, case_64, case_65, case_66, case_68, case_69, case_70, case_71, case_72, case_74, case_75, case_116, case_120, case_122, case_123, case_124, case_125, case_126, case_128, case_131, case_132, case_168, case_169, case_171, case_173, case_174, case_176, case_181, case_182, case_213, case_214, case_215, case_216, case_217, case_218, case_219, case_220, case_221, case_224, case_228, case_229, case_230, case_232, case_236, case_240, case_241, case_242, case_275, case_278, case_279, case_280, case_281, case_282, case_315, case_316, case_317, case_318, case_320, case_321, case_325, case_329, case_332, case_334, case_335, case_336, case_337, case_338, case_339, case_340, case_341, case_342, case_373, case_377, case_425, case_426, case_428, case_432, case_466, case_468, case_469, case_471, case_472, case_485, case_488, case_528, case_529, case_531

**R** — 66 cases (VERIFICATION_SET_INCOMPLETE 54, REQUIRED_RESOURCE_UNRESOLVED 12)

case_36, case_37, case_38, case_83, case_84, case_85, case_86, case_87, case_92, case_105, case_133, case_135, case_137, case_139, case_141, case_153, case_211, case_259, case_261, case_265, case_266, case_267, case_268, case_271, case_272, case_307, case_355, case_357, case_363, case_364, case_366, case_368, case_369, case_371, case_372, case_383, case_384, case_385, case_387, case_391, case_392, case_405, case_413, case_414, case_415, case_416, case_417, case_420, case_421, case_422, case_433, case_435, case_439, case_440, case_441, case_453, case_475, case_477, case_511, case_513, case_515, case_516, case_517, case_518, case_519, case_521

**C+P+S** — 24 cases (VERIFICATION_SET_INCOMPLETE 21, REQUIRED_RESOURCE_UNRESOLVED 3)

case_76, case_78, case_114, case_118, case_119, case_130, case_166, case_172, case_179, case_180, case_222, case_227, case_234, case_328, case_330, case_376, case_382, case_431, case_483, case_484, case_490, case_492, case_526, case_527

**R+S** — 18 cases (VERIFICATION_SET_INCOMPLETE 14, REQUIRED_RESOURCE_UNRESOLVED 4)

case_40, case_41, case_42, case_88, case_136, case_138, case_142, case_269, case_270, case_365, case_367, case_370, case_418, case_436, case_442, case_514, case_520, case_522

**C** — 16 cases (VERIFICATION_SET_INCOMPLETE 16, REQUIRED_RESOURCE_UNRESOLVED 0)

case_67, case_115, case_129, case_163, case_177, case_223, case_237, case_273, case_333, case_379, case_381, case_429, case_465, case_489, case_523, case_525

**P+S** — 15 cases (VERIFICATION_SET_INCOMPLETE 14, REQUIRED_RESOURCE_UNRESOLVED 1)

case_47, case_94, case_95, case_100, case_102, case_143, case_148, case_198, case_246, case_251, case_287, case_347, case_351, case_443, case_498

**S** — 12 cases (VERIFICATION_SET_INCOMPLETE 1, REQUIRED_RESOURCE_UNRESOLVED 11)

case_44, case_51, case_77, case_81, case_82, case_201, case_233, case_235, case_292, case_324, case_326, case_331

**LB+R+S** — 8 cases (VERIFICATION_SET_INCOMPLETE 8, REQUIRED_RESOURCE_UNRESOLVED 0)

case_90, case_91, case_134, case_140, case_386, case_388, case_434, case_438

**F+P+R** — 6 cases (VERIFICATION_SET_INCOMPLETE 0, REQUIRED_RESOURCE_UNRESOLVED 6)

case_57, case_112, case_155, case_204, case_308, case_480

**N+P** — 3 cases (VERIFICATION_SET_INCOMPLETE 0, REQUIRED_RESOURCE_UNRESOLVED 3)

case_33, case_61, case_63

**LB+R** — 3 cases (VERIFICATION_SET_INCOMPLETE 2, REQUIRED_RESOURCE_UNRESOLVED 1)

case_89, case_389, case_437

**A+R** — 2 cases (VERIFICATION_SET_INCOMPLETE 1, REQUIRED_RESOURCE_UNRESOLVED 1)

case_34, case_419

**C+S** — 2 cases (VERIFICATION_SET_INCOMPLETE 2, REQUIRED_RESOURCE_UNRESOLVED 0)

case_165, case_487

**P+U** — 1 cases (VERIFICATION_SET_INCOMPLETE 0, REQUIRED_RESOURCE_UNRESOLVED 1)

case_45

**N** — 1 cases (VERIFICATION_SET_INCOMPLETE 0, REQUIRED_RESOURCE_UNRESOLVED 1)

case_46

**A+R+S** — 1 cases (VERIFICATION_SET_INCOMPLETE 1, REQUIRED_RESOURCE_UNRESOLVED 0)

case_263

**N+R+S** — 1 cases (VERIFICATION_SET_INCOMPLETE 0, REQUIRED_RESOURCE_UNRESOLVED 1)

case_264

**L+R+S** — 1 cases (VERIFICATION_SET_INCOMPLETE 0, REQUIRED_RESOURCE_UNRESOLVED 1)

case_390


---

## 10. Open decisions raised (none decided here)

- **X-HELD-MAPPING:** already open; the first full measurement is now available.
- **X-MEDIA-TRANSMISSION:** already open; scope sized in §5.
- **R for INCOMPLETE future checks** (§4.2): new; would revise Q-RETENTION-UNOBSERVED and Q-VERIFICATION-SET-INCOMPLETE.
- **rule_05 interpretation and FALSE branch** (§4.4): new.
- **X-SORT-CONFIRM:** unchanged.
