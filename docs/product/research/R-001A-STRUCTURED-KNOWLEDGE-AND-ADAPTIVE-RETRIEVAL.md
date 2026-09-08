# R-001A — Structured Knowledge & Adaptive Retrieval Deep Dive

**Status:** RESEARCH IN PROGRESS — DECISION INPUT ONLY  
**Parent:** `R-001-NEXT-GENERATION-KNOWLEDGE-RETRIEVAL-ARCHITECTURE.md`  
**Research owner:** Product / Architecture (Agent A)  
**Repository:** `harryhua-ai/ask-ai`  
**Research branch:** `research/r001-knowledge-retrieval-architecture`  
**ASK-AI engineering reference baseline:** `292c83a159eb77d1efb979d42ac00ce0dbef6220`  
**Date:** 2026-09-08

> This document is research evidence. It does not authorize implementation, production mutation, Benchmark mutation, or a graph migration.

---

## 1. Purpose

R-001 established a working hypothesis: ASK-AI should preserve its Evidence Planning / Coverage control plane while allowing multiple evidence substrates underneath it.

This deep dive narrows two questions:

1. What structured knowledge should become first-class in ASK-AI?
2. How should ASK-AI choose between fast flat retrieval, structured/graph retrieval, hierarchical/global retrieval, and bounded corrective retrieval?

The goal is not to choose a framework. The goal is to define the product semantics that a future retrieval architecture must support.

---

## 2. New external evidence

### 2.1 No single RAG paradigm is universally optimal

RAGRouter-Bench (2026) evaluates multiple RAG paradigms across query/corpus contexts and explicitly reports that no single paradigm is universally optimal. More advanced mechanisms do not automatically produce a better effectiveness/efficiency trade-off.

**ASK-AI implication:** retrieval architecture should become routing-aware rather than replacing the current Hybrid substrate with one globally applied advanced retriever.

### 2.2 Global and local retrieval are distinct product needs

Microsoft GraphRAG distinguishes local/entity-centered retrieval from corpus-global questions. DRIFT combines community/global context with local follow-up exploration, and bounds refinement using termination criteria.

**ASK-AI implication:** global/hierarchical/graph retrieval should be a query-mode capability, not a tax imposed on ordinary factual product Q&A.

### 2.3 Hierarchical retrieval helps abstraction but does not solve cross-document relations by itself

RAPTOR recursively clusters and summarizes text to provide multiple abstraction levels. Later work continues to explore cross-document tree retrieval, but also identifies structural isolation as a limitation of pure tree indexes for cross-document multi-hop tasks.

**ASK-AI implication:** hierarchical summaries and explicit structured relationships solve different problems. They should not be collapsed into one feature.

### 2.4 Graph/vector dual state has real lifecycle cost

Current LightRAG supports graph + vector retrieval, incremental updates and selective deletion, but production operation requires multiple logical storage surfaces: KV, vector, graph and document status. Its storage contracts explicitly discuss persistence callbacks, multi-worker visibility and consistency concerns around deletes/upserts.

**ASK-AI implication:** graph quality must be evaluated together with source lifecycle correctness, reconciliation, rollback and provenance. A graph substrate cannot become an opaque second truth.

### 2.5 Associative memory is a different horizon

HippoRAG 2 frames the problem as non-parametric continual memory, targeting factual memory, associativity and sense-making. This is strategically relevant to persistent Agent Context, but it is not evidence that the current interactive Widget path should be rebuilt around memory-oriented retrieval.

**ASK-AI implication:** keep associative memory in I-005 unless production evidence proves an earlier need.

---

## 3. Structured knowledge: what should become first-class?

The key distinction is between **stable domain relations** and **volatile/document-derived claims**.

### 3.1 Candidate first-class entity types

The strongest candidates for explicit structured representation are:

- `Product`
- `ProductVariant`
- `Capability`
- `Accessory`
- `Interface`
- `Solution`
- `Case`
- `Document`
- `StoreSKU`
- `Region`

These are useful because users naturally ask questions whose answer depends on relationships among them rather than isolated prose similarity.

### 3.2 Candidate first-class relation types

High-value candidate relations:

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

ProductVariant
  ├─ SOLD_AS → StoreSKU
  ├─ AVAILABLE_IN → Region
  └─ SUPPORTS → Capability

Solution
  ├─ REQUIRES → Capability
  ├─ USES → Product / ProductVariant
  └─ EVIDENCED_BY → Case
```

This is intentionally small. It is not an ontology project.

### 3.3 What should NOT automatically become graph truth

Do not promote arbitrary extracted prose claims into authoritative graph facts merely because an LLM can extract them.

Examples that should remain source-backed evidence unless separately governed:

- subjective product suitability;
- recommendations;
- inferred compatibility;
- inferred limitations;
- transient pricing;
- availability;
- current firmware behavior;
- claims that depend on document version/time;
- customer-specific conclusions.

The graph may index or point to such claims, but the authoritative answer must still resolve to source evidence and freshness semantics.

---

## 4. Authority model for structured knowledge

A future structured substrate should distinguish at least three provenance classes.

### A. Connector-native structured truth

Examples:

- WooCommerce SKU / variant / price / availability;
- explicit product IDs;
- connector-native metadata.

This is the strongest candidate for first-class structured truth because structure already exists at the source.

### B. Explicit document-declared structure

Examples:

- a product page explicitly lists an interface;
- official documentation explicitly lists a supported capability;
- a case page explicitly names the deployed product.

This may be represented structurally, but must preserve source identity and source lifecycle.

### C. Derived/inferred structure

Examples:

- an LLM infers that a solution requires a capability;
- an extraction pipeline infers a relationship across prose;
- graph community processing creates a higher-order relationship.

This is useful for discovery but must not silently outrank A/B evidence.

### Candidate authority invariant

```text
connector-native truth
    > explicit authoritative source relation
    > derived/inferred relation
```

This is a research hypothesis for later architecture closure, not yet a Frozen Contract.

---

## 5. Provenance contract hypothesis

Every structured relation used as material answer evidence should be able to resolve back to one or more stable source identities.

Conceptually:

```text
StructuredRelation
    relation_id
    subject
    predicate
    object
    provenance[]
        source_id
        chunk_index / native_record_id
    authority
    observed_at / effective_at where available
    derivation
```

The exact schema is intentionally NOT frozen here.

The important semantic requirement is:

> Graph traversal may discover evidence; it must not erase where the evidence came from.

This preserves compatibility with ASK-AI's EvidencePlan, CoverageReport, citation and claim-validation direction.

---

## 6. Lifecycle contract hypothesis

A graph/structured substrate introduces a derived-state lifecycle problem.

Minimum future lifecycle semantics should cover:

```text
SOURCE ACTIVE
    ↓ update
DERIVED RELATIONS RECONCILED

SOURCE RETIRED
    ↓
RELATIONS NO LONGER ELIGIBLE

SOURCE DELETED
    ↓
SOURCE-EXCLUSIVE RELATIONS REMOVED
SHARED RELATIONS RECOMPUTED / RECONCILED
```

Important principles:

- no orphan edge may survive solely because a retired source once asserted it;
- shared relations require provenance-aware reference semantics;
- a failed graph update must not silently corrupt the current answer truth;
- graph health must be observable separately from source/index health;
- recovery must have an explicit rebuild/reconciliation path.

This is why I-003 lifecycle work remains a prerequisite for production graph adoption.

---

## 7. Retrieval routing hypothesis

The strongest current architecture hypothesis is not `Hybrid vs Graph` but **adaptive substrate selection under one EvidencePlan**.

```text
Task Understanding
        ↓
EvidencePlan
        ↓
Retrieval Route
        │
        ├─ FAST_FLAT
        ├─ STRUCTURED
        ├─ GLOBAL_HIERARCHICAL
        └─ BOUNDED_CORRECTIVE
        ↓
Evidence Composition
        ↓
CoverageReport
```

### FAST_FLAT

Default for ordinary factual/support questions where evidence is likely local and lexical/semantic retrieval is sufficient.

Expected substrate:

- BM25;
- vector;
- metadata filters;
- reranker.

### STRUCTURED

Use when the task explicitly depends on stable relationships or constraints.

Candidate examples:

- product ↔ variant;
- product ↔ capability;
- accessory compatibility;
- solution ↔ required capability;
- Store SKU/variant constraints.

### GLOBAL_HIERARCHICAL

Use for corpus-level synthesis where the question is not naturally answered by a small set of local chunks.

Candidate examples:

- major solution patterns across the knowledge base;
- recurring deployment architectures across cases;
- summarize major differences across a product family.

This could use hierarchical summaries, graph communities, or another global index. The product contract should not care which implementation supplies it.

### BOUNDED_CORRECTIVE

Escalation only when the first retrieval pass leaves material required evidence uncovered and a second retrieval has a clearly defined evidence target.

Candidate invariant:

```text
CoverageReport incomplete
AND missing required evidence is retrievable in principle
AND escalation budget remains
→ one bounded corrective retrieval
```

Do not create an unconstrained agent loop.

---

## 8. Why CoverageReport is strategically important

Most agentic-RAG systems decide to continue searching using model reflection, heuristics, or reward logic.

ASK-AI has the opportunity to use a more inspectable control signal:

```text
EvidencePlan
    defines required evidence

CoverageReport
    states what required evidence is actually present
```

This makes future retrieval escalation potentially deterministic or tightly bounded.

Example:

```text
Recommendation request
    ↓
EvidencePlan:
  SOLUTION_GUIDE required
  PRODUCT_SPEC optional
    ↓
first retrieval
    ↓
CoverageReport:
  SOLUTION_GUIDE missing
  PRODUCT_SPEC covered
    ↓
corrective retrieval target is known:
  retrieve SOLUTION_GUIDE
```

This is materially different from asking an unrestricted agent to “search again until satisfied.”

**Research recommendation:** preserve CoverageReport as the primary retrieval-completeness signal and allow agentic behavior only as a bounded mechanism underneath it.

---

## 9. Product-level experiment design

A useful experiment must answer a product decision, not merely demonstrate that a graph can be built.

### Research question

> Does structured/graph retrieval materially improve ASK-AI answers on relationship-heavy and global questions while preserving provenance, lifecycle correctness and acceptable latency?

### Candidate comparison arms

1. Current accepted Hybrid retrieval.
2. Context-enhanced Hybrid retrieval.
3. Minimal structured domain retrieval.
4. LightRAG or equivalent graph-oriented prototype.
5. Optional hierarchical/global prototype if global questions form a material use case.

### Test slices

#### Slice A — Local factual control

Questions that should remain easy for Hybrid retrieval.

Purpose: prove advanced routing does not regress ordinary Q&A.

#### Slice B — Structured relationship

Examples:

- which product variants support capability X and are sold in region Y?
- which accessory is compatible with product X?
- which current SKU corresponds to a specific product configuration?

#### Slice C — Multi-hop solution

Examples:

- given deployment constraints A/B/C, which product/variant fits, what solution pattern supports it, and what first-party case evidence exists?
- which products support a required capability and have evidence of deployment in a similar scenario?

#### Slice D — Global/corpus

Examples:

- what deployment patterns recur across official cases?
- what major capability gaps differentiate the product family?

#### Slice E — Lifecycle mutation

Controlled source update/delete/retirement cases.

Purpose: prove derived knowledge follows authoritative source lifecycle.

---

## 10. Required experiment metrics

Quality alone is insufficient.

Measure:

### Answer / evidence quality

- required-slot coverage;
- evidence recall;
- unsupported-claim rate;
- provenance completeness;
- product/variant isolation;
- multi-hop completeness;
- global-answer comprehensiveness.

### Operational fitness

- indexing LLM calls;
- embedding work;
- incremental update cost;
- delete/retirement cost;
- recovery/rebuild cost;
- storage complexity;
- reconciliation failures.

### Runtime

- retrieval latency;
- TTFT impact;
- E2E impact;
- additional LLM calls;
- escalation frequency.

### Governance

- source → derived relation traceability;
- stale relation detection;
- rollback semantics;
- observability.

A graph prototype that improves answer score but cannot satisfy lifecycle/provenance gates should not be production-adopted.

---

## 11. Framework decision implications

### Microsoft GraphRAG

Use as architecture/reference research for global/community retrieval and DRIFT-style exploration. Do not adopt as ASK-AI control plane.

### LightRAG

Keep as the leading current graph prototype candidate because it combines graph/vector retrieval and supports incremental lifecycle operations. Treat its multi-storage consistency requirements as part of the evaluation, not an implementation detail to ignore.

### RAPTOR / tree retrieval

Treat hierarchical abstraction as a separate optional substrate for global/document-level questions. It is complementary to structured relationships.

### HippoRAG 2

Keep deferred to Agent Context / memory research unless future evidence shows a near-term Widget requirement for associative continual memory.

### Generic Knowledge Graph

This remains the most strategically important concept because ASK-AI can introduce a small governed domain graph without adopting a generic GraphRAG framework.

---

## 12. Updated architecture hypothesis

```text
                              ASK-AI Evidence Control Plane

                                   Query
                                     │
                              Task Understanding
                                     │
                                EvidencePlan
                                     │
                         Deterministic / bounded routing
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        │                            │                            │
        ▼                            ▼                            ▼
   FAST_FLAT                   STRUCTURED                GLOBAL/HIERARCHICAL
 BM25 + Vector               Domain relations           summaries / graph
   + reranker                 + native data              communities
        │                            │                            │
        └────────────────────────────┼────────────────────────────┘
                                     ▼
                             Evidence Composition
                                     │
                                CoverageReport
                                     │
                     ┌───────────────┴───────────────┐
                     │                               │
                  complete                       incomplete
                     │                               │
                     │                    bounded corrective retrieval
                     │                       only when justified
                     └───────────────┬───────────────┘
                                     ▼
                              Response Strategy
                                     │
                                 Generation
                                     │
                         Claim / Citation Validation
```

The important design choice is **control-plane stability with substrate evolution**.

---

## 13. Updated decision summary

### Stronger than R-001 initial view

- `STRUCTURED DOMAIN KNOWLEDGE`: **PRIORITY EXPERIMENT**, especially connector-native Product/Variant/Store relationships.
- `ADAPTIVE RETRIEVAL ROUTING`: **STRATEGIC DIRECTION**, but routing should initially be deterministic/bounded rather than LLM-agent-controlled.
- `CoverageReport-driven corrective retrieval`: **HIGH-VALUE FUTURE EXPERIMENT**.

### Unchanged

- current Hybrid retrieval remains default fast path;
- EvidencePlan/Coverage remain the control plane;
- no wholesale GraphRAG migration;
- unrestricted agentic retrieval remains rejected as default;
- HippoRAG-style memory remains deferred to I-005;
- production graph adoption remains blocked on lifecycle/provenance evidence.

---

## 14. Roadmap implications

### I-003 — Knowledge Intelligence & Operations

Recommended capability order:

```text
Knowledge observability
    ↓
Lifecycle / retirement correctness
    ↓
Authority / freshness semantics
    ↓
Structured connector-native knowledge
    ↓
Derived structured relations with provenance
    ↓
Graph/structured retrieval experiment
```

Do not reverse this sequence by building a production graph before lifecycle truth is governable.

### I-004 — Interactive Answer Performance

Add retrieval-route latency and escalation frequency to performance evaluation. The default path must remain cheap.

### I-005 — Agent Context Platform

Revisit associative memory, richer graph traversal and longer-horizon agentic retrieval after the core structured knowledge model is proven.

---

## 15. Evidence still required before Architecture Decision

R-001/R-001A still cannot freeze a target architecture.

Required evidence:

1. post-I-002 production Benchmark and Failure Attribution;
2. a graph/structured-suitable ASK-AI research test slice;
3. Repo Reality Check for connector/native product semantics and current retrieval extension points;
4. lifecycle/provenance feasibility for derived relations;
5. measured comparison of Hybrid vs structured vs graph candidate on ASK-AI data;
6. latency/cost measurements.

Until these exist:

`ARCHITECTURE DECISION = NOT READY TO FREEZE`.

---

## 16. Current research verdict

**Evidence supports:**

> Evolve ASK-AI toward a multi-substrate, routing-aware evidence architecture while keeping EvidencePlan and CoverageReport as the stable control plane.

**Evidence does not yet support:**

> Migrating ASK-AI to GraphRAG, LightRAG, HippoRAG, or any other framework as the product's core architecture.

**Implementation authorization:** `NONE`  
**Production mutation:** `NONE`  
**Benchmark mutation:** `NONE`
