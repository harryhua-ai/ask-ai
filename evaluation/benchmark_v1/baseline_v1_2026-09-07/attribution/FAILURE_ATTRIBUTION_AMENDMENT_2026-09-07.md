# Failure Attribution Amendment — 2026-09-07 (REV2)

- **Base**: `74ffb53e905e318ce2022a96e14cd18f3c586b5b` (rev1; NOT amended — separate commit below)
- **Scope**: taxonomy and aggregation semantics corrections only, using existing retained evidence. No re-investigation, no reruns, no fixes, no Target Architecture.
- **Revision lineage**: rev1 = `74ffb53e` → rev2 = this commit. Updated machine-readable artifacts carry `revision` + `revision_lineage` fields; cluster membership (entry→cluster) is unchanged — only K semantics, confidence semantics, gap normalization, and denominator definitions change.

## 1. PII attribution — K1 → K6/K7

Frozen K1 means authoritative information exists upstream but was **not** ingested/available. The retained evidence shows the opposite: internal case documents **were** ingested and reached generation (that is why identities could surface). Ingestion success is not a K1 failure. Re-adjudicated per frozen taxonomy: **PRIMARY = K6** (Evidence Composition — identity-bearing content is a property of the composed evidence set: the background channel), **SECONDARY = K7** (Generation / Response Strategy — the act of surfacing identities, observed in 1 of 3 runs per case). Applies to sq-008 r3, sq-040 r2, cg-r18 r3 (`F-ATTR-06`, cluster C4). Severity policy remains undecided (qualification preserved). No contrary evidence for a different direction was found.

## 2. C1 K3/K4 consistency — K3 primary removed

rev1 assigned 21 entries to K3 while stating the K3-vs-K4 split unresolved — inconsistent with the frozen RCA standard. Per-run fused/rerank lists are not retained, so retrieval failure is **not evidenced at stage granularity** for any C1 entry (sq-013 r1 evidences an irrelevant source in the *visible* set, but the relevant document could have been fused-then-displaced). All 21 C1 entries become **PRIMARY = K9, candidates [K3, K4]**, with **K6 secondary** (the composition consequence — empty citable section + background-only generation — is retained-evidence-backed). What would resolve the split: server-side fused/rerank lists per run.

## 3. C6 generation-instability — K7 primary removed

K7 requires evidenced generation-stage divergence (same routing + materially equivalent context + divergence at generation). Retained per-run source counts across the 19 split-verdict cases:

- **12 cases (src_same=False)**: FAIL runs carry fewer public sources than PASS siblings (typically 0 vs 1–5) — **upstream retrieval variance is evidenced**; generation divergence cannot be isolated → PRIMARY = K9, candidates **[K3, K4]**.
- **7 cases (src_same=True)**: identical public-source state, but the background set is not retained, so context equivalence cannot be proven → PRIMARY = K9, candidates **[K6, K7]**.
- **2 inverted runs** (sq-032 r1, sq-080 r1: FAIL *with* sources while a sibling PASSed *without*) → candidates **[K4, K6, K7]**.

K7 therefore survives only where the failure is content-level provable regardless of context: **sq-093 r3 (C7, K7, HIGH)** — assertions exceed any plausible evidence — and as SECONDARY in C4 (identity relay act). All 28 C6 entries: PRIMARY = K9 with the candidates above.

## 4. Measurement unit semantics

| Denominator | Count | Definition |
|---|---|---|
| Baseline interaction FAIL runs | **63** | runs whose `interaction_correctness` dimension = FAIL |
| CRITICAL_FAIL-flagged runs | **10** | runs carrying a critical flag — **all 10 are interaction-PASS** (criticals are independent of the interaction verdict) |
| Material failure observations (Attribution) | **73** | one RUN carrying EITHER interaction FAIL **OR** a critical flag; 63 + 10 with zero overlap |

One "observed failure" = one run-level material observation. Multiple observations per run: **none** (exactly one primary cluster per entry). **PASS-interaction runs can still be material observations** via critical flags — evidence/citation/privacy failures need not degrade the interaction verdict (this is exactly how 10 runs entered the inventory). The two denominators must not be used interchangeably.

## 5. Systemic capability gaps — normalized (capabilities, not fixes)

| ID | Capability | Substance (unchanged evidence basis) |
|---|---|---|
| SC-1 | Interaction Understanding | surface-form gates (anchored patterns, substring deixis, four-label intent) misclassify paraphrases, domain-adjacent and scenario-complete inputs; no clarify/escalation path |
| SC-2 | Evidence Selection / Authority | no authoritative-source preference for narrative phrasing; no stage-level selection visibility (instrumentation gap) |
| SC-3 | Evidence Semantics (currency) | no current-vs-historical semantics in compose/generate |
| SC-4 | Evidence Composition / Trust Boundary | background channel composes identity-bearing internal documents; provenance invisible; identity suppression prompt-level only |
| SC-5 | Claim–Evidence Integrity | numeric-presence citation validation, not claim–source correspondence |
| SC-6 | Response Decision Stability | answer/refuse/relay unstable across equivalent-intent runs; retained evidence shows upstream retrieval variance participates — stage-attributable instrumentation is itself missing |

Competitor/source absence (cg-r16, K0) is **removed from the capability list** and retained as a corpus-coverage observation — the engine honestly refused on absent sources; no evidence of a structural Answer Engine deficiency.

## Revised quantification

- **PRIMARY_K_DISTRIBUTION (73 entries)**: K0 = 3 · K3 = 0 · K5 = 9 · **K6 = 11** (C2 8 + C4 3) · K7 = 1 (C7) · **K9 = 49** (C1 21 candidates [K3,K4]; C6 28 candidates per source-pattern evidence) · K1/K2/K4/K8 = 0 primary.
- Confidence: HIGH 21 (C3, C2, C4, C7) · MEDIUM 3 (C5) · 49 entries are confident **UNRESOLVED** assignments with explicit candidates.
- Cluster entry counts unchanged: C1 21 / C2 8 / C3 9 / C4 3 / C5 3 / C6 28 / C7 1.

## Updated artifacts (this commit)

`failure_attribution_v1.json` · `failure_clusters_v1.json` · `zero_source_analysis_v1.json` · `systemic_capability_gaps_v1.json` · `quantification_v1.json` — each now carries `revision`/`revision_lineage`; rev1 text remains in git history at `74ffb53e`. The rev1 report (`FAILURE_ATTRIBUTION_V1_2026-09-07.md`) is superseded on the corrected points by this amendment.

## Unresolved (unchanged + explicit)

K3-vs-K4 stage split (needs fused/rerank traces) · generation sampling parameters · per-run PII surfacing trigger · exact PII fields in the production corpus · intent LLM reason strings · Store chunk text content. Resolution paths are recorded per group in `failure_attribution_v1.json → unresolved_evidence`.
