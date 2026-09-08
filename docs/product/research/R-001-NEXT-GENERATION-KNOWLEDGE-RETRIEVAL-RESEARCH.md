# R-001 — Next-Generation Knowledge & Retrieval Research

**Status:** RESEARCH CONSOLIDATED — AUTHORITATIVE RESEARCH INPUT  
**Authority:** AUTHORITATIVE for R-001 research evidence and architecture-option conclusions  
**Repository:** `harryhua-ai/ask-ai`  
**Research branch:** `research/r001-knowledge-retrieval-architecture`  
**Date:** 2026-09-08  
**Implementation authorization:** NONE  
**Production mutation:** NONE  
**Benchmark mutation:** NONE

**Supersedes:**
- `R-001-NEXT-GENERATION-KNOWLEDGE-RETRIEVAL-ARCHITECTURE.md`
- `R-001A-STRUCTURED-KNOWLEDGE-AND-ADAPTIVE-RETRIEVAL.md`
- `R-001B-ARCHITECTURE-OPTION-MATRIX.md`

**Downstream decision framework:**
- `R-001C-ASK-AI-CAPABILITY-GAP-ARCHITECTURE-DECISION-FRAMEWORK.md`

---

## 1. Purpose and authority

This document consolidates R-001, R-001A and R-001B into the single research Source of Truth for ASK-AI's next-generation knowledge and retrieval architecture.

It answers:

> Which knowledge and retrieval capabilities should ASK-AI evaluate over the next 1–3 years, which architectural patterns can provide them, and which directions should ASK-AI keep, borrow, experiment with, reject or defer?

It deliberately does **not** answer:

> Which framework should ASK-AI migrate to now?

R-001 is research evidence and architecture-option consolidation. It does not freeze a target architecture. ASK-AI-specific capability gaps, experiment selection and architecture freeze gates live in R-001C.

Where earlier R-001/R-001A working conclusions differ from the later R-001B consolidation, this document follows the later consolidated conclusion.

---

## 2. Architecture selection principles

### 2.1 Best evidence-backed target architecture

> ASK-AI SHALL optimize for the best evidence-backed target architecture available at the time of decision. Existing ASK-AI architecture has no preservation privilege. Newer paradigms have no adoption privilege.

Architecture decisions must be driven by measured:

- final answer quality;
- evidence quality;
- adaptivity;
- efficiency;
- reliability;
- provenance;
- lifecycle correctness;
- operational cost.

Migration constraints influence execution sequencing, not the target architecture ceiling.

### 2.2 Final-answer gain > retrieval novelty

A new retrieval mechanism is not valuable merely because it increases recall or is architecturally newer. It must improve final answer/evidence outcomes and/or efficiency enough to justify latency, cost and operational complexity.

### 2.3 Capability before framework

ASK-AI should decide which capabilities it needs before selecting frameworks.

GraphRAG, LightRAG, RAPTOR, HippoRAG, vector databases and graph databases are implementation candidates inside an architecture; none should become the product architecture by brand name.

### 2.4 Graph for navigation; source-backed evidence for truth

Structured/graph representations may improve discovery and navigation, but material answer truth must remain attributable to authoritative source evidence or connector-native records.

### 2.5 Bounded intelligence over unrestricted autonomy

Adaptive and agentic retrieval are legitimate future capabilities, but open-ended agent loops should not become the default request path. Retrieval control must remain bounded, observable and evidence-oriented.

---

## 3. ASK-AI architecture model

The research converged on four architectural layers.

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
- authorized external/tool retrieval

### Layer 4 — Retrieval Control

- deterministic routing
- parallel multi-route retrieval
- sequential escalation
- lightweight / learned routing
- cost-aware policy
- CoverageReport-driven corrective retrieval
- bounded agentic retrieval

The strategic architecture question is therefore not `Hybrid vs GraphRAG`. It is how ASK-AI should evolve its Evidence Control Plane to select and compose interchangeable evidence substrates.

---

## 4. Research landscape conclusion

The 2026 RAG landscape does not converge on one universal successor to traditional RAG.

The investigated directions solve different failure classes:

```text
Advanced Hybrid Retrieval
Structured / Graph Knowledge
Hierarchical / Global Retrieval
Adaptive Retrieval Routing
Bounded Agentic Retrieval
Continual / Associative Memory
Long Context
```

The research conclusion is:

> ASK-AI should treat retrieval as a capability portfolio rather than replace its current architecture with one universal advanced retriever.

Recent routing/adaptive-RAG research reinforces that no single retrieval paradigm is universally optimal across query and corpus conditions. This supports route selection rather than universal migration.

---

## 5. Advanced Hybrid Retrieval

Modern Hybrid retrieval remains a strong default substrate:

```text
lexical / sparse
+ dense semantic retrieval
+ metadata constraints
+ contextualized representation
+ reranking
```

Contextual Retrieval research demonstrates that improving chunk representation, lexical+dense retrieval and reranking can materially reduce retrieval failures without graph infrastructure.

### ASK-AI conclusion

- current Hybrid retrieval remains the control/default fast path;
- BM25/vector and reranking remain complementary;
- context-enhanced chunk representation deserves experiment coverage;
- Hybrid has no preservation privilege and must compete empirically with newer approaches.

**Disposition:** `KEEP AS BASELINE / EVOLVE / EXPERIMENT`.

---

## 6. Structured Knowledge

ASK-AI has a strong product-specific case for first-class structured knowledge because users ask relationship and constraint questions that are not naturally represented as isolated chunks.

### Candidate entities

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

### Candidate relations

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

This is intentionally a small domain model, not an ontology project.

### What should not automatically become authoritative structured truth

Do not silently promote arbitrary LLM-extracted prose into authoritative facts, especially:

- subjective suitability;
- recommendations;
- inferred compatibility;
- inferred limitations;
- volatile pricing/availability;
- current firmware behavior;
- version/time-dependent claims;
- customer-specific conclusions.

Derived structure can aid discovery, but answer authority must remain governed.

---

## 7. Structured Knowledge authority model

The strongest research hypothesis distinguishes three provenance classes.

### A — Connector-native structured truth

Examples:

- WooCommerce SKU / variation / price / availability;
- source-native IDs;
- connector-native metadata.

This is the strongest candidate for first-class structured truth because the structure already exists authoritatively upstream.

### B — Explicit authoritative source relation

Examples:

- official documentation explicitly lists an interface;
- a product page explicitly lists a capability;
- a case explicitly names a deployed product.

These may become structured relations while preserving source identity and lifecycle.

### C — Derived / inferred relation

Examples:

- an LLM infers a relationship from prose;
- an extraction process derives a relation across documents;
- graph/community processing creates a higher-order relationship.

Useful for discovery, but weaker than A/B.

### Candidate authority invariant

```text
connector-native truth
    > explicit authoritative source relation
    > derived / inferred relation
```

Every material relation should remain resolvable to stable provenance such as `source_id + chunk_index` or a connector-native record identity.

---

## 8. Lifecycle and provenance are architecture gates

A structured/graph substrate introduces derived-state lifecycle obligations.

Minimum semantics must cover:

```text
SOURCE ACTIVE
    ↓ update
DERIVED STATE RECONCILED

SOURCE RETIRED
    ↓
DERIVED RELATIONS NO LONGER ELIGIBLE

SOURCE DELETED
    ↓
SOURCE-EXCLUSIVE RELATIONS REMOVED
SHARED RELATIONS RECOMPUTED / RECONCILED
```

Required principles:

- no orphan relation survives solely because a retired source once asserted it;
- shared relations require provenance-aware reference semantics;
- failed derived-state updates must not silently corrupt answer truth;
- graph/structured health must be observable independently;
- recovery requires explicit rebuild/reconciliation semantics.

This is why graph retrieval quality cannot be evaluated independently of I-003 lifecycle/provenance correctness.

---

## 9. Knowledge Graph ≠ GraphRAG

A first-class domain Knowledge Graph does not require adopting a GraphRAG framework.

ASK-AI may gain substantial value from a small governed relationship substrate while retaining its own Evidence Control Plane.

Potential relationship-heavy tasks include:

```text
Requirement
→ Capability constraints
→ Product / Variant
→ Solution pattern
→ Case evidence
→ Current commercial truth
```

This can be implemented through structured retrieval or graph traversal without making graph-generated facts the answer authority.

**Disposition:** governed structured/domain graph capability = `PRIORITY EXPERIMENT`.

---

## 10. Microsoft GraphRAG

GraphRAG's important architectural contributions are:

- local/entity-centered retrieval;
- global/corpus-level retrieval;
- entity/relation extraction;
- community summaries;
- cross-document relationship reasoning.

DRIFT-style search is particularly relevant because it combines global/community context with local exploration and bounded follow-up queries.

### Strengths

- corpus-global questions;
- cross-document relationship discovery;
- multi-hop solution/design questions;
- global/community summaries.

### Risks

- indexing cost;
- graph extraction quality;
- maintenance complexity;
- graph freshness/deletion semantics;
- provenance from derived graph facts back to authoritative evidence;
- risk of creating a second weaker source of truth.

### ASK-AI conclusion

- GraphRAG concepts: `BORROW`;
- local/global/DRIFT ideas: `BORROW / EXPERIMENT`;
- Microsoft GraphRAG as ASK-AI control-plane/core replacement: `NOT RECOMMENDED`.

---

## 11. LightRAG

LightRAG is a useful graph-oriented prototype candidate because it combines graph and vector retrieval and supports dynamic knowledge operations.

Relevant patterns include:

- graph + vector retrieval;
- local/global/mix modes;
- reranking;
- incremental updates;
- document deletion / regeneration;
- multiple storage backends.

Its operational model also exposes the lifecycle cost of dual graph/vector state: KV, vector, graph and document-status surfaces can diverge and require explicit consistency/recovery handling.

### ASK-AI conclusion

- LightRAG patterns: `BORROW`;
- isolated prototype: `PROMISING / EXPERIMENT`;
- direct ASK-AI migration: `NOT RECOMMENDED WITHOUT BENCHMARK + LIFECYCLE EVIDENCE`.

---

## 12. Hierarchical Retrieval / RAPTOR

Hierarchical retrieval addresses loss of document/global context through multi-level abstraction:

```text
leaf chunks
→ semantic clusters
→ cluster summaries
→ higher-level summaries
```

Potential ASK-AI use cases:

- product-family overview;
- cross-document solution synthesis;
- large documentation navigation;
- corpus-level themes.

However, hierarchical summaries do not inherently solve arbitrary cross-document relationships. They are complementary to structured relations.

### ASK-AI conclusion

`CONDITIONAL EXPERIMENT` when real global/corpus questions prove material.

---

## 13. HippoRAG / Associative Memory

HippoRAG-style systems target non-parametric continual memory, associativity and multi-hop contextual recall.

This is strategically more aligned with the future Agent Context Platform than the current Widget answer path.

Potential future uses:

- persistent agent context;
- cross-repository engineering knowledge;
- long-lived support/solution memory;
- associative recall across continually growing corpora.

### ASK-AI conclusion

`DEFER TO I-005 / MEMORY RESEARCH` unless production evidence establishes an earlier need.

---

## 14. Adaptive Retrieval Routing

The strongest research conclusion is that retrieval should become routing-aware.

Conceptually:

```text
Task Understanding
        ↓
EvidencePlan
        ↓
Retrieval Policy
        ├─ FAST_FLAT
        ├─ STRUCTURED
        ├─ GRAPH / RELATIONSHIP
        ├─ GLOBAL / HIERARCHICAL
        └─ BOUNDED CORRECTIVE
        ↓
Evidence Composition
        ↓
CoverageReport
```

### FAST_FLAT

Default for ordinary factual/support queries where evidence is local.

### STRUCTURED

For stable relationship/native-data constraints such as product ↔ variant ↔ SKU ↔ capability ↔ region.

### GRAPH / RELATIONSHIP

For relationship-heavy or multi-hop navigation where explicit traversal measurably beats structured/flat alternatives.

### GLOBAL / HIERARCHICAL

For corpus-level synthesis that cannot be answered well by a small local chunk set.

### BOUNDED CORRECTIVE

Only when the first pass leaves material required evidence uncovered and a clear retrieval objective remains.

**Disposition:** `STRATEGIC TARGET`.

---

## 15. CoverageReport-driven Corrective Retrieval

ASK-AI already has a potentially valuable control primitive:

```text
EvidencePlan
= what evidence the task requires

CoverageReport
= which required evidence is actually present
```

This creates a more inspectable corrective-retrieval mechanism than unconstrained model reflection.

Example:

```text
EvidencePlan:
  SOLUTION_GUIDE required
  PRODUCT_SPEC optional

first retrieval:
  PRODUCT_SPEC found
  SOLUTION_GUIDE missing

CoverageReport:
  incomplete
  missing_required = SOLUTION_GUIDE

corrective action:
  retrieve specifically for SOLUTION_GUIDE
```

Candidate invariant:

```text
CoverageReport incomplete
AND missing required evidence is retrievable in principle
AND escalation budget remains
→ bounded corrective retrieval
```

This remains a hypothesis requiring experiment evidence.

**Disposition:** `PRIORITY EXPERIMENT`.

---

## 16. Bounded Agentic Retrieval

Agentic RAG expands retrieval into iterative planning/search/refinement.

Potential advantage:

- decomposition;
- exploratory retrieval;
- reformulation;
- multi-hop/tool use;
- recovery from incomplete first-pass evidence.

Major risks:

- latency;
- token/inference cost;
- non-determinism;
- trajectory reliability;
- debugging/failure attribution;
- authority drift.

ASK-AI should therefore treat agentic retrieval as bounded escalation rather than the default path.

Potential policy evolution, not frozen:

```text
v1 deterministic routing
→ v2 lightweight learned router
→ v3 cost-aware adaptive policy
→ v4 bounded agentic policy
```

**Disposition:** bounded agentic retrieval = `PRIORITY EXPERIMENT`; unrestricted default loop = `REJECT`.

---

## 17. Long Context

Large context windows can reduce retrieval pressure when a bounded relevant context is already known, but they do not solve:

- authority;
- freshness;
- source visibility;
- product/variant isolation;
- current commercial truth;
- evidence-role coverage;
- provenance;
- citation support;
- missing-evidence truth;
- efficient corpus search.

**Disposition:** `SUPPORTING CAPABILITY`; long-context-only retrieval replacement = `REJECT`.

---

## 18. Context Utility Optimization

Research and competitive evidence indicate that retrieval quality and generator-context quality are distinct.

Even high-recall retrieval can deliver redundant, distracting or low-utility context to generation.

ASK-AI should evaluate context utility/pruning while protecting required evidence slots.

Experiment dimension:

```text
C0 current pruning
C1 evidence-role deterministic pruning
C2 listwise model pruning
C3 required-slot protected + listwise pruning
```

**Disposition:** `EXPERIMENT REQUIRED` under I-004.

---

## 19. Failure taxonomy implications

ASK-AI Benchmark v1 uses:

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

The pre-I-002 attribution did **not** prove graph/multi-hop retrieval as ASK-AI's dominant problem. Known failures were materially concentrated in interaction/evidence composition, while many observations remained K9.

Therefore current evidence does not justify a wholesale graph migration.

### Graph/structured retrieval may help

- multi-hop relationships;
- product/variant/capability compatibility;
- solution architecture synthesis;
- relationship-heavy recommendation constraints;
- corpus-global questions;
- associative discovery.

### Graph does not inherently solve

- source absence/discovery;
- freshness;
- wrong authority;
- Store lifecycle;
- retirement/deletion;
- wrong interaction classification;
- bad response strategy;
- citation correctness;
- latency;
- Admin knowledge observability.

---

## 20. Architecture Option Matrix

| Option / Direction | Primary problem | Strength | Main risk | Disposition | Ownership |
|---|---|---|---|---|---|
| Current Hybrid | Local factual retrieval | Cheap, mature, deterministic | Weak on some relationships/global tasks | BASELINE / CONTROL | I-004 |
| Frontier Hybrid | Stronger flat retrieval | Low architectural burden | Does not solve native structure/global reasoning | EXPERIMENT | I-004 |
| Connector-native Structured | Exact native truth | High authority, low inference risk | Connector-specific normalization | PRIORITY EXPERIMENT | I-003 → I-004 |
| Governed Structured Domain Knowledge | Stable domain relations | Explicit constraints/isolation | Governance/lifecycle burden | PRIORITY EXPERIMENT | I-003 → I-004 |
| Graph capability | Multi-hop relationship navigation | Natural traversal | Stale/opaque derived truth | PRIORITY EXPERIMENT | I-003 → I-004 |
| GraphRAG patterns | Local/global/community retrieval | Strong reference architecture | Heavy indexing/control coupling | BORROW IDEAS | I-004 research |
| LightRAG/equivalent | Graph+vector prototype | Practical graph experiment | Multi-state lifecycle complexity | PROMISING / EXPERIMENT | I-003/I-004 |
| RAPTOR/hierarchical | Global abstraction | Good corpus synthesis | Does not replace explicit relations | CONDITIONAL EXPERIMENT | I-004 |
| Adaptive Routing | Select best path per task | Avoid universal advanced-path tax | Router errors/observability | STRATEGIC TARGET | I-004 |
| Retrieval Policy Engine | Evidence-aware action selection | Stable control plane | Must remain bounded/inspectable | STRONG TARGET HYPOTHESIS | I-004 |
| Parallel Multi-Substrate | Complementary evidence | Higher coverage ceiling | Latency/cost/conflict | EXPERIMENT | I-004 |
| Coverage Corrective Retrieval | Missing required evidence | Explicit bounded objective | Depends on plan/coverage quality | PRIORITY EXPERIMENT | I-004 |
| Bounded Agentic Policy | Difficult iterative search | High ceiling | Cost/latency/reliability | PRIORITY EXPERIMENT | I-004 |
| Unrestricted Agent Loop | Open-ended search | Maximum flexibility | Unbounded operational risk | REJECT DEFAULT | None |
| Associative Memory | Long-horizon context | Agent memory | Wrong current horizon | DEFER | I-005 |
| Long-context-only | Avoid retrieval | Simplicity in bounded cases | Fails truth/lifecycle/governance | REJECT REPLACEMENT | None |

---

## 21. Preferred target architecture hypothesis

The strongest current hypothesis is a **Multi-Substrate Adaptive Evidence Architecture**:

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
Rerank / Context Utility Optimization
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

The control plane remains ASK-AI-owned. Retrieval frameworks remain replaceable mechanisms/substrates.

This is a **target hypothesis**, not an architecture decision.

---

## 22. Architecture Experiment Matrix

| Arm | Composition | Decision purpose |
|---|---|---|
| A0 — Current Baseline | Current accepted Hybrid | Establish real control |
| A1 — Frontier Hybrid | Strong sparse+dense/hybrid + rerank/context enhancement | Determine flat-retrieval ceiling |
| A2 — Structured Hybrid | A1 + connector-native/governed structured knowledge | Measure native/structured truth value |
| A3 — Graph-Augmented | A2 + graph relationship traversal | Measure incremental multi-hop/relationship gain |
| A4 — Multi-Substrate Routed | Route/compose A1/A2/A3 + global where justified | Test preferred target hypothesis |
| A5 — Bounded Agentic Policy | A4 + bounded iterative retrieval/reformulation | Measure marginal agentic value/cost |

Frameworks such as LightRAG, GraphRAG-derived components or RAPTOR may implement experiment arms; they do not define the arms.

### Mandatory test slices

- local factual control;
- structured relationship;
- exact connector-native commercial truth;
- multi-hop solution;
- product/version isolation;
- global/corpus synthesis where material;
- lifecycle mutation/update/delete/reconciliation;
- corrective retrieval with a deliberately uncovered required slot;
- rich/tool knowledge representation where relevant.

---

## 23. Experiment metrics

### Answer / evidence quality

- final answer correctness;
- required-slot coverage;
- evidence recall;
- unsupported-claim rate;
- provenance completeness;
- product/variant isolation;
- multi-hop completeness;
- global-answer comprehensiveness;
- answer usefulness/completeness.

### Runtime / efficiency

- retrieval latency;
- TTFT;
- E2E;
- additional LLM calls;
- escalation frequency;
- token/inference cost.

### Operational fitness

- indexing LLM calls;
- embedding work;
- incremental update cost;
- delete/retirement cost;
- recovery/rebuild cost;
- storage complexity;
- reconciliation failures.

### Governance

- source → derived relation traceability;
- stale relation detection;
- rollback semantics;
- observability;
- authority preservation.

### Pareto decision

```text
quality gain / added latency
quality gain / added cost
quality gain / added architecture and operational risk
```

---

## 24. Roadmap ownership

### I-003 — Knowledge Intelligence & Operations

Owns Knowledge Truth and substrate governance:

- source content observability;
- lifecycle / retirement / deletion;
- authority / freshness;
- connector-native structured knowledge;
- governed domain relations;
- provenance;
- reconciliation/rebuild;
- structured/graph substrate health;
- rich representation;
- hierarchical/global derived-state lifecycle if adopted.

### I-004 — Adaptive Retrieval Intelligence

Owns retrieval decision intelligence:

- Retrieval Policy Engine;
- frontier Hybrid;
- structured retrieval;
- graph traversal;
- hierarchical/global retrieval;
- parallel/sequential multi-substrate retrieval;
- EvidencePlan-aware retrieval;
- CoverageReport-driven corrective retrieval;
- bounded agentic retrieval;
- Context Utility Optimization;
- latency/cost/escalation budgets;
- retrieval-policy observability.

Performance is a hard acceptance dimension, not the initiative's sole product identity.

### I-005 — Agent Context Platform

Owns longer-horizon agent context:

- agent-facing Retrieval API / MCP;
- product semantics for tool planning;
- persistent/cross-session context;
- associative memory;
- long-horizon retrieval;
- HippoRAG-style memory research where justified.

---

## 25. Current dispositions

```text
Multi-Substrate Adaptive Evidence Architecture = STRONG TARGET HYPOTHESIS
EvidencePlan / CoverageReport control primitives = STRONG HYPOTHESIS
Retrieval Policy Engine                         = STRATEGIC TARGET
Frontier Hybrid                                 = EXPERIMENT
Connector-native Structured Retrieval           = PRIORITY EXPERIMENT
Governed Structured Knowledge                   = PRIORITY EXPERIMENT
Graph Retrieval                                 = PRIORITY EXPERIMENT
Hierarchical / Global Retrieval                 = CONDITIONAL EXPERIMENT
CoverageReport-driven Corrective Retrieval      = PRIORITY EXPERIMENT
Context Utility Optimization                    = EXPERIMENT REQUIRED
Bounded Agentic Retrieval                       = PRIORITY EXPERIMENT
Wholesale GraphRAG Migration                    = NOT RECOMMENDED
Unrestricted Agent Loop                         = REJECT AS DEFAULT
Long-context-only Replacement                   = REJECT
HippoRAG-style Memory                           = DEFER TO I-005
Target Architecture Freeze                      = NOT READY
```

---

## 26. Evidence still required before architecture freeze

R-001 research is sufficiently consolidated to stop broad architecture research. Architecture authority still requires ASK-AI-specific evidence:

1. post-I-002 Production Benchmark and failure attribution;
2. R-001C capability-gap reconciliation;
3. Repo Reality Check for connector-native semantics, lifecycle and retrieval extension points;
4. A0–A5 experiments on representative ASK-AI data;
5. measured final-answer/evidence quality, latency and cost;
6. lifecycle/provenance feasibility for structured/graph/derived state;
7. quality/efficiency/operability review.

Decision sequence:

```text
R-001 consolidated research
        +
R-002 Kapa competitive research
        ↓
R-001C ASK-AI Capability Gap
        ↓
Post-I-002 Production Benchmark
        ↓
Repo Reality Check
        ↓
A0–A5 Experiments
        ↓
Quality / Efficiency / Operability Evaluation
        ↓
Target Architecture Decision
        ↓
I-003 / I-004 Roadmap Freeze
```

Until those gates are satisfied:

```text
ARCHITECTURE DECISION = NOT READY TO FREEZE
IMPLEMENTATION AUTHORIZATION = NONE
```

---

## 27. Research closure summary

R-001 broad research is now consolidated and sufficient for decision preparation.

The central conclusion is not that ASK-AI should become a GraphRAG, LightRAG or agentic-RAG product.

It is:

> ASK-AI should evolve toward an evidence-oriented architecture in which one governed control plane can select and compose multiple replaceable knowledge/retrieval substrates according to the task's explicit evidence objective.

The strongest target hypothesis is therefore **Multi-Substrate Adaptive Evidence Architecture**.

The strongest ASK-AI-specific control hypothesis is:

```text
EvidencePlan
→ retrieval policy
→ evidence composition
→ CoverageReport
→ bounded corrective retrieval when required
→ generation
→ claim/citation validation
```

Whether structured knowledge, graph traversal, hierarchical retrieval and bounded agentic control earn production adoption must now be decided by ASK-AI-specific experiments rather than additional broad research.
