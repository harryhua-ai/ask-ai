# Issue #78 — Role B Implementation Report: Authoritative User-Facing Recall Bucket

**Status:** `CANDIDATE READY` (unmerged; Role A acceptance review required)
**Candidate:** branch `candidate/issue-78-recall-remediation-20260915` @ **`e936587`** (parent: design+RED `f210698`; base: `origin/main` `f4e6751` — fresh worktree, per baseline rule)
**Scope discipline:** DESIGN PASS boundaries honored — implementation = exactly the accepted D1+D2; no reranker/threshold/top_k/RRF/symbol/query-rewrite/#77/connector/content/production changes.

---

## 1. Exact changed files

| File | Change |
|---|---|
| `backend/retrieval/search.py` | `search_bucket`: +2 optional kwargs `use_hybrid: bool = False`, `alpha: float = 0.5`. When false → existing BM25 path byte-identical. When true → `collection.query.hybrid(query, vector=<embed query>, alpha, filters=<same composed class filters>, limit, MetadataQuery, same return_properties)` — mirrors the main `search()` hybrid call (L269) with identical filter composition. |
| `backend/pipeline/rag.py` | ① `INTENT_BOOST_FILTERS` values → **per-intent bucket spec lists** (+ `_bucket_specs` legacy-dict normalizer → single-spec behavior preserved). ② New `_USER_FACING_BUCKET` spec: `{chunk_types: [paragraph, heading, list, table], use_hybrid: True, limit: 20}` (chunk-type predicate = the comparison path's existing tier1 definition). ③ commercial/support = `[primary spec unchanged, _USER_FACING_BUCKET]`; **product unchanged**. ④ Bucket block iterates specs; per-candidate path names `boost:0/boost:1` for multi-spec intents (`boost` preserved for single-spec). ⑤ `_retrieve_and_fuse` returns 4-tuple incl. per-bucket attribution; `stages.retrieve.buckets` wired in BOTH answer and stream paths. |
| `tests/pipeline/test_issue78_authoritative_recall_red.py` | RED suite upgraded to GREEN-capable: boundary simulator gained a deterministic dense-topic model for `use_hybrid` buckets (production control `34ba7159…` proved authoritative entry is dense-carried; a pure lexical proxy cannot express the mechanism); seam probe reads the list-shaped config via the real `_bucket_specs`. |
| `tests/pipeline/test_rag.py` | `test_rag_support_intent_triggers_search_bucket` updated to the **authorized two-bucket contract** (call_count 1→2; first call `source_types=["filesystem"]` preserved; second call = user-facing spec with `use_hybrid=True, limit=20`). Only test in the suite asserting a bucket call count. |

**Not touched (scope audit):** reranker/`RerankPipeline`/threshold 0.3; global `top_k=10`; `rrf_fuse` (k=60, dedup); `search_symbols` semantics; `query_rewrite`; evidence planning/selection/reservation/citation (#77 stage); connectors/ingestion; product-intent bucket spec; prompts; Wiki/content; production.

## 2. Before/after behavioral evidence

| Query class | Before (baseline `f4e6751`) | After (`e936587`) |
|---|---|---|
| en company-fact, intent=commercial (`cbafab32…` class) | hybrid top-30 = 28 code + 2 blog; symbol = code; bucket = woocommerce only → **0 company chunks in pool**; rerank rejects all → fallback answers from pool remnants | user-facing bucket returns class-relevant non-code chunks (dense-matched) → authoritative chunk **in pool via `boost:1`**, attribution recorded in `stages.retrieve.buckets` (RED-1) |
| shipping question (`654f74b8…` class) | same starvation | shipping-policy chunk admitted via user-facing bucket (RED-2) |
| synthetic company query (no production vocabulary) | starved identically | admitted structurally (RED-5) — proves no vocabulary dependence |
| code-oriented query | hybrid+symbol keep code dominant | unchanged — symbol path and hybrid untouched; user-facing bucket excludes `code` chunks by `chunk_type` filter (RED-3) |
| commerce query | woocommerce bucket | woocommerce bucket preserved verbatim as commercial spec 0; store evidence still in pool (RED-4) |
| authoritative chunk already in pool | rerank retains/promotes (0.705 production control) | unchanged — reranker not modified (RED-6, real `RerankPipeline`) |

## 3. RED→GREEN results

| Test | Baseline (pre-impl) | After implementation |
|---|---|---|
| RED-1 HQ authority entry | FAIL | **PASS** |
| RED-2 shipping authority entry | FAIL | **PASS** |
| RED-5 synthetic wording | FAIL | **PASS** |
| Seam probe (no bucket carries web content) | FAIL | **PASS** (`support`,`commercial` carry) |
| RED-3 code control | PASS | **PASS** |
| RED-4 commerce control | PASS | **PASS** |
| RED-6 rerank retention (real `RerankPipeline`) | PASS | **PASS** |

## 4. Regression counts (worktree, venv pytest)

| Suite tree | Result |
|---|---|
| `tests/pipeline` + `tests/retrieval` (incl. RED suite, inc1/inc5/inc6/inc7, comparison, reservation, citation, boundary) | **815 passed, 0 failed** (16.8s) |
| `tests/api` + `tests/db` | **581 passed** (44s) |
| `tests/auth llm connectors utils benchmark scripts project_automation services` | **1100 passed, 5 skipped** (52s) |
| `tests/runtime` | **57 passed** (1.7s) |
| `tests/embedder` | **17 passed** |
| Root files (`test_evidence_meta` 61, `test_release_identity` 15, `test_models_trace` 3, `test_final_rc_combination` 6, `test_main` 2, `test_widget_hosting` 4) | **91 passed** |
| **Total** | **≈2661 passed / 5 skipped / 0 failed** |

Pre-existing environmental exclusions (verified **identical on clean baseline** via stash-A/B): `tests/e2e` (needs live services) excluded by policy; `tests/test_lifespan_smoke.py` and the combined `runtime+embedder` invocation hang in this sandbox on baseline as well (individually both trees pass). Focused suites re-run after every edit; final post-edit runs green.

## 5. Candidate-budget / semantics notes (implementation as designed)

- Per-bucket limit: primary spec unchanged (`recall_limit=30`); user-facing bucket capped at **20** → worst-case pool growth 77 → ~107 before dedup (RRF dedups by `(source_id, chunk_index)`); `top_k=10`, threshold, RRF `k=60` untouched.
- Latency: +1 Weaviate hybrid query and +1 query embedding per RAG answer for `support`/`commercial` intents only (product intent has no new call). Bounds as designed.
- Telemetry (acceptance 9, minimal): `stages.retrieve.buckets` = `[{name, source_types, chunk_types, use_hybrid, limit, hits(或 error)}…]`; per-candidate `paths` gains `boost:0`/`boost:1` names for multi-spec intents (single-spec `boost` preserved → zero change to existing trace consumers). Broader observability (run_stats persistence, sitemap↔ledger diff, stream fallback flag, pool_scores) remains the recommended follow-up issue — **not** bundled.

## 6. Acceptance mapping (mandated 1-10)

1. RED-1 GREEN ✓ 2. RED-2 GREEN ✓ 3. RED-5 GREEN (no case-specific keywords — synthetic wording) ✓ 4. RED-3 GREEN ✓ 5. RED-4 GREEN ✓ 6. RED-6 GREEN (real `RerankPipeline`) ✓ 7. answer/stream share `_retrieve_and_fuse`; parity suite green; `buckets` wired in both ✓ 8. regression suites pass (§4) ✓ 9. attribution = `stages.retrieve.buckets` + `boost:i` paths only ✓ 10. no production mutation/resync/deploy/tag/content change ✓

## 7. PROVEN / INFERRED

- All acceptance runs, diff surface, and counts: **PROVEN** (executed commands in this worktree).
- Production-effect of the fix (real corpus probes) **UNPROVEN until deployment**, and production re-sync/runtime validation remains gated by **#75** (website-camthink syncs wedged on the 413 repair-embed defect) — post-deploy probes deferred per design §13 step 4.

---

**STOP.** CANDIDATE READY, unmerged. No production mutation, no resync/reindex, no deployment, no tag, no Wiki/content change.
