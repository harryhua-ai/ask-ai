# R-001B — Architecture Option Matrix

**Status:** RESEARCH CONSOLIDATION — DECISION INPUT ONLY  
**Parent:** R-001 / R-001A  
**Research branch:** `research/r001-knowledge-retrieval-architecture`  
**Date:** 2026-09-08  
**Implementation authorization:** NONE  
**Production mutation:** NONE  
**Benchmark mutation:** NONE

## 1. Purpose

Consolidate the architecture alternatives already investigated across R-001, R-001A and architecture discussions into one decision-oriented matrix. This document is not a new broad technology survey and does not freeze the target architecture.

Architecture selection principle:

> R-001 SHALL optimize for the best evidence-backed target architecture available at the time of decision. Existing ASK-AI architecture has no preservation privilege. Newer paradigms have no adoption privilege. Architecture decisions SHALL be driven by measured answer quality, evidence quality, adaptivity, efficiency, reliability, provenance, lifecycle correctness and operational cost. Migration constraints influence execution sequencing, not the target architecture ceiling.

Supporting principle:

> Final-answer gain > retrieval novelty.

## 2. Architecture layers

ASK-AI should distinguish capabilities from frameworks.

### Layer 1 — Evidence Control Plane

- Task Understanding
- EvidencePlan
- Retrieval Policy
- Evidence Composition
- CoverageReport
- Response Strategy
- Claim / Citation Validation

### Layer 2 — Knowledge Substrates

- source documents / chunks
- connector-native structured data
- governed structured domain knowledge
- graph / relationship substrate
- hierarchical / global summaries
- future persistent agent memory

### Layer 3 — Retrieval Mechanisms

- lexical / sparse retrieval
- dense semantic retrieval
- hybrid retrieval
- structured query
- graph traversal
- hierarchical / global retrieval
- connector-native retrieval
- external/tool retrieval where authorized

### Layer 4 — Retrieval Control

- deterministic routing
- parallel multi-route retrieval
- sequential escalation
- lightweight / learned routing
- cost-aware policy
- CoverageReport-driven corrective retrieval
- bounded agentic retrieval

Frameworks are implementation candidates inside these layers; they are not the product architecture by themselves.

## 3. Architecture Option Matrix

| Option / Direction | ASK-AI Layer | Primary problem solved | Prior research conclusion | Main strengths | Hard limits / risks | Current disposition | Roadmap ownership |
|---|---|---|---|---|---|---|---|
| Current Hybrid RAG — BM25 + vector + RRF/reranker | L3 | Ordinary local factual retrieval | Accepted baseline, but no preservation privilege | Cheap, deterministic, mature, good local retrieval control | Weak on explicit relationships, global synthesis and some multi-hop tasks; baseline must compete with newer approaches | BASELINE / CONTROL | I-004 |
| Frontier / Context-enhanced Hybrid | L2/L3 | Chunk context loss and stronger flat retrieval | Previously identified as experiment candidate | Low conceptual disruption; may improve local evidence recall/precision without graph lifecycle burden | Does not inherently solve stable structured relationships or corpus-global reasoning | EXPERIMENT | I-004 |
| Connector-native Structured Retrieval | L2/L3 | Exact SKU/variant/price/availability/native metadata truth | Strongest candidate structured authority | Exact source-native semantics, freshness can follow connector lifecycle, low inference risk | Connector-specific schemas and normalization; not sufficient for prose-only knowledge | PRIORITY EXPERIMENT | I-003 → I-004 |
| Governed Structured Domain Knowledge | L2/L3 | Product/variant/capability/accessory/solution/case relationships | Priority research/experiment | Explicit constraints, relationship queries, product isolation, explainable semantics | Requires authority, provenance, lifecycle, reconciliation and schema governance | PRIORITY EXPERIMENT | I-003 → I-004 |
| Generic Knowledge Graph capability | L2/L3 | Cross-document relationship navigation / multi-hop discovery | KG ≠ GraphRAG; strategically important capability | Natural relationship traversal; can connect products, capabilities, solutions, cases and documents | Graph truth can become stale/opaque; inferred edges cannot silently outrank authoritative sources | PRIORITY EXPERIMENT | I-003 → I-004 |
| Microsoft GraphRAG patterns | L2/L3 | Entity/local and corpus-global/community retrieval | Borrow Local/Global/DRIFT ideas; no core migration | Strong reference for global/community retrieval and local/global separation | Heavy graph/index pipeline; framework adoption would over-couple ASK-AI control plane | BORROW IDEAS | R-001 / I-004 experiments |
| LightRAG or equivalent graph-oriented implementation | L2/L3 | Graph + vector retrieval with incremental operations | Leading graph prototype candidate, not architecture decision | Practical graph/vector prototype; useful for testing relationship-heavy retrieval | Multi-storage consistency, update/delete/rebuild and lifecycle correctness are material product costs | PROMISING / EXPERIMENT | I-003/I-004 experiment |
| RAPTOR / hierarchical retrieval | L2/L3 | Hierarchical abstraction and corpus/document-level synthesis | Complementary substrate, not replacement for explicit relationships | Useful for global synthesis and abstraction across long/cross-document corpora | Tree/hierarchy does not inherently solve arbitrary cross-document relations; summary can lose details | CONDITIONAL EXPERIMENT | I-004 |
| Hierarchical / graph-community global retrieval | L2/L3 | Corpus-global questions | Capability required only if real global questions are material | Better corpus-level synthesis than small local chunk sets | Added indexing/runtime cost; global summaries can sacrifice fine-grained evidence | CONDITIONAL EXPERIMENT | I-003/I-004 |
| Adaptive Retrieval Routing | L4 | No single retriever/paradigm is universally optimal | Strategic direction | Can select evidence substrate by task/query/corpus characteristics and avoid paying advanced-path cost universally | Router quality, observability, training/evaluation and route errors become new failure modes | STRATEGIC TARGET | I-004 |
| Retrieval Policy Engine | L1/L4 | Generalize routing from fixed paths into evidence-aware action selection | New refinement consistent with prior adaptive-routing work | Keeps ASK-AI control plane stable while substrates evolve; supports single, parallel and sequential actions | Must remain bounded, inspectable and evidence-oriented; should not become an opaque autonomous agent | STRONG TARGET HYPOTHESIS | I-004 |
| Parallel Multi-Substrate Retrieval | L4 | Complex tasks needing evidence from multiple substrates | Allowed future composition model | Can combine structured + vector + graph + native evidence in one task | Latency/cost amplification and duplicate/conflicting evidence | EXPERIMENT | I-004 |
| CoverageReport-driven Corrective Retrieval | L1/L4 | First pass misses required evidence | High-value ASK-AI-specific future experiment | Missing required evidence is explicit; corrective target can be bounded and inspectable | Depends on EvidencePlan/CoverageReport quality and retrievability of missing slots | PRIORITY EXPERIMENT | I-004 |
| Bounded Agentic Retrieval Policy | L4 | Iterative search/reformulation for difficult tasks | Strategic research target; unrestricted loop rejected | Higher ceiling for multi-hop/tool use while retaining budgets and stopping rules | Latency, cost, trajectory reliability, debugging and authority risks | PRIORITY EXPERIMENT | I-004 |
| Unrestricted Agentic RAG loop | L4 | Open-ended autonomous retrieval | Rejected as default | Maximum flexibility | Non-determinism, cost, latency, difficult failure attribution, authority drift | REJECT AS DEFAULT | None |
| HippoRAG / HippoRAG 2 style associative memory | Future L2/L4 | Continual associative memory / long-horizon context | Deferred from core retrieval architecture | Promising for agent memory and associative recall | Different product horizon; premature for Widget knowledge retrieval unless evidence changes | DEFER | I-005 |
| Long-context-only retrieval replacement | Generation/context | Avoid retrieval by putting large corpus/context into model | Rejected as RAG replacement | Simple conceptual path; useful selectively when bounded context is already known | Does not solve authority, freshness, provenance, missing evidence, lifecycle or efficient corpus search | REJECT AS REPLACEMENT | None |

## 4. Structured knowledge authority model

Candidate authority invariant retained from R-001A:

```text
connector-native truth
    > explicit authoritative source relation
    > derived / inferred relation
```

Derived relations may improve discovery, but must not silently become stronger answer truth than their sources.

Candidate first-class domain entities already identified:

- Product
- ProductVariant
- Capability
- Accessory
- Interface
- Solution
- Case
- Document
- StoreSKU
- Region

Candidate relationships include:

```text
Product
  ├─ HAS_VARIANT → ProductVariant
  ├─ SUPPORTS → Capability
  ├─ HAS_INTERFACE → Interface
  ├─ COMPATIBLE_WITH → Accessory
  ├─ USED_IN → Solution
  ├─ EVIDENCED_BY → Case
  ├─ DOCUMENTED_BY → Document
  └─ SOLD_AS → StoreSKU
```

Core graph principle:

> Graph for navigation; source-backed evidence for truth.

Every material structured relation should remain resolvable to stable provenance such as `source_id + chunk_index` or a connector-native record identity.

## 5. Preferred target architecture hypothesis

Current strongest hypothesis is **not** Hybrid RAG, GraphRAG, LightRAG or Agentic RAG as the product architecture.

It is a **Multi-Substrate Adaptive Evidence Architecture**:

```text
User / Agent Query
        ↓
Task Understanding
        ↓
EvidencePlan
        ↓
Retrieval Policy Engine
        ↓
┌────────────────────────────────────────────────────┐
│ lexical / dense / hybrid                           │
│ connector-native structured retrieval              │
│ governed structured-domain retrieval               │
│ graph traversal                                    │
│ hierarchical / global retrieval                    │
│ authorized tool/external retrieval                 │
└────────────────────────────────────────────────────┘
        ↓
Single / Parallel / Sequential Retrieval
        ↓
Rerank / Prune
        ↓
Evidence Composition
        ↓
CoverageReport
        ↓
   sufficient?
   /        \
 yes        no
  ↓          ↓
Response   bounded retrieval-policy escalation
Strategy      ↓
  │       re-route / reformulate / retrieve
  └───────────┬──────────────────────────────
              ↓
          Generation
              ↓
     Claim / Citation Validation
```

The control plane should remain owned by ASK-AI. Retrieval frameworks should remain replaceable evidence substrates or mechanisms.

Potential policy evolution, not frozen:

```text
v1 deterministic rules
→ v2 lightweight learned router
→ v3 cost-aware adaptive policy
→ v4 bounded agentic policy
```

## 6. Architecture Experiment Matrix v2

The previous framework-centric experiment arms should evolve into capability/architecture arms.

| Arm | Composition | Decision purpose |
|---|---|---|
| A0 — Current Baseline | Current accepted Hybrid | Control / real baseline |
| A1 — Frontier Hybrid | Strong sparse+dense/hybrid + rerank/context enhancement | Determine ceiling without structured/graph substrate |
| A2 — Structured Hybrid | A1 + connector-native / governed structured knowledge | Measure value of exact relationships and native truth |
| A3 — Graph-Augmented | A2 + graph relationship traversal | Measure multi-hop / cross-document relationship gain |
| A4 — Multi-Substrate Routed | Route/compose A1/A2/A3 + hierarchical/global where justified | Test preferred target architecture hypothesis |
| A5 — Bounded Agentic Policy | A4 + bounded iterative retrieval / reformulation | Measure marginal value and cost of agentic control |

Frameworks such as LightRAG, GraphRAG-derived components or RAPTOR are implementation candidates inside arms; they do not define the architecture arms themselves.

### Test slices

- **Local factual control** — advanced architecture must not regress ordinary Q&A.
- **Structured relationship** — product/variant/capability/accessory/SKU/region constraints.
- **Multi-hop solution** — requirements → capabilities → product/variant → solution → first-party case evidence.
- **Global/corpus synthesis** — recurring solution patterns, product-family differences, corpus-wide themes.
- **Lifecycle mutation** — update, retirement, delete, reconciliation and stale-derived-state handling.
- **Corrective retrieval** — first pass deliberately leaves a material EvidencePlan slot uncovered.

### Required metrics

Answer / evidence quality:
- required-slot coverage
- evidence recall
- unsupported-claim rate
- provenance completeness
- product/variant isolation
- multi-hop completeness
- global-answer comprehensiveness
- final answer correctness / usefulness

Runtime / efficiency:
- retrieval latency
- TTFT impact
- E2E impact
- additional LLM calls
- escalation frequency
- token / inference cost

Operational fitness:
- indexing LLM calls
- embedding work
- incremental update cost
- delete / retirement cost
- recovery / rebuild cost
- storage complexity
- reconciliation failures

Governance:
- source → derived relation traceability
- stale relation detection
- rollback semantics
- observability
- authority preservation

Pareto-oriented decision metrics:
- quality gain per added latency
- quality gain per added cost
- quality gain per added architectural complexity/risk

A new retrieval technique should not be adopted merely because retrieval recall improves. It must improve final-answer/evidence outcomes and/or efficiency sufficiently to justify its operational cost.

## 7. Roadmap ownership

### I-003 — Knowledge Intelligence & Operations / Knowledge Substrate

Owns the truth and lifecycle side:

- knowledge observability
- source lifecycle / retirement / deletion correctness
- authority / freshness semantics
- connector-native structured knowledge
- governed domain relationships
- provenance
- reconciliation / rebuild
- structured/graph substrate health
- hierarchical/global derived state if adopted

### I-004 — Adaptive Retrieval Intelligence

Recommended replacement for the earlier `Interactive Answer Performance` framing.

Owns retrieval decision intelligence and efficiency:

- Retrieval Policy Engine
- frontier hybrid retrieval
- structured retrieval
- graph traversal
- hierarchical/global retrieval
- parallel/sequential multi-substrate retrieval
- CoverageReport-driven corrective retrieval
- bounded agentic retrieval
- latency / cost / escalation budgets
- retrieval-policy observability

Performance is a hard I-004 acceptance dimension, not the initiative's sole product identity.

### I-005 — Agent Context Platform

Owns longer-horizon context/memory:

- persistent agent context
- cross-session memory
- associative memory
- long-horizon retrieval
- agent-facing context APIs / MCP
- HippoRAG-style memory research where justified

## 8. Current dispositions

```text
Multi-substrate adaptive evidence architecture = STRONG TARGET HYPOTHESIS
EvidencePlan / CoverageReport control primitives = STRONG HYPOTHESIS
Retrieval Policy Engine = STRATEGIC TARGET
Structured knowledge = PRIORITY EXPERIMENT
Connector-native structured retrieval = PRIORITY EXPERIMENT
Graph retrieval = PRIORITY EXPERIMENT
Hierarchical/global retrieval = CONDITIONAL EXPERIMENT
CoverageReport-driven corrective retrieval = PRIORITY EXPERIMENT
Bounded agentic retrieval = PRIORITY EXPERIMENT
Wholesale GraphRAG migration = NOT RECOMMENDED
Unrestricted agent loop as default = REJECT
Long-context-only replacement = REJECT
HippoRAG-style memory = DEFER TO I-005
Target architecture freeze = NOT READY
```

## 9. Remaining evidence before architecture freeze

R-001 should now move from broad research into consolidation / decision preparation.

Required next evidence:

1. post-I-002 Production Benchmark and failure attribution;
2. ASK-AI-specific capability gap mapping using real Benchmark failures, Issues #26–#31 and real CamThink questions;
3. A0–A5 architecture experiments on representative ASK-AI data;
4. measured final-answer/evidence quality, latency and cost;
5. lifecycle/provenance feasibility for structured/graph derived state;
6. Repo Reality Check for current extension points and connector-native semantics.

Decision sequence:

```text
Existing R-001 / R-001A research
        ↓
Architecture Option Matrix   ← this document
        ↓
ASK-AI Capability Gap
        ↓
A0–A5 Experiments
        ↓
Quality / Efficiency / Operability Evaluation
        ↓
Target Architecture Decision
        ↓
I-003 / I-004 architecture and roadmap freeze
```

Until those gates are satisfied:

`ARCHITECTURE DECISION = NOT READY TO FREEZE`
