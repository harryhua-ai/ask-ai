# v1.6.4 Engineering Reality Audit — Knowledge & Answer Integrity (#25 / #28 / #31 / #48)

- Date: 2026-09-13
- Auditor: Role A planning run (4 independent parallel audits + code spot-checks + production read-only probe)
- Base tree: `origin/main = 5c501914636ae274bdf54896e3decf86c4584e12` (clean; v1.6.3 B1/B2 candidate branches NOT included by design)
- Production state probed: **v1.6.3 @ ed71be77dc97a08998dce49da23fc5b50dc521ca, `/health` ok, app_mode=production**
- Method: each Issue's original Product Intent / Acceptance (issue bodies incl. v1.6.0 Iteration Scope sections) taken as the contract start point; current `origin/main` code, schema, APIs, ingestion/retrieval/generation/citation paths, frontend/runtime consumers, tests, execution/review reports, and production/runtime evidence checked independently. Six load-bearing claims re-verified by direct code reading before freezing (listed in §7).
- Verdict vocabulary: IMPLEMENTED / PARTIAL / NOT IMPLEMENTED / SUPERSEDED (per acceptance requirement), and reconciliation categories A–D (per issue).

---

## 0. Production read-only probe evidence (2026-09-13, tesla-t4)

| Probe | Result |
|---|---|
| `/health` | `{"status":"ok","version":"1.6.3","git_sha":"ed71be77…","app_mode":"production"}` |
| `documents` lifecycle distribution | **`active`: 12,000 — no other state.** Zero `superseded`/`retired`/`deleted`/`missing_candidate` document rows in production. |
| `documents.url` shapes (n=12,000) | `https://github.com/…` non-wiki: **11,183 (93%)**; `github.com/camthink-ai/wiki-documents…`: **467** (the only class with a canonical mapping); `file://…`: **179**; empty: 0 |
| `index_generations` | 3 rows total: `ready`×2, `failed`×1; `withdrawn_at`/`retired_at` non-null: **0**; `gc_eligible_at` non-null: 1 (no retirement ever exercised) |

Interpretation: the TB-P1 lifecycle *machinery* exists but has **zero production exercise** (no retirement, no GC, no withdrawal); and **93% of the production corpus is GitHub-URL documents outside the only canonical-URL mapping** — directly relevant to #48's verdict and to #25's "retirement truth surface is mostly empty" finding.

---

## 1. Issue #25 — Filesystem disappearance / retirement / withdrawal / GC lifecycle

### 1.1 What actually exists on main (verified)

Lifecycle **foundation** is real and tested (TB-P1, v1.6.1):

- Four-state document lifecycle + version/generation model: `backend/services/document_lifecycle.py` (constants `RETIRED_RETENTION_DAYS=7` :90, `SERVING_WITHDRAWAL_MAX_DAYS=1` :94; `retire_generation_if_withdrawn` :235-261; serving projection `active_generation_ordinals_sync` :269-283; `activate_document_version` :340-385; `tombstone_document` :388-406).
- Atomic activation / immediate supersession at version level: `backend/pipeline/generation_builder.py:372-452`; withdrawal+RETIRE is Phase 6 of the same commit (:448-452) — so withdrawal is **immediate** (stronger than the 1-day cap).
- Fail-closed serving projection wired into retrieval: `backend/main.py:368-382`, `backend/retrieval/search.py:439-454` (empty authoritative set ⇒ zero results; provider failure ⇒ exception).
- Connector-declared removal (tombstone) exists for: `backend/connectors/github.py:397-430` (git log diff-filter), `local_git.py:192`, `web_crawl.py:728-760` (full-round membership diff, kill-safe snapshot). Consumed at `scripts/sync.py:1069-1083`.
- Vector-side orphan retirement (`EXTRA_CONFIRMED_RETIRED`) with completeness guards: `scripts/sync.py:648-860`, `backend/services/vector_consistency.py` (read-only checker).
- GC engine: `backend/services/lifecycle_gc.py:84-222` (RETIRED past `gc_eligible_at` purge; SUPERSEDED docs at +7d; DELETED docs only if tombstone-days configured — default off, `backend/config.py:49`). **Trigger = manual CLI only** (`scripts/gc_lifecycle.py`, dry-run default). No cron/compose/lifespan caller exists (grep-verified).
- Admin truth surface (#50, shipped v1.6.2, production-accepted): `backend/api/admin/data_sources.py:811-1135` + `admin/src/lib/dataSourceLifecycle.ts` (three buckets + per-state WHY).

### 1.2 Acceptance matrix

| # | Requirement | Implementation evidence | Test evidence | Runtime/production evidence | Residual gap | Verdict |
|---|---|---|---|---|---|---|
| R1 | Superseded/removed must not remain Current Truth; loses it immediately on replacement | Version supersession immediate (`document_lifecycle.py:340-385`; serving set :269-302) | `tests/services/test_document_lifecycle.py:194`; `tests/pipeline/test_generation_builder.py:220` | Migration acceptance §18: **zero production supersession events** ("被阻断，无生产证据可采”) | *Removal* (disappearance) ≠ supersession: a vanished file keeps `lifecycle=active` + serving **indefinitely**; doc-level `set_successor` has zero production callers | **PARTIAL** |
| R2 | Withdraw from serving ≤1 day, then RETIRED | Immediate at activation commit; `retire_generation_if_withdrawn` :235-261 | Constants frozen `test_document_lifecycle.py:101-104`; `:274-310` | §18: withdrawal has no production occurrence | Correct for existing flows; disappearance triggers no withdrawal at all | **PARTIAL** |
| R3 | RETIRED retained 7 days, then eligible for **automatic** physical GC | `RETIRED_RETENTION_DAYS=7`, `gc_eligible_at` column, purge logic `lifecycle_gc.py:96-143` | `tests/services/test_lifecycle_gc.py:169-276` (7d gate, exact-UUID purge, idempotence) | §19: **one manual dry-run ever**, empty eligibility; `--apply` never run; no scheduler wiring anywhere | **"Automatic" is not true** — nothing triggers GC in production | **PARTIAL** |
| R4 | 1-day window must not make old+new co-equal Current Truth | Single-transaction activation; derived fail-closed serving set | `test_generation_builder.py:220` (serving switches exactly once) | Freeze clause + in-serve `[0]×12,000` verified post-migration | None for implemented flows | **IMPLEMENTED** |
| R5 | No retirement from a single transient failure / permission error / timeout / vector absence | Completeness guards `sync.py:648-710` (fetch failure / discovered==0 / coverage<80% ⇒ not confirmable); tombstone only from connector-declared events; vector absence → repair, never delete | `tests/pipeline/test_sync_lifecycle.py` G003b/G004a-e | D-11 / P1-RES production prune evidence (vector side) | N-consecutive-discovery confirmation **not built** (single complete discovery is the current standard); moot for fs/woo (no removal path) | **IMPLEMENTED** (guards real; N-confirmation absent) |
| R6 | Retirement auditable + idempotent | Timestamps (`deleted_at/withdrawn_at/retired_at/purged_at`), GCReport, SyncLog `items_deleted` | Idempotence tests `:254,309-310`; `test_lifecycle_gc.py:274-276`; `test_sync.py:500-532` | SyncLog rows live in production | Tombstone **reason is logged, not persisted**; GCReport not persisted; no retirement-event record | **PARTIAL** |
| R7 | Generic across filesystem / website / GitHub / WooCommerce | Primitives connector-agnostic; removal proof: github/local_git/web_crawl real; **filesystem `fetch_deleted` returns `[]` (`backend/connectors/filesystem.py:212-219`, spot-checked), woocommerce `return []` (`woocommerce.py:333`)** — both documented as honest degradation | `test_filesystem.py:150-156` and `test_woocommerce.py:118-130` **lock in** the empty return | Production sources include fs+woo types | **2 of the 4 named connector classes have no removal proof** | **PARTIAL** |
| R8 | #30 inventory: Admin distinguishes Current / Needs Attention / Retired + WHY | Read-only truth endpoints + three-bucket mapping + per-state reason text (see §1.1 last bullet) | 24-test workspace suite (`tests/api/admin/test_data_source_workspace.py`) | v1.6.2 production acceptance: truth walkthrough wiki 467 / woo 41 | `missing_candidate`/doc-`superseded` buckets unreachable in practice (no producer); tombstone why = timestamp only | **IMPLEMENTED** (surface complete; underlying truth mostly empty) |
| R9 | Acceptance: prove create/update/supersede/remove/retire/GC without mixed truth or silent deletion; GC default 7d | All primitives exist + tested; P0-A exact-UUID deletion; dry-run defaults | Full unit coverage per primitive | Only create/update proven in production; supersede/tombstone/withdrawal explicitly unproven (§18); GC never applied; remove (fs) nonexistent | remove→retire→GC chain **not exercisable** for fs/woo; GC never runs automatically | **PARTIAL** |
| R10 | **(Founding defect)** Filesystem file disappearance must eventually retire the ledger row | `filesystem.py:212-219` still `return []`; no snapshot diffing; no ledger-side full-discovery confirmation exists anywhere | `test_filesystem.py:150-156` asserts the empty return as *intended*; no test anywhere asserts fs-disappearance retirement | Issue #25 documents the 2026-09-05 production incident (26 stuck rows, manually repaired); post-migration the same scenario now **resurrects deleted content** from PG persistent chunks via gap-heal (`sync.py:565-567` → `generation_builder.py:613-659`) | **The issue's core is not built** | **NOT IMPLEMENTED** |
| R11 | Reconciliation truth surface explicit, no silent auto-heal | `_handle_no_change` explicit skip / targeted repair with recorded `error_detail` (`sync.py:474-645`) | G006; `tests/scripts/test_sync_gap_heal.py` | D-11 prod review | Gap-heal rebuilds from PG truth but is recorded, not silent | **IMPLEMENTED** |

Additional verified interaction facts: include_dirs/file_types/exclusion **policy-absence is indistinguishable from source-removal** in every lifecycle path (no code treats it); policy-invisible rows would also remain Current Truth forever.

### 1.3 Residual list (feeds planning)

1. Ledger-side disappearance confirmation + retirement for filesystem (and connector-deletion-less sources incl. WooCommerce): the founding defect (R10).
2. Absence-confirmation producer for `missing_candidate` (temporarily-unavailable vs source-confirmed-removed distinction) — currently unreachable in practice.
3. Automatic GC trigger wiring + controlled first production apply (R3 "automatic").
4. Policy-absence (include_dirs/file_types/exclusion) explicit classification — must not be confirmable as source-removal.
5. Persisted retirement reason/evidence (audit depth, R6).
6. (Optional/derived) doc-level identity supersession (`set_successor`) remains unreachable — either wire or explicitly retire the concept.

---

## 2. Issue #28 — WooCommerce variation / SKU / price / stock authoritative truth

### 2.1 What actually exists on main (verified)

- WooCommerce ingestion lives at `backend/connectors/woocommerce.py` (registered :351; production source `woocommerce-mall`; website crawl explicitly excludes store pages :47 — no parallel store path).
- **Endpoints called: only `GET /wp-json/wc/v3/products`** (`_fetch_page` :293-300; incremental `modified_after` :324). **`grep -rn "variations" backend/ tests/ scripts/` → zero hits.** No `/variations` call exists anywhere. `fetch_deleted` returns `[]` (:333-347).
- One RawDocument per **parent** product (`_product_to_document` :229-291) with metadata `product_id, sku, price, regular_price, sale_price, stock_status, stock_quantity, categories, type, status, date_modified` (:275-287).
- **Chunk-level metadata loss**: Weaviate schema has **no commerce properties** (`backend/pipeline/ingest.py:240-271`; `_build_props` :297-332 never reads `doc.metadata`). Commerce fields survive only as connector-formatted prose ("Price: $X / SKU: …", woo :246-258) wherever chunking keeps them together. PG `documents.metadata_` JSONB does receive them (`db/models.py:74`).
- Corpus reality (F-1' report §5.1): NE101 store doc has only base price $69 + SKU family names; **the $69–$112 variation band does not exist in the corpus**.
- Existing retrieval/authority scaffolding (generic, tested): commercial intent → RRF boost bucket restricted to `source_type=["woocommerce"]` (`backend/pipeline/rag.py:438-442`); STORE_OFFICIAL required+citable slot (`evidence_planning.py:181-193`, `evidence_selection.py:78,192-194`); F-1' evidence reservation (`backend/pipeline/evidence_reservation.py:200-247`); store eligibility (`backend/product_taxonomy.py:40-49`); commercial frame prompt directive against price folding/fabrication (`response_strategy.py:168-178`, fires only when `category=="commercial"`); product isolation gates (`product_taxonomy.py:270`, `evidence_selection.py:205-208`).
- Generation numeric rule (the overstatement mechanism): `rag.py:1154-1157` mandates “资料未载明时，明确说明『官方资料未载明该数值』” — scoped to retrieved context only.
- Admin (#50): doc-level inspection shipped/production-verified, but schemas have **no sku/price/stock fields**; nothing variation-level exists to inspect.
- Governance: KNOWLEDGE-INTEGRITY freeze line 97 routed Woo variant ingestion to **Trace B Phase 3**; TB-P1 explicitly did not absorb it; **TB-P3 has not started** (no P2/P3 execution reports exist). This iteration contract supersedes the routing in favor of v1.6.4 (see §6 Reconciliation).

### 2.2 Acceptance matrix

| # | Requirement | Implementation evidence | Test evidence | Runtime/production evidence | Residual gap | Verdict |
|---|---|---|---|---|---|---|
| R1 | Repro no longer claims official NE101 pricing absent when Store pricing exists | Store eligibility + citability fixes shipped | sq-080 FAIL→PASS | **cg-r05 (frozen verbatim repro) = FAIL/FAIL** at last run (follow-up report §4); variation band absent from corpus | Per-model prices still unanswerable → false-absence still structurally possible | **PARTIAL** |
| R2 | Actual purchasable variation prices with correct SKU/attribute association | None — no variation ingestion | None | F-1' §5.1: “Woo 变体价格未入灌入管道” | Whole feature missing | **NOT IMPLEMENTED** |
| R3 | NE301 config pricing from Store w/o technical regression | Store slot + reservation | cg-r06/cg-r09 normal | "NE301 半边达标” (follow-up §4) | Per-config prices = same variation gap | **PARTIAL** |
| R4 | No single parent-price collapse for per-config asks | Prompt-only directive `response_strategy.py:175-177` | frame tests only | Parent $69 is the only price in corpus | No variation data to collapse *from*; directive fires only for commercial category | **NOT IMPLEMENTED** (data side) |
| R5 | No fabricated combinations (no Cartesian product) | Prompt prohibition; claim_validation numeric grounding | claim validation suite | No combination generation exists | Vacuously true; needs ingestion-side real-variation identity to become enforceable | **PARTIAL** (vacuous) |
| R6 | Store evidence selected/retained for price queries when healthy+relevant | Boost bucket + required STORE slot + F-1' reservation | 13 reservation tests + correctives suite (27 green locally) | 38 commercial chunks unlocked (90fac46); cg-r05 T1a fixed | Only when intent=**commercial**; mixed config+price routed to `product` bypasses all STORE handling (intent prompt excludes mixed from commercial by definition, `backend/pipeline/intent.py:21-40`) | **IMPLEMENTED** (parent-level, commercial-intent only) |
| R7 | Static docs cannot cause false "no official price" when Store truth available | Citable-case fix; **but** generation prompt still mandates context-scoped absence (`rag.py:1156-1157`); no Store>docs price-authority rule exists | false_absence mechanism documented in correctives suite | RCA: model claimed 官方未载明 while evidence invisible (follow-up §2) | Price-authority precedence absent (F-1' residual #2) | **PARTIAL** |
| R8 | Truthful freshness/source semantics for current price | Sync-window only (`sync.py:428-447`); `source_verified_at` nullable column, ops semantics deferred; `evidence_meta` temporality **always unknown** (frozen contract); no stale/commerce result keys | INC-2b explicitly not built | sq-026 run2 reported historical $59/$109 as current | No answer-visible price freshness semantics at all | **NOT IMPLEMENTED** |
| R9 | Product isolation intact | Taxonomy gates + scope check + device identity derivation + migration script | Sibling-exclusion + taxonomy tests | v1.1.2 identity corrections live | — | **IMPLEMENTED** |
| R10 | Generic, not CamThink-hard-coded | F-1' genericity proven (no IDs/URLs/expected-answer anchoring) | Stub-fixture tests | — | `_DEVICE_CATEGORY_MAP` hardcodes device slugs as **config** (acceptable); variation implementation doesn't exist to assess | **PARTIAL** |
| I1 | Variations endpoint fetched | **None — zero hits repo-wide** | None | Discovery:343 “woo variations 零摄取” | Entire fetch missing | **NOT IMPLEMENTED** |
| I2 | Per-variation docs w/ attributes/SKU/prices/stock + anti-conflation identity; chunk-level metadata persistence | None; chunk props drop commerce metadata entirely | None | — | — | **NOT IMPLEMENTED** |
| I3 | Freshness/sync semantics for commercial truth | Sync window only | — | — | No retrieval/answer-visible freshness | **PARTIAL** |
| I4 | #30/#50 inspectability of product/variation representation | #50 shipped (doc-level, production-verified) | v162-i50 suite | woo 41 docs canonical IDs verified | No sku/price/stock fields in admin schemas; nothing variation-level | **PARTIAL** |

### 2.3 Residual list (feeds planning)

1. Variations endpoint ingestion (I1) + per-variation first-class truth: attributes/SKU/regular/current/sale price/stock/purchasability/canonical identity (I2, R2).
2. Chunk-level structured commerce metadata (anti-conflation identity), not prose-only (I2).
3. Answer-side price-authority rule (Store > static docs) + absence semantics fix (R7, shared with #31 R6).
4. Mixed config+price intent boundary (R6/R3 remainder): mixed questions must reach Store handling.
5. Freshness/staleness semantics for commercial truth (R8/I3).
6. Admin variation/SKU/price/stock inspectability (I4 remainder).
7. cg-r05 end-to-end acceptance with real variation truth (R1 final closure).

---

## 3. Issue #31 — Solution/Case/Wiki evidence authority, claim ownership, composition/precedence

### 3.1 What actually exists on main (verified)

Pipeline map (answer/stream parity verified): task understanding (4-class intent; `backend/pipeline/task_understanding.py:68-112`) → product resolution → evidence planning with 4-role vocabulary `PRODUCT_SPEC / SOLUTION_GUIDE / CASE_EVIDENCE / STORE_OFFICIAL` (`evidence_planning.py:43-52`; **category-level, not claim-level**; recommendation plan :195-214) → hybrid+symbol+intent-bucket RRF retrieval (`retrieval/search.py`, `retrieval/rrf.py`; intent buckets `rag.py:438-442`; **no source-role weighting anywhere**) → rerank by chunk_type only (`retrieval/rerank.py:36-42`) → F-1' plan-driven evidence reservation (required-slot / anchored-store-page / spec-rescue; `evidence_reservation.py`, comparison-exempt) → role-predicate evidence selection (`evidence_selection.py:161-263`) → coverage + response strategy frames (`response_strategy.py`) → source extraction + citation context (`rag.py:1170-1231`, `citation.py:125-237`) → citation enforcement + INC-6 claim validation (role attribution **trace-only**; `claim_validation.py:10-11` explicitly disclaims authority correctness).

Key predicates (spot-checked): `_SOURCE_CASE = "filesystem"` (`evidence_selection.py:75`) — **CASE_EVIDENCE matches filesystem only**; official website case-study pages (web_crawl) can only satisfy SOLUTION_GUIDE via title/doc_section signals (`:64-72`). Solution pages have **no retrieval bucket** (boost buckets cover support/commercial only). `evidence_meta.evidence_authority_class` is **always `"unknown"` by design** (INC-2A safety revision; no producer, no runtime consumer) — a dormant authority dimension.

### 3.2 Acceptance matrix

| # | Requirement | Implementation evidence | Test evidence | Runtime/production evidence | Residual gap | Verdict |
|---|---|---|---|---|---|---|
| R1 | Solution queries retrieve/retain official Solution pages | SOLUTION_GUIDE required slot (product+recommendation); solution title/doc_section signals; required-first ordering; F-1' promotion | INC-4/5 selection tests | cg-r07 live-verified at deixis level; no evidence the infrastructure-monitoring page is retained e2e | No solution retrieval bucket; signal-only matching (false-negative risk; EN signals untested) | **PARTIAL** |
| R2 | Case studies as proven-deployment evidence | CASE_EVIDENCE role; first-party cases citable-numbered | INC-5 red4/red4b; INC-6 attribution | sq-080 case [5] cited | **CASE_EVIDENCE matches `filesystem` only** — website `/case-studies/` pages can't satisfy the case role; no "proven deployment" vs historical-support-case distinction; NexAscent page indexing unverified | **PARTIAL** |
| R3 | NE101 Wiki facts available when needed | PRODUCT_SPEC slot; F-1' R3a/R3b spec rescue (incl. focused re-search) | reservation tests; F-1' §5.2 causally proven | wiki matrix chunk confirmed in context | Availability yes; but answers still cited the case for baseline specs (sq-045 FAIL) — an R11 failure, not availability | **PARTIAL** |
| R4 | Model/use-case evidence available when discussing capability | Generic retrieval only; tools buckets via taxonomy | sq-034 composition PARTIAL-pass | #29 tools pages citable in production | **No model/use-case/capability role** in the role vocabulary; SDK/API and compatibility claim mappings absent | **PARTIAL** |
| R5 | Distinguish validated facts vs recommendation vs site assumptions | Recommendation-frame directive (fact/recommendation split; gap disclosure) | INC-7 frame tests; sq-034 judgment | — | Prompt-only; zero deterministic enforcement | **PARTIAL** |
| R6 | No false absence claims when eligible first-party evidence exists | **Operative instruction is the opposite polarity**: `rag.py:1156-1157` mandates “官方资料未载明该数值” when absent **from retrieved context**; mitigation = recommendation-frame only | **Zero tests assert absence-claim semantics** | sq-026 production false-absence RCA'd | Cross-source-class absence assessment does not exist anywhere | **NOT IMPLEMENTED** |
| R7 | Multi-source answers preserve complementary evidence roles | Multi-role plan slots; required-first ordering; background section preserves non-citable evidence; per-role coverage truth | INC-4/5 + reservation suites | v1.5.0 production: multi-class visitor sources observed | Retention is category-level, not per-claim; visible-sources cap 5 + top_k=10 can still collapse multi-layer answers | **PARTIAL** |
| R8 | Existing contracts intact (isolation / comparison / citation integrity / fail-closed) | All gates verified in code | Dedicated suites (comparison 35KB, citation integrity, trust boundary, generation filter) | Red lines cg-r03/r04/cg-s01 byte-identical through F-1' + production | None identified | **IMPLEMENTED** |
| R9 | EN/ZH equivalent solution queries → equivalent coverage | Bilingual signal list; i18n path folding; cross-language equivalence required in understanding prompt | ML-G001..G013 exist but **no EN/ZH solution-evidence pair** | — | Equivalence only implicit; nothing asserts/measures it | **PARTIAL** |
| R10 | Generic core (no hard-coded water meter/NE101/URLs) | Taxonomy-driven; F-1' genericity statement; NE101 appears only in RCA docstrings | Brand-plural generic anchoring test | — | Orthogonal exceptions noted (canonical_url constants; bootstrap seed) — belong to #48/deploy, not #31 | **IMPLEMENTED** |
| R11 | **Claim-type → authority precedence exists in code (the v1.6.0 residual)** | **Exhaustively searched: absent from all five candidate layers** (retrieval scoring / rerank / evidence selection / generation instructions / citation layer); INC-6 attribution is trace-only; `evidence_authority_class` dormant | None possible — nothing exists | Both prior reports name it as deferred product decision (“规格>案例 引用优先”) | **Entire v1.6.0 authority mapping absent from main** | **NOT IMPLEMENTED** |

### 3.3 Residual list (feeds planning)

1. Claim-dependent authority mapping + enforcement point(s) (R11) — the issue's own v1.6.0 scope, zero implementation.
2. Absence-across-eligible-source-classes semantics (R6) + fix of the context-scoped absence instruction.
3. CASE_EVIDENCE eligibility for website-published case studies + proven-deployment role distinction (R2).
4. Solution-page retrieval retention path (R1 remainder) + model/use-case owning role (R4).
5. EN/ZH solution-equivalence regression pair (R9).
6. (Sanity) deterministic enforcement for fact/recommendation separation stays honest prompt-level — acceptance via eval, not fake determinism.

---

## 4. Issue #48 — Canonical citation URL end-to-end

### 4.1 What actually exists on main (verified end-to-end flow)

`connector → RawDocument.url` (contract `base.py:40`):
- **github**: `https://github.com/{owner}/{repo}/blob/{branch}/{rel}` (`github.py:317`; title = file stem :315; metadata carries path/branch/repo_url). Built unconditionally — **no repo visibility/accessibility awareness** (token-embedded clone for private repos :146-153).
- **filesystem/local_git**: `file://{abs}` (filesystem.py:120, local_git.py:140; local_git no longer registered but still linkable, see below). **woocommerce**: `permalink`, may be `""` (woo :242, :274). **web_crawl/website**: real canonical page URL (:605, :117-133).

Persistence verbatim: Weaviate `url` property (`ingest.py:241-260,318`); PG `documents.url`/`document_versions.url` (`models.py:73,122`); conversation `sources` JSONB raw. No URL rewrite/backfill exists — stored URL frozen at ingestion (documented `canonical_url.py:20-23`).

Retrieval verbatim (`search.py:481`, default `""`). Citation context prints URL to LLM (`citation.py:209`).

**The one intentional transformation**: `RAGOrchestrator._extract_sources` (`rag.py:1170-1231`): `wiki_canonical_url(r.url)` maps **only** `github.com/camthink-ai/wiki-documents/blob/<ref>/docs/**.md` (+i18n) → `https://wiki.camthink.ai/docs/…` (`canonical_url.py:43-89`, spot-checked constants); everything else **passes through unchanged** (no fabrication). First-party knowledge cases get `"url": ""` **deliberately** (privacy; `rag.py:1214-1229`). `PUBLIC_SOURCE_TYPES = {local_git, github, woocommerce, website, web_crawl}` (`citation.py:54-56`, spot-checked) — **`local_git` still included despite `file://` URLs**.

API serialization passthrough (`routes.py:289-296` SSE; sync `RAGAnswer.sources`). Click telemetry endpoint exists (`routes.py:540-555`) — **widget never calls it**.

**Widget = the fabrication point (spot-checked)**: `widget/src/utils/sanitize.ts:84` renders the `[N]` badge as `<a href="${escapeHtml(src.url)}" …>` with **no empty-URL guard and no `isAllowedUrl` check** (Markdown links ARE gated, :47-56). `href=""` renders a clickable self-navigating badge; `file://` renders a dead badge. Admin, by contrast, guards correctly (`DataSourceDetail.tsx:457-468`, `Conversations.tsx:696-707`).

### 4.2 Acceptance matrix

| # | Requirement | Implementation evidence | Test evidence | Runtime/production evidence | Residual gap | Verdict |
|---|---|---|---|---|---|---|
| R1 | Repro-class GitHub citations resolve to authoritative source | CIT-URL wiki canonical mapping (commit `0403248`, in all current builds); wiki path sitemap-verified | `test_canonical_url.py` (17 cases) + `test_rag_citation_source.py` — **21 passed locally on this tree** | v1.6.2 acceptance: wiki 467/467 truth-consistent | **Non-wiki GitHub sources (11,183 docs = 93% of production corpus) pass through unmapped**; private repos → public-looking 404s (the Sep-11 trace mix: Dockerfile/build/SDK repos) | **PARTIAL** |
| R2 | No dead/malformed/misdirected clickable citations | Only Markdown links are whitelist-gated | sanitize tests cover markdown policy, **not badges** | T29 click test used a public blog URL | **Badge path unguarded**: `href=""` (cases) and `file://` (legacy local_git) render clickable; private-repo 404s | **NOT IMPLEMENTED** (for badges) |
| R3 | GitHub repo/ref/path identity preserved | Full identity in stored URL + metadata + `provenance_url` + trace | `test_github.py:238`; provenance asserted `test_rag_citation_source.py:76` | wiki truth panel verified | Ref = **branch name, not SHA** → move/rename staleness window until next successful sync | **IMPLEMENTED** (branch-ref caveat) |
| R4 | No-URL sources rendered non-clickable | Backend blanks case URL (privacy intent); **Admin** guards correctly | Admin guard untested; **no widget empty-url test exists** | — | **Widget renders `<a href="">`** — direct violation of "no fake navigability" | **PARTIAL** (admin yes / widget no) |
| R5 | Navigation fix must not alter retrieval/grounding | Mapping is display-layer only; provenance bridge preserves numbering; grounding text unchanged | numbering + stream-parity tests | CIT-URL zero-regression gates G002/G005 PASS | None | **IMPLEMENTED** |
| R6 | Inline numbering/rendering no regression | CitationStreamFilter + validate_citations + widget CIT-01 layer | 30+ citation-integrity cases; 14 widget cases; T29 30/30 vitest | T29 real-browser badge DOM verified | None | **IMPLEMENTED** |
| R7 | EN/ZH equivalent | i18n tree → same canonical page; locale dedup | canonical + source tests | G003 PASS | Deliberate default-locale canonicalization | **IMPLEMENTED** |
| R8 | Generic + tested across representative source types | Mapping repo-scoped (constants, not NE503-hardcoded); per-type passthrough | github/website/woo/filesystem URL tests exist | Real-stack smoke for web_crawl | `local_git` citation-layer behavior untested; **no automated cross-source "no dead citations" suite; no stored-URL→API→href e2e assertion** | **PARTIAL** |
| R9 | End-to-end chain survival | Full flow mapped with every transformation point identified | Chain covered piecewise | Production corpus carries frozen URLs | No single e2e test for one GitHub doc's URL chain | **PARTIAL** |
| R10 | UI semantics: valid / none / stale / private | Valid: clickable both UIs. None: admin non-clickable; **widget clickable-empty**. Stale: **no detection anywhere**. Private: **no awareness anywhere in chain** | Untested states | Operator diagnosis via doc truth panel + trace | Stale/private/no-URL unrepresented in widget; click telemetry orphaned | **PARTIAL** |

### 4.3 Residual list (feeds planning)

1. Widget badge/link validity gate: no fake navigability for empty/`file://`/non-http/private-inaccessible sources (R2/R4/R10).
2. Linkability as explicit backend-owned citation state (widget must not guess) — closes the `url=""` ambiguity by contract.
3. GitHub private/inaccessible repo semantics (connector knows visibility at clone time) — no fake public navigability (R10).
4. `local_git` removal from linkable classes / legacy `file://` hazard (R8/R2).
5. Staleness semantics (branch-ref 404 window) made explicit & truthful (R10).
6. Cross-source citation URL regression suite incl. stored→API→href e2e (R8/R9); optional: wire click telemetry.

---

## 5. Issue #25/#28/#31/#48 — what is NOT in scope of any residual (verified as fine)

- #25 R4/R11 + #50 admin surface: done, production-verified; do not re-develop.
- #28 R9 product isolation + store eligibility/reservation scaffolding: done; v1.6.4 builds **on** it, not around it.
- #31 R8 contract set (isolation/comparison/citation-integrity/fail-closed) + F-1' reservation: green; v1.6.4 must not regress (red lines cg-r03/r04/cg-s01).
- #48 R3/R5/R6/R7: identity preservation, display-layer-only mapping, numbering, EN/ZH: done; preserve.

---

## 6. Reconciliation (Phase 2 verdicts)

| Issue | Category | Rationale |
|---|---|---|
| #25 | **B — Partial: define residual scope only** | Foundation (four-state lifecycle, immediate supersession, 7d GC eligibility, admin truth) implemented + tested; founding defect (fs disappearance retirement), absence-confirmation producer, automatic GC, policy-absence classification, persisted retirement reasons are the residual. No superseded content; nothing closeable. |
| #28 | **C — Not implemented & still valid: keep for v1.6.4** | Core commitment (variation-level truth) has **zero implementation** (no `/variations` call anywhere; no commerce chunk metadata). Existing scaffolding is adjacent, not satisfying. The prior "Trace B Phase 3" routing is hereby superseded by this v1.6.4 iteration contract (same scope, executed now; no conflicting parallel design permitted). |
| #31 | **B — Partial: define residual scope only** | Category-level composition + complementary retention + intact contracts shipped (v1.5.0 wave); claim-level authority (R11) and absence-across-classes (R6) have zero implementation; case-role gap for website case studies. Merged with #28 into one authority track (see plan) because price-authority **is** a claim-authority instance and both touch the same pipeline files. |
| #48 | **B — Partial: define residual scope only** | CIT-URL wiki canonical mapping (467 wiki docs) shipped + identity/numbering/parity done; badge validity gate, linkability state, private/stale semantics, local_git hazard, cross-source e2e suite are the residual — against a production corpus that is **93% unmapped GitHub URLs**. |

**No issue qualifies for A (close) or D (superseded).** Nothing may be closed in this planning pass.

---

## 7. Audit integrity notes

Six load-bearing claims were re-verified by direct code reading immediately before freezing (all confirmed):
1. `backend/connectors/filesystem.py:212-219` `fetch_deleted` → `return []`.
2. `backend/pipeline/rag.py:1154-1157` context-scoped absence instruction (“官方资料未载明该数值”).
3. `backend/pipeline/evidence_selection.py:74-76` `_SOURCE_CASE = "filesystem"`.
4. `widget/src/utils/sanitize.ts:84` badge anchor `<a href="${escapeHtml(src.url)}">` unguarded.
5. `lifecycle_gc.sweep` callers = `scripts/gc_lifecycle.py` only (no scheduler/cron/compose/lifespan); tombstone GC default off (`backend/config.py:49`).
6. `backend/pipeline/citation.py:54-56` `PUBLIC_SOURCE_TYPES` includes `local_git`.

Focused tests executed during audit (read-only-safe, all green): `test_evidence_reservation.py` + `test_inc4_evidence_planning.py` (35), `test_inc5_evidence_selection.py` + `test_inc7_response_strategy.py` (56), `test_canonical_url.py` + `test_rag_citation_source.py` (21).

Key prior reports consulted: `tb-p1-lifecycle-foundation-{plan,execution}.md`, `tb-p1-production-migration-runtime-acceptance.md` (§18/§19 = supersession/withdrawal/GC production evidence explicitly absent), `v162-i50-data-source-workspace-v2-execution.md`, `v162-production-acceptance.md`, `issue26-31-answer-intel-shared-execution.md`, `issue28-31-followup-corrective-execution.md`, `issue28-f1p-retrieval-corrective-execution.md`, `trace-a-release1-v150-production-acceptance.md`, `BUG-FIX-SPRINT-REVIEW-MANIFEST.md`, `KNOWLEDGE-INTEGRITY-INITIATIVE-FREEZE.md`, `KNOWLEDGE-FRESHNESS-RETRIEVAL-INTEGRITY-DISCOVERY.md`, `docs/implementation/CAMTHINK_V1_PRODUCT_UX_CITATION_OFFTOPIC_2026-09-02.md`, `t29-widget-citation-number-*.md`.
