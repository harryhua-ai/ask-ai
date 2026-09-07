# INTELLIGENT ANSWER ENGINE — ENGINEERING DISCOVERY

- **Gate**: ASK-AI / Intelligent Answer Engine / Engineering Discovery
- **Date**: 2026-09-07
- **Inputs**: Target Architecture `7a535449` · Attribution REV2 `81482fc0` · Baseline `PB-V1-20260907-CDBCAD3` · production code at `cdbcad38` (local main HEAD)
- **Method**: read-only code/schema inspection at the production SHA + retained baseline artifacts. No production contact, no reruns, no mutation. Live-corpus (Weaviate) contents were NOT inspected in this gate; corpus-level claims below are marked as documentary vs inspected.
- **Report location**: `docs/engineering/discovery/` (docs repo; no stronger established location exists — `docs/engineering/` holds all engineering reports).

---

## 1. Executive Summary

The accepted architecture is **feasible as an evolution, not a rewrite**. Today's runtime already contains: a structured retrieval layer with pluggable metadata (`SearchResult`, 8 Weaviate properties + 7 in-memory fields), an intent-boost bucket mechanism that already isolates internal case retrieval (`product="knowledge"` support bucket), a per-target planned-evidence pipeline for comparisons (the exact embryo of Evidence Planning), a two-line channel trust boundary (index filter + fail-closed guard), a citation filter with a deterministic marker state machine, and a stage-level `Trace` table (JSONB `stages`) that already records most decision points coarsely.

What is missing is **semantics and decisions, not infrastructure**: no evidence metadata (authority/currency/sensitivity/citation-eligibility) exists anywhere in the pipeline; the three pre-retrieval gates make open-input decisions by surface form; background composition is unchecked and unredacted; response strategy is implicit in the generator; and per-candidate traces are not retained (the direct cause of 49/73 K9 attribution entries).

Four increments are contract-ready now (observability completion; task-understanding consolidation; evidence-metadata schema + deterministic backfill; and the redaction-compatible ingestion boundary), the remainder need bounded further discovery (redaction quality sample, slot taxonomy, strategy mapping ownership, claim granularity). Latency is manageable **only if** the task model consolidates the three existing serial pre-retrieval LLM calls instead of adding to them.

**Observability-first: YES** — evidence-based recommendation in §11.

## 2. Current Runtime Map (verified at `cdbcad38`)

```
routes.ask (SSE, rate-limited 20/min)
 ├─ mask_pii(user msg)                      [routes.py:128]  — user message only
 ├─ lead context + site gate + language resolve (resolve_answer_language, pure fn)
 ├─ budget pre-check (S2 circuit)
 └─ RAGOrchestrator.stream_answer (rag.py:1567)
     ├─ override_matcher.match              [admin answers]
     ├─ _social_answer                      [social.py — anchored regex, 5 kinds × zh/en, ≤30 chars]
     ├─ _resolve_product_boundary           [product_resolver.py — pure fn; MODE exact/
     │                                       comparison/ambiguous/unsupported/none;
     │                                       AMBIGUOUS/UNSUPPORTED → canned, pre-retrieval]
     ├─ classify_intent (LLM, 4 labels)     [intent.py — fail-open product]
     ├─ extract_query (LLM) → rewrite_query (LLM)
     ├─ _retrieve_and_fuse                  [rag.py:735 — hybrid(BGE-m3+BM25) + symbol
     │                                       BM25 + intent-boost bucket → rrf_fuse k=60]
     ├─ comparison? → _comparison_evidence_pipeline (per-target retrieval + quota
     │                + focus rerank + own_final D-preflight)   [rag.py:190-…]
     ├─ rerank: bge-reranker, threshold 0.3, top_k 10, chunk_type weights
     ├─ pruner: LLMPruner (deepseek-v4-flash, batch, fail-open)
     ├─ defensive eligible-slug filter
     ├─ min-gate → fused-fallback → canned insufficient rejects
     ├─ sources = _extract_sources (PUBLIC_SOURCE_TYPES whitelist, top5, dedup)
     ├─ build_citation_context              [citation.py:102 — numbered citable +
     │                                       UNLABELED background(filesystem cases)]
     ├─ LLM stream (task="generation", thinking disabled)
     │   └─ CitationStreamFilter            [dangling / numeric-presence / product-eligibility]
     └─ persistence: Conversation + Trace(stages JSONB) + lead
```

LLM calls on the critical path today: **intent → extract → rewrite → (pruner) → generation = 4–5 serial calls** (pruner is a small model; lead qualifier runs in parallel). Baseline measured: TTFT p50 10.1 s, E2E p50 13.0 s.

Data structures:

- `SearchResult` (frozen dataclass): `text, source_id, source_type, product, title, url, score, chunk_index, chunk_type, doc_section, channel_visibility, symbol_name, symbol_signature`. **No authority / currency / sensitivity / valid-as-of / citation-eligibility fields.**
- Weaviate `Document` collection properties: `source_id, source_type, product, title, text, url, channel_visibility, chunk_* , symbol_*` (8+ exposed; `content_hash` hidden). Deterministic uuid5 per (source_id, chunk_index).
- Connectors: `github` / `local_git` / `woocommerce` (emits `Price/Regular/Sale` text lines, metadata `date_modified` present at connector level but NOT persisted to the index) / `web_crawl` / `filesystem` (support cases; `fetch_changes` uses file mtime — dates exist at source, discarded downstream). Product derivation via `taxonomy.derive_product(url, source_id)` rule engine.
- Trust: chunk-level `channel_visibility` filter in HybridSearcher (main line) + `SourceVisibilityGuard` fail-closed re-check before rerank/LLM context (unknown/ghost source → DENY). This guards **channel eligibility only** — it has no authority/currency/sensitivity semantics.
- Trace: `Trace(conversation_id, turn_index, type, stages JSONB, config_snapshot)`. Types in use: `rag / reject_short / smalltalk / override / product_clarify / product_unsupported / budget_declined / generation_error`. Stage payloads already include: language, intent (ms/category/reason), rewrite (extracted/rewritten/ms), retrieve (ms/hybrid_count/effective_min/path_counts), rerank (ms/top_score/count/pruned/**result snippets**), product_scope (mode/targets/source/quotas), composition stats exist on `CitationContext.stats` (public/background/dropped counts), lead. `result_key` taxonomy already enumerates strategy outcomes: `smalltalk/override/off_topic/product_clarify/product_unsupported/no_evidence/product_evidence_insufficient/comparison_evidence_insufficient/rag`.

## 3. Target → Current Mapping (summary matrix)

| Target stage | Current component(s) | Disposition |
|---|---|---|
| S0 Intake/Trust | mask_pii, site gate, budget | reuse; ADD ingestion-side redaction + sensitivity labeling |
| S1 Interaction Understanding | social.py + product_resolver + classify_intent + extract/rewrite | REUSE social (closed set) + resolver (structured); MERGE intent+extract+rewrite into one structured task call; ADD entity-state + mode recommendation |
| S2 Mode decision | canned branches (product_clarify/unsupported/off_topic/insufficient) | REUSE branch plumbing + `result_key` analytics; REPLACE canned content with generated clarification; ADD post-evidence re-decision |
| S3 Evidence Planning | `_comparison_evidence_pipeline` (per-target quota) | GENERALIZE targets→slots; ADD slot taxonomy for recommend/troubleshoot/price |
| S4 Retrieval Core | `_retrieve_and_fuse` (3-path RRF) | REUSE wholesale; plan-driven query fan-out added |
| S5 Selection | bge-reranker + LLMPruner + eligibility filter | REUSE reranker as relevance signal; ADD authority/currency/scope signals + per-slot quotas + traced displacement; pruner becomes slot-aware or subsumed |
| S6 Composition/Trust | `build_citation_context` + SourceVisibilityGuard | REUSE numbering machinery; ADD evidence-object semantics, redaction re-check, coverage/conflict report |
| S7 Strategy | implicit; `result_key` taxonomy exists | FORMALIZE mapping (task×coverage)→result_key-family |
| S8 Generation | single prompt + stream | keep streaming; move rules to contract; de-templatize open inputs |
| S9 Claim validation | CitationStreamFilter + validate_citations | EXTEND with class/currency checks (evidence-object metadata available at filter time); claim granularity = discovery |
| S10 Provenance | sources SSE event | ADD declared-class envelope from composition report |
| S11 Observability | Trace table + stage payloads | EXTEND per-candidate retention + decision events + retention policy |

## 4. Reusable Components (substantially intact)

1. **HybridSearcher + RRF + reranker + eligibility filter** — recall/fusion machinery reused wholesale; S5 wraps, not replaces.
2. **`_comparison_evidence_pipeline`** — per-target retrieval/quota/focus-rerank/D-preflight is the working embryo of S3+S5; generalization path is targets→slots.
3. **`intent-boost` bucket mechanism** — already isolates internal case retrieval (`product="knowledge"`) by intent; the natural hook for slot/class-scoped retrieval.
4. **`social.py`** — keep verbatim as a closed-set boundary (its defect was coverage scope, not concept).
5. **`product_resolver`/`taxonomy`** — keep as structured entity-state provider + CIT-03 eligibility; stop using its AMBIGUOUS mode as a pre-retrieval reject (mode moves to S2 as a decision).
6. **`CitationStreamFilter` state machine + `build_citation_context` numbering** — extend, don't replace; the authoritative-numbering invariant (LLM numbering set == visitor set) is correct and must survive.
7. **`result_key` taxonomy + Trace stages JSONB** — the strategy enum and observability skeleton already exist.
8. **`SourceVisibilityGuard`** fail-closed pattern — reuse the pattern for the new sensitivity gate.
9. **Connector architecture + `taxonomy.derive_product` rule engine** — the rule-engine pattern is the natural implementation vehicle for authority-class derivation.
10. **Benchmark v1 frozen corpus + harness** — regression instrument for every increment.

## 5. Required Engineering Changes (change surfaces)

1. **Weaviate schema**: add evidence-semantics properties (authority_class, currency, valid_as_of, sensitivity, citation_eligible — names TBD at contract). Schema migration + backfill + re-embed NOT required for pure property adds if vectors unchanged (properties are stored alongside vectors; backfill = update objects, no re-embed) — but **redaction changes chunk text → re-embed → re-index of affected sources is unavoidable** for INC redaction. Internal case corpus is the affected set (size UNKNOWN — production corpus not inspected).
2. **Connector layer**: woocommerce — persist `date_modified` → valid_as_of; filesystem — add deterministic redaction stage + `sensitivity=internal` + ticket-date derivation if present in source; github/web_crawl — currency=current + capture time.
3. **Pipeline**: merge intent/extract/rewrite into task-understanding call; plan→per-slot query fan-out; selection scoring extension; composition coverage report; strategy mapping module; claim filter class/currency extension.
4. **Contracts/API**: SSE envelope gains declared-class provenance (additive, backward-compatible); `result_key` values extended additively.
5. **Config**: per-task LLM routing already exists (`registry._get_chain(task)`) — new tasks (task-understanding, planner) route through the same mechanism; no new config system.

## 6. Evidence / Data Model Discovery

- **Derivable today without new sources**: `source_class` (connector type → wiki/store/github/website/internal-case: direct from `source_type`), `citation_eligibility` (= today's `PUBLIC_SOURCE_TYPES` whitelist, already coded), `entity scope` (= existing `product` derivation), `sensitivity` (source-type rule: filesystem=internal, public connectors=public — matches today's visibility semantics).
- **Derivable with small connector changes**: `valid_as_of` — woocommerce `date_modified` (exists, discarded), web_crawl capture time, git commit date, filesystem mtime (exists, discarded downstream).
- **NOT reliably derivable**: statement-level currency inside documents (a 2026-05 case quote inside a wiki page; an old price line inside a current page). Backfill can classify the OBJECT (document/chunk) but not each statement. Consequence: **UNKNOWN/undated currency must have defined behavior** (proposed default: treated as undated-internal for class purposes; never satisfies a `currency=current` slot unless source class is authoritative-current — contract decision).
- **Migration shape**: property adds + rule-based backfill job + deterministic uuid5 overwrite (idempotent by design). Re-embed required only where text changes (redaction). Full reindex not required for metadata-only backfill.
- **UNKNOWN (not inspected)**: production Weaviate object counts per source class; whether historical case TEXT contains dates usable for valid_as_of; actual field-level PII distribution in case docs (documentary evidence from acceptance/attribution says identity-bearing content exists; direct corpus query deliberately not exercised in this gate).

## 7. Trust / Privacy Discovery

- Today's two-line defense (index-level channel filter + fail-closed guard) protects **channel eligibility**; nothing enforces identity redaction or claim-support class. The engineering boundary for the four composition rules maps 1:1 onto existing hooks:
  - *may-enter*: composition stage (citation.py) — same place background is built today;
  - *may-support*: S9 filter extension (evidence-object class check — the file already receives `source_products`; extend to `source_class/currency`);
  - *may-display*: `_extract_sources` whitelist (exists);
  - *never-reproduce*: deterministic redaction at connector + composition re-check (new; the only new enforcement point).
- Redaction placement: **connector-level** (filesystem `_make_document`/chunking) is the durable point (protects index + traces); composition re-check covers legacy/missed cases. Both are deterministic text transforms.
- Reindex implication: text-changing redaction requires re-embedding the internal corpus (sync machinery already supports per-source incremental; uuid5 idempotency allows in-place overwrite). Backfill runbook = contract item after INC-2b discovery.
- Privacy risk of tracing: per-candidate traces would capture internal chunk previews — traces must store source metadata + hashes, not raw text (matches existing `_rerank_snippets` preview pattern, which needs a policy review for internal sources).

## 8. Interaction / Task Model Discovery

- Current decision inventory: social (deterministic, closed set — retain); product boundary (pure function — retain as entity-state provider; its AMBIGUOUS→canned path relocates to S2 as a decision); intent (open 4-label LLM — becomes task_type signal); extract/rewrite (open LLM — become plan/query generation); off_topic rejection (intent label → rejection — becomes mode decision).
- **Smallest viable migration boundary**: replace the `classify_intent + extract_query + rewrite_query` triple with **one structured task-understanding call** producing `{task_type, entity_state, mode_recommendation, language, queries[], slots?}`; downstream compatibility via thin adapters (intent label for traces/analytics; `search_query` string for the existing retriever; `result_key` unchanged). social.py and product_resolver remain untouched in this increment. This is call-count-neutral (3→1) and independently benchmarkable (C3 cases + no-regression on the other 112).
- Open question for contract: intent fail-open semantics (currently fail-open=product) must be preserved as mode fail-open=retrieve.

## 9. Retrieval / Selection / Composition Discovery

- Data flow verified: `HybridSearcher.search` (channel+product_labels filtered at Weaviate) → `rrf_fuse` (dedup by source_id+chunk_index; fused score written back to `score`) → `RerankPipeline` (replace(score) immutability; threshold+top_k+type weights) → `LLMPruner` (batch, fail-open) → eligibility filter → `build_citation_context`.
- **Information lost between stages today**: fused candidate list beyond snippets (rerank keeps `results` previews in trace, fusion keeps only `path_counts`); prune decisions (count only — no which/why); displaced-by relationships (none); composition input↔output mapping (stats only). This is precisely the K3/K4 blindness.
- **Minimum K3/K4/K6-distinguishing observability** (all metadata-level, no sensitive text): fused top-N (id, source_type, product, scores per path), rerank in/out with per-candidate score+threshold verdict, prune verdict per candidate (kept/pruned + reason class), composition slot coverage + background/public counts + per-slot evidence ids. Feasible within existing Trace.stages JSONB; volume bounded by top_k/recall limits (candidates ≈ tens per request).
- Composition merge point: `build_citation_context` is the single choke point where public/background split happens — the may-enter/may-support enforcement extends exactly there; `_extract_sources` remains the may-display boundary; never-reproduce is connector+composition redaction.

## 10. Claim Validation Discovery

- Current unit: the `[N]` marker + preceding text window; provenance available at filter time: `n_sources`, `source_texts` (per number), `source_products`, `eligible_slugs`. Claims are NOT objects today; association is implicit (window → last marker).
- Deterministic extension boundary: `source_texts` can be accompanied by per-number `source_class/currency` (from S6 evidence objects) with zero structural change to the filter — enabling class-mismatch drops (price claim cited to case doc; historical claim cited as current). This covers the proven C2/K8 failure deterministically.
- Open (discovery → contract): claim granularity beyond the marker-window heuristic — options are (a) keep marker-window semantics + class checks (deterministic, cheap, covers proven failures), (b) add post-generation claim extraction (LLM, E2E cost, better comparison-claim coverage). Recommendation deferred to contract; (a) is the incremental floor.

## 11. Observability Discovery — and the ordering question

- Exists today: Trace table (JSONB stages), per-stage ms, intent reason, rewrite inputs, retrieve path_counts, rerank snippets/top_score/pruned-count, product_scope, composition stats object, config_snapshot, result_key. Retention/access policy: not found in this discovery (UNKNOWN).
- Missing for attribution: fused candidate list, prune verdicts+reasons, selection displacement relationships, composition slot-coverage mapping to evidence ids, strategy-decision events (beyond result_key), claim verdicts, per-task LLM config snapshots (partially in config_snapshot).
- Volume/latency: candidate-level metadata is tens of rows/request (bounded by recall_limit/top_k); JSONB appends are already the pattern; latency impact negligible (no new calls); sensitive exposure bounded by metadata-only policy + snippet policy review (§7). Production logging implications: write amplification on conversations/trace tables — volume estimate needs production request-rate data (UNKNOWN here).
- **OBSERVABILITY_FIRST = YES.** Evidence: (a) attribution REV2 could not stage-resolve 49/73 material observations — every future increment's regressions will be equally blind without it; (b) the increment sequence below makes behavior changes (INC-3..7) that each need before/after stage attribution to be acceptance-testable; (c) cost is low (metadata traces, no new LLM calls, existing table). Completing observability FIRST is what prevents "another baseline where K3/K4/K6/K7 cannot be distinguished".

## 12. Performance Analysis

- Measured baseline: TTFT p50 10.1 s / E2E p50 13.0 s (363 runs). Current serial critical path: intent → extract → rewrite → pruner → generation (4–5 LLM calls); lead qualifier parallel.
- Per-capability impact assessment (no invented numbers; UNKNOWN where unmeasured):
  - Task understanding (S1): **call-consolidating** — replaces intent+extract+rewrite (3 calls) with 1 structured call → net −2 serial calls; UNKNOWN per-call latency delta (output larger).
  - Evidence planning (S3): rides the same consolidated call for open tasks (slots in the same JSON) → no additional call; comparison path already does its own planning.
  - Class-aware selection (S5): metadata arithmetic + existing bge-reranker (local) → no new model call; LLMPruner unchanged or absorbed.
  - Composition/trust (S6): deterministic → negligible.
  - Strategy decision (S7): deterministic mapping → negligible.
  - Claim validation (S9): deterministic extension of the streaming filter → no TTFT impact, small E2E cost (unchanged pattern).
  - Redaction (S0/ingestion): offline at ingestion; composition re-check deterministic → negligible.
  - Overall: the architecture can be introduced **without adding serial LLM calls to the critical path**; net latency is UNKNOWN but structurally neutral-to-improved. Any per-increment latency contract must be measured, not assumed (per gate instruction).

## 13. Migration / Compatibility Risks

1. **Re-embed/reindex on redaction** (text change) — internal corpus only; volume UNKNOWN; uuid5 idempotency makes it safe but sync-cron will not rewrite unchanged files → explicit one-shot backfill required; risk: partial redaction if backfill interrupted (mitigable: runbook + verification query).
2. **Schema evolution**: new Weaviate properties are additive (no re-embed); old objects without properties must have defined UNKNOWN behavior everywhere (fail-open vs fail-closed per attribute — contract decision; sensitivity must fail-CLOSED).
3. **Comparison-path regression** (AD10 generalization touches a proven component) — mitigation: keep comparison pipeline behavior-identical behind the generalized abstraction; benchmark comparison cases gate the change.
4. **Analytics compatibility**: `result_key`/intent values feed admin analytics — additive evolution + alias mapping required.
5. **Benchmark comparability**: behavior changes mid-benchmark-v1 create cross-version comparability breaks — each increment should carry a focused regression slice (C3 cases for INC-3; C1/C2 cases for INC-4/5/6) with the frozen corpus; formal re-baselining is a product decision outside this gate.
6. **Pruner fail-open** can mask selection regressions — observability must record prune verdicts before selection changes (ordering dependency).
7. **Latency budget**: any slippage toward adding serial calls violates the measured-baseline envelope — task-model consolidation (§12) is the guard.

## 14. Engineering Dependency Graph

```
INC-1 Observability completion ──────────────┐ (attribution substrate for all)
INC-2a Evidence metadata schema + backfill ──┼─► INC-4 Planning + slot retrieval ─┐
INC-2b Ingestion redaction (needs sample) ───┼─► (trust hardening, independent)   │
INC-3 Task understanding consolidation ──────┴─► INC-5 Class-aware selection +   │
                                                  composition coverage +          │
                                                  strategy mapping ───────────────┤
INC-2a ─► INC-6 Claim class/currency validation ◄─────────────────────────────────┘
INC-7 Envelope declaration + generation naturalization (last; depends 4/5/6)
```

## 15. Recommended Increment Sequence

**INC-1 Observability completion** — PURPOSE: full K3/K4/K6 separation. CAPABILITIES: S11. DEPS: none. SURFACE: trace payloads only. MIGRATION: none. RISK: low (additive). BENCHMARK VALUE: makes every later increment's effect stage-attributable; direct closure of the 49-K9 problem. **READY_FOR_CONTRACT**.

**INC-2a Evidence metadata schema + deterministic backfill** — PURPOSE: evidence objects exist. CAPABILITIES: SC-2/SC-3 substrate. DEPS: none. SURFACE: Weaviate properties, connector metadata passthrough, backfill job. MIGRATION: property add + rule-based backfill (source-class rules per §6); no re-embed. RISK: UNKNOWN-attribute semantics (contract must define fail-open/closed per attribute). BENCHMARK VALUE: enables C1/C2-class verification. **READY_FOR_CONTRACT** (rule table is fully derivable from §6 findings).

**INC-2b Ingestion redaction** — PURPOSE: never-reproduce enforcement. DEPS: INC-2a schema. SURFACE: filesystem connector + composition re-check + one-shot internal-corpus backfill (re-embed). RISK: usefulness degradation; backfill interruption. BENCHMARK VALUE: C4-class closure. **MORE_DISCOVERY_REQUIRED**: redaction precision/recall on a labeled internal sample; corpus volume for reindex planning.

**INC-3 Task understanding consolidation** — PURPOSE: one structured call replacing intent/extract/rewrite; entity state; mode recommendation. DEPS: none hard (INC-1 recommended first for attribution). SURFACE: rag pre-retrieval section + adapters. MIGRATION: behavior-compatible adapters (intent label, search_query, result_key). RISK: prompt/task-model quality on 112 non-C3 cases; latency UNKNOWN (call-count-neutral by construction). BENCHMARK VALUE: C3 cases + seeds. **READY_FOR_CONTRACT**.

**INC-4 Evidence planning + slot-driven retrieval** — PURPOSE: generalize comparison pipeline to slots. DEPS: INC-3 (slots), INC-2a (metadata). SURFACE: retrieval fan-out + comparison-path refactor behind shared abstraction. RISK: comparison regression; planner failure modes. BENCHMARK VALUE: C1 honest-empty/background-relief cases. **MORE_DISCOVERY_REQUIRED**: slot taxonomy for recommend/troubleshoot/price; planner fallback semantics.

**INC-5 Class-aware selection + composition coverage + strategy mapping** — PURPOSE: authority/currency scoring; coverage report; deterministic strategy. DEPS: INC-2a, INC-4. SURFACE: rerank/prune wrapper, citation context, strategy module. RISK: comparison regression; strategy-mapping rigidity. BENCHMARK VALUE: C2/C6 verification. **MORE_DISCOVERY_REQUIRED**: strategy mapping table (product); conflict-resolution rules.

**INC-6 Claim class/currency validation** — PURPOSE: close K8. DEPS: INC-2a (+INC-5 for coverage inputs). SURFACE: citation filter extension. RISK: over-dropping (false positives degrade answers). BENCHMARK VALUE: sq-026-class. **MORE_DISCOVERY_REQUIRED**: claim granularity (marker-window extension vs post-generation extraction).

**INC-7 Provenance envelope + generation naturalization** — PURPOSE: transparency + de-robotization. DEPS: INC-4/5/6. SURFACE: SSE envelope, generation prompt/style. RISK: low technical, product wording decisions. BENCHMARK VALUE: EXPERIENCE-group improvement. **MORE_DISCOVERY_REQUIRED**: envelope wording; naturalness acceptance criteria.

## 16. Remaining Unknowns

Production Weaviate per-class object counts and reindex duration; field-level PII distribution in internal case docs (documentary evidence only — corpus not queried in this gate); per-task LLM latencies (intent/extract/rewrite/pruner) — none measured in this gate; Trace retention/access policy today; deepseek-v4-flash pruner latency share; internal case ticket-date availability for valid_as_of; whether any Store chunk text contains historical price phrasing (carried from attribution).

## 17. Contract-Readiness Assessment

| Increment | Readiness | Basis |
|---|---|---|
| INC-1 Observability | **READY_FOR_CONTRACT** | surfaces/limits/policy all discovered; additive |
| INC-2a Metadata schema + backfill | **READY_FOR_CONTRACT** | derivation rules fully discovered from existing fields |
| INC-2b Ingestion redaction | MORE_DISCOVERY_REQUIRED | redaction quality sample + corpus volume |
| INC-3 Task understanding | **READY_FOR_CONTRACT** | merge boundary, adapters, fail-open semantics discovered |
| INC-4 Planning/slot retrieval | MORE_DISCOVERY_REQUIRED | slot taxonomy + fallback semantics |
| INC-5 Selection/strategy | MORE_DISCOVERY_REQUIRED | strategy mapping + conflict rules (product input) |
| INC-6 Claim validation | MORE_DISCOVERY_REQUIRED | claim granularity decision |
| INC-7 Envelope/naturalization | MORE_DISCOVERY_REQUIRED | product wording + acceptance criteria |

Cross-cutting prerequisite: **INC-1 must land before INC-3..7 acceptance testing** so every behavior change lands with stage attribution (see §11).
