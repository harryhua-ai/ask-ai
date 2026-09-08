# R-001 — Next-Generation Knowledge & Retrieval Architecture

**Status:** RESEARCH IN PROGRESS — NOT A FROZEN ARCHITECTURE DECISION  
**Research owner:** Product / Architecture (Agent A)  
**Repository:** `harryhua-ai/ask-ai`  
**Research branch:** `research/r001-knowledge-retrieval-architecture`  
**ASK-AI engineering reference baseline:** `292c83a159eb77d1efb979d42ac00ce0dbef6220`  
**Date:** 2026-09-08

---

## 1. Purpose

ASK-AI is approaching the point where near-term Answer Intelligence work must be connected to a longer-term knowledge and retrieval architecture.

This research does **not** ask:

> Which RAG framework is best?

It asks:

> Which knowledge and retrieval capabilities does ASK-AI actually need over the next 1–3 years, which architectural patterns provide those capabilities, and which patterns should ASK-AI KEEP, BORROW, EXPERIMENT with, ADOPT, REJECT, or DEFER?

The output is a decision input for future Product Strategy, especially:

- I-003 — Knowledge Intelligence & Operations;
- I-004 — Interactive Answer Performance;
- I-005 — Agent Context Platform;
- the 6–12 month Product Roadmap.

This document is **research evidence**, not an implementation authorization and not a replacement for a future Architecture Decision Record.

---

## 2. Current ASK-AI architectural position

The current ASK-AI direction is already more than a simple `vector search → LLM` RAG system.

The accepted Answer Intelligence architecture is evolving toward:

```text
Task Understanding
        ↓
Evidence Planning
        ↓
Hybrid Retrieval / Reranking
        ↓
Evidence Selection & Composition
        ↓
Coverage Truth
        ↓
Generation Strategy
        ↓
Natural Generation
        ↓
Claim / Citation Validation
```

Important existing or accepted capabilities include:

- hybrid lexical/vector retrieval;
- RRF/reranking;
- deterministic Task Understanding consolidation;
- explicit EvidencePlan;
- evidence-role-aware selection/composition;
- CoverageReport as evidence truth;
- citation eligibility and product isolation;
- deterministic claim/citation validation;
- bounded observability and benchmark infrastructure.

This means the strategic question is **not** whether ASK-AI should abandon its current retrieval system for a branded GraphRAG framework.

The more useful question is whether future ASK-AI should add additional retrieval substrates and knowledge representations under the existing evidence-control plane.

---

## 3. 2026 landscape: RAG is becoming a capability portfolio

The market/research landscape has fragmented into several distinct directions rather than converging on one universal successor to traditional RAG.

```text
                          Knowledge / Retrieval Architecture
                                      │
      ┌───────────────────────────────┼─────────────────────────────────┐
      │                               │                                 │
      ▼                               ▼                                 ▼
Advanced Retrieval              Structured / Graph                 Agentic Retrieval
Hybrid retrieval                Knowledge Graph                    planning
Contextual chunks               GraphRAG                           iterative search
Reranking                       LightRAG                           corrective retrieval
Hierarchical retrieval          HippoRAG                           tool use
      │                               │                                 │
      └───────────────────────────────┼─────────────────────────────────┘
                                      ▼
                               Memory / Continual
                               knowledge systems
```

These techniques solve different failure classes. They should not be evaluated as if they were interchangeable frameworks.

---

## 4. Advanced Hybrid RAG remains a strong default substrate

Traditional retrieval is not obsolete.

Modern hybrid retrieval combines lexical matching, dense semantic retrieval, document/chunk contextualization, reranking, metadata constraints and better evidence composition.

Anthropic's Contextual Retrieval work is a useful example: contextualized embeddings + BM25 materially reduced retrieval failures, and reranking improved the result further. The architectural lesson is that a strong flat retrieval substrate can remain extremely competitive when chunk representation and ranking quality are improved.

**Implication for ASK-AI:**

- KEEP hybrid retrieval as the default fast-path substrate;
- continue treating BM25/vector retrieval and reranking as complementary;
- investigate contextual chunk representation before assuming graph retrieval is required;
- do not replace a working deterministic retrieval core merely because graph approaches are newer.

**Initial classification:** `KEEP / EVOLVE`.

External reference:
- Anthropic, *Introducing Contextual Retrieval*: https://www.anthropic.com/engineering/contextual-retrieval

---

## 5. Hierarchical retrieval: useful pattern, not necessarily a framework adoption

RAPTOR-style systems address the loss of document/global context caused by flat chunking. The general pattern is:

```text
leaf chunks
    ↓
semantic clusters
    ↓
cluster summaries
    ↓
higher-level summaries
```

This supports retrieval at different abstraction levels: detailed facts can come from leaves, while corpus/document-level questions can retrieve summaries.

For ASK-AI this is potentially useful for questions such as:

- product-family overviews;
- cross-document solution summaries;
- architecture/use-case synthesis;
- large documentation set navigation.

However, ASK-AI's Evidence Planner already has an explicit concept of **what evidence roles are needed**. A hierarchical layer should therefore be considered as another evidence source, not as the controller of the answer pipeline.

**Initial classification:** `BORROW PATTERN / EXPERIMENT LATER`.

External reference:
- RAPTOR: https://arxiv.org/abs/2401.18059

---

## 6. Microsoft GraphRAG: architecture ideas remain important, direct adoption is less compelling

GraphRAG transforms unstructured documents into entities, relationships and claims, detects graph communities, and creates community summaries that support local and global queries.

Its strongest conceptual contribution is not simply “use a graph database.” It is the distinction between:

- local/entity-centered retrieval;
- global/corpus-level understanding;
- graph/community summaries;
- cross-document relationship reasoning.

Microsoft's DRIFT Search further combines global/community context with local exploration and dynamically generated follow-up queries. This is particularly relevant to ASK-AI because it demonstrates a bounded escalation model rather than requiring every query to execute an expensive global search.

**ASK-AI fit:**

High value for:

- global corpus questions;
- cross-document relationship discovery;
- multi-hop solution/design questions;
- structured exploration of product/solution/case relationships.

Weaknesses / risks:

- indexing cost;
- graph extraction quality;
- maintenance complexity;
- graph freshness and deletion semantics;
- provenance from derived graph facts back to authoritative source evidence;
- risk of making a derived graph a second, weaker source of truth.

**Initial classification:**

- GraphRAG concepts: `BORROW`;
- Microsoft GraphRAG as ASK-AI core replacement: `REJECT`;
- graph/global retrieval experiment: `EXPERIMENT`.

External references:
- Microsoft GraphRAG project: https://www.microsoft.com/en-us/research/project/graphrag/
- DRIFT Search: https://www.microsoft.com/en-us/research/blog/introducing-drift-search-combining-global-and-local-search-methods-to-improve-quality-and-efficiency/

---

## 7. LightRAG: strongest near-term graph-pattern research candidate

LightRAG is currently a more directly relevant graph-RAG system for ASK-AI than the original GraphRAG architecture because it explicitly targets dynamic knowledge bases and combines graph and vector representations.

Relevant capabilities include:

- dual graph + vector retrieval;
- local/global/mix retrieval modes;
- reranker support;
- incremental updates;
- document deletion with affected KG regeneration;
- multiple storage backends;
- multimodal ingestion extensions;
- retrieval context/evaluation integration.

This aligns with ASK-AI's future requirements around continuous synchronization, knowledge lifecycle and self-hosting.

However, LightRAG also exposes an important architectural warning: once graph objects and vector objects coexist, deletion/recovery ordering and consistency become materially harder. Current LightRAG documentation includes repair procedures where graph, chunks and vector state can diverge, and a full VDB rebuild may require a full re-embed. A current 2026 RFC also proposes an explicit `DELETING` state for partially deleted documents, demonstrating that lifecycle truth becomes a first-class problem in a graph/vector dual-state system.

This is directly relevant to ASK-AI #25 and the planned I-003 lifecycle work.

**Strategic lesson:** graph retrieval quality cannot be evaluated independently of lifecycle correctness.

**Initial classification:**

- architecture patterns: `BORROW`;
- isolated experiment: `HIGH-PRIORITY EXPERIMENT`;
- direct migration of ASK-AI to LightRAG: `NOT RECOMMENDED WITHOUT BENCHMARK EVIDENCE`.

External references:
- LightRAG: https://github.com/HKUDS/LightRAG
- LightRAG processing/repair model: https://github.com/HKUDS/LightRAG/blob/main/docs/FileProcessingPipeline.md
- deletion lifecycle RFC: https://github.com/HKUDS/LightRAG/issues/3659

---

## 8. HippoRAG 2: treat primarily as a future memory architecture

HippoRAG 2 explicitly moves from “RAG” toward non-parametric long-term memory.

Its target capabilities are described as:

- factual memory;
- associativity / multi-hop retrieval;
- sense-making across large or complex contexts;
- continual integration of new knowledge.

The implementation uses graph/associative retrieval concepts such as Personalized PageRank rather than treating every query as independent vector similarity search.

For ASK-AI, the strongest fit is not the current Widget answer path. It is the longer-term **Agent Context Platform**, where agents may need persistent associative knowledge across large first-party corpora.

Potential future uses:

- cross-repository engineering knowledge;
- long-lived support/solution memory;
- relationship-based contextual recall;
- agents that need to navigate a continually growing enterprise knowledge graph.

**Initial classification:** `DEFER TO I-005 / EXPERIMENT AS MEMORY LAYER`.

External reference:
- HippoRAG 2: https://github.com/OSU-NLP-Group/HippoRAG

---

## 9. Knowledge Graph and GraphRAG must be treated separately

A first-class domain Knowledge Graph does not require adopting a GraphRAG framework.

ASK-AI has an unusually strong case for selectively structured domain knowledge because its first deployment domain naturally contains stable relationships such as:

```text
Product
  ├─ has Variant
  ├─ supports Capability
  ├─ compatible with Accessory
  ├─ used in Solution
  ├─ appears in Case
  ├─ has Documentation
  ├─ sold as Store SKU
  └─ constrained by Region / Interface / Environment
```

For example, a user asking for a product recommendation may require both unstructured evidence and structured relationships:

```text
Requirement
   ↓
Capability constraints
   ↓
Candidate product / variant
   ↓
Solution pattern
   ↓
Case evidence
   ↓
Current commercial truth
```

This may be better solved by adding a **structured retrieval substrate** under Evidence Planning than by re-platforming ASK-AI around a generic graph-RAG framework.

A 2025 systematic RAG-vs-GraphRAG evaluation also supports a non-dogmatic position: traditional RAG and GraphRAG show different strengths depending on task/evaluation perspective, and hybrid integration can be preferable to universal replacement.

**Initial classification:** `HIGH-PRIORITY PRODUCT/ARCHITECTURE RESEARCH`.

External reference:
- *RAG vs. GraphRAG: A Systematic Evaluation and Key Insights*: https://arxiv.org/abs/2502.11371

---

## 10. Agentic RAG: powerful, but should be bounded

Agentic RAG expands retrieval from a fixed pipeline into an iterative process:

```text
understand
  ↓
plan
  ↓
retrieve
  ↓
inspect evidence
  ↓
refine/decompose
  ↓
retrieve again
  ↓
answer
```

2026 surveys frame the major advantage as adaptive decomposition, exploratory retrieval and iterative evidence refinement for problems that cannot be solved by a single fixed retrieve-then-generate pass.

The major ASK-AI risk is latency/cost.

ASK-AI already has material TTFT pressure. An unrestricted pattern such as:

```text
LLM planner
→ retrieval
→ LLM critic
→ retrieval
→ LLM synthesis
→ validator
→ generator
```

would likely regress interactive experience and increase failure surface.

The more suitable product principle is:

> **Bounded Agentic Retrieval is an escalation path, not the default request path.**

Candidate future semantics:

```text
simple / sufficiently covered query
→ deterministic fast path

complex / decomposable query
→ bounded multi-query path

coverage remains materially incomplete
→ optional single corrective retrieval escalation

hard limit reached
→ answer supported portion / state evidence gap
```

This pattern aligns naturally with ASK-AI's existing EvidencePlan and CoverageReport.

**Initial classification:** `BORROW / EXPERIMENT AS BOUNDED ESCALATION`; unrestricted agent loop: `REJECT FOR DEFAULT PATH`.

External reference:
- ACL Findings 2026, *Data-Centric Perspectives on Agentic Retrieval-Augmented Generation*: https://aclanthology.org/2026.findings-acl.78/

---

## 11. Long context is not a replacement for knowledge architecture

Large context windows can reduce retrieval pressure for bounded documents, but they do not solve several ASK-AI-specific knowledge problems:

- authority;
- freshness;
- source visibility;
- product/variant isolation;
- current commercial truth;
- evidence-role coverage;
- provenance;
- citation support;
- missing-evidence truth.

Long context should therefore be viewed as a **larger evidence consumption budget**, not a source-of-truth or retrieval architecture.

**Initial classification:** `USE AS SUPPORTING CAPABILITY`, not a replacement strategy.

---

## 12. ASK-AI failure taxonomy → architecture mapping

The current Benchmark v1 failure taxonomy is K0–K9:

- K0 SOURCE ABSENT
- K1 DISCOVERY / INGESTION
- K2 INDEX / VISIBILITY
- K3 RETRIEVAL
- K4 RERANK / PRUNE
- K5 INTERACTION / ROUTING
- K6 EVIDENCE COMPOSITION
- K7 GENERATION / RESPONSE STRATEGY
- K8 CITATION / CLAIM
- K9 UNKNOWN

The accepted failure-attribution snapshot contained the majority of observations in K9, with material known failures concentrated in K5/K6 rather than proven K3 graph-traversal failures.

This is strategically important.

### What current evidence does **not** prove

Current Benchmark evidence does **not** prove that ASK-AI's dominant quality problem is inability to traverse a knowledge graph.

The accepted I-002 architecture primarily addresses:

- interaction understanding;
- evidence role planning;
- evidence composition;
- claim/citation validation;
- natural response realization.

Therefore a major GraphRAG migration before a post-I-002 comparative Benchmark would be premature.

### Failure classes likely helped by graph / structured retrieval

Graph or structured retrieval is most likely to help future cases involving:

- multi-hop relationships across several source documents;
- product/variant/capability compatibility;
- solution architecture synthesis;
- relation-heavy recommendation constraints;
- corpus-level/global questions;
- associative discovery where the exact target vocabulary is not in the question.

### Failure classes graph does not inherently solve

GraphRAG does not automatically solve:

- source discovery gaps (K0/K1);
- freshness;
- incorrect source authority;
- Store variation lifecycle;
- source retirement;
- wrong interaction classification (K5);
- bad response strategy (K7);
- citation correctness (K8);
- production latency;
- Admin knowledge observability.

This is the main reason graph work should remain evidence-gated.

---

## 13. Initial capability decision matrix

| Capability / Pattern | ASK-AI Current | Product Value | Complexity/Risk | Initial Decision |
|---|---|---:|---:|---|
| Hybrid lexical + vector retrieval | Yes | Very High | Low/known | **KEEP** |
| RRF / reranking | Yes | Very High | Low/known | **KEEP** |
| Task Understanding | Yes | Very High | Medium | **KEEP / EVOLVE** |
| Evidence Planning | Yes | Very High | Medium | **DIFFERENTIATOR** |
| Evidence Selection / Coverage | Yes | Very High | Medium | **DIFFERENTIATOR** |
| Claim/citation validation | Yes | High | Medium | **KEEP / EVOLVE** |
| Contextual chunk representation | Partial / verify | High | Medium | **RESEARCH / EXPERIMENT** |
| Hierarchical retrieval | No | Medium–High | Medium | **BORROW / EXPERIMENT** |
| Structured product/domain KG | No | Very High potential | Medium–High | **PRIORITY RESEARCH** |
| Generic GraphRAG | No | Medium | High | **SELECTIVE EXPERIMENT** |
| LightRAG pattern | No | High potential | High lifecycle complexity | **PRIORITY EXPERIMENT** |
| HippoRAG memory | No | Long-term High | High | **DEFER TO I-005** |
| Bounded agentic retrieval | Limited | High potential | Medium–High | **EXPERIMENT** |
| Unrestricted agent loop | No | Mixed | Very High latency/cost | **REJECT DEFAULT** |
| Long-context-only architecture | No | Medium | High truth/provenance risk | **REJECT AS REPLACEMENT** |
| Knowledge lifecycle/freshness | Partial | Very High | Medium | **I-003 PRIORITY** |
| Authority/temporality semantics | Metadata foundation | Very High | Medium | **I-003 PRIORITY** |

---

## 14. Emerging target architecture hypothesis

The strongest current hypothesis is that ASK-AI should become a **multi-substrate evidence retrieval system**, while preserving one deterministic evidence-control plane.

```text
                              Query
                                │
                                ▼
                       Task Understanding
                                │
                                ▼
                         Evidence Planning
                                │
              ┌─────────────────┼──────────────────┐
              │                 │                  │
              ▼                 ▼                  ▼
          Lexical            Semantic          Structured
           BM25               Vector          Knowledge/Graph
              │                 │                  │
              └────────────┬────┴────────────┬─────┘
                           ▼                 │
                       Rerank / Merge        │
                           │                 │
                           └────────┬────────┘
                                    ▼
                          Evidence Composition
                                    │
                           Coverage / Authority
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
              sufficient                      insufficient
                    │                               │
                    │                        bounded corrective
                    │                            retrieval
                    │                               │
                    └───────────────┬───────────────┘
                                    ▼
                          Response Strategy
                                    │
                                Generation
                                    │
                         Claim / Citation Validation
```

Key architectural principle:

> **Evidence Planning and Coverage remain the control plane; retrieval technologies become pluggable evidence substrates.**

This preserves ASK-AI's strongest emerging differentiation instead of making a third-party RAG framework the product architecture authority.

---

## 15. Graph-specific safety principles for ASK-AI

If graph/structured knowledge is introduced, the following principles should be treated as candidate hard boundaries for later Architecture Decision work:

1. **Derived graph facts are not automatically source truth.** Every material relationship should preserve provenance to authoritative source evidence.
2. **Graph lifecycle must follow source lifecycle.** Update, deletion, retirement and rollback cannot leave invisible stale relationships.
3. **No silent second truth.** Ledger/source truth and derived graph state must have explicit reconciliation semantics.
4. **Freshness is first-class.** A stale graph edge must not override current Store or documentation truth.
5. **Product isolation remains mandatory.** Graph expansion cannot become a new sibling-product contamination path.
6. **Graph retrieval must be benchmark-gated.** It should demonstrate benefit on graph-suitable ASK-AI tasks, not only public GraphRAG benchmarks.
7. **Fast path remains available.** Ordinary product factual Q&A should not pay graph/agentic costs unnecessarily.

---

## 16. Implications for roadmap

### I-002 — Intelligent Answer Engine

No graph architecture change should be introduced into the current I-002 implementation. Complete INC-7, production acceptance and comparative Benchmark first.

### I-003 — Knowledge Intelligence & Operations

This research strengthens I-003 rather than replacing it.

Highest-value likely capabilities:

- source inventory / observability;
- lifecycle and retirement correctness;
- freshness;
- authority/temporality;
- connector semantics;
- optional structured domain entities and relationships;
- lifecycle-safe derived knowledge.

A graph experiment, if authorized later, belongs after lifecycle and provenance contracts are clear enough to keep the graph trustworthy.

### I-004 — Interactive Answer Performance

The target architecture should preserve a deterministic low-latency default path. Graph/global/agentic retrieval must be measured against TTFT/E2E budgets.

### I-005 — Agent Context Platform

HippoRAG-style associative memory, structured relationship traversal and bounded agentic retrieval are more strategically relevant here than in the current Widget path.

---

## 17. Recommended research sequence before Architecture Decision

R-001 should not close until the following evidence is available:

### R1 — post-I-002 Benchmark mapping

Run Benchmark v1 only after the accepted production release. Re-attribute remaining failures and identify how many are plausibly caused by:

- flat retrieval limitations;
- missing relationship knowledge;
- multi-hop reasoning;
- global/corpus reasoning;
- lifecycle/knowledge-source gaps;
- performance constraints.

### R2 — graph-suitable ASK-AI test slice

Construct a small research-only set of real domain questions requiring relationships/multi-hop/global reasoning. Examples should span product compatibility, solution architecture, variants, case evidence and commercial constraints.

### R3 — local architecture experiment

Compare at minimum:

- current Hybrid RAG;
- improved/contextual Hybrid RAG;
- structured domain retrieval prototype;
- one graph-oriented prototype (LightRAG is currently the strongest candidate).

Evaluate:

- evidence recall/coverage;
- factuality;
- multi-hop completeness;
- provenance;
- update/delete correctness;
- indexing cost;
- query latency/TTFT impact;
- operational complexity.

### R4 — Repo Reality Check

Only after external landscape narrowing, ask the Engineering Executor to determine the real ASK-AI integration/blast radius for the surviving candidate patterns.

### R5 — Architecture Decision

Agent A then produces an ADR-style decision:

- problem;
- evidence;
- chosen architecture;
- rejected alternatives;
- migration/evolution path;
- product/engineering boundaries;
- roadmap impact.

---

## 18. Current decision summary

### KEEP

- hybrid BM25/vector retrieval;
- reranking;
- Evidence Planning as control plane;
- Evidence Selection/Composition;
- Coverage truth;
- claim/citation validation.

### BORROW

- contextual chunk representation;
- hierarchical abstraction;
- GraphRAG global/local concepts;
- DRIFT-style bounded exploration;
- LightRAG graph/vector complementary retrieval;
- provenance-aware structured relations.

### EXPERIMENT

- structured Product/Variant/Capability/Solution/Case graph;
- LightRAG against graph-suitable ASK-AI questions;
- bounded corrective/agentic retrieval;
- hierarchical summaries for global questions.

### DEFER

- HippoRAG-style long-term associative memory to I-005;
- broad Agentic GraphRAG.

### REJECT AS CURRENT DEFAULT

- replacing ASK-AI with Microsoft GraphRAG;
- unrestricted agent loops for normal Q&A;
- long-context-only knowledge architecture;
- treating graph-derived facts as authority without source provenance;
- adopting graph complexity before post-I-002 evidence proves a material retrieval gap.

---

## 19. Open questions

1. After I-002 is in production, what proportion of remaining benchmark failures are true K3/K4 retrieval failures rather than knowledge lifecycle, interaction or composition problems?
2. Which ASK-AI domain relationships are stable enough to deserve first-class structured representation?
3. Should structured knowledge be derived automatically from documents, connector-native where possible, manually governed, or hybrid?
4. What is the authoritative lifecycle contract for derived edges when a source document changes or retires?
5. Can structured retrieval improve multi-hop answers without materially worsening TTFT?
6. Does ASK-AI need corpus-global summarization in the Widget product, or mainly in Agent Context use cases?
7. What minimum graph experiment would provide decisive evidence without creating a parallel production knowledge stack?

---

## 20. Research status

**Current state:** `IN PROGRESS`  
**Architecture frozen:** `NO`  
**Implementation authorized by this research:** `NO`  
**Production mutation authorized:** `NO`  
**Benchmark mutation authorized:** `NO`

Next major evidence gate:

```text
INC-7 / I-002 completion
        ↓
Production acceptance
        ↓
Benchmark v1 comparative rerun
        ↓
Remaining-failure architecture mapping
        ↓
Targeted graph/structured retrieval experiment decision
        ↓
Architecture Decision / Roadmap reconciliation
```
