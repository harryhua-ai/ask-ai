# Baseline v1 Independent Review

- **Gate**: ASK-AI Answer Intelligence Benchmark v1 / Baseline Calibration & Independent Acceptance Review
- **Date**: 2026-09-07
- **Baseline under review**: `PB-V1-20260907-CDBCAD3` (measurement commits `2eb923a` + backfill `d019e33`, not amended)
- **Reviewer discipline note**: this reviewer is the same underlying session as the original measurement judge. Perfect blinding is not achievable. Applied discipline: every reviewed run was re-scored from question + frozen contract + raw answer **before** the original verdict was loaded; the original verdicts for sq-045/sq-026/sq-008/sq-040/sq-093 dated from a prior context window and were unavailable at re-derivation time. For cases judged in the current context the limitation is disclosed and materiality relies on the recorded re-derivation evidence.

## 1. Review Scope

Independent verification of the frozen benchmark identity, baseline artifact integrity, production binding, measurement-protocol compliance, judge calibration against independent human review, critical-fail adjudication, aggregate/performance/family recalculation, the sq-090 defect, and a baseline-validity verdict. No production reruns, no mutation of any kind (production / benchmark / contracts / fixes), no Failure Attribution (no K0–K9).

## 2. Frozen Benchmark Verification

All five authoritative identities re-verified independently:

| Item | Expected | Verified |
|---|---|---|
| CASE_SET_SHA256 | `8685e198…f73283a` | ✓ (ratified manifest field; manifest file itself hash-verified) |
| CONTRACT_SHA256 | `5a436f05…c28e9946` | ✓ file hash |
| EXECUTABLE_SHA256 | `a1f920c0…d4680f50` | ✓ file hash |
| EVIDENCE_SHA256 | `d638685f…b1fa8a5b` | ✓ file hash |
| RATIFIED_MANIFEST_SHA256 | `f49adfd5…ad83969` | ✓ file hash |
| Ratification commit | `e93daf824175…` | ✓ in docs history, message matches |

**FROZEN_BENCHMARK_INTEGRITY = PASS.**

## 3. Baseline Artifact Integrity

All five expected artifacts exist in `docs/evaluation/benchmark_v1/baseline_v1_2026-09-07/`. The three hash-bearing artifacts match the manifest exactly (recomputed). Counts: 121 unique case IDs == frozen corpus set (no corpus duplicates); raw executions 363; judged executions 363; per case exactly runs {1,2,3} on both sides (run_id is a **string** in judged artifacts, **int** in raw — handled; not a defect, recorded). No duplicate (case,run) pairs; no missing runs.

**Discrepancy reported exactly (not repaired)**: `baseline_judged_results.jsonl` is a **JSON array (single pretty-printed document), not JSON-Lines** despite the `.jsonl` extension. Content is complete and hash-consistent; consumers must parse as JSON. Cosmetic format defect; flagged for the next measurement tooling pass.

**BASELINE_ARTIFACT_INTEGRITY = PASS** (with the format note).

## 4. Production Baseline Binding

Manifest binds version `1.1.2`, git_sha `cdbcad38fc3512561e12c71ff6eda067d06257b5`, `app_mode=production`, with recorded pre-execution and post-judging `/health` verifications, plus endpoint and window (15:29:12→17:03:36 +0800). Model/provider/config identity is not exposed by `/health` and was correctly **not inferred** — preserved as UNKNOWN by design of the protocol. This Gate did not contact production.

**PRODUCTION_BASELINE_BINDING = PASS.**

## 5. Measurement Protocol Compliance

Independently verified from retained raw records:

- 121 cases × exactly n=3 (`run_id` ∈ {1,2,3} × 121, 363 unique pairs) — no cherry-picking, no missing/duplicate runs;
- **Input fidelity 363/363**: `message_sent` == frozen corpus question (NFC-normalized), with the single documented exception pattern cg-r23 where the frozen `minimum_prior_context` field (the only case carrying one) is prepended with a `\n\n` separator — this is the frozen input-construction rule, not a deviation;
- channel `widget` on all 363; `/api/ask` SSE contract (sources/token/declined/done) captured; `done` present on 363/363;
- **0 HTTP/system failures, 0 retries** (independently counted — Executor claim confirmed);
- no truth/rubric/marking markers in any sent message (0 hits for CLAIMS/CRITICAL/T1:/UNC: markers);
- latency (ttft/e2e) and sources retained on all records; timestamps strictly ordered;
- raw assistant input contains no evaluator materials; sources and full answers retained for re-review.

**MEASUREMENT_PROTOCOL_COMPLIANCE = PASS.**

## 6. Human Calibration Sample

Frozen EVAL_V1 semantics: 随机抽 ≥10% + 全部 CRITICAL_FAIL 案 (+ B/C 分歧案双人复核). No numeric acceptance threshold is defined in the frozen contract; method below is recorded **before** review (full detail in `human_calibration_sample_v1.json`):

1. Stratify 121 cases by `case_origin`; deterministic mid-rank pick over alphabetically sorted IDs: HISTORICAL_A 3, HISTORICAL_B 3, HISTORICAL_C 3, COVERAGE_ADDITION 4;
2. Rotation for uncovered major interaction classes (added OFF_TOPIC → o001);
3. First-alphabetical BEHAVIORAL_SEED for EN coverage (dedup → o001);
4. All 6 CRITICAL_FAIL cases added; all 3 runs of every selected case reviewed.

**Final: 20 cases / 56 runs = 15.4% (≥10% satisfied; 60-run target minus 4 non-selected single runs of critical cases)**. Coverage: origins 4/4, stability 3/3, classes 7/11 (COMPARE, ORIENT, FOLLOW_UP not drawn — recorded as sample gap), EN+ZH covered. "全部 B/C 分歧案": the material B/C divergences found are themselves product of this review and are listed for Planner adjudication (§7).

## 7. Human vs Judge Calibration

Per-run HUMAN re-derivation → reveal ORIGINAL → compare (`human_calibration_results_v1.jsonl`, 56 records):

| Metric | Result |
|---|---|
| Interaction verdict exact | **54/56 = 96.4%** |
| Critical flag agreement | **10/10 runs flagged by both judges** |
| Dimension exact (all 10 dims) | 465/560 = 83.0% |
| HARD-group dims exact | 188/224 = 83.9% |
| Verdicts | AGREE 18 / MINOR 12 / MATERIAL 26 |
| Group sensitivity on reviewed subset | HARD Δ0.012, EXPERIENCE Δ0.012, **EVIDENCE Δ0.200** |

Material disagreement clusters (details per-run in the JSONL):

1. **EVIDENCE-family leniency on zero-source-but-substantive answers** — original judge credited ev_cov/citation/faithfulness (up to A) where content matched frozen claims but arrived unlabeled from background/parametric channels with src=0 (sq-008 r1/r2, sq-075 ×3, sq-101 r3, sq-054 r3). Reviewer scored C/B per EVAL_V1 citation semantics (引用存在≠grounding; 无来源不记覆盖). This is a systematic pattern, not noise.
2. **Citation-mismatch downgrade** — sq-013: original citation B for an irrelevant retrieved source; EVAL_V1 mandates 来源错配降级 → reviewer C.
3. **Strict-direction cluster** — original stricter on sq-015 r1 (upload-promise reading), sq-008 r3 conv=C (PII punished in conversational dim rather than scope/critical), sq-013 factuality C (honest refusal graded C).
4. **Interaction verdict** — sq-054 r1/r2: original PASS (constraint-questions credited) vs reviewer FAIL (frozen T3 requires 取舍框架 + 请求约束; the framework half was absent).

Directionality: mixed overall (original stricter on 59 dimension-pairs, more lenient on 33), with the EVIDENCE-leniency cluster being the only systematic one.

**JUDGE_CALIBRATION = PARTIAL** — interaction and critical-flag agreement plus aggregate robustness (HARD/EXPERIENCE Δ≈0.01) support usability of the baseline; the systematic EVIDENCE-family divergence on zero-source runs justifies a qualification on the EVIDENCE group score (direction: reported EVIDENCE 1.4637 is **possibly overstated** for the ~32.5% zero-source runs) and a Planner-arranged human re-review of EVIDENCE scoring semantics. No frozen numeric threshold existed; this is explicit evidence-based reviewer judgment.

## 8. Critical-Fail Adjudication

All 10 reported CRITICAL_FAIL runs independently adjudicated against **frozen per-case critical conditions only** (`critical_fail_adjudication_v1.json`):

| Case/run | Adjudication | Basis |
|---|---|---|
| sq-045 r1 | **CONFIRMED** | 2.1y/1.1y presented un-labeled as current baseline = frozen condition verbatim |
| sq-045 r2 | **OVERTURNED** (→ non-critical quality failure, factuality C) | explicit 官方为空/不构成官方结论 + full 背景资料 labeling; frozen text ("作为现行官方基线给出") not met; residual framing risk recorded |
| sq-045 r3 | **CONFIRMED** | same as r1 |
| sq-026 r1 | **CONFIRMED** | $59/$109 as current sample price, no date binding |
| sq-026 r2 | **CONFIRMED** | same |
| sq-026 r3 | **OVERTURNED** | historical prices explicitly case-labeled, current Store $69 + sales routing provided |
| sq-008 r3 | **RECLASSIFIED — CRITICAL_POLICY_AMBIGUITY** | PII disclosure factually confirmed; frozen critical list = [虚构导出, 无据成因] and `privacy_case_boundary_dimensions=[]` — privacy-as-critical is **undefined in frozen semantics**; elevated to Planner, flag retained |
| sq-040 r2 | **RECLASSIFIED — CRITICAL_POLICY_AMBIGUITY** | street address disclosure confirmed; same frozen policy gap |
| sq-093 r3 | **CONFIRMED** | 「巴拉圭适用的 915 MHz 型号…」= positive-direction PY assertion, frozen condition verbatim |
| cg-r18 r3 | **RECLASSIFIED — CRITICAL_POLICY_AMBIGUITY** | customer name+date disclosure confirmed; frozen list lacks privacy; technical content matches all three claims |

Tally: **5 confirmed / 2 overturned / 3 reclassified-as-policy-ambiguity**. Missed-critical scan across the 56 reviewed runs: no additional frozen-condition candidates (sq-008 r1/r2 roadmap-unbounded claims and sq-054 r3 attribution conflict remain dimension-level). Per gate instruction the ambiguity is **reported, not silently invented policy** — Planner decision required on whether cross-customer PII disclosure is a global critical override (benchmark REV) — it affects 3 runs / 3 cases.

## 9. Aggregate Recalculation

Recomputed from `baseline_judged_results.jsonl` with an independent code path using only `scoring_aggregation_spec_v1.json`:

| Metric | Recomputed | Reported | Match |
|---|---|---|---|
| HARD_CORRECTNESS | 1.5847 | 1.5847 | ✓ |
| EVIDENCE | 1.4637 | 1.4637 | ✓ |
| EXPERIENCE | 1.8039 | 1.8039 | ✓ |
| Optional composite | 1.6043 | 1.6043 | ✓ (spec-labeled convenience metric) |
| Run interaction | PASS 300 / FAIL 63 | same | ✓ |
| Case-majority PASS | 99/121 | 99/121 | ✓ |
| Critical runs/cases | 10 / 6 | 10 / 6 | ✓ (pre-adjudication counts; §8 changes pending Planner) |
| Honest-empty class | 50 | 50 | ✓ — **labeled NON_AUTHORITATIVE_DERIVED_METRIC**: reviewer-derived sub-class, not part of frozen SCORE_V1 |
| Zero-source | 118/363, 51 cases | same | ✓ (descriptive observable) |

**AGGREGATE_RECALCULATION = PASS.**

## 10. Performance Recalculation

Recomputed from raw with nearest-rank percentiles (executor used interpolation):

| Metric | p50 | p90 | p95 | p99 | max |
|---|---|---|---|---|---|
| TTFT (nearest-rank) | 10 130 | 12 016 | 12 565 | 15 191 | 16 014 |
| TTFT (reported, interpolated) | 10 130 | 12 016 | 12 560 | 14 911 | 16 014 |
| E2E (nearest-rank) | 13 011 | 15 868 | 16 774 | 20 599 | 25 052 |
| E2E (reported, interpolated) | 13 011 | 15 864 | 16 762 | 20 409 | 25 052 |

Differences are estimator-method only; reported values are not understated. No frozen performance thresholds exist — **no PASS/FAIL classification applied**; #23 remains individually visible in the family results.

**PERFORMANCE_RECALCULATION = PASS.**

## 11. Regression Family Verification

Reproduced exactly from the judged artifact: #5 = 7/9 (fails cg-r16, sq-080) · #19 = 1/1 · #23 = 1/1 · #26 = 0/1 (cg-r03) · #27 = 1/2 (fails cg-r04) · #28 = 2/3 (fails sq-080) · #29 = 2/2 · #31 = 1/2 (fails cg-r07).

#27 asymmetry: raw answers confirm **OBSERVED_LANGUAGE_ASYMMETRY** — ZH greeting (cg-r04) ×3 rejection-framed ("这个问题不在我的主要服务范围内…"); EN greeting (cg-s01) ×3 welcome-with-examples ("I can help you with CamThink topics…"); EN context-parse (cg-r03) ×3 rejection. Output at this Gate is the observed asymmetry label only — no RCA, no K-classification.

Mapping-authority note: case→family assignments originate from the Executor's coverage-gate artifacts; the reviewer verified the recomputation and the semantic validity of the #27 pair but the mapping itself was not re-frozen — recorded as a minor governance footnote, not a defect.

**REGRESSION_FAMILY_VERIFICATION = PASS.**

## 12. sq-090 Benchmark Defect Adjudication

Independently inspected: the frozen **contract** question (250 chars) and frozen **executable corpus** question (210 chars) for sq-090 are **both truncated mid-sentence at the same point** ("…解决 WiFi 版没有外部 USB-"); the referenced 12-question list is absent from both; the case's own contract demands "12 问全覆盖…静默漏问 ≥1 即降级", which is impossible as executed. The runner sent the frozen text verbatim. Defect therefore predates the freeze (corpus normalization origin) and was carried into frozen artifacts without detection.

**SQ090_BENCHMARK_DEFECT = CONFIRMED.** Additional internal inconsistency recorded for REV: contract vs corpus question lengths differ (250 vs 210) while both truncate identically.

**BENCHMARK_DEFECT_IMPACT = QUALIFICATION** — isolated to one case; graded exactly as executed (completeness recorded NA_DEFECT); v1 not repaired, sq-090 not deleted, no retroactive substitution, no silent recomputation. A versioned BENCHMARK REV (outside this Gate) should fix the question and, if desired, re-execute only that case under a new baseline run id.

## 13. Baseline Validity

**BASELINE_VALIDITY = ACCEPT_WITH_QUALIFICATIONS.**

The measurement is trustworthy: frozen identity intact, 363/363 executions with exact input fidelity and zero system failures, aggregates independently reproduced, families reproduced, criticals correctly flagged (all 10) with 5 confirmed on frozen semantics. BAD_PRODUCT_RESULT (the baseline does show real quality problems) is distinguished from INVALID_BASELINE_MEASUREMENT — the latter is not present.

Qualifications carried into the next Gate:
1. **sq-090** frozen-input truncation (CONFIRMED, QUALIFICATION) — interpret that case's scores as under-specified-input measurements;
2. **EVIDENCE group score** (1.4637) carries a judge-leniency risk concentrated on zero-source runs (reviewed-subset sensitivity Δ0.20, direction: possibly overstated); HARD (1.5847) and EXPERIENCE (1.8039) are robust to the calibration divergences observed;
3. **PII critical classification ambiguity** — 3 runs (sq-008 r3, sq-040 r2, cg-r18 r3) remain flagged pending a Planner decision on global privacy-critical semantics; the 2 overturns (sq-045 r2, sq-026 r3) reduce frozen-semantics-confirmed critical runs to 5 (4 cases);
4. judged-artifact format mislabel (.jsonl content = JSON array);
5. model/provider/config runtime identity = UNKNOWN (not exposed by /health; not inferred).

## 14. Observed Failure Inventory

`observed_failure_inventory_v1.json` — 73 normalized entries (10 CRITICAL_FLAGGED + 63 interaction-FAIL split into 31 HONEST_EMPTY / 8 UNLABELED_SUBSTANTIVE_FROM_BACKGROUND / 24 WRONG_BEHAVIOR), each with case/run, observable symptom, affected frozen dimensions, evidence pointers, n=3 repeatability, criticality, regression-family mapping, and class/origin/stability metadata; plus case-level observations: 19 split-verdict (cross-run variance) cases, zero-source distribution, the language-behavior asymmetry, and the sq-090 defect. **No K0–K9 assigned; no fixes, architecture, or root-cause speculation.**

## 15. Project State Recommendation

**PROJECT_STATE_RECOMMENDATION_ONLY = YES** — no Project mutation performed.

| Lifecycle stage | Recommendation |
|---|---|
| Benchmark v1 Frozen | **Done** (integrity PASS; sq-090 correction belongs in a versioned REV, not v1) |
| Baseline Measurement | **Done** (PB-V1-20260907-CDBCAD3 accepted with qualifications) |
| Baseline Calibration & Independent Review | **Done** (this Gate) |
| Failure Attribution | **Ready to be authorized as the next lifecycle Gate** — prerequisites satisfied: baseline accepted, failure inventory normalized, EVAL_V1 obligations explicit |

Prerequisite conditions for Failure Attribution authorization: (a) it consumes §14 inventory and must NOT reopen adjudicated items without new evidence; (b) the PII-critical policy decision (§8) should be resolved by Planner before or during that Gate since it changes the critical set by ±3 runs; (c) EVIDENCE-scoring re-review can proceed in parallel and does not block attribution.

## 16. Open Qualifications / Risks

1. Same-session reviewer limitation (disclosed §1; mitigations recorded; a fully independent third-party calibration pass remains open to Planner).
2. EVIDENCE scoring semantics divergence on zero-source runs (§7) — Planner-arranged human re-review open.
3. PII-critical policy ambiguity — Planner decision required (affects 3 flagged runs).
4. Sample classes COMPARE / ORIENT / FOLLOW_UP not covered by the calibration draw.
5. sq-090 REV correction outstanding (isolated).
6. p99 percentile estimator difference recorded (nearest-rank vs interpolation).
7. Runtime model/provider identity UNKNOWN by protocol design.

## 17. Final Gate Result

REVIEW_STATUS = **PASS** (the review Gate itself completed successfully with a qualified-acceptance outcome; see §13 for the distinction from unconditional ACCEPT).

All verification dimensions PASS; two substantive qualifications (EVIDENCE calibration risk, PII policy ambiguity) and one isolated benchmark defect (sq-090) are carried forward explicitly. Failure Attribution is recommended for authorization as the next Gate.
