# Failure Attribution v1 — ASK-AI Answer Intelligence Benchmark v1

- **Baseline**: `PB-V1-20260907-CDBCAD3` (ACCEPT_WITH_QUALIFICATIONS; review commit `e96a63d9`)
- **Production code inspected at**: `cdbcad38fc3512561e12c71ff6eda067d06257b5` (= local main HEAD, tag v1.1.2) — no production contact, no reruns, no mutations
- **Unit of analysis**: 73 inventory entries → 10 attribution groups → 7 clusters → 8 systemic capability gaps

## 1. What actually failed?

73 material entries (10 critical-flagged runs + 63 interaction-FAIL runs across 42 cases), normalized into: honest-empty outcomes (31), background-relay failures (8), routing misfires (9), stale/current composition failures (8), PII disclosures (3), competitor absence (3), generation overreach (1), split-verdict instability entries (28 — overlapping categories resolved by one-primary-cluster-per-entry rule; see `failure_attribution_v1.json → entry_to_cluster`).

## 2. Where in the pipeline did it fail? / 3. Why?

The production pipeline (traced at the production SHA): `mask_pii(user msg)` → override → **social short-circuit** → **product boundary (ambiguous/unsupported canned)** → **intent LLM (off_topic reject)** → extract/rewrite → retrieve (3-way RRF) → rerank → prune → eligible filter → min-gate/fallback → **sources = public whitelist only** → citation context (**citable numbered + 背景资料 unlabeled internal-case chunks**) → generation → CitationStreamFilter.

Divergence points per cluster (all code-anchored at this SHA):

| Cluster | Stage | Root mechanism |
|---|---|---|
| C1 zero-source background dependence | retrieval selection → composition | narrative queries select internal case chunks; public spec/price/battery docs not selected despite being indexed; citable section renders "(无可引用资料)" while background still feeds generation (`citation.py:164-172`) |
| C2 stale/current composition | composition + citation validation + generation | historical case numbers compete with current pages with no currency semantics; `numbers_supported` (`citation.py:227-236`) passes on number-presence alone ($59 ⊂ $59.9 Dev Kit; $109 inside $69.00–$112.00 range) → stale claim acquires a real Store citation |
| C3 interaction/routing | pre-retrieval gates | `social.py` ZH capability patterns omit the paraphrase 你会干什么; `product_taxonomy.yaml` deixis `the camera` substring-matches "the cameras" → MODE_AMBIGUOUS canned clarification kills a full scenario (170 ms ×3); intent taxonomy has no clarify path for commerce-adjacent questions |
| C4 PII provenance | ingestion → composition → generation | internal support-case docs (with customer identities) are ingested and injected as 背景资料 by design (`citation.py:119-149`); `mask_pii` covers only the user message (`routes.py:128`); generation surfaces identities in 1 of 3 runs |
| C5 competitor absence | corpus coverage | archived third-party evidence never ingested; honest refusal is the only possible outcome |
| C6 strategy instability | generation | response strategy varies across near-identical context (19 split-verdict cases); production sampling params UNKNOWN |
| C7 claim overreach | generation | regional availability asserted beyond any retrieved evidence (r3 only; r1/r2 bounded) |

## 4. Which failures share the same mechanism?

- C1 covers 21 all-FAIL honest/insufficient entries + 8 background-relay entries — one mechanism (background-only context), two symptoms.
- C2 covers sq-045 + sq-026 + sq-080 r1 — one mechanism (stale/current composition), two faces (battery baseline, prices).
- C3 covers cg-r03 + cg-r04 + cg-r07 — three different gates, one mechanism family (surface-form routing).
- C6 overlaps C1/C2 (r2-labeling vs r1/r3-assertion variance is the same instability), but entries are assigned to their dominant cluster to avoid double counting.

## 5. Which K categories dominate?

PRIMARY by entry count: **K7 = 28** (strategy instability C6 + overreach C7) · **K3 = 21** (C1, with K3-vs-K4 split explicitly UNRESOLVED) · **K5 = 9** (C3) · **K6 = 8** (C2) · **K5-family K0/K1 tails = 3+3** (C5, C4). K2 and K4 never primary on retained evidence; K8 is secondary in C2; K9 is reserved for genuinely unresolvable drivers (sampling params; per-run surfacing trigger), not used as a blanket.

## 6. Regression families → mechanisms

#5 → C5 (competitor absence) + C6 (sq-005 split) · #19 → C1/C6 · #23 → **PASS** (latency family has no failure entries; measured p50 TTFT 10.1 s / E2E 13.0 s) · #26 → C3 · #27 → C3 (cg-r04 vs cg-s01 pattern-coverage pair) · #28 → C2 · #29 → **PASS** · #31 → C3. Families are evidence groupings, not tasks: C3 alone explains three families.

## 7. Zero-source behavior explained

118/363 = 32.5%. Split (`zero_source_analysis_v1.json`): **EXPECTED_ZERO_SOURCE 15** (seeds/off-topic/injection — correct) · **ROUTING_SHORT_CIRCUIT 9** (6 misrouted C3 + 3 canned clarify C3) · **HONEST_EVIDENCE_ABSENCE 26** (bound refusals) · **SUBSTANTIVE_FROM_BACKGROUND 68** (dominant mode). Headline mechanism: the sources event carries only public source types, while internal case chunks are authorized into generation as unlabeled 背景资料 — **zero-source ≠ no-context**. Case-narrative query style (not topic absence) decides whether public pages are selected: same-topic spec-style sibling cases retrieved the authoritative docs (cg-r05 prices src=4; cg-r06 battery src=2; cg-r10 overview src=1).

## 8. ZH/EN asymmetry explained

Not a language-capability gap. cg-s01 ("What can you do?") matches the EN capability pattern in `social.py` verbatim → deterministic capability reply (PASS). cg-r04 ("你会干什么") — a ZH paraphrase absent from the ZH pattern list — misses the anchored matcher, falls to the intent LLM, is classified off_topic, and receives the rejection template (FAIL ×3). **Attribution: K5 (interaction/routing), HIGH** — pattern-coverage asymmetry in a deterministic gate; the cite is `social.py:_PATTERNS` vs the two frozen inputs.

## 9. Stale/current truth failures explained

Two sub-mechanisms, one composition root: (a) **sq-026**: current Store pages AND historical quote chunks both reach context; generation selects the historical numbers and attaches [2] to the current Store page because `numbers_supported` verifies only that the digits appear in the cited source ($59 appears inside $59.9; $109 inside the $69.00–$112.00 SKU range) → **K6 primary + K8 secondary, HIGH**. (b) **sq-045**: zero public sources; the current battery baseline IS indexed (proven by cg-r06) but was not selected for the troubleshooting-narrative query; case baseline presented as current in r1/r3, explicitly disclaimed in r2 → **K6 primary, K3/K4 split UNRESOLVED** (server traces not retained), r1/r3-vs-r2 difference belongs to C6. Source-truth is clean (the wiki carries the current numbers); this is a retrieval/composition/interpretation failure, not a source problem.

## 10. PII disclosure provenance explained

The disclosed identities exist in **ingested internal support-case documents** (filesystem source type). Those chunks are authorized into generation as 背景资料 (`citation.py:148-149` — "虽参与检索与生成") while being hidden from the visible source list (`_extract_sources` whitelist) — so the leak path carries no user-visible provenance. `mask_pii` sanitizes only the user's own message. The names/addresses are absent from the frozen questions, so the corpus is the only entry path. Surfacing is generation-variance-dependent (1 of 3 runs per case). **Attribution: K1 (ingestion corpus hygiene) + K7 (generation surfacing), HIGH for provenance; severity policy deliberately NOT decided** (per accepted-baseline qualification #3).

## 11. Systemic capabilities missing (`systemic_capability_gaps_v1.json`)

- **G1** No current-vs-historical evidence semantics anywhere in select→compose→generate.
- **G2** Task-type routing by surface-form gates that cannot distinguish "product unclear" from "scenario task" and cannot escalate domain-adjacent questions to retrieval-with-clarification.
- **G3** Citation integrity = numeric presence, not claim-source correspondence or currency.
- **G4** No authoritative-source preference for narrative phrasing; public-vs-background split invisible to selection quality.
- **G5** Background channel replays identity-bearing internal case documents with presentation-layer-only protection and prompt-level (non-deterministic) identity suppression.
- **G6** Response strategy unstable across identical-intent runs.
- **G7** No third-party/competitive corpus.
- **G8** Zero-source outcomes structurally invisible to the user (used internal evidence produces no visible provenance).

Dominance assessment: **two materially independent systemic axes** — evidence-layer currency/authority semantics (G1+G3+G4) and interaction-layer routing (G2) — plus trust (G5) and reliability (G6) axes. They fail in different stages with disjoint case populations; fixing one would not have prevented the other in this baseline.

## 12. What remains UNKNOWN?

K3-vs-K4 split for zero-source and stale cases (server traces not retained); production generation sampling params (C6 driver); per-run PII surfacing trigger; exact PII fields in the production corpus (read-only DB access not exercised); intent LLM literal reasons (client-invisible); whether any Store chunk text contains sample-price phrasing. Each is recorded per-group in `unresolved_evidence` with what evidence would resolve it.

## PASS-vs-FAIL comparisons used

cg-r06 PASS (src=2 battery doc) vs sq-045 FAIL (src=0) — same topic, query style decides selection. cg-s01 PASS vs cg-r04 FAIL — same intent class, pattern coverage decides. o001 PASS vs cg-r03 FAIL — both EN, both routed by the same gate; domain-adjacency decides. cg-r05 PASS vs sq-026 r1 FAIL — same commercial intent, framing changes the composition mix.

## Artifacts

`failure_attribution_v1.json` · `failure_clusters_v1.json` · `zero_source_analysis_v1.json` · `systemic_capability_gaps_v1.json` · `quantification_v1.json` · this report. Qualifications preserved: EVIDENCE-score calibration caveat, sq-090 frozen defect untouched, PII severity undecided. No fixes, no architecture, no benchmark/baseline/production mutation.
