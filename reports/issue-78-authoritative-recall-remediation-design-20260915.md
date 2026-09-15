# Issue #78 — Authoritative Recall Failure: Remediation Design + RED Proof (Role B)

**Status:** `ISSUE_78_REMEDIATION_DESIGN = READY FOR ROLE A REVIEW`
**Role:** Role B, Senior Engineering Executor — DESIGN + RED PROOF ONLY. Production fix NOT implemented; no merge/deploy/resync/content changes.
**Baseline:** `origin/main` = **`f4e67515af810840aa10fa800f0203c2ba290df0`** (`f4e6751`; = r3 code `5eac2b2` + 2 docs commits).
**Isolated worktree/branch:** `candidate/issue-78-recall-remediation-20260915` (fresh from `origin/main`, worktree clean before changes; deliberately NOT based on the investigation branch).
**RED suite:** `tests/pipeline/test_issue78_authoritative_recall_red.py` — on baseline: **4 failed (RED-1/2/5 + seam probe), 3 passed (RED-3/4/6)**, 0.15s, hermetic (no Weaviate/network).
**RCA re-verification:** all accepted RCA claims re-checked against `f4e6751` — **no material contradiction found**; RCA not reopened.

---

## 1. Baseline SHA

`origin/main` after `git fetch origin` = `f4e67515af810840aa10fa800f0203c2ba290df0`. Worktree created at this SHA; `git status --porcelain` empty before any change.

## 2. RCA re-verification (baseline `f4e6751`)

| Accepted RCA claim | Baseline evidence | Verdict |
|---|---|---|
| `INTENT_BOOST_FILTERS`: support→`filesystem`, product→doc `chunk_types`, commercial→`woocommerce` only | `backend/pipeline/rag.py:447-451` | PROVEN, unchanged |
| symbol path unconditional on every RAG query; code-only | `rag.py:802` (`search_symbols`); `chunk_code.py` sole `symbol_tokens` producer | PROVEN |
| bucket path = BM25-only (`query.bm25`), class filters `source_types`/`chunk_types` | `backend/retrieval/search.py:427` (bucket), `:328` (symbols); `query.hybrid` only at `:269` (main search) | PROVEN |
| `HybridSearcher.search` has **no** source_type/chunk_type/class filter param | `search.py:183` signature (product/channel/generation only) | PROVEN |
| fallback ("P1 兜底") degrades to `fused[:top_k]`; flag written only on answer path | `rag.py` fallback block; single `stages["rerank"]["fallback"]` write (answer path) | PROVEN |
| answer & stream share `_retrieve_and_fuse` | call sites `rag.py:1592` (answer), `:2335` (stream), `:926` (comparison per-target) | PROVEN |

Both production anchors (contact-us / shipping-policy serving in Weaviate gen 0; pool composition 47 code + 30 store + 2 blog + 0 company; control rank-29 entry with rerank 0.705) are production-side facts from the accepted investigation — not re-derived here, and not contradicted by any baseline code change.

## 3. Exact retrieval pipeline map (baseline)

```
query → understanding/rewrite (rag.py:1536-1548; effective_min=1 for product/support/commercial)
  → _retrieve_and_fuse (rag.py:769)  [answer 1592 ∥ stream 2335 — same seam]
      ├─ search()            hybrid dense+BM25, limit=recall_limit(30), CLASS-BLIND   (search.py:183)
      ├─ search_symbols()    BM25 over symbol_tokens^3 — code-only field, ALWAYS RUN  (search.py:275)
      └─ search_bucket()     BM25-only, class filters, ONE cfg per intent:            (search.py:356)
             INTENT_BOOST_FILTERS (rag.py:447):
               support    → {source_types: [filesystem]}
               product    → {chunk_types: [paragraph,heading,list,table]}
               commercial → {source_types: [woocommerce]}     ← web_crawl in NO bucket
  → rrf_fuse(k=60) dedup by (source_id, chunk_index)      (retrieval/rrf.py)
  → visibility guard (per-chunk channel; not class-aware)
  → rerank_scored (cross-encoder × chunk_type weights: code ×1.1; threshold 0.3; top_k 10)
  → [len(reranked) < effective_min → fallback fused[:top_k]]
  → evidence planning/selection/reservation (F-1') → citation context
```

**Earliest common point where starvation can be prevented:** the **path-declaration layer** — `INTENT_BOOST_FILTERS` plus the bucket-invocation block in `_retrieve_and_fuse` (and, only if class-scoped semantic matching is required, the `search_bucket` primitive it configures). Everything downstream (RRF, rerank, fallback, evidence) can only re-order or discard what the paths returned; nothing downstream can admit an absent chunk. RED-1's failing assertion is precisely this boundary.

## 4. Earliest safe remediation seam

**The intent-bucket machinery is the correct seam** — it is the only existing place where a per-intent, class-filtered recall path is declared and fused into the same candidate pool. Two qualifications proven below:

1. **Config-level seam:** adding a bucket spec that can carry authoritative user-facing content (`chunk_types: [paragraph, heading, list, table]` — the same non-code predicate the comparison path already uses as its tier1 definition, `rag.py:239-244`) to `commercial`/`support` (product already has it).
2. **Primitive-level qualification:** today's `search_bucket` is BM25-only. The production control (`34ba7159…`) shows the contact-us chunk entered hybrid's global top-30 via its **dense** component while carrying ~zero lexical overlap with the starved query; a BM25-only bucket re-creates the same lexical starvation inside the bucket. Therefore the design adds an **optional class-scoped hybrid mode** to the existing `search_bucket` primitive (reusing the existing hybrid call pattern and the existing filter composition) — `search.py` is the second (and last) touched file.

No new abstraction, policy engine, taxonomy, or retrieval layer is introduced: both touched seams are existing mechanisms with existing tests.

## 5. Option comparison (mandated)

| | Seam (exact) | Fixes proven cases? | Generalization | Regression risk | Code queries | Commerce queries | Latency | #77 overlap | Case-specific? |
|---|---|---|---|---|---|---|---|---|---|
| **A. intent-bucket extension (config)** | `INTENT_BOOST_FILTERS` (rag.py:447) — add `web_crawl` to commercial/support `source_types` | Likely PARTIAL: bucket is BM25-only; lexically-weak chunks (the anchors) may still miss in-bucket at production scale (control trace shows entry was dense-carried) | All `web_crawl` content for those intents; nothing for wiki-doc (github) starvation | Low (one dict entry); noise: all web pages compete in-bucket | None (support/product buckets untouched for code; symbol path untouched) | Commercial bucket semantics preserved if woocommerce spec retained | +1 BM25 query (~0 embed) | None | No |
| **B. class-aware composition / reserved capacity pre-rerank** | post-`rrf_fuse` re-composition in `_retrieve_and_fuse` / new quota fn | **NO** — composition cannot admit a chunk that no retrieval path returned (HQ case: chunk absent from all 3 paths' outputs; pool dump proven). Only helps if paired with an extra retrieval = option A/C in disguise | n/a | Medium (new composition logic; overlaps #77's tiering mandate) | Risk of quota squeeze | Risk of quota squeeze | 0 | **HIGH — this is #77 territory** | No |
| **C. modify hybrid retrieval itself** | `HybridSearcher.search` — per-class quotas / multi-query inside Weaviate call | Yes in principle | Global | HIGH: touches the most sensitive primitive used by every path incl. comparison; no existing seam for class quotas inside one hybrid call | Untested blast radius | Untested blast radius | ×k queries or complex server-side logic | None | No |
| **D. query rewrite / expansion** | `query_rewrite.py` (one_call rewriter already exists) | NO — failure is class-structural, not lexical-poverty: control case shows lexical-fit queries work; rewrite cannot guarantee class representation; adds nondeterminism | Poor | Medium (changes every query's semantics) | Risk | Risk | +LLM call (already spent) | None | Effectively yes (would need company-term expansions = hard-coding) |
| **E. increase top_k / recall_limit** | orchestrator `recall_limit`(30)/`top_k`(10) | NO — RED-1 boundary shows the chunk is not at rank 31-of-30 marginally; it is absent from a path whose slots are filled by a 100k-chunk code corpus; capacity is unbounded in principle | Poor | High: rerank cost scales linearly; dilutes precision for every query | Dilutes | Dilutes | rerank ms ↑ ~linearly | None | No |
| **F. narrower existing mechanism (discovered)** | candidates inspected: F-1' R3b focused re-retrieval (`evidence_reservation.py`) — slot-gated second hybrid; `apply_page_context_boost` — page-hint only; `override_matcher` — explicit Q&A; pruner — discards | R3b is the closest ("second-chance hybrid") but is plan-slot-gated and (per #77) slot coverage is class-blind — code satisfies PRODUCT_SPEC, so the rescue precondition never fires for these queries. Not reachable for #78 without re-working #77's slot semantics | n/a | n/a | n/a | n/a | n/a | **HIGH (#77's slot machinery)** | n/a |

**Selected: A's seam with F-disclosed primitive qualification** — i.e., bucket-spec extension **plus** the optional class-scoped hybrid mode on `search_bucket`. This is the narrowest change that provably turns the RED assertions GREEN without touching #77's stage, reranker thresholds, top_k, or any query-specific vocabulary.

## 6. Recommended design

**D1 — `search_bucket` optional hybrid mode (`backend/retrieval/search.py`).**
Add kwargs `use_hybrid: bool = False` (and optional `alpha`). When false: existing BM25 behavior, byte-identical (all current callers/tests unaffected). When true: run `collection.query.hybrid(query=query, vector=<embed query>, alpha=alpha, filters=<same composed class filters>, limit=limit, return_metadata=MetadataQuery(distance=True))` — the filter composition (`source_types`/`chunk_types` via `Filter.any_of(equal)`, channel, generation) is reused verbatim from the current bucket implementation; distance→score conversion mirrors `search()`. Cost when enabled: +1 query embedding (mirrors `search()`; acceptable initially — optimization to pass a precomputed vector can follow without interface change).

**D2 — multi-bucket intent configuration (`backend/pipeline/rag.py`).**
`INTENT_BOOST_FILTERS` values become a **list** of bucket specs (normalizing legacy single-dict internally so product intent behavior is unchanged):

```python
_INTENT_USERFacing = {"chunk_types": ["paragraph", "heading", "list", "table"], "use_hybrid": True, "limit": 20}
INTENT_BOOST_FILTERS = {
    "support":    [{"source_types": ["filesystem"]}, dict(_USER_FACING)],
    "product":    [{"chunk_types": ["paragraph", "heading", "list", "table"]}],   # unchanged semantics
    "commercial": [{"source_types": ["woocommerce"]}, dict(_USER_FACING)],
}
```

The bucket block in `_retrieve_and_fuse` (rag.py:813-826) iterates the list, calling `search_bucket` per spec and concatenating into `bucket_results` (RRF already dedups by `(source_id, chunk_index)` and sums multi-path scores — the same dual-path advantage code chunks already enjoy via hybrid+symbol).

**Candidate-budget semantics:** per-path limits unchanged (`recall_limit=30`); the new user-facing bucket capped at `limit=20`; RRF `k=60` unchanged; `top_k=10` and threshold untouched. Worst-case pool 77 → ~97-107 → rerank input +~25-40% (cross-encoder ms scales; measured production rerank ≈2s at 77 candidates → budget ≈+0.5-0.8s worst case; the `limit=20` cap bounds it). If Role A wants zero latency growth, dropping the woocommerce/filesystem bucket limit to 20 is the counterweight — decision left to Role A.

**Dedup/fusion:** unchanged (RRF).
**Interaction with symbol search:** none (untouched; code queries keep hybrid+symbol advantage — RED-3).
**Interaction with commercial bucket:** preserved verbatim as the first commercial spec (RED-4 guards the `source_types == ["woocommerce"]` call shape).
**Interaction with #77:** zero stage overlap. #78 admits the authoritative class to the pool; #77 (downstream) composes/orders it. The user-facing bucket also admits blog/news — ordering among admitted non-code content is #77/comparison-tiering semantics, not #78's.
**Stream/non-stream parity:** both call the same `_retrieve_and_fuse`; one change point; parity test (`test_inc7_stream_trace_parity.py` pattern) included in the acceptance plan.
**Class predicate choice:** `chunk_type != "code"` (expressed as the doc chunk-type list, identical to the comparison path's tier1 predicate, `rag.py:239-244`) — reuses existing metadata only; **no new source taxonomy** (answer to investigation question D: existing primitives are sufficient).

## 7. Rejected alternatives

See §5 matrix. Summary of decisive reasons: B overlaps #77 and cannot resurrect unreturned chunks; C has no existing seam and unbounded blast radius; D is nondeterministic and effectively vocabulary hard-coding; E misreads the failure (not marginal capacity — RED-1 boundary composition proves it); F's R3b is gated by #77's class-blind slot coverage.

## 8. RED evidence (baseline `f4e6751`, hermetic, 0.15s)

`/Users/harryhua/Documents/GitHub/ask-ai/.venv/bin/python -m pytest tests/pipeline/test_issue78_authoritative_recall_red.py`

| Test | Result on baseline | What it proves |
|---|---|---|
| `test_red1_hq_company_authority_starved_from_candidate_pool` | **FAIL** | With the measured production hybrid boundary (28 code + 2 blog top-30) and the real `_retrieve_and_fuse`, the authoritative contact chunk never enters the fused pool; seam diagnosis shows the commercial bucket requested only `woocommerce`. |
| `test_red2_shipping_authority_starved_from_candidate_pool` | **FAIL** | Same structural starvation for shipping-policy content. |
| `test_red5_synthetic_company_query_same_structural_failure` | **FAIL** | Synthetic wording ("Which city is your company headquarters located in?" — zero production-case vocabulary) reproduces the starvation: structural, not lexical accident. |
| `test_red_seam_probe_no_bucket_carries_web_crawl_on_baseline` | **FAIL** | Module-constant-level proof: no intent bucket can carry `web_crawl` (and support/commercial carry no non-code bucket). |
| `test_red3_code_oriented_queries_keep_code_competitive` | PASS | Code-oriented queries keep ≥20 code chunks in the pool (hybrid+symbol) — regression guard. |
| `test_red4_commerce_queries_keep_store_evidence_competitive` | PASS | Commercial intent keeps the `["woocommerce"]` bucket call shape and store evidence in the pool — regression guard. |
| `test_red6_reranker_retains_authority_once_admitted` | PASS | **Real `RerankPipeline`** (threshold 0.3 + chunk_type weights) retains and promotes the authoritative chunk once admitted — protects the RCA localization (pre-rerank) against accidental "reranker fixes". |

Harness fidelity note (explicit): `_ScriptedBoundarySearcher` scripts only the **Weaviate boundary outputs** (hybrid/symbol = measured production traces; bucket = truthful class-filter evaluation over a fixed corpus with recorded kwargs). The code under test is the real `_retrieve_and_fuse` + `INTENT_BOOST_FILTERS` + `rrf_fuse` + `RerankPipeline`. Adjacent suites re-run on baseline: `27 passed` (inc1 lineage, page-context boost, evidence reservation) — no interference.

## 9. Regression / control evidence

RED-3 (code), RED-4 (commerce), RED-6 (reranker retention) are the standing controls; all green on baseline and required to stay green post-fix. Additionally: `27 passed` on the three nearest-neighbor suites; full-suite and `test_inc7_stream_trace_parity.py` re-run are part of the implementation acceptance (§13).

## 10. Exact expected implementation change surface

1. `backend/retrieval/search.py` — `search_bucket`: add `use_hybrid`/`alpha` kwargs; hybrid branch reusing the existing filter composition and `search()`'s hybrid kwargs pattern (`:269`). No other method changes.
2. `backend/pipeline/rag.py` — `INTENT_BOOST_FILTERS` (L447): values → list of bucket specs (with legacy normalization); bucket block (L813-826): iterate specs, concatenate results, keep `path_counts["boost"]` as the sum; add per-spec telemetry (§12).
3. Tests: `tests/pipeline/test_issue78_authoritative_recall_red.py` turns fully green; new unit tests for `search_bucket(use_hybrid=True)` filter semantics (mock collection, mirroring existing search tests); parity assertion per `test_inc7_stream_trace_parity.py`.
No changes to: reranker, thresholds, top_k, RRF, evidence/selection, citation, connectors, ingestion, prompts.

## 11. Interaction with #77 / #75

- **#77:** strictly upstream/downstream separation — #78 ends at pool entry; #77 composes/eligibilizes after. The enlarged, class-representative pool feeds #77's tiering; no shared file changes (rag.py bucket block is recall-declaration, not composition). #77's RED/GREEN suites are unaffected by D1/D2 (they mock the searcher boundary).
- **#75:** runtime validation on production (`website-camthink` syncs) remains blocked until #75 lands; the staged production probe (§13 step 4) must be scheduled after #75. RED/GREEN itself is production-independent.

## 12. Observability split

**REQUIRED FOR #78 FIX VALIDATION (bundle with D1/D2, minimal):**
- per-bucket-spec recall accounting in `stages.retrieve.path_counts` (e.g. `boost_woocommerce` / `boost_user_facing`) + the bucket specs used (kwargs, bounded) — proves *which* path admitted the authoritative class;
- that is sufficient for RED→GREEN validation (pool entry + path attribution).

**FOLLOW-UP GOVERNANCE / OBSERVABILITY (recommend a separate issue; not created):**
- persist web_crawl `run_stats` into `sync_log.delta_counts` (contract already claims it; production rows empty);
- sitemap-membership ↔ ledger diff surface (would have prevented the 12-day "shipping not ingested" false belief);
- persist bounded rerank `pool_scores`; write `fallback` flag on the **stream** path (sole write today is the answer path, rag.py L1770);
- per-path boundary dumps / filter-drop counters (knowledge exclusion, visibility guard).

## 13. RED→GREEN implementation acceptance plan

1. Implement D1 (with its own unit tests for both bucket modes); verify existing `search_bucket` tests byte-identical behavior in BM25 mode.
2. Implement D2; RED-1/2/5 + seam probe turn **GREEN**; RED-3/4/6 remain **GREEN**; full `tests/pipeline` green; `test_inc7_stream_trace_parity.py` green (parity by construction, asserted).
3. Latency guard: record pool size and rerank ms in the new telemetry; assert pool ≤ bounded budget in a unit test (e.g., ≤ 2×baseline).
4. Production probe (after #75 unblocks syncs; read-only widget probes only): replay `cbafab32…`-class and `654f74b8…`-class questions; assert via trace that a `website-camthink` chunk enters the pool via the user-facing bucket and the answer cites it; confirm code-oriented probe (e.g. NE503 SDK/CMake question) unchanged via path_counts.
5. Benchmark guards: cg-r05 / sq-026 / sq-045 families not regressed.

## 14. PROVEN / INFERRED / UNPROVEN (material claims)

| Claim | Level |
|---|---|
| Baseline seam facts (§2 table, all line numbers) | PROVEN |
| RED failures/green controls on baseline | PROVEN (executed, 0.15s) |
| Bucket primitive is BM25-only; hybrid exists only in main `search()` | PROVEN |
| Config-only bucket extension (Option A) may still starve lexically-weak chunks at production scale (bucket BM25 has no dense component) | INFERRED (control trace shows dense-carried entry; not production-scale-provable in harness) |
| Worst-case pool/latency growth numbers | INFERRED (production rerank ≈2s @77 candidates; bounded cap proposed) |
| Staged production improvement after fix | UNPROVEN until §13 step 4 (blocked by #75) |

---

**STOP.** Design + RED proof only. Production fix not implemented; nothing merged; no deploy/tag; no production mutation; no resync/reindex; no Wiki/content edits; #77/#75 untouched.
