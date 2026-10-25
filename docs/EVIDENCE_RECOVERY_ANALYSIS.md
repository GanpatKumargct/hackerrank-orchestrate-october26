# Evidence-Recovery Feasibility Analysis — held cases of run `runs/20261025T024207Z`

**Read-only. Prepared 2026-10-25 for the project owner's review before Stage 10.**

This builds on `docs/HELD_CASE_ANALYSIS.md`. That report looked at what the pipeline concluded. This one goes beneath the pipeline: it re-reads the **raw evidence files** and checks whether any blocker could be cleared from evidence already in the repository, without changing an approved rule.

Nothing was modified: no production code, tests, dataset, evidence, staged run files, `.gitignore` or root `output.csv`. No network call was made and no screenshot was transmitted.

**Labels:**

- **[VERIFIED]** — measured on the repository's data.
- **[HYPOTHESIS]** — plausible, but not proven by evidence.
- **[RECOMMENDATION]** — a proposed next step. It is not a decision and has not been implemented.

---

## 0. Answer

**[VERIFIED] No held case is demonstrably resolvable from existing evidence under the current approved rules.** All 464 stay held.

- **Indexing is not what holds these cases back.** The raw corpus and the observation index agree on 2 507 of 2 508 (resource ID, file) pairs. The one unindexed pair belongs to no held case.
- **Three parser or labelling gaps were found.** None of them would unblock a case on its own (§3.7):
  - **G1** — a noise-filtered log line;
  - **G2** — a PDF "retain until" date that is extracted but not recognised as a retention field (case_45);
  - **G3** — a misleading reason label on `backup_3250` (case_264).
- **What remains needs new evidence or an owner decision** (§5): the identity basis for P, retention evidence for R, pre-cutoff evidence for C, the rule_05 interpretation for S, and screenshot reading (X-MEDIA-TRANSMISSION).

---

## 1. Method and integrity

- **Inputs:**
  - `docs/HELD_CASE_ANALYSIS.md`, the Stage 9 run files and `docs/IMPLEMENTATION_PLAN.md`;
  - every participant evidence file except the 11 PNGs (unreadable without transmission) — that is 24 SQL, 28 JSON, 26 log, 1 TXT and 4 PDF files.
- **Raw corpus:**
  - SQL, log and TXT files were read line by line.
  - JSON files were parsed and walked down to each record dict.
  - PDFs were read through the existing stdlib decoder, page by page.
- **Comparisons.** The raw corpus was compared with the existing `ObservationIndex`, scope builder, identity resolver and Stage 7 assessments. The pipeline ran **in memory only**, from scratchpad scripts outside the repository.
- **The staging writer was not run.**
- **Integrity [VERIFIED].** The SHA-256 of the five files in `runs/20261025T024207Z/` was recorded before the analysis and re-checked after it: all unchanged (§7).
- **Identifiers only.** Raw text was masked for email addresses and phone numbers before any output was inspected. Names and addresses seen in two PDFs are not reproduced here.

---

## 2. Summary of the 464 held cases (overlapping classes)

| Class | Root cause | Cases touched | Only blocker in |
|---|---|---|---|
| **P** | Primary-account slot empty | 333 | 96 |
| **R** | Audit-record retention period not observed (rule_12) | 202 | 66 |
| **C** | Member observed only in files captured after `audit_at` | 134 | 16 |
| **S** | Support message: shared context not evidenced (rule_05) | 82 | 12 |
| LB | Analytics handover label only | 11 | 0 |
| F | Support message: requester slots not all observed | 6 | 0 |
| N | No admissible observation | 5 | 1 |
| A | Support attachment: owner not observed (rule_06) | 3 | 0 |
| L | Legal hold: retained-until not observed (rule_13) | 1 | 0 |
| U | Category ungrounded / owner ambiguous | 1 | 0 |

**The "cases touched" column overlaps** (it sums to 778). The exact combinations, with each case counted once, are in `docs/HELD_CASE_ANALYSIS.md` §3.1 and §9. Gate reasons: `VERIFICATION_SET_INCOMPLETE` 327, `REQUIRED_RESOURCE_UNRESOLVED` 137.

---

## 3. Per class: available evidence, missing evidence, parser gaps, resolvability

### 3.1 P — primary account out of scope (333 cases)

**[VERIFIED] Evidence available:**

1. **Raw records.** 716 raw records (lines or record dicts) name an `account_*` resource. For each P case, these were searched for any identifier of the subject known at `audit_at`: email, hash, phone or `user_id`.
   - 301 cases: no raw record contains both a subject identifier and an account ID.
   - 32 cases: such a record exists only in **late-captured** files. In 28 of them the account is already in scope (and therefore C, see §3.3). In 4 it is not a candidate, because those records' inner times are after the cutoff.
2. **Indexed hits through the resolver** (including `TRACE_KEY`). There is no state-admissible account observation attributable to the subject in any P case.
   - 262 cases: no attributable account observation at any time.
   - 61 cases: attributable observations are link-only (late file, inner time ≤ cutoff); the account is in scope but its state is unknown.
   - 10 cases: attributable observations exist, but their inner time is after the cutoff (inadmissible).
3. **Claims.** The remaining account candidates come from `deletion_worker` claims ("submitted primary profile `<id>` to account_service", 532 activities). These carry no identifier, and each is shared by 3–14 claimant cases. Q-WEAK-VERIFY = No excludes them, and this analysis does not weaken that.

**Evidence missing:** an admissible, pre-cutoff observation that ties any account of these subjects to the subject through a C.5 link.

**Parser/indexing gaps:** none affecting P. Raw and index agree.

**Resolution without changing approved rules:** **not possible.**

**P subgroups (by account candidates):**

| Subgroup | Cases |
|---|---|
| P1a — shared-claim accounts with zero observations | 204 |
| P1b — shared-claim accounts, one with an identifier-free observation | 65 |
| P2 — account in scope only through a late-captured link | 61 |
| P3 — no account candidate | 3 |

Case IDs for each subgroup are in §6.

### 3.2 R — audit retention not observed (202 cases, 202 records)

**[VERIFIED] Evidence available:**

- **None of the 202 records' own raw records** contains a retention-like token (`retain`, `retention`, `until`, `expir`, `purge`) in any file, pre- or post-cutoff.
- These evidence schemas have no such column. For example, there are handover rows (`actor_type`, `event_name`, `integrity_seal`, `subject_reference`) and readback lines (`integrity_check`, `rows`).
- `retention_until` does exist elsewhere: in the `security_audit_records` tables of evidence_63, 66, 69 … 93, in readback lines of evidence_64, 70, 73 … 94, and in JSON exports. Those cover **other** audit records.
- **No document anywhere states a retention schedule or period** (no "retention period/schedule/policy", "retain for N", or "N years" phrase). So a period cannot be "supplied" from which a date could be computed.

**Evidence missing:** a retention date or a supplied retention period for each of the 202 records.

**Parser/indexing gaps:** none for these 202. For the related gap G2 on `audit_record_003`, see §3.7.

**Resolution without changing approved rules:** **not possible** (Q-RETENTION-UNOBSERVED is strict). Presence and sample answers were not used to infer dates.

### 3.3 C — post-cutoff-only members (134 cases, 185 members)

**[VERIFIED] Evidence available:**

- All 185 members are mentioned **only** in files captured after the case's `audit_at`. There is no pre-cutoff raw mention in any file.
- The earliest late capture is ≥ 47.9 h after the cutoff. For 177 members the inner event time is ≤ cutoff (link-only under Q-LATE-LINK); for 8 it is later.

**Evidence missing:** any pre-cutoff observation of the member.

**Parser gaps:** none.

**Resolution:** **not possible.** Q-LATE-LINK forbids late evidence as proof of state or category, and capture time and inner time stay distinct.

### 3.4 S — support shared context (82 cases, 83 members)

**[VERIFIED] Evidence available:**

- **Own raw records, pre-cutoff.** 79 members contain **no** shared-context marker of any kind: no `ticket_id`, order reference, `CS-` reference, or the words agent, order, delivery, parcel, shipment, receipt, thread, participant or cc.
- **The 4 "delivery" hits are not context.** For support_3364, support_165, support_6688 and support_4123 (cases 434, 436, 438, 442), the word appears only in the reporting service name `downstream_delivery_service`, not in message content.
- **The "account access" excerpt.** 22 of the 87 distinct support resources carry only "Customer contacted support about account access." Under the Stage 7 decision, this phrase is not added to the word list without validated meaning.
- **[HYPOTHESIS]** The phrase describes a single customer's own issue. It is not shared customer, agent or order context.

**Evidence missing:** message content or fields showing shared context.

**Parser gaps:** none. The excerpts and fields are fully extracted.

**Resolution without changing approved rules:** **not possible.** The word list stays conservative.

### 3.5 PNG gaps and ambiguous resources

**[VERIFIED]**

- Each of the 12 catalog claims (`LINK_RESOURCE_IDENTITY`) follows a same-system capture by 7 min 1 s: 11 PNGs, plus the evidence_18 PDF.
- The local alternative evidence for the paired resources is:
  - **Six paired resources** (search_428, data_flow_1121, analytics_7438, export_1260, support_1034, backup_9287 — cases 35, 39, 50, 52, 53, 55) appear only in evidence_01 or evidence_02. Those files were captured on 09-15 and 09-17, **after** each case's cutoff, so they are link-only.
  - **Four catalog-claim resources** (export_1842, tombstone_17, object_19, marketing_001 — cases 33, 46, 61, 63) appear in **no** raw file at all.
  - **evidence_18** (the PDF paired with export_1842) holds a customer statement with no resource ID.
  - **account_5762** (case_34) has pre-cutoff evidence in evidence_01. case_34 is held for A+R, not for its account.
- **audit_record_003** (case_45): see G2 in §3.7. Its owner system is still not stated anywhere, so the owner ambiguity is kept.

**[HYPOTHESIS]** Each screenshot shows its paired resource.

The cases each PNG could affect are listed without assuming any content:

| PNG | Paired resource | Case | Other blockers in that case | Could media alone unblock it? |
|---|---|---|---|---|
| evidence_04 | account_5762 | case_34 | A, R | No |
| evidence_09 | search_428 | case_35 | C, P | No |
| evidence_14 | data_flow_1121 | case_39 | C, P | No |
| evidence_19 | analytics_7438 | case_50 | C, P | No |
| evidence_23 | export_1260 | case_52 | C, P | No |
| evidence_28 | support_1034 | case_53 | C, P | No |
| evidence_32 | backup_9287 | case_55 | C, P | No |
| evidence_37 | audit_record_003 | case_45 | P, U | No |
| evidence_42 | tombstone_17 | case_46 | N only | **Possibly**, if the image proves state |
| evidence_46 | object_19 | case_61 | N, P | No |
| evidence_60 | marketing_001 | case_63 | N, P | No |

Screenshot transmission stays unauthorized (X-MEDIA-TRANSMISSION open).

### 3.6 Other classes

| Class | Case (resource) | Verified evidence | Missing | Type |
|---|---|---|---|---|
| LB | 89–91 (evidence_08), 134, 140 (evidence_13), 386, 388, 389 (evidence_36), 434, 437, 438 (evidence_41) | Handover rows: `record_type`, `result` label, `subject_reference` only | Slot content | Genuinely missing |
| F | 57, 112, 155, 204, 308, 480 | `ticket_id` present (so the condition is evidenced) | Not every requester slot observed | Genuinely missing |
| A | 34 (support_9538), 263 (support_5234), 419 (support_2944) | PII-scan lines: `file`, `detector`, `matched_value` | Owner/uploader field | Genuinely missing (matched_value is not an owner, Q-IDENTIFYING-FIELDS) |
| L | 390 (legal_hold_8049) | Handover row: FOUND, `subject_reference` | `retained_until` | Genuinely missing. The evidence_27 register lists retain-until dates only for six orders of other users, with no resource IDs. |
| N | 264 (backup_3250) | Admissible `restore_authorization_completed decision=deny` (captured 09:58, cutoff 10:00) | A restore-state reading | Approved rule: deny alone is insufficient (Q-RESTORE-AUTH-SIGNAL). See G3. |
| N | 33, 46, 61, 63 | Catalog claim only | Any observation | Missing locally; media-dependent |
| U | 45 (audit_record_003) | evidence_55 PDF | Category signal; owner system | See G2 |

### 3.7 Parser, indexing and labelling gaps found

| ID | Gap | Where | Effect on held cases |
|---|---|---|---|
| G1 | A `thumbnail_failed` ERROR line from `attachment_preview` naming `support_7731` is not indexed (noise service). It is the only raw (resource, file) pair missing from the index. | evidence_61 line 7 | None: support_7731 is in no case's scope |
| G2 | The PDF parser extracts "retain until" as the field `event_time.retain until`, but Stage 7 reads only `retention_until`. The document also gives no category signal ("Compliance journal", "Event reference") and no owner system. | evidence_55 → audit_record_003, case_45 | **None alone.** Category and owner stay unresolved (owner ambiguity kept by instruction), and case_45 is also blocked by P. |
| G3 | The reason code `NO_ADMISSIBLE_OBSERVATION` is reported where the true cause is "admissible observation, but no restore-state reading" (deny-only). The verdict is correct; the label is imprecise. | backup_3250, case_264 | None: a reporting clarity issue only |

---

## 4. Explicit confirmation

**[VERIFIED]** Under the current approved rules (Q-WEAK-VERIFY, Q-LATE-LINK, Q-RETENTION-UNOBSERVED, Q-SPLIT-PROOF, Q-SHARED-CONTEXT-WORDS, Q-RESTORE-AUTH-SIGNAL, Q-IDENTIFYING-FIELDS, the owner-ambiguity instruction and the cutoff rules), **0 of the 464 held cases** can be resolved from evidence already in the repository.

Fixing G1–G3 would change **0** case outcomes:

- G1 touches no case.
- G2 leaves case_45 blocked by P, its category and its owner.
- G3 is a label change only.

---

## 5. Decisions and external evidence still required

| Item | What is needed | Cases that depend on it | Kind |
|---|---|---|---|
| X-HELD-MAPPING | How to proceed when cases stay held, since no compliant 518-row `output.csv` can exist (A.8.3) | all 464 | Owner decision (open) |
| X-MEDIA-TRANSMISSION | Authorization to read the 11 PNGs, or an approved human-transcription route into the hash-pinned cache | 11 cases directly (§3.5); only case_46 could become unblocked by media alone | External / owner decision (open) |
| Identity evidence for P | Pre-cutoff, identifier-bearing account evidence. Not obtainable locally. | 333 | New evidence |
| Retention for R | A retention date or a supplied period per record | 202 | New evidence, or an owner decision on R for INCOMPLETE future checks (raised in HELD_CASE_ANALYSIS §4.2) |
| Pre-cutoff evidence for C | Any pre-cutoff observation | 134 | New evidence |
| rule_05 interpretation for S | Per-record condition vs category-level REDACT, and the FALSE branch | 82 | Owner decision |
| LB, F, A, L | Slot content, requester slots, owner field, hold date | 21 | New evidence |
| X-SORT-CONFIRM | Organizer confirmation of numeric order | — | External (open) |

---

## 6. Case IDs by class (evaluation inputs; classes overlap)

**P — primary account slot** — 333 cases

case_33, case_35, case_39, case_45, case_47, case_48, case_49, case_50, case_52, case_53, case_54, case_55, case_56, case_57, case_58, case_59, case_60, case_61, case_62, case_63, case_64, case_65, case_66, case_68, case_69, case_70, case_71, case_72, case_74, case_75, case_76, case_78, case_94, case_95, case_96, case_97, case_98, case_99, case_100, case_101, case_102, case_103, case_104, case_106, case_107, case_108, case_109, case_110, case_111, case_112, case_114, case_116, case_118, case_119, case_120, case_122, case_123, case_124, case_125, case_126, case_127, case_128, case_130, case_131, case_132, case_143, case_144, case_145, case_146, case_147, case_148, case_149, case_150, case_151, case_152, case_154, case_155, case_156, case_157, case_158, case_159, case_160, case_161, case_162, case_166, case_168, case_169, case_171, case_172, case_173, case_174, case_175, case_176, case_178, case_179, case_180, case_181, case_182, case_183, case_184, case_185, case_186, case_188, case_190, case_191, case_192, case_194, case_197, case_198, case_200, case_203, case_204, case_205, case_206, case_207, case_208, case_209, case_210, case_212, case_213, case_214, case_215, case_216, case_217, case_218, case_219, case_220, case_221, case_222, case_224, case_225, case_226, case_227, case_228, case_229, case_230, case_231, case_232, case_234, case_236, case_240, case_241, case_242, case_243, case_244, case_245, case_246, case_248, case_250, case_251, case_252, case_253, case_254, case_255, case_256, case_257, case_258, case_260, case_262, case_274, case_275, case_276, case_277, case_278, case_279, case_280, case_281, case_282, case_284, case_287, case_288, case_289, case_290, case_291, case_293, case_294, case_295, case_296, case_297, case_298, case_299, case_300, case_301, case_302, case_303, case_304, case_305, case_306, case_308, case_309, case_310, case_311, case_312, case_315, case_316, case_317, case_318, case_320, case_321, case_325, case_328, case_329, case_330, case_332, case_334, case_335, case_336, case_337, case_338, case_339, case_340, case_341, case_342, case_343, case_344, case_345, case_346, case_347, case_348, case_349, case_350, case_351, case_352, case_353, case_354, case_356, case_358, case_359, case_360, case_361, case_362, case_373, case_376, case_377, case_382, case_393, case_394, case_395, case_396, case_397, case_398, case_399, case_400, case_401, case_402, case_403, case_404, case_406, case_407, case_408, case_409, case_410, case_411, case_412, case_423, case_424, case_425, case_426, case_427, case_428, case_431, case_432, case_443, case_444, case_445, case_446, case_447, case_448, case_449, case_450, case_451, case_452, case_454, case_455, case_456, case_457, case_458, case_459, case_460, case_461, case_462, case_466, case_468, case_469, case_471, case_472, case_473, case_474, case_476, case_478, case_479, case_480, case_481, case_482, case_483, case_484, case_485, case_488, case_490, case_492, case_493, case_494, case_495, case_496, case_497, case_498, case_500, case_502, case_503, case_504, case_505, case_506, case_507, case_508, case_509, case_510, case_512, case_524, case_526, case_527, case_528, case_529, case_530, case_531, case_532, case_543, case_544, case_545, case_546, case_547, case_548, case_549, case_550

**R — audit retention not observed** — 202 cases

case_34, case_36, case_37, case_38, case_40, case_41, case_42, case_54, case_56, case_57, case_58, case_59, case_60, case_62, case_83, case_84, case_85, case_86, case_87, case_88, case_89, case_90, case_91, case_92, case_103, case_104, case_105, case_106, case_107, case_108, case_109, case_110, case_111, case_112, case_133, case_134, case_135, case_136, case_137, case_138, case_139, case_140, case_141, case_142, case_153, case_154, case_155, case_156, case_157, case_158, case_159, case_160, case_161, case_162, case_203, case_204, case_205, case_206, case_207, case_208, case_209, case_210, case_211, case_212, case_253, case_254, case_255, case_256, case_257, case_258, case_259, case_260, case_261, case_262, case_263, case_264, case_265, case_266, case_267, case_268, case_269, case_270, case_271, case_272, case_303, case_304, case_305, case_306, case_307, case_308, case_309, case_310, case_311, case_312, case_353, case_354, case_355, case_356, case_357, case_358, case_359, case_360, case_361, case_362, case_363, case_364, case_365, case_366, case_367, case_368, case_369, case_370, case_371, case_372, case_383, case_384, case_385, case_386, case_387, case_388, case_389, case_390, case_391, case_392, case_403, case_404, case_405, case_406, case_407, case_408, case_409, case_410, case_411, case_412, case_413, case_414, case_415, case_416, case_417, case_418, case_419, case_420, case_421, case_422, case_433, case_434, case_435, case_436, case_437, case_438, case_439, case_440, case_441, case_442, case_453, case_454, case_455, case_456, case_457, case_458, case_459, case_460, case_461, case_462, case_473, case_474, case_475, case_476, case_477, case_478, case_479, case_480, case_481, case_482, case_503, case_504, case_505, case_506, case_507, case_508, case_509, case_510, case_511, case_512, case_513, case_514, case_515, case_516, case_517, case_518, case_519, case_520, case_521, case_522, case_543, case_544, case_545, case_546, case_547, case_548, case_549, case_550

**C — post-cutoff-only member** — 134 cases

case_35, case_39, case_50, case_52, case_53, case_55, case_64, case_65, case_66, case_67, case_68, case_69, case_70, case_71, case_72, case_74, case_75, case_76, case_78, case_114, case_115, case_116, case_118, case_119, case_120, case_122, case_123, case_124, case_125, case_126, case_128, case_129, case_130, case_131, case_132, case_163, case_165, case_166, case_168, case_169, case_171, case_172, case_173, case_174, case_176, case_177, case_179, case_180, case_181, case_182, case_213, case_214, case_215, case_216, case_217, case_218, case_219, case_220, case_221, case_222, case_223, case_224, case_227, case_228, case_229, case_230, case_232, case_234, case_236, case_237, case_240, case_241, case_242, case_273, case_275, case_278, case_279, case_280, case_281, case_282, case_315, case_316, case_317, case_318, case_320, case_321, case_325, case_328, case_329, case_330, case_332, case_333, case_334, case_335, case_336, case_337, case_338, case_339, case_340, case_341, case_342, case_373, case_376, case_377, case_379, case_381, case_382, case_425, case_426, case_428, case_429, case_431, case_432, case_465, case_466, case_468, case_469, case_471, case_472, case_483, case_484, case_485, case_487, case_488, case_489, case_490, case_492, case_523, case_525, case_526, case_527, case_528, case_529, case_531

**S — support shared context not evidenced** — 82 cases

case_40, case_41, case_42, case_44, case_47, case_51, case_76, case_77, case_78, case_81, case_82, case_88, case_90, case_91, case_94, case_95, case_100, case_102, case_114, case_118, case_119, case_130, case_134, case_136, case_138, case_140, case_142, case_143, case_148, case_165, case_166, case_172, case_179, case_180, case_198, case_201, case_222, case_227, case_233, case_234, case_235, case_246, case_251, case_263, case_264, case_269, case_270, case_287, case_292, case_324, case_326, case_328, case_330, case_331, case_347, case_351, case_365, case_367, case_370, case_376, case_382, case_386, case_388, case_390, case_418, case_431, case_434, case_436, case_438, case_442, case_443, case_483, case_484, case_487, case_490, case_492, case_498, case_514, case_520, case_522, case_526, case_527

**LB — analytics label only** — 11 cases

case_89, case_90, case_91, case_134, case_140, case_386, case_388, case_389, case_434, case_437, case_438

**F — support slot coverage incomplete** — 6 cases

case_57, case_112, case_155, case_204, case_308, case_480

**N — no admissible observation** — 5 cases

case_33, case_46, case_61, case_63, case_264

**A — attachment owner not observed** — 3 cases

case_34, case_263, case_419

**L — legal-hold date not observed** — 1 cases

case_390

**U — category ungrounded / owner ambiguous** — 1 cases

case_45

**P subgroups**

- P1a shared-claim accounts with zero observations — 204: case_39, case_45, case_47, case_48, case_49, case_53, case_55, case_56, case_57, case_58, case_59, case_60, case_61, case_62, case_74, case_75, case_76, case_78, case_94, case_98, case_99, case_100, case_101, case_102, case_103, case_104, case_106, case_107, case_108, case_109, case_123, case_124, case_125, case_127, case_128, case_130, case_131, case_132, case_143, case_144, case_145, case_146, case_147, case_148, case_154, case_155, case_158, case_159, case_160, case_161, case_162, case_179, case_180, case_181, case_182, case_185, case_186, case_194, case_197, case_198, case_200, case_203, case_204, case_205, case_206, case_207, case_208, case_209, case_210, case_212, case_227, case_228, case_229, case_230, case_231, case_232, case_243, case_244, case_245, case_246, case_248, case_250, case_251, case_252, case_253, case_254, case_255, case_256, case_257, case_258, case_260, case_262, case_278, case_279, case_280, case_281, case_282, case_284, case_293, case_294, case_295, case_296, case_297, case_298, case_299, case_300, case_301, case_303, case_304, case_305, case_306, case_308, case_309, case_310, case_311, case_312, case_325, case_328, case_329, case_330, case_332, case_347, case_348, case_349, case_353, case_354, case_356, case_358, case_359, case_360, case_361, case_362, case_373, case_376, case_377, case_382, case_393, case_394, case_395, case_396, case_398, case_399, case_401, case_402, case_403, case_404, case_406, case_407, case_408, case_409, case_410, case_411, case_428, case_431, case_432, case_443, case_444, case_445, case_446, case_447, case_448, case_449, case_450, case_451, case_452, case_454, case_455, case_456, case_457, case_458, case_459, case_460, case_461, case_462, case_473, case_474, case_476, case_478, case_479, case_480, case_481, case_482, case_493, case_494, case_495, case_496, case_497, case_500, case_502, case_503, case_504, case_505, case_506, case_507, case_508, case_509, case_510, case_512, case_527, case_528, case_529, case_543, case_544, case_545
- P1b shared-claim accounts; one has an identifier-free observation — 65: case_35, case_52, case_54, case_95, case_96, case_97, case_110, case_111, case_112, case_149, case_150, case_151, case_152, case_156, case_157, case_173, case_174, case_175, case_176, case_178, case_183, case_184, case_188, case_190, case_191, case_192, case_224, case_225, case_226, case_274, case_275, case_276, case_277, case_287, case_288, case_289, case_290, case_291, case_302, case_343, case_344, case_345, case_346, case_350, case_351, case_352, case_397, case_400, case_412, case_423, case_424, case_425, case_426, case_427, case_498, case_524, case_526, case_530, case_531, case_532, case_546, case_547, case_548, case_549, case_550
- P2 account in scope only via late-captured link (POST_CUTOFF_ONLY) — 61: case_64, case_65, case_66, case_68, case_69, case_70, case_71, case_72, case_114, case_116, case_118, case_119, case_120, case_122, case_126, case_166, case_168, case_169, case_171, case_172, case_213, case_214, case_215, case_216, case_217, case_218, case_219, case_220, case_221, case_222, case_234, case_236, case_240, case_241, case_242, case_315, case_316, case_317, case_318, case_320, case_321, case_334, case_335, case_336, case_337, case_338, case_339, case_340, case_341, case_342, case_466, case_468, case_469, case_471, case_472, case_483, case_484, case_485, case_488, case_490, case_492
- P3 no account candidate — 3: case_33, case_50, case_63

---

## 7. Recommended next actions (ranked by safety, then likely impact)

| # | Recommendation | Safety | Likely impact |
|---|---|---|---|
| 1 | **[RECOMMENDATION] Decide X-HELD-MAPPING.** Evidence recovery cannot reduce the held count, so this decision determines whether any `output.csv` can exist. | Decision only | All 464 |
| 2 | **[RECOMMENDATION] Decide X-MEDIA-TRANSMISSION**, or approve a human-transcription route into the hash-pinned media cache. This adds evidence without relaxing any rule. | High | Small: 11 cases touched; at most case_46 unblocked by media alone |
| 3 | **[RECOMMENDATION] Fix G3 (label) and record G2 as a known parser limitation.** The G2 field-name mapping (`event_time.retain until` → retention date) would need its own approval and tests. It changes no outcome now. | High (no outcome change) | Report accuracy only |
| 4 | **[RECOMMENDATION] Take the owner decisions already raised:** R for INCOMPLETE future checks; the rule_05 interpretation. These are rule changes with compliance trade-offs (`HELD_CASE_ANALYSIS.md` §4.2, §4.4). They are not evidence recovery. | Medium | R: up to 66 solely; S: up to 12 solely |
| 5 | **[RECOMMENDATION] Keep P, C, LB, F, A and L held.** No local evidence exists for them, and relaxing identity or cutoff rules would risk false findings or false COMPLETEs. | Highest (no change) | — |
| 6 | **[RECOMMENDATION] Stage 10** (evaluator and metrics) can proceed independently once authorized. | No production effect | Measurement |

---

## 8. Integrity record

SHA-256 of `runs/20261025T024207Z/` files, before and after this analysis (identical):

```text
9a436b18df28c8b1ce57b720e41433485df8a9195cf927dd3504ed22cc10c5d1  held_cases.json
f1dc6d97ee42acef5bb6741ff8f1dbb5da2916d5f4f216fa59b5ee100ce39de1  held_report.md
0887682a5e9e3c459614d344f491391d44c04c2e71a1f3187cbbfcd8f3c7682a  run_summary.json
3faa4d3a45535274ae1e36eea9ca45f0d785538a4454550b02ba681ae07e0c24  staging_output.partial.csv
8bd16ae6ba7ddd1f0c85e9ca222e57b2bb09ce14e3bf84804600587c5bc29a15  validation_report.md
```
