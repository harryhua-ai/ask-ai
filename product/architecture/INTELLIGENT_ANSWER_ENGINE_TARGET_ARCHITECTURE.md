# INTELLIGENT ANSWER ENGINE — TARGET ARCHITECTURE

- **Gate**: ASK-AI / Intelligent Answer Engine / Target Answer Architecture
- **Date**: 2026-09-07
- **Evidence base**: Baseline `PB-V1-20260907-CDBCAD3` (ACCEPT_WITH_QUALIFICATIONS) · Attribution rev1 `74ffb53e` + REV2 `81482fc0` · Production code inspected at `cdbcad38fc3512561e12c71ff6eda067d06257b5`
- **Status**: architecture definition only. No implementation, no production change, no Benchmark v1 change. Implementation sequencing (§15) is a dependency order, not a contract.

---

## 1. Executive Summary

The current system is a single-shot RAG pipeline guarded by three independent surface-form gates (verbatim social patterns, substring deixis, a four-label intent classifier) that make pre-retrieval routing decisions; evidence composition splits retrieved chunks into a numbered public section and an unlabeled background section (internal support cases) with no semantics of authority, currency, or identity; and the only claim-level check is numeric presence. The accepted baseline demonstrates these are not edge bugs but structural behaviors: surface gates misroute paraphrases and complete scenarios (C3), narrative queries let symptom-similar historical cases displace current authoritative documents (C1), stale case facts present themselves as current truth with spurious citations (C2), internal identity-bearing evidence reaches generation invisibly (C4), and response strategy varies run-to-run (C6).

The target architecture reorganizes the engine around an explicit **decision chain**: understand the task → decide the response mode → plan what evidence the task requires → recall → select by relevance AND authority AND currency-fit → compose under an explicit trust boundary → decide the response strategy from plan coverage → realize naturally → validate claims at claim level → expose provenance and a full stage trace. The two load-bearing new concepts are the **Evidence Plan** (typed evidence slots with required semantics that drive retrieval and validate composition) and the **Evidence Object** (every chunk carries authority class, currency, entity scope, sensitivity, and citation eligibility from ingestion onward). Template text is confined to closed sets (safety, true off-topic, social); everything else is naturally realized under truth constraints enforced by the composition and validation contract, not by the prompt alone.

## 2. Current Answer Architecture (as built at `cdbcad38`)

Traced production path (streaming):

```
mask_pii(user msg) → lead context → site gate → language resolve
→ [G1] admin override match
→ [G2] social matcher (deterministic regex, 5 kinds × zh/en, anchored ^$)
→ [G3] product boundary: product_resolver (explicit hint > query products >
        page context > deixis+history) → MODE exact/comparison/ambiguous/
        unsupported/none → AMBIGUOUS/UNSUPPORTED → canned text, pre-retrieval
→ [G4] intent classifier (LLM, 4 labels) → off_topic → canned rejection
→ query extract + rewrite (LLM)
→ retrieval: 3-path RRF fusion, channel-visibility gate at the index
→ reranker (top_k) → pruner → defensive product-eligibility filter
→ [comparison mode: per-target evidence pipeline]
→ min-gate → fused-fallback → canned insufficient/no-evidence rejection
→ sources = public-whitelist extraction (top 5, dedup)
→ citation context = numbered citable section + UNLABELED background section
   (internal case chunks, no numbers, "禁止引用" prompt rule)
→ LLM stream (single system+user prompt) + CitationStreamFilter
   (dangling drop / numeric-presence support / product eligibility)
→ SSE (sources/tokens/done) + persistence + lead qualification
```

Honest properties of this architecture that the target must preserve or consciously replace:

- Comparison mode already implements a per-target planned-evidence pattern (per-target retrieval, quotas, focus rerank) — the seed of generalized Evidence Planning exists for one task type only.
- The channel-visibility gate at the index and the source whitelist are presentation/trust mechanisms that currently do NOT bound what enters generation context.
- Canned text is used not only for closed sets but for open decisions (clarification, insufficient evidence), which is the robotic-answer complaint's structural root.

## 3. Proven Architectural Problems (attribution-anchored)

| # | Problem | Attribution evidence |
|---|---|---|
| P1 | Task type decided by three independent surface-form gates; paraphrase (你会干什么), substring deixis ("the cameras"⊃"the camera"), and missing clarify paths misroute open inputs pre-retrieval | C3 (9 runs, #26/#27/#31) — code-level |
| P2 | No evidence-requirements notion: a narrative query retrieves symptom-similar internal case chunks and never asks whether the *current authoritative* slot (spec/price/battery) is filled | C1 (21 entries, K9[K3,K4]); sibling spec-style queries retrieve the same docs that narrative queries miss |
| P3 | No evidence semantics: historical case numbers ($59/$109, 2.1y/1.1y) and current pages are composed into one context with no currency/authority distinction; generation alone decides how to treat them, unstably (r1 assert vs r2 label) | C2 (8 entries, incl. 4 of 5 confirmed criticals) |
| P4 | Trust boundary is presentation-only: internal case chunks are authorized into generation as unlabeled background; identity-bearing content reaches the model and surfaces; user-visible sources hide what was actually used | C4 (PII provenance HIGH); "zero visible sources ≠ zero generation context" (68 background-substantive zero-source runs) |
| P5 | Claim validation = number presence: a stale claim acquires a legitimate citation to a current page when its digits appear anywhere in it ($59 ⊂ $59.9) | C2 / K8 secondary — code-level (`numbers_supported`) |
| P6 | Response strategy (answer / bound-refuse / relay-background) is not a decided, traceable state; it emerges from the generator and varies across equivalent-intent runs, partly driven by upstream retrieval variance | C6 (28 entries; 12/19 split cases evidence source-state variance, 7/19 same-state variance) |
| P7 | Stage observability insufficient to separate K3/K4/K6/K7 post-hoc | attribution REV2: 49/73 entries K9-with-candidates purely for lack of stage traces |

## 4. Target Answer Architecture

```
                        ┌────────────────────────────────────────────┐
 user input ──────────► │ S0 Intake & Trust Preprocessing            │
                        └──────────────┬─────────────────────────────┘
                                       ▼
                        ┌────────────────────────────────────────────┐
                        │ S1 Interaction Understanding (task model)  │
                        │   task type · entity state · safety flags  │
                        └──────────────┬─────────────────────────────┘
                                       ▼
                        ┌────────────────────────────────────────────┐
                        │ S2 Response Mode Decision (①pre-evidence)  │
                        │   answer-direct / retrieve / clarify /     │
                        │   capability / refuse / continue-context   │
                        └──────────────┬─────────────────────────────┘
                                       ▼ (mode=retrieve)
                        ┌────────────────────────────────────────────┐
                        │ S3 Evidence Planning                       │
                        │   typed slots: role · entities · currency  │
                        │   · source-class · must/nice               │
                        └──────────────┬─────────────────────────────┘
                                       ▼ (per-slot queries)
                        ┌────────────────────────────────────────────┐
                        │ S4 Retrieval Core (recall; hybrid, fused)  │
                        └──────────────┬─────────────────────────────┘
                                       ▼
                        ┌────────────────────────────────────────────┐
                        │ S5 Evidence Selection & Scoring            │
                        │   relevance × authority × currency-fit ×   │
                        │   entity-scope · per-slot coverage ·       │
                        │   conflict detection                       │
                        └──────────────┬─────────────────────────────┘
                                       ▼
                        ┌────────────────────────────────────────────┐
                        │ S6 Evidence Composition / Trust Boundary   │
                        │   evidence objects · slot coverage report  │
                        │   · redaction · visibility classes         │
                        └──────────────┬─────────────────────────────┘
                                       ▼
                        ┌────────────────────────────────────────────┐
                        │ S2' Response Mode Re-decision +            │
                        │    S7 Response Strategy Decision           │
                        │   (task × coverage × conflicts → strategy) │
                        └──────────────┬─────────────────────────────┘
                                       ▼
                        ┌────────────────────────────────────────────┐
                        │ S8 Natural Generation (realization only)   │
                        └──────────────┬─────────────────────────────┘
                                       ▼
                        ┌────────────────────────────────────────────┐
                        │ S9 Claim–Evidence Validation               │
                        │   claim-level: value + class + currency    │
                        └──────────────┬─────────────────────────────┘
                                       ▼
                        ┌────────────────────────────────────────────┐
                        │ S10 Provenance & Response Envelope         │
                        └────────────────────────────────────────────┘
  S11 Observability & Attribution Backbone — wraps EVERY stage (trace contract, redaction-by-default)
```

Stage notes:

- The proposed gate sequence is **modified**: the proposed linear "Interaction Understanding → Context Resolution → Evidence Planning → …" is restructured into a **decision loop** — response mode is decided twice (S2 pre-evidence, S2' post-composition) because three proven failures (insufficient evidence, slot conflicts, clarification-worthy gaps) are only knowable after composition. Keeping mode decisions pre-evidence only would reproduce today's canned-reject behavior.
- The monolithic "rerank+prune" of today is **split** into S5 (class-aware selection) and the composition report; "rerank" alone is no longer a responsibility boundary.
- Deterministic short-circuits are retained but **confined to closed sets** (exact social idioms, injection/safety patterns, admin overrides). They may resolve an input; they may never *classify* an open input by themselves.

## 5. Stage Responsibilities

**S0 Intake & Trust Preprocessing** — sanitize injection patterns; redact user PII (existing); session/history/language/site context assembly; budget accounting. Owns: input safety. Does NOT decide task type.

**S1 Interaction Understanding** — produce a structured task representation: `task_type ∈ {factual-lookup, comparison, troubleshooting, recommendation/solution, commercial, capability/orientation, social, off-topic, clarification-needed}`, resolved/unresolved entity state, explicit deixis referents, safety flags, language, confidence + rationale. General capability boundary (not phrase fixes): *task type is a semantic property of the request, inferred with evidence and confidence; deterministic matchers are admissible only where the input space is closed and the cost of error is rejection of a trivial input.* The product/entity resolver becomes an entity-state provider inside S1 (its exact/comparison/none outputs feed task representation), and deixis becomes an entity-grounding sub-task (resolve the referent from page/history; if unresolvable, record "unresolved referent" instead of short-circuiting). "你会干什么" and "the cameras" both become ordinary task-model inputs: the first is a capability/orientation request regardless of phrasing; the second is a scenario recommendation whose entity slots are filled by constraints (1000 cameras, 6 warehouses), not by model names.

**S2 Response Mode Decision (① and ②)** — decide how to respond before and after evidence work: `answer-direct` (closed sets: social, safety), `retrieve-then-answer`, `clarify`, `capability-orientation`, `refuse-off-topic`, `continue-from-context`. Clarification is a **response decision with content**: the clarifying question is generated from what the task model/planner says is missing (entity referent? usage constraints? comparison set?), never a canned "which product model" emitted because a regex fired. Semantic rule (replaces today's AMBIGUOUS gate): **AMBIGUOUS ENTITY** = the request's referent cannot be grounded (explicit deixis, unresolved in page/history) → clarify. **SUFFICIENTLY SPECIFIED TASK WITH MULTIPLE/NO NAMED ENTITIES** = the task is complete as stated and entity choice is part of the answer (recommendation, comparison-request, scenario design) → proceed to planning; the engine selects/compares candidates and shows its basis. Mode re-decision (②) after composition may switch to clarify/partial/bounded-refusal with a *stated reason*.

**S3 Evidence Planning** — yes, ASK-AI needs it. For every evidence-requiring mode, produce a plan of typed slots: `{role, entities, currency(current | historical-as-of(t) | any), source-class preference(authoritative-doc | pricing-page | case-example | community | …), must-have | nice-to-have}`. Canonical expansions: comparison → one slot per compared target per compared property; recommendation → constraints + candidate-product current specs + solution/case examples (as *examples*); current pricing → current commercial evidence only; historical example → evidence explicitly marked historical; troubleshooting → product docs + symptom evidence + similar cases (as cases). The plan drives S4 queries and S6's coverage report. It is also the natural home for the already-proven comparison per-target quota pattern, generalized.

**S4 Retrieval Core** — recall-oriented: hybrid multi-path retrieval issuing per-slot queries derived from the plan (plus the user query), fused (RRF or successor). Owns: recall and candidate volume. Does NOT decide final evidence; every fused candidate (id, path scores, source metadata) is traced (S11) so K3 becomes observable.

**S5 Evidence Selection & Scoring** — select per slot with multi-signal scoring: semantic relevance × **authority class** (official documentation/pricing page > marketing/case/community) × **currency-fit** (slot requires current; evidence valid-as-of matches or is explicitly historical) × entity-scope match (exact product/sibling/family) — plus per-slot coverage quotas (generalizing the comparison quota) and **conflict detection** (same fact, different values/currency across candidates → conflict record forwarded to S6, never silently resolved by score alone). Symptom similarity may rank a case high **only for a case/example slot**; it can never displace an unfilled current-spec slot — this is the structural fix for "symptom-similar historical case dominates". Pruning becomes slot-aware selection with traced decisions (selected / displaced-by / filtered-by-class) so K4 becomes observable.

**S6 Evidence Composition / Trust Boundary** — compose the generation evidence set from selected evidence objects under explicit rules:
- *May enter generation*: citation-eligible public evidence (numbered), internal case evidence **after deterministic redaction** of customer identifiers (ingested redacted at S0-of-ingestion AND re-checked at composition; redaction is never presentation-only), conversation context (instruction-isolated), user-provided attachments (sandboxed).
- *May support factual claims*: only citation-eligible evidence for public-facing claims; internal case evidence may support experiential framing ("in a comparable deployment…") but never current-product facts; conversation context supports nothing factual by itself.
- *May be shown as provenance*: citation-eligible public evidence (numbered); internal evidence may be **declared as a class** ("internal case records") without exposing paths/identities.
- *Must never be reproduced directly*: customer names/companies/addresses/identifiers, internal markers/tickets, credentials, other visitors' data.
- Composition emits a **coverage report**: per-slot filled/empty/conflicted + the evidence-class mix — the honest, machine-readable statement of "what the answer is based on". The proven condition is inverted by design: *zero visible public sources with internal-evidence usage becomes an explicitly declared evidence state* (answer says it draws on internal case records), not a silent condition.

**S2' + S7 Response Strategy Decision** — a separate decision layer between composition and realization. Inputs: task type, plan coverage report, conflicts, sensitivity flags. Output: one strategy family — `full-answer / partial-answer-with-named-gaps / compare / recommend-with-options / troubleshooting-flow / clarify(generated question) / bounded-refusal(reason) / orientation` — with a deterministic mapping from (task, coverage, conflicts) to strategy family; randomness permitted only inside realization. Partial answers must *name the gaps* ("官方资料未载明 X；以下基于既有案例经验…") instead of silently declining. This is the stability fix: strategy becomes a decided, traced state; observed instability becomes a diffable strategy-decision trace, and upstream variance (different source states) legitimately yields different strategies *by rule*, not by drift.

**S8 Natural Generation** — realization only: given composed evidence + strategy + slot structure, produce the answer in an experienced-engineer voice — direct answer first, appropriately concise or detailed, naturally structured (headings where they serve, prose where they don't), no filler repetition, no forced boilerplate sections, no emoji; grounded by contract, not by prompt pleading. Canned templates are abolished for open inputs; they survive only in closed sets (safety refusals, true off-topic, social idioms) where naturalness has no room to matter. Naturalness must never relax truth: every factual statement remains bound to S6's evidence objects and S9's validation.

**S9 Claim–Evidence Validation** — claim-level, not marker-level. A claim is `{subject, predicate, value(s), currency-implied, comparison-structure?}`. Validation requires the cited evidence object to (a) actually contain the claim's content, (b) be of the **class the claim requires** (a current-price claim requires current pricing evidence; a spec claim requires authoritative spec evidence; a historical claim must cite evidence marked historical), and (c) for comparisons, have per-target support. Failure handling: strip the citation authority, and either downgrade the claim to the evidence's actual class ("a comparable case had…") or drop it — the strategy layer owns rewording; validation never silently lets "a similar number appeared somewhere" stand as "the current price is X". Coverage: numeric claims, pricing, specifications, comparison claims, historical/current claims, provenance correctness.

**S10 Provenance & Response Envelope** — user-facing truth about the answer's basis: numbered public sources actually used; declared evidence classes for internal/background usage; named gaps for partial answers; refusal reasons for bounded refusals. Provenance and envelope text are generated from machine state (composition report, strategy), not from the generator's discretion.

**S11 Observability / Attribution Backbone** — cross-cutting trace contract with stable stage events: `task.understanding` (output + confidence + which gate/mode decided), `plan.slots`, `retrieval.per_slot` (fused candidates: id, path, scores, source metadata), `selection.decisions` (per candidate: selected/displaced-by/filtered-by which signal), `composition.report` (slot coverage, conflicts, redaction events), `mode.strategy.decisions` (both mode decisions with inputs), `generation.invocation` (model/config snapshot, token counts), `claims.verdicts` (per claim: supported / class-mismatch / unsupported → action taken). Redaction-by-default: internal content appears as class + hash, identities never logged; trace retention policy is a discovery item. This backbone is what converts future failures into K3/K4/K6/K7-attributable evidence — the direct closure of attribution REV2's 49 K9 entries.

## 6. Evidence Model

Every evidence object carries, from ingestion and refined at composition:

| Attribute | Values (examples) | Drives |
|---|---|---|
| authority class | authoritative-doc / official-pricing / case-example / community / marketing | S5 selection, S9 claim-class requirements |
| currency | current · historical-as-of(date) · undated-internal | S5 currency-fit, S3 slot matching, S9 currency claims |
| entity scope | exact product / family / sibling / platform / cross-product | S5 scope match, S9/CIT-03 eligibility |
| source class | wiki / store / website / github / internal-case / user-context | S5, S6 visibility, S10 provenance |
| sensitivity | public / internal / personal-data(redacted) / user-provided | S6 trust boundary, S11 redaction |
| citation eligibility | citable-numbered / background-declared / context-only | S6 numbering, S9 supportability |

Minimum viable semantics to prevent the proven failure: **authority class + currency + citation eligibility + sensitivity must exist before selection**, not after generation. Whether `valid-as-of` can be derived (git dates, store price capture dates, ticket dates) is an engineering discovery item (§14).

## 7. Trust / Privacy Boundaries

Trust becomes a property of the composed set, enforced at three fixed points: **ingestion** (redact customer identifiers in case documents before indexing; sensitivity labeling), **composition** (re-check redaction; class-based composition rules; instruction-isolation of conversation/page context), and **envelope** (provenance declares classes without leaking content). The boundary questions are answered explicitly in S6's four rules (enter / support / show / never-reproduce). Boundary violations are observable events (redaction events, class-mismatch usage), not silent behaviors. Per the accepted qualification, the unresolved Benchmark v1 CRITICAL *severity policy* is out of scope here; the architecture provides the mechanism (deterministic redaction + declared classes) regardless of how severity is later classified.

## 8. Claim–Evidence Model

Claim as first-class object (S9) with three-part validation: content-support (does the evidence contain it — today's only check), class-support (is the evidence of the class the claim requires — new), currency-support (does temporal semantics match — new). Output per claim: verdict + action (`keep+cite / keep+reclass-as-example / drop / strategy-reword`). Numeric-presence survives only as a fast pre-filter, never as validation. This directly encodes the distinction the baseline failed: "a similar number appeared somewhere" ≠ "this specific claim is supported by this evidence".

## 9. Observability Model

Stage-event contract (S11) with: stable IDs linking one request across stages; per-candidate retrieval/selection traces; composition coverage/conflict report; both mode decisions with inputs; generation config snapshot; per-claim verdicts. Trust-respecting: personal data and internal content are redacted/hashed in traces; trace access is role-governed; retention is bounded (discovery item). Acceptance property: after this backbone exists, a benchmark failure must be classifiable as K3/K4/K6/K7 **from traces alone** — measured by re-running a sample of the accepted baseline's K9 entries through the new trace contract (future gate).

## 10. Current → Target Gap Mapping

| Target stage | CURRENT (exists at cdbcad3) | GAP | TARGET responsibility |
|---|---|---|---|
| S0 Intake | mask_pii, lead ctx, site gate, budget | ingestion-side redaction absent; sensitivity unlabeled | + ingestion redaction & labeling (feeds evidence objects) |
| S1 Interaction Understanding | 3 independent gates: social regex / product_resolver deixis / 4-label intent LLM | surface-form decisions; paraphrase & scenario failures; no task representation | single task model + confined closed-set short-circuits; entity state as input |
| S2 Mode Decision | canned clarify/unsupported/off_topic pre-retrieval only | clarification is a regex/LLM side effect; no post-evidence re-decision | twice-decided mode with generated clarification content |
| S3 Evidence Planning | none for open inputs (comparison quota = embryo) | no requirements notion; coverage unvalidatable | typed slot plan driving retrieval & composition |
| S4 Retrieval Core | 3-path RRF + channel gate | fine (recall); queries not plan-driven | plan-driven multi-query; full candidate tracing |
| S5 Selection | reranker + pruner + eligibility filter | relevance-dominant; no authority/currency signals; K4 invisible | class-aware per-slot scoring + traced displacement decisions |
| S6 Composition | numbered public section + unlabeled background | no semantics on objects; no coverage/conflict report; no redaction re-check; visibility-only trust | evidence objects + coverage report + redaction + class rules |
| S7 Strategy | implicit in generator prompt | unstable; unattributable | deterministic (task × coverage) → strategy mapping |
| S8 Generation | single LLM prompt with rule pleading | makes strategy decisions; canned fallbacks; robotic patterns | realization only; canned text confined to closed sets |
| S9 Claim Validation | CitationStreamFilter (numeric presence) | class/currency blindness (K8) | claim-level class+currency validation |
| S10 Provenance | sources list (public only) | hides actual evidence basis | machine-state envelope incl. declared internal-class usage |
| S11 Observability | partial trace stages | K3/K4/K6/K7 inseparable post-hoc | full stage-event contract, redaction-by-default |

## 11. How SC-1…SC-6 are addressed

- **SC-1 Interaction Understanding** → S1+S2: task model with entity state; deterministic gates confined to closed sets; clarify as generated decision; AMBIGUOUS-ENTITY vs SPECIFIED-TASK rule (§5 S1/S2).
- **SC-2 Evidence Selection / Authority** → S3+S5: plan slots make the authoritative-doc requirement explicit; authority/currency/scope are selection signals with per-slot quotas; all selection decisions traced (kills silent displacement, restores K3/K4 separability).
- **SC-3 Evidence Semantics** → Evidence Model (§6): currency/authority attributes from ingestion; currency-fit scoring; historical evidence usable only as historical.
- **SC-4 Evidence Composition / Trust Boundary** → S6+S10: composition rules for enter/support/show/never; deterministic redaction at ingestion+composition; internal usage declared as a class; zero-public-sources becomes a designed, visible state.
- **SC-5 Claim–Evidence Integrity** → S9: claim-level class+currency validation; numeric-presence demoted to pre-filter.
- **SC-6 Response Decision Stability** → S2/S2'+S7: strategy is a decided state with deterministic mapping and full tracing; upstream variance yields different strategies by rule; instability becomes a diffable event.

## 12. Architecture Decisions

| # | DECISION | EVIDENCE / WHY | ALTERNATIVES CONSIDERED | TRADE-OFF |
|---|---|---|---|---|
| AD1 | Single Interaction Understanding replaces parallel surface-form gates; deterministic matchers confined to closed sets | C3 code-level: paraphrase 你会干什么, deixis substring "the cameras"⊂"the camera" | (a) extend phrase lists — rejected: open paraphrase space, repeats failure mode; (b) LLM-only, no matchers — rejected: latency/cost for trivial closed inputs, injection safety needs determinism | one task-model call on the critical path; mitigated by closed-set short-circuits and caching |
| AD2 | Clarify is a generated response decision from missing-information analysis; AMBIGUOUS-ENTITY vs SPECIFIED-TASK rule | cg-r07: full scenario killed by canned clarification (170 ms ×3) | keep canned clarify but fix trigger — rejected: wrong question content is the complaint; trigger fixes are whack-a-mole | clarify content quality depends on task model; slight latency on clarify paths |
| AD3 | Explicit Evidence Planning (typed slots) for evidence-requiring tasks | C1: authoritative docs exist but narrative queries never asked for them; comparison quota already proves the pattern | implicit multi-query expansion — rejected: no coverage contract, composition cannot validate | planning adds a stage and failure mode; bounded scope (skip for direct/social) |
| AD4 | Evidence objects with authority/currency/scope/sensitivity from ingestion; class-aware selection | C2 + C1: composition had no semantics to distinguish case-example from current spec | post-hoc reordering of rerank output — rejected: displacement already happened; metadata-only without selection use — rejected: decorative | ingestion must produce/derive metadata (discovery: derivability of valid-as-of); stale metadata risk |
| AD5 | Trust boundary enforced at ingestion + composition with deterministic redaction; presentation hiding demoted | C4: internal chunks reach generation today; whitelist hiding is proven insufficient; prompt pleading non-deterministic (2/3 runs clean, 1/3 leaks) | prompt-rules-only — rejected by baseline evidence; full PII scrubbing of free text at generation — rejected: nondeterministic | redaction may reduce case-answer usefulness; measurable via benchmark re-run |
| AD6 | Response strategy as explicit decided layer, deterministic (task × coverage) → strategy mapping | C6: 28 entries; strategy emerges today and drifts; 12/19 split cases prove upstream variance participates (so strategy must react to measured evidence-state, not hope for stable generation) | prompt-only stability instructions — rejected: unverifiable, unattributable | mapping rigidity; mitigated by realization freedom + strategy escape-hatch events |
| AD7 | Claim-level validation with class+currency requirements; numeric presence demoted to pre-filter | C2 K8: $59⊂$59.9 spurious citation to current Store page | stricter numeric matching — rejected: presence≠correspondence is the failure; LLM-judge validation — deferred: cost/determinism (discovery) | compute cost; "important claims" scope must be defined (discovery) |
| AD8 | Full stage-event observability contract, redaction-by-default | attribution REV2: 49/73 K9 purely from missing traces | log-everything — rejected: trust boundaries; stay read-only-client — rejected: keeps K9 forever | storage and redaction complexity; retention policy discovery |
| AD9 | Zero-visible-public-sources becomes an explicit declared evidence state ("informed by internal case records") | 68 zero-source substantive runs; user currently cannot know the basis | keep silent background — rejected: proven transparency/trust failure; refuse all such inputs — rejected: destroys legitimate case-informed value | product wording/messaging decisions needed (discovery) |
| AD10 | Generalize the existing comparison per-target evidence pattern into the plan/slot model rather than inventing a parallel mechanism | comparison pipeline already implements per-target retrieval+quota+focus rerank in production | greenfield planner — rejected: discards proven component; keep comparison special-cased — rejected: perpetuates per-task hacks | generalization refactor touches the comparison path (regression risk, mitigated by benchmark) |

## 13. Explicit Non-Goals

Not in this architecture: model/provider selection; prompt texts; specific algorithms for matching/redaction/validation; database/index schema; file/class-level design; fixing #26–#31 as individual patches; defining Benchmark CRITICAL severity policy; changing retrieval vendors; building the competitive corpus (a corpus-coverage decision, K0, separate track); latency optimization.

## 14. Engineering Questions Still Requiring Discovery

1. Currency derivability: can valid-as-of be derived reliably per source class (VCS dates, store capture timestamps, ticket dates)? What for undated pages?
2. Authority labeling: rule-set vs model-assisted classification of source class/authority at ingestion; who owns the label taxonomy (product decision).
3. Ingestion redaction quality: precision/recall of customer-identifier redaction on real case documents (needs a labeled sample; privacy-safe protocol).
4. Task-model budget: latency/cost envelope for S1/S3 given current p50 TTFT 10.1 s; caching and small-model feasibility.
5. "Important claims" taxonomy for S9 scope (product + engineering).
6. Strategy mapping table: initial (task × coverage) → strategy assignments are product decisions.
7. Trace retention: duration, storage, access roles, hashing scheme for internal content.
8. Internal-evidence declaration wording (AD9) — user-facing product language.
9. Interaction-model evaluation set: how to regression-test S1 paraphrase coverage without freezing phrase lists.

## 15. Recommended Implementation Sequencing (dependency order, not a contract)

1. **S11 Observability backbone** — prerequisite for attributing every later change; zero user-visible behavior change; lowest risk.
2. **S0-extension + S6 trust-boundary hardening** (ingestion redaction/labeling, composition re-check, class declaration) — independent of model work; closes the proven PII path.
3. **S1+S2 Interaction Understanding consolidation** (task model, entity-state, mode decisions, generated clarification) — removes the C3 failure class.
4. **Evidence Model metadata + S3 Planning + S5 class-aware selection** — depends on discovery items 1–2; closes C1/C2's structural root.
5. **S9 Claim–Evidence validation** — depends on evidence semantics metadata (4).
6. **S7 Response Strategy layer** — depends on plan/coverage outputs (4) and strategy mapping discovery (6).
7. **S8 Generation naturalization + S10 envelope** — last: naturalness work is only safe once truth constraints (4–6) hold.

Rationale: observability before capability (everything must be attributable), trust before intelligence (privacy path is proven and independent), understanding before evidence, evidence before claims, claims before strategy, strategy before style.

---

*Boundary: this document defines WHAT the engine must be capable of and where responsibilities lie. HOW (components, models, schemas, prompts) is deliberately open and belongs to Engineering Discovery and implementation gates.*
