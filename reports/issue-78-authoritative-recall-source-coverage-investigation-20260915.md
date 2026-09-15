# Issue #78 Investigation — Authoritative Company/Support Knowledge: Recall & Source Coverage

**Role:** Senior Engineering Investigator — INVESTIGATION ONLY (no fix implemented, no production mutation, no resync/reindex, no deployment, no new issues).
**Repo state inspected:** `main` worktree @ `f4e6751` (code) + production `v1.6.3-r3` @ `5eac2b2b…` (runtime evidence).
**Production evidence:** read-only Postgres (`data_sources`, `sync_log`, `documents`), read-only Weaviate GraphQL (`Document` collection), live sitemap/robots HTTP GET, and the 2026-09-15 conversation export traces.
**Machine-readable artifact:** `reports/data/issue-78-recall-coverage-evidence-20260915.json`.

---

## 1. Executive Root-Cause Verdict

**Both named production anchors are PROVEN Class-A RECALL FAILURES, not coverage failures.** The investigation **disproves** the issue's Class-B example:

- `website-camthink/company/contact-us` — **1 chunk verified serving in Weaviate at generation 0** (`heading`, 814 chars, **contains "Headquarters / Software Park Phase III, Xiamen 361024, Fujian, China"**), ledger row active with current version (created 2026-09-02 01:25:31). Question asked 2026-09-14.
- `website-camthink/shipping-policy` — **3 chunks verified serving in Weaviate at generation 0** (ledger active, created 2026-09-02 01:25:33). "Do you ship internationally?" was asked 2026-09-03 11:46 — ~34 h after ingestion. The #73/#74 classification of shipping as "MISSING_KNOWLEDGE / NEW_DOCUMENT ingest" is **disproven at the storage layer**.

**Root cause of the recall failure (PROVEN chain, trigger → mechanism → loss → failure):**

> Query "where is your head office" (en, intent=commercial conf 0.85, rewrite no-op)
> → the only retrieval path that can carry a `web_crawl` chunk is the class-blind hybrid search (dense+BM25, `limit=30` global slots): the symbol path is code-only (`symbol_tokens` exist only on code chunks — it returned 21 code hits even here), and the commercial bucket is `woocommerce`-only (returned 30 store chunks)
> → in that single path, the query's only content token `"head"` is extremely frequent across the 11 indexed git repos (HTTP `HEAD`, headers, list heads…): hybrid top-30 = **28 code chunks + 2 blog chunks; 0 company/support chunks**; contact-us (whose text contains no token `head`/`office` — only "Headquarters", a different BM25 token) fell below the pool boundary
> → fused 79-candidate pool = 47 code + 30 store + 2 blog + 0 company
> → the cross-encoder correctly rejected every candidate (<0.3, top 0.029)
> → the rerank-fallback degraded to raw RRF pool order and answered from store/code/eval-fixture remnants → the honest-but-useless "cannot confirm" answer with the authoritative HQ address sitting unserved in the same index.

**Class-B (source coverage) verdict:** at page level, company/support coverage is **complete** — the ledger holds 130 `website-camthink` documents covering essentially the whole `page-sitemap.xml` (+BFS extras), all `lifecycle=active` with current versions. Remaining genuine coverage items are: (a) intentional config excludes (`/cookie`, `/terms`, `/store/`, `/login`, `/register`, …); (b) one config-drift artifact (`register` ingested despite the exclude — added after the first crawl); (c) **a live wedge: every `website-camthink` sync since 2026-09-14 15:20 fails** (`修复代 N embed 失败(零激活): internal embeddings HTTP 413: text exceeds max_length=1024`) — no new page or update can land on this source until #75 is fixed; (d) a latent mechanism: incremental sync only ingests sitemap URLs whose `lastmod ≥ since` (`fetch_changes`), so a URL added to the sitemap without a lastmod bump is permanently invisible until a full crawl — not currently harming any proven case.

**Observability root gap:** the system computed and then discarded the evidence that would have prevented the false "shipping not ingested" conclusion: the web_crawl connector builds full coverage stats (`run_stats` incl. per-URL rejection reasons; docstring: "由同步层写入 SyncLog 真实呈现覆盖"), but **production `sync_log.delta_counts` is empty on every sampled row** — coverage truth never lands. Combined with citation-inventory-based auditing (link_checks shows only *retrieved* URLs), an ingested-and-serving page appeared "not in KB" for 12 days.

## 2. Production Anchors

| Conv | Query | Asked | Authoritative state at ask time | Verdict |
|---|---|---|---|---|
| `cbafab32…` | "where is your head office" | 09-14 22:51 | contact-us chunk serving (gen 0, since 09-02) | **PROVEN_RECALL_FAILURE** |
| `654f74b8…` | "Do you ship internationally?" | 09-03 11:46 | shipping-policy 3 chunks serving (gen 0, since 09-02 01:25) | **PROVEN_RECALL_FAILURE** |
| `2de09754…` | "What is camthink and who are the owners?" | 09-12 | about-us chunk serving (since 09-02; "Built within Milesight's industrial system") | LIKELY_RECALL_FAILURE (authority lost to news/blog cites; answer still correct) |
| `6ecdff55…` | "你们老板是谁" | 09-04 | — | OTHER (off-topic reject at intent gate; retrieval never ran) |
| `5f771583…` | "What country is it made in?" | 09-12 | — | OTHER (task_clarify; retrieval never ran) |
| `afd6cad9…` | "你们的项目地址在哪" | 09-09 | — | OTHER (task_clarify) |
| `f1b0a018…` | "ne302在哪里购买？" | 09-10 11:10 | NE302 store product ingested **09-11 05:09** | OTHER (coverage **lag** ≤1 day, since resolved; at ask time genuinely absent) |
| `40076034…` | IP67 test report | 09-11 | upstream public existence unproven | UNPROVEN (→ #73 K08 content question) |
| `93379bc3…` | NeoMind default password | 09-10 | candidate coverage mechanism: `neomind-local` config `exclude_dirs: [".github","docs"]` [PROVEN config]; whether needed doc lives there | UNPROVEN (→ #73 K10) |

## 3. Current Source Topology (production, read-only)

15 enabled sources (all `knowledge_role` NULL = CURRENT):

| Source | Type | Product | Company/support relevance |
|---|---|---|---|
| `website-camthink` | web_crawl | website | **The company/support source**: sitemap(robots→`sitemap_index.xml`→post/page/product sub-sitemaps)+BFS(≤150 extra). 130 ledger docs, all active+versioned, chunks in Weaviate gen 0. Holds contact-us, about-us, shipping-policy, payment-methods, warranty-and-return-policy, business-inquiry, solutions/*, campaigns, developer-center/*. |
| `woocommerce-mall` | woocommerce | online-store | 41 product docs; store pages; the commercial bucket's only source. |
| `knowledge-support-cases` | filesystem | knowledge | support-case library (support bucket's only source). |
| `wiki-documents-local` + 10 git repos | github/local_git | wiki + firmware/app code | product docs (wiki) and source code — code floods the class-blind hybrid path. |

Production `exclude_patterns` (config, replaces defaults): `/account /archive /author/ /cart /category/ /checkout /cookie /feed /login /my-account /privacy /register /search /signin /signup /store/ /tag/ /tags/ /terms /wp-admin /wp-json /wp-login`. None of these matches `/shipping-policy`, `/company/*`, `/solutions/*`, `/payment-methods`, `/developer-center/*`, `/tools`, `/campaign/*`.

**Coverage ledger-vs-sitemap diff (PROVEN):** of 32 `page-sitemap.xml` URLs, 24 are in the ledger (incl. every company/support page); 5 excluded-by-config (cookie/terms/store/login + register-drift, where register IS ingested — pre-config artifact); 3 campaign pages ARE ingested. **No unintentional page-level coverage gap exists in the company/support domain.** (robots.txt Disallows only wp-* /search /tag — irrelevant here.)

## 4. Contact-Us Failure Trace (`cbafab32…`) [PROVEN]

```
query "where is your head office" — rewrite no-op ("extracted"="rewritten"=query), lang=en,
intent=commercial (conf .85), response_strategy=commercial, effective_min=1
├─ hybrid (dense α=0.5 + BM25, limit=30, class-blind): returned 30 = 28 code + 2 blog
│    (query token "head" is lexically dense across git repos; contact-us text has no
│     "head"/"office" token — only "Headquarters", a distinct BM25 token)
├─ symbol BM25 (limit=30, symbol_tokens = code-only field): 21 code hits
├─ commercial bucket (limit=30, source_types=["woocommerce"]): 30 store chunks
├─ RRF fuse → pool 79 = 47 code + 30 store + 2 blog + 0 company  ◄── CONTACT-US NEVER ENTERS
├─ rerank (cross-encoder + code×1.1, threshold 0.3): every candidate < 0.3 (top 0.029)
│    → survivors = 0 → len(reranked) < effective_min(1)
├─ fallback ("P1 兜底"): reranked = fused[:10] — raw RRF order becomes evidence
│    (trace survivor scores 0.0164=1/61 RRF constant; stream path writes NO fallback flag)
├─ citation: store+code(+eval fixture at pool rank 3) numbered as public sources
└─ answer: "retrieved official materials do not contain… head office… cannot be confirmed"
   while chunk `website-camthink/company/contact-us#0` — containing the exact HQ address —
   sat serving in the same index.
```

Earliest candidate-loss point: **the hybrid top-30 pool boundary** (the only viable path for this source class). Not the reranker (it never saw the chunk), not the fallback (it only converted a rejection into pollution), not filters (none applied to this chunk), not query preprocessing (no-op).

## 5. Successful Control Trace (`34ba7159…`, test/internal) [PROVEN]

Query: long zh mining-case description (Edge IoT & AI / Tendayi). `path_counts: hybrid=30, boost=0, symbol=0` — **both pollution paths idle** (zh tokens don't hit code symbols; bucket returned 0). Hybrid's 30 slots contained website/case/wiki pages and — **`website-camthink/company/contact-us` at pool rank 29**. Rerank promoted it (survivor score **0.705**; the chunk text preview in the trace matches the indexed text verbatim). Second control `cf95f652…` ("如何联系技术支持?", hybrid-only) also cited contact-us.

**Stage-by-stage delta (SUCCESS vs FAILURE):** identical index, identical serving generation, identical chunk. Differences: (1) query language/length → zh case text gives code paths zero lexical traction (`symbol=0`, no code in hybrid top-30), while `"head"` in the en query activates 28 code chunks; (2) intent routing → commercial handed 30 slots to woocommerce (boost=30) vs 0; (3) pool pressure → contact-us needed rank ≤30 in a hybrid ordering that code dominated in the failure case. Rerank behavior is a constant (it ranks contact-us well whenever it sees it) — **the pool entry boundary is the defect**.

## 6. Earliest Candidate-Loss Point

`HybridSearcher.search(limit=recall_limit=30)` over the whole 147k-chunk corpus, class-blind, is the sole entry gate for `web_crawl` chunks: `search_symbols` cannot carry them (no `symbol_tokens` — populated only by `chunk_code.py`), and `INTENT_BOOST_FILTERS` (rag.py L447-451) has no bucket containing `web_crawl`/company content for **any** intent (`support→filesystem`, `product→paragraph/heading/list/table chunk_types` — note this bucket COULD carry the contact-us `heading` chunk but only fires for intent=product, not the commercial intent these questions actually get — `commercial→woocommerce`). [PROVEN: config + traces; the "why below rank 30" score ordering is INFERRED (no per-path score telemetry), the entry-failure itself is PROVEN (full 79-member pool dump).]

## 7. Shipping / Source-Coverage Trace — the Class-B example disproven

- `documents` ledger: `website-camthink/shipping-policy` created **2026-09-02 01:25:33**, `chunk_count=3`, `lifecycle=active`, current version present. [PROVEN, read-only SQL]
- Weaviate: Aggregate(source_id equal) → **count=3**, objects at `generation_ordinal=0` (chunk types heading/list/paragraph). [PROVEN, read-only GraphQL]
- Question `654f74b8…` at 09-03 11:46 retrieved firmware code (`arch.h`, `mongoose.c`) → honest decline. The authoritative chunks were already serving. **PROVEN_RECALL_FAILURE.**
- Sync history (369 runs since 08-30: 232 success / 52 partial / 85 failed): new-page ingestion happened in only 4 runs (08-30 +131; 09-01 +2; 09-11 +2; 09-11 +1) — the 09-02 01:25 batch (about-us, contact-us, shipping-policy, payment-methods, developer-center…) corresponds to the manual-era re-crawl after the 08-31 failure storm (18+ consecutive failures). Full crawls are rare; between them, coverage growth depends solely on `lastmod ≥ since` incrementals.
- Residual coverage facts: `register` in ledger despite `/register` exclude (config added after first crawl — drift, over-inclusion); `neomind-local` excludes `docs/` [config PROVEN, impact UNPROVEN]; **live wedge:** all 6 most-recent `website-camthink` syncs FAIL with `修复代 embed 413 (零激活)` → this source currently cannot ingest anything until #75 lands [PROVEN, sync_log.error_detail].

## 8. Blast Radius

From the 119-candidate audit population (no re-audit): **2 PROVEN recall failures** (both named anchors), **1 likely** (ownership — canonical authority outrun by marketing pages, answer still correct), **3 OTHER** (intent-gate/clarify pre-retrieval), **1 coverage-lag** (NE302 product, ≤1 day, resolved), **2 UNPROVEN** (cert reports; NeoMind credential). Test/internal corroboration: 4× "price of NE301 + how to order + shipping options" — the shipping half is never answered, same recall signature. Beyond company/support, the same single-viable-path structure applies to every `web_crawl` chunk (solutions pages, developer-center — ingested, serving, **zero citations in 1427 conversations**) — latent breadth INFERRED.

## 9. Observability Findings (concrete, code-grounded)

| Question the operator asks | Currently answerable? | Gap [evidence] |
|---|---|---|
| 1. Upstream knowledge absent? | NO | Nothing diffs upstream (sitemap/repo) membership vs ledger. web_crawl builds `run_stats` with per-URL rejection lists ("由同步层写入 SyncLog 真实呈现覆盖", web_crawl.py docstring) — **production `sync_log.delta_counts` is empty on every sampled row**: stats computed, never persisted. [PROVEN] |
| 2. Upstream exists, source doesn't cover it? | NO | Same as above; the audited "shipping not ingested" false belief persisted 12 days precisely because neither Admin nor queries surface ledger/vector truth. [PROVEN] |
| 3. Indexed but retrieval misses it? | PARTIAL | Trace shows fused-pool membership only; **no per-path boundary dump, no per-path score lists, no filter-drop counters** (knowledge-exclusion and visibility-guard filter silently). Absence from pool is observable; *why* is not. [PROVEN] |
| 4. Retrieved but rerank rejects? | PARTIAL | `rerank_scored` computes the full weighted score table (`pool_scores`) but it is not persisted; the fallback flag is written **only on the answer path** (rag.py L1770) — **stream traces (the widget path) never record fallback** [PROVEN — sole write site]. |
| 5. Evidence present, generation fails? | YES | `generation_error` trace type + generate stage (ttft/tokens) exist. [PROVEN] |

## 10. Relationship to #71 / #73 / #74 / #77

- **#77:** complementary and sequential — #77 owns composition/eligibility/fallback/slot-truth *after* pool entry; #78 owns *entry into the pool* for company/support-class sources plus coverage observability. No overlap of seam: #77's tiering cannot fix `cbafab32…` (the pool contained zero company chunks to tier).
- **#75:** hard dependency — the `website-camthink` sync pipeline is wedged on the repair-generation embed 413; no coverage change or update lands on this source until #75 is fixed. (#72 same family.)
- **#71:** orthogonal (freshness/false-healthy of *synced* content vs entry/coverage). The current sync *failures* are loud (failed status + error detail), not false-healthy.
- **#73:** requires reclassification — K02 (shipping) is **not** MISSING_KNOWLEDGE/NEW_DOCUMENT; it is a recall failure (this issue). K12's "no dedicated About page" weakens: `about-us` IS ingested and serving (recall/authority-selection issue).
- **#74:** G-02 stays owned here (recall); G-06's "shipping not ingested" premise is corrected by this report; G-01/G-04 remain #77.

## 11. Root-Cause Classification

- **RECALL FAILURE — PROVEN** for `cbafab32…` and `654f74b8…` (trigger: en/commercial company query → mechanism: single class-blind hybrid path + intent bucket excluding web_crawl + code lexical pollution → loss: below hybrid top-30 → user-visible: honest decline/polluted evidence while authoritative chunks serve).
- **SOURCE COVERAGE GAP — DISPROVEN for the audited example** (shipping-policy is ingested and serving); residual coverage items are config-intentional excludes, one drift artifact (`register`), a latent lastmod mechanism, and the live #75 wedge (dependency, owned by #75).
- **ANSWER FAILURE — none new** (declines were honest; generation behaved on the evidence it was given).

## 12. Narrow Remediation Options (analysis only)

- **R1 — recall seam (code, existing mechanism):** extend `INTENT_BOOST_FILTERS` so company/support-carrying sources compete for bucket slots — e.g. commercial gains a `web_crawl` component (and/or support gains one), reusing the existing bucket→RRF→rerank machinery. Addresses the proven cause directly (gives the authoritative class a second, intent-appropriate path). Regression risk: more web-page noise in commercial/support pools (mitigated downstream by #77 tiering + rerank); product/code paths untouched (symbol/hybrid unchanged). RED: replay `cbafab32…`/`654f74b8…` queries against a fixture index containing the real chunks → assert a `website-camthink` company/policy chunk enters the fused pool. GREEN: T1 passes; existing suites green; code-oriented queries unchanged.
- **R2 — coverage observability (code, contract already claims it):** persist web_crawl `run_stats` (discovered/accepted/extracted/rejected+URLs) into `sync_log.delta_counts`; add a sitemap-membership↔ledger diff to the source surface; persist bounded `pool_scores` and write the fallback flag on the stream path (L1770 is the sole write). Directly implements issue requirement "coverage gap must be observable" and would have prevented the 12-day false belief. RED: seeded crawl with a thin-content page → run_stats visible in sync row; stream trace with all-below-threshold rerank shows `fallback:true`.
- **R3 — config review (no change required for the anchors):** document intentional excludes; reconcile `register` drift; revisit `neomind-local docs/` exclusion only if #73 K10 proves content lives there.
- **Explicitly rejected:** keyword/question hard-coding and CamThink-specific aliases (invariant 5/6 — evidence shows a class-level mechanism, not a question-specific one); re-ranking changes (rerank already promotes the chunk — control 0.705); raising global recall limits (indiscriminate; #77 seam owns composition); any new ingestion of shipping content (already ingested — that would "fix" a non-existent gap).

## 13. Recommended Direction

**R1 + R2 (code changes); no knowledge-content addition; no source-config change required for the two anchors.** R1 because the proven loss is pool entry for a source class with no intent-appropriate path; R2 because the second product invariant ("coverage gaps must be observable, not treated as ranking failures") is unimplementable with today's discarded stats. Sequencing dependency: land after/with #77 (composition benefits both) and after #75 un-wedges the source (otherwise no live verification of coverage observability on real syncs is possible).

## 14. RED→GREEN Acceptance Plan

1. **RED-R1a:** fixture hybrid corpus = {28 code chunks containing token "head", contact-us chunk, store chunks}; query "where is your head office", intent=commercial → current pipeline: no `web_crawl` chunk in fused pool (reproduces `cbafab32…`). GREEN: with R1, ≥1 company/policy `web_crawl` chunk in pool AND rerank-orderable (control shows 0.705 when seen).
2. **RED-R1b:** same fixture, query "Do you ship internationally?" → shipping-policy chunk enters pool (reproduces `654f74b8…`).
3. **RED-R2a:** crawl run with one thin-content and one robots-blocked URL → sync row exposes run_stats incl. rejected URLs (currently: empty delta_counts).
4. **RED-R2b:** streaming request with all rerank scores <0.3 → trace carries `fallback:true` (currently absent on stream path).
5. **Regression GREEN:** existing pytest suites green (2630-pass baseline); comparison pipeline untouched; code-oriented queries keep symbol path + hybrid behavior (bucket additions don't touch `search_symbols`); benchmark guards cg-r05/sq-026/sq-045 not regressed.

## 15. PROVEN / INFERRED / UNPROVEN (material claims)

| Claim | Level |
|---|---|
| contact-us/shipping-policy chunks serving in Weaviate gen 0 before the questions | PROVEN (SQL+GraphQL, timestamps) |
| Pool composition & single-viable-path structure for the failure | PROVEN (79-member pool dump + bucket/symbol configs) |
| Query preprocessing was a no-op; intent=commercial | PROVEN (rewrite/understanding stages) |
| Control entry at rank 29 + rerank 0.705 | PROVEN (trace) |
| Stream-path fallback flag never written | PROVEN (sole write site rag.py L1770) |
| run_stats computed but not persisted in production | PROVEN (code contract vs empty `delta_counts`) |
| Sync wedged on 413 since 09-14 15:20 | PROVEN (sync_log.error_detail) |
| Why contact-us ranked below hybrid top-30 (score ordering) | INFERRED (lexical sparsity + code "head" density; no per-path telemetry) |
| Latent lastmod invisibility harming a real page today | INFERRED mechanism, UNPROVEN instance |
| `neomind docs/` exclusion hiding needed credential docs | UNPROVEN |

## 16. Open Questions / Blockers

1. #75 must land before any live validation of coverage observability on `website-camthink` (sync currently fails every run).
2. Whether `/policies/shipping-policy` (non-sitemap URL, HTTP 200) is a distinct page or a redirect/alias of `/shipping-policy/` — irrelevant to remediation (canonical is covered) but worth an upstream note.
3. Role A decision: whether the commercial-intent bucket should carry all `web_crawl` content or a narrower company/policy subset (invariant 6 forbids keyword hacks; a source-type-level rule is the narrowest non-hack seam).
4. `effective_min` semantics (product/support/commercial → 1) made the fallback fire on a *total* rerank rejection; whether a total rejection should ever degrade to raw RRF order for citable answers is a #77-adjacent policy question this investigation records but does not own.

---

**STOP.** Investigation only. No fix implemented; no production mutation; no resync/reindex; no deployment; no new issues created.
