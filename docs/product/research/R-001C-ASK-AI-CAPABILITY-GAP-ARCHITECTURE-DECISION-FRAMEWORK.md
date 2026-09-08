# R-001C — ASK-AI Capability Gap & Architecture Decision Framework

**Status:** DECISION PREPARATION — FRAMEWORK READY / EVIDENCE PENDING  
**Repository:** `harryhua-ai/ask-ai`  
**Research branch:** `research/r001-knowledge-retrieval-architecture`  
**Date:** 2026-09-08  
**Implementation authorization:** NONE  
**Production mutation:** NONE  
**Benchmark mutation:** NONE

## 1. Purpose

R-001C converts the completed architecture and competitive research into an ASK-AI-specific decision framework.

It is intentionally not another broad technology survey. Its job is to connect:

```text
Observed Product Failure
→ Required Product Capability
→ Current ASK-AI Capability
→ Capability Gap
→ Competitive Bar / Kapa Status
→ Candidate Architecture Capability
→ Initiative Ownership
→ Experiment / Evidence Required
→ Decision Readiness
```

Primary inputs:

- R-001 / R-001A — next-generation knowledge/retrieval research;
- R-001B — Architecture Option Matrix;
- R-002 — authoritative Kapa.ai Competitive Research;
- accepted I-002 Answer Intelligence architecture;
- production Issues #26–#31;
- frozen Benchmark v1 baseline and failure taxonomy;
- post-I-002 Production Benchmark when available.

R-001C does **not** freeze a target architecture or authorize I-003/I-004 implementation.

---

## 2. Current decision state

```text
R-001 broad architecture research       = SUFFICIENT
R-002 Kapa competitive research         = CLOSED / AUTHORITATIVE
I-002 engineering                       = CLOSED / ACCEPTED
I-002 production deployment             = PENDING
POST_I002_BENCHMARK_EVIDENCE            = PENDING
ASK-AI capability-gap framework         = READY
A0–A5 architecture experiments          = NOT RUN
TARGET_ARCHITECTURE_FREEZE               = NOT READY
I-003 / I-004 IMPLEMENTATION CONTRACTS   = NOT AUTHORIZED
```

The missing post-I-002 Benchmark does not block creation of this framework. It blocks final attribution and architecture freeze.

---

## 3. Decision principles

### 3.1 Final-answer gain > retrieval novelty

A retrieval or knowledge architecture change is justified only when it materially improves one or more of:

- answer correctness;
- answer completeness/usefulness;
- evidence coverage;
- uncertainty/non-fabrication;
- citation/claim faithfulness;
- latency/cost efficiency;
- knowledge freshness/lifecycle correctness;
- operational diagnosability.

A newer framework receives no adoption privilege.

### 3.2 Existing architecture has no preservation privilege

Current Hybrid RAG is the control arm, not the target by default.

Migration cost affects sequencing, not the ceiling of the target architecture.

### 3.3 Capability before framework

Architecture decisions are expressed as capabilities:

```text
Knowledge Truth
Evidence Planning
Retrieval Policy
Structured Retrieval
Graph Traversal
Global/Hierarchical Retrieval
Corrective Retrieval
Context Utility Optimization
Bounded Agentic Retrieval
Claim/Evidence Governance
Agent Context Delivery
```

Frameworks such as GraphRAG, LightRAG, RAPTOR or a specific vector/graph database are implementation candidates only.

### 3.4 Evidence objective before generic search

The leading ASK-AI hypothesis remains:

```text
Task Understanding
→ EvidencePlan
→ Retrieval Policy
→ Evidence Composition
→ CoverageReport
→ corrective action when required evidence is missing
→ Response Strategy
→ Generation
→ Claim / Citation Validation
```

This is a hypothesis to prove, not a differentiation claim to assume.

### 3.5 Knowledge truth and retrieval intelligence are separate responsibilities

```text
I-003 = what knowledge exists, what it means, whether it is authoritative/current/usable
I-004 = how a task finds and composes the right evidence efficiently
```

Do not solve a missing-truth problem only with smarter retrieval, or a retrieval-policy problem only by adding more indexed content.

---

## 4. Current accepted ASK-AI capability baseline

I-002 established an accepted Evidence Control Plane foundation:

```text
Task Understanding
→ deterministic EvidencePlan
→ evidence selection/composition
→ CoverageReport
→ deterministic ResponseStrategy
→ existing single generation
→ Claim / Citation Validation
```

Accepted strengths relevant to future architecture:

- unified task understanding;
- explicit EvidencePlan and evidence roles;
- required-first evidence composition;
- CoverageReport as runtime evidence-coverage truth;
- natural response strategy derived without a new LLM call;
- partial-supported response semantics;
- claim/evidence validation after generation;
- stable evidence lineage;
- answer/stream semantic parity;
- zero-new-LLM control-plane additions in I-002.

Important limitation:

> I-002 primarily improves how already-retrieved evidence is understood, composed, realized and validated. It does not yet provide the future adaptive multi-substrate retrieval architecture or complete Knowledge Truth Plane.

Therefore the next architecture question is not whether to replace I-002, but how to extend its control primitives into knowledge truth and retrieval policy without breaking their authority boundaries.

---

## 5. Capability Gap Matrix

### G-01 — Interaction / context semantics

**Observed evidence:** Issues #26 and #27.

- #26: plausible in-domain but underspecified questions can be falsely rejected as off-topic.
- #27: assistant capability/orientation questions can be semantically treated as off-topic/refusal.

**Required capability:**

- distinguish true off-topic, capability orientation, clarification-required and normal in-domain interaction;
- resolve safe product/context state before rejecting a plausible domain request;
- preserve conversation continuity without guessing product identity.

**Current ASK-AI capability:**

I-002 INC-3 introduced unified task understanding with `standard`, `clarification_required`, `capability_orientation`, and `off_topic` interaction modes.

**Gap status:**

```text
ENGINEERING CAPABILITY = IMPLEMENTED IN I-002
PRODUCTION VALIDATION   = PENDING
```

**Kapa benchmark status:** not a strategic differentiation area; conversational routing quality is expected product behavior.

**Architecture implication:** do not create a new I-003/I-004 architecture solely for #26/#27 until post-I-002 production evidence shows residual failure.

**Owner if residual:** Answer Intelligence / interaction semantics, not Knowledge Truth or advanced retrieval by default.

**Decision readiness:** `PENDING POST-I002 BENCHMARK / PRODUCTION REPRO`.

---

### G-02 — Connector-native structured commercial truth

**Observed evidence:** Issue #28.

Variable WooCommerce products can expose parent-level product information while exact purchasable variation/SKU/price/stock truth is not represented as first-class evidence.

**Required capability:**

```text
authoritative connector object
→ stable identity
→ variant/SKU attributes
→ current price/sale/stock
→ freshness/lifecycle
→ product isolation
→ evidence retrieval
```

**Current ASK-AI capability:**

- WooCommerce connector exists;
- parent product knowledge exists;
- accepted evidence metadata can classify Store evidence;
- no proven first-class variation truth path in the issue evidence.

**Gap:** structural Knowledge Truth gap, with a possible secondary retrieval-selection gap.

**Kapa benchmark status:** Kapa publicly does not generalize arbitrary SQL/database ingestion; Agent SDK can query live databases through custom tools. This leaves room for ASK-AI to treat supported domain connectors as governed native truth.

**Candidate architecture capability:**

- connector-native structured substrate;
- explicit source authority/freshness/lifecycle;
- structured retrieval;
- mixed structured + document evidence composition.

**Primary owner:** `I-003 → I-004`.

**Experiment/evidence:**

- inspect real WooCommerce variation contract;
- measure exactness/freshness/isolation;
- compare flattened text vs structured-native retrieval on commercial benchmark cases.

**Decision readiness:** `PRIORITY EXPERIMENT / STRONG CAPABILITY NEED`.

---

### G-03 — First-party rich/tool knowledge representation

**Observed evidence:** Issue #29.

Official Battery Life Calculator contains relevant NE101/NE301 evidence that may be absent, incompletely represented, or not retained by retrieval.

**Required capability:**

- treat first-party technical tools/calculators as eligible authoritative knowledge;
- preserve useful tables, labels, units, parameters, caveats and product scope;
- distinguish static source truth from dynamic/calculated outputs;
- retain provenance and freshness.

**Current ASK-AI capability:** normal website crawling/document ingestion; no proven generic contract for interactive technical-tool knowledge.

**Gap:** could occur at discovery/admission, representation, metadata, retrieval or composition. Exact stage remains issue-specific Discovery evidence.

**Kapa benchmark status:** Kapa has publicly productized ingestion-time representation of images/non-text content, reinforcing that representation quality is a competitive capability.

**Candidate architecture capability:**

- richer Knowledge Representation;
- source-type-aware parsing;
- optional tool-native/structured representation where static text is insufficient;
- provenance-preserving derived representations.

**Primary owner:** `I-003`, then `I-004` if indexed evidence exists but is not selected.

**Experiment/evidence:** compare ordinary crawl representation against richer representations on calculator/table/visual technical sources.

**Decision readiness:** `NEEDS REPO/SOURCE REALITY CHECK + EXPERIMENT`.

---

### G-04 — Source Content Inventory / Pipeline Truth

**Observed evidence:** Issue #30.

Admin cannot reliably answer:

```text
upstream exists?
→ discovered?
→ admitted/excluded?
→ fetched/parsed?
→ ledgered?
→ indexed/searchable?
→ failed/skipped?
→ retired/deleted/stale?
```

**Required capability:** inspectable source-item lifecycle and index/searchability truth.

**Current ASK-AI capability:** aggregate source health/counts and connector/index state exist, but Issue #30 identifies insufficient item-level diagnosability.

**Gap:** Knowledge Operations / observability gap.

**Kapa benchmark status:** Kapa already has mature Source Analytics and page-level usage visibility. ASK-AI must not claim generic source analytics as differentiation. Public evidence does not establish equivalent end-to-end item pipeline truth; that remains UNKNOWN.

**Candidate architecture capability:**

- canonical source item identity;
- source/content inventory;
- lifecycle state derived only from authoritative evidence;
- ledger ↔ index reconciliation;
- scalable query/filter/pagination;
- connector-specific identity extensions.

**Primary owner:** `I-003 G1`.

**Experiment/evidence:** Repo Reality Check to determine which states are already reconstructable and where durable manifest/state is actually required.

**Decision readiness:** `HIGH CONFIDENCE PRODUCT GAP / IMPLEMENTATION CONTRACT NOT YET READY`.

---

### G-05 — Solution-aware multi-role evidence retrieval

**Observed evidence:** Issue #31.

Solution recommendations can retrieve locally plausible product facts while missing complementary Solution, Case, Wiki/model and commercial evidence.

**Required capability:**

```text
solution/use case
→ proven case
→ device capability
→ AI/model/workflow
→ integration/protocol
→ commercial/operational constraints
```

with explicit distinction between proven facts, recommendation, and site-specific assumptions.

**Current ASK-AI capability:**

I-002 now provides EvidencePlan roles, evidence composition and CoverageReport, including roles such as solution/case/product/store evidence. However retrieval itself is not yet generally EvidencePlan-driven/adaptive.

**Gap status:**

```text
CONTROL-PLANE SEMANTICS = IMPLEMENTED
RETRIEVAL POLICY        = NOT YET PROVEN
KNOWLEDGE COVERAGE       = MAY ALSO BE INCOMPLETE
```

**Kapa benchmark status:** Kapa already has query decomposition, iterative/agentic retrieval and multi-source retrieval as competitive reality.

**Candidate architecture capability:**

- EvidencePlan-aware retrieval;
- multi-route/multi-source retrieval;
- required-role protection through rerank/pruning;
- CoverageReport-driven corrective retrieval;
- bounded escalation when required evidence remains missing.

**Primary owner:** `I-004`, with I-003 prerequisite where expected source roles are not represented/indexed.

**Experiment/evidence:** solution benchmark slice comparing A0/A1/A2/A4/A5 and explicitly measuring required-slot coverage + final answer quality.

**Decision readiness:** `PRIORITY EXPERIMENT`.

---

### G-06 — Evidence sufficiency as a retrieval control signal

**Observed evidence:** Benchmark v1 failure taxonomy and #28/#29/#31 all expose the risk that selected evidence can be incomplete even when some relevant evidence exists.

**Required capability:** retrieval must know not only whether chunks are relevant, but whether the task's required evidence objective is satisfied.

**Current ASK-AI capability:** CoverageReport exists after evidence composition and is authoritative for evidence coverage; it does not yet generally drive another bounded retrieval action.

**Gap:** control signal exists, corrective retrieval policy does not.

**Kapa benchmark status:** public Kapa evidence proves multi-step search but does not establish an equivalent explicit EvidencePlan/CoverageReport/missing-slot contract. Status `UNKNOWN`.

**Candidate architecture capability:** `CoverageReport-driven Corrective Retrieval`.

**Primary owner:** `I-004`.

**Experiment/evidence:** deliberately construct cases where first pass misses one required slot; compare generic second search vs missing-slot-targeted retrieval.

**Decision readiness:** `PRIORITY EXPERIMENT / LEADING DIFFERENTIATION HYPOTHESIS`.

---

### G-07 — Adaptive retrieval policy

**Observed evidence:** Different task classes require materially different evidence paths: factual lookup, exact commercial truth, solution synthesis, global questions and potentially multi-hop relationships.

**Required capability:** choose the cheapest reliable retrieval action(s) for the task/evidence objective rather than force all queries through one advanced path.

**Current ASK-AI capability:** current Hybrid retrieval plus specialized behavior; no generalized Retrieval Policy Engine is yet accepted.

**Kapa benchmark status:** single-pass + agentic retrieval coexist; query decomposition and iterative retrieval are strategic parity requirements.

**Candidate architecture capability:**

```text
deterministic policy
→ parallel/sequential multi-route
→ cost-aware adaptive policy
→ bounded agentic escalation
```

**Primary owner:** `I-004`.

**Experiment/evidence:** A0–A5, with route accuracy, escalation rate, answer gain, TTFT/E2E and cost.

**Decision readiness:** `STRATEGIC TARGET HYPOTHESIS / NOT READY TO FREEZE`.

---

### G-08 — Context Utility Optimization

**Observed evidence:** retrieval recall can be high while generator context contains redundant or distracting evidence; Kapa reports material pruning/cost gains from a listwise stage.

**Required capability:** maximize useful evidence delivered to generation while preserving all required EvidencePlan slots.

**Current ASK-AI capability:** rerank/prune exists, plus INC-5 required-first evidence composition; no accepted listwise set-level context optimizer.

**Kapa benchmark status:** productized/experimentally reported; strategic parity experiment area, not something to copy automatically.

**Candidate experiment arms:**

```text
A. current pruning
B. evidence-role deterministic pruning
C. listwise model pruning
D. required-slot protected + listwise pruning
```

**Primary owner:** `I-004`.

**Decision readiness:** `EXPERIMENT REQUIRED`.

---

### G-09 — Relationship / multi-hop knowledge

**Observed evidence:** solution and compatibility tasks may require traversal across product, variant, capability, accessory, interface, solution, case and source relationships.

**Required capability:** explicit, provenance-preserving relationship navigation where flat retrieval is measurably insufficient.

**Current ASK-AI capability:** document/chunk retrieval plus evidence metadata; no target graph substrate is frozen.

**Kapa benchmark status:** no public evidence that a universal GraphRAG/graph-database architecture is required for competitive performance.

**Candidate architecture capability:**

- governed structured domain relations;
- graph traversal as optional substrate;
- source-backed evidence remains answer truth.

Authority invariant:

```text
connector-native truth
> explicit authoritative source relation
> derived/inferred relation
```

**Primary owner:** `I-003 → I-004`.

**Experiment/evidence:** A2 Structured Hybrid vs A3 Graph-Augmented on relationship-heavy and multi-hop slices.

**Decision readiness:** `PRIORITY EXPERIMENT; GRAPH TECHNOLOGY NOT FROZEN`.

---

### G-10 — Global / corpus-level reasoning

**Observed evidence:** R-001 research identifies global/corpus synthesis as a distinct capability, but current production failure evidence does not yet establish it as a dominant ASK-AI problem.

**Required capability:** only if real questions require corpus-wide themes, recurring patterns or global summaries beyond local evidence retrieval.

**Candidate architecture capability:** hierarchical summaries, graph communities, RAPTOR/GraphRAG-inspired global retrieval or equivalent.

**Kapa benchmark status:** no evidence that ASK-AI must adopt a specific global-retrieval framework to reach parity.

**Primary owner:** `I-004`, with derived-state lifecycle in I-003 if adopted.

**Decision readiness:** `CONDITIONAL EXPERIMENT / NOT CURRENTLY A P0 GAP`.

---

### G-11 — Agent Context delivery

**Observed evidence:** Kapa has productized Retrieval API, Hosted MCP and Agent SDK; its own observations show knowledge search helps agents answer, contextualize native tool output and choose the correct tool.

**Required capability:** expose governed product/evidence context to external and internal agents, not only the Widget.

**Current ASK-AI capability:** future direction; not yet the current Answer Intelligence delivery contract.

**Kapa benchmark status:** agent-facing retrieval is already table stakes/strategic parity for the future category.

**Candidate capability:**

```text
Retrieval API / MCP
+ product semantics for tool planning
+ provenance/evidence context
+ source/version scope
+ machine-consumable sufficiency
+ persistent context where justified
```

**Primary owner:** `I-005`.

**Decision readiness:** `ROADMAP VALIDATED / IMPLEMENTATION DEFERRED`.

---

### G-12 — Enterprise control and deployment sovereignty

**Observed evidence:** R-002 establishes that SSO, SCIM, access controls, audit, retention, regional hosting and VPC discussion are already competitive capabilities.

**Required capability:** mature enterprise governance plus customer control where ASK-AI's market requires it.

**Current ASK-AI strategic opportunity:** self-host/customer-controlled deployment, inspectable evidence/knowledge control plane, model/provider control and operational transparency.

**Kapa benchmark status:** generic enterprise controls are table stakes; general full-stack self-host/on-prem remains publicly UNKNOWN.

**Primary owner:** `I-006`.

**Decision readiness:** `LATER ROADMAP; DO NOT PREMATURELY BUILD CHECKBOX PARITY`.

---

## 6. Consolidated capability classification

### TABLE STAKES

Do not use these as primary differentiation claims:

- multi-source ingestion;
- continuous freshness;
- product/version/source scoping;
- strong Hybrid retrieval;
- reranking;
- grounded citations;
- uncertainty handling;
- Retrieval API/MCP at mature agent stage;
- source/conversation analytics;
- enterprise identity/access/audit/retention controls.

### STRATEGIC PARITY

ASK-AI should experimentally achieve competitive capability in:

- query decomposition;
- iterative/multi-step retrieval;
- adaptive/multi-route retrieval;
- multi-source evidence retrieval;
- context utility optimization;
- production evaluation discipline;
- agent-facing knowledge retrieval/planning semantics.

### DIFFERENTIATION BETS

Must be proven with ASK-AI evidence before external claims:

1. EvidencePlan as explicit retrieval objective.
2. Required evidence-role/slot planning.
3. CoverageReport as runtime evidence-sufficiency truth.
4. Missing-slot-driven corrective retrieval.
5. Partial-supported-answer semantics tied to coverage truth.
6. Connector-native structured truth with authority/freshness/lifecycle.
7. Deep source-item pipeline truth and diagnosability.
8. Integrated evidence-control contract through claim/citation validation.
9. Unified evidence semantics across human answers and Agent Context.
10. Customer-controlled/inspectable deployment and provider choices where market demand values them.

---

## 7. Initiative ownership framework

### I-003 — Knowledge Intelligence & Operations

Owns **Knowledge Truth**:

```text
G1 Source Content Inventory / Pipeline Truth
G2 Lifecycle / Freshness / Authority
G3 Connector-native Structured Truth
G4 Governed Domain Relations / Derived Knowledge
G5 Rich Knowledge Representation
G6 Structured/Graph substrate health and reconciliation where adopted
```

Exit intent:

> ASK-AI can prove what authoritative knowledge it has, what it means, whether it is current, how it maps to products/variants/relations, and whether it is actually usable by retrieval.

### I-004 — Adaptive Retrieval Intelligence

Owns **Evidence Acquisition Policy**:

```text
Retrieval Policy Engine
Frontier Hybrid
Structured Retrieval
Graph Retrieval where justified
Hierarchical/Global Retrieval where justified
Parallel / Sequential Multi-Route Retrieval
EvidencePlan-aware Retrieval
CoverageReport-driven Corrective Retrieval
Bounded Agentic Retrieval
Context Utility Optimization
Latency / Cost / Escalation Budgets
Retrieval-policy Observability
```

Exit intent:

> ASK-AI can choose and control the right retrieval actions for the evidence objective, know when evidence is insufficient, and improve coverage without paying advanced-path cost universally.

### I-005 — Agent Context Platform

Owns **governed context delivery to agents**:

- Retrieval API / MCP;
- product semantics for tool planning;
- provenance/evidence context;
- source/version scope;
- machine-consumable sufficiency/uncertainty;
- persistent/cross-session context where justified;
- future associative memory where justified.

### I-006 — Enterprise Platform

Owns mature platform governance and deployment controls, treating common enterprise security features as parity rather than differentiation.

---

## 8. Architecture Experiment Matrix

R-001B A0–A5 remains the decision experiment structure:

| Arm | Composition | Primary question |
|---|---|---|
| A0 | Current accepted Hybrid baseline | What is the real control? |
| A1 | Frontier Hybrid | How far can strong flat retrieval go? |
| A2 | Structured Hybrid | What value comes from native/governed structured truth? |
| A3 | Graph-Augmented | Does explicit graph traversal add material relationship/multi-hop value beyond A2? |
| A4 | Multi-Substrate Routed | Does adaptive evidence-oriented routing beat a universal path? |
| A5 | Bounded Agentic Policy | What marginal answer gain justifies iterative agentic control? |

Add a cross-cutting **Context Utility** dimension to applicable arms:

```text
C0 current pruning
C1 evidence-role deterministic pruning
C2 listwise model pruning
C3 required-slot protected + listwise pruning
```

### Mandatory experiment slices

- local factual control;
- exact structured commercial truth;
- product/version isolation;
- relationship/compatibility;
- multi-hop solution recommendation;
- first-party rich/tool evidence;
- deliberately incomplete first pass for corrective retrieval;
- global/corpus synthesis if validated as material;
- lifecycle mutation/update/delete/reconciliation.

### Primary metrics

**Hard answer quality**
- factual correctness;
- interaction correctness;
- non-fabrication;
- product/scope safety.

**Evidence quality**
- required-slot coverage;
- evidence recall;
- provenance completeness;
- unsupported-claim rate;
- claim/citation faithfulness.

**Answer utility**
- completeness;
- usefulness;
- solution/multi-hop completeness.

**Efficiency**
- retrieval latency;
- TTFT;
- E2E;
- additional LLM calls;
- tokens/cost;
- escalation frequency.

**Operability**
- indexing/update/delete cost;
- recovery/rebuild complexity;
- stale-derived-state handling;
- reconciliation failures;
- observability/traceability.

Decision should be Pareto-oriented:

```text
quality gain / added latency
quality gain / added cost
quality gain / added architecture and operations risk
```

---

## 9. Post-I-002 Benchmark reconciliation gate

The frozen pre-I-002 Benchmark baseline remains the historical control. It must not be interpreted as post-I-002 performance.

After:

```text
I-002 Release Gate
→ Production Deployment
→ Production Acceptance
→ Benchmark v1 rerun
```

R-001C must be updated with:

1. post-I-002 scores by hard/evidence/experience dimensions;
2. zero-source rate;
3. updated K0–K9 failure attribution;
4. explicit status of #26/#27/#28/#29/#31 repro families;
5. which failures were removed by I-002 control-plane work;
6. which remaining failures are Knowledge Truth vs Retrieval Policy vs Generation/other;
7. representative evidence traces for architecture experiments.

Only then should ASK-AI select the highest-value A0–A5 experiment slices.

---

## 10. Architecture freeze gates

Target architecture is **NOT READY TO FREEZE** until all of the following are satisfied:

### Gate A — Post-I-002 production evidence

- Release accepted;
- production accepted;
- Benchmark v1 rerun complete;
- residual failure attribution reviewed.

### Gate B — Repo Reality Check

Establish actual extension points and truth contracts for:

- connector item identity;
- WooCommerce variation semantics;
- web/tool representation;
- ledger/index reconciliation;
- structured metadata/provenance;
- retrieval routing extension points;
- CoverageReport feedback path;
- lifecycle/update/delete semantics.

### Gate C — A0–A5 experiments

Run representative ASK-AI data through the relevant arms with frozen source snapshots.

### Gate D — Quality / efficiency / operability evaluation

No architecture wins on retrieval recall alone.

### Gate E — Authority / lifecycle safety

Any structured, graph, hierarchical or derived substrate must preserve:

- provenance;
- authority ordering;
- product/version isolation;
- freshness;
- retirement/deletion;
- reconciliation/rebuild;
- rollback/diagnosability.

### Gate F — Product decision

A freezes the target capability architecture only after evidence shows which mechanisms are worth their complexity.

---

## 11. Current decision dispositions

```text
Knowledge Truth Plane                         = STRATEGIC REQUIREMENT
Source Content Inventory / Pipeline Truth     = HIGH-CONFIDENCE I-003 GAP
Connector-native Structured Truth             = PRIORITY I-003 EXPERIMENT
Rich Knowledge Representation                 = PRIORITY/CONDITIONAL I-003 EXPERIMENT
Governed Domain Relations                     = PRIORITY I-003 EXPERIMENT

Retrieval Policy Engine                       = STRONG I-004 TARGET HYPOTHESIS
EvidencePlan-aware Retrieval                  = PRIORITY I-004 EXPERIMENT
CoverageReport-driven Corrective Retrieval    = PRIORITY I-004 EXPERIMENT
Adaptive Multi-Route Retrieval                = STRATEGIC I-004 TARGET HYPOTHESIS
Context Utility Optimization                  = EXPERIMENT REQUIRED
Bounded Agentic Retrieval                     = PRIORITY EXPERIMENT
Unrestricted Agentic Loop                     = REJECT AS DEFAULT

Graph Retrieval                               = OPTIONAL CAPABILITY / EXPERIMENT
Wholesale GraphRAG Migration                  = NOT RECOMMENDED
Hierarchical/Global Retrieval                 = CONDITIONAL EXPERIMENT
Long-context-only Replacement                 = REJECT

Agent Context Platform                        = STRATEGIC ROADMAP VALIDATED
Generic MCP Alone                             = TABLE STAKES, NOT I-005 DIFFERENTIATION
Enterprise SSO/SCIM/Audit/etc.                = TABLE STAKES AT MATURE STAGE

POST_I002_BENCHMARK_EVIDENCE                  = PENDING
A0–A5 EXPERIMENTS                             = PENDING
TARGET_ARCHITECTURE_FREEZE                     = NOT READY
I-003/I-004 IMPLEMENTATION AUTHORIZATION       = NONE
```

---

## 12. Immediate next sequence

```text
R-001C framework                         ← CURRENT / CREATED
        │
        ├────────────── parallel ──────────────┐
        │                                      │
        ↓                                      ↓
I-002 Release → Production             Repo Reality Check preparation
        ↓                                      │
Production Acceptance                          │
        ↓                                      │
Post-I-002 Benchmark                           │
        └──────────────┬───────────────────────┘
                       ↓
            R-001C Evidence Reconciliation
                       ↓
            Select highest-value A0–A5 tests
                       ↓
              Architecture Experiments
                       ↓
       Quality / Efficiency / Operability Review
                       ↓
             Target Architecture Decision
                       ↓
              I-003 / I-004 Roadmap Freeze
                       ↓
           Frozen Implementation Contracts
```

No third Answer Intelligence implementation lane should be opened before this evidence sequence is complete.

---

## 13. Decision summary

R-001C establishes that ASK-AI's next-generation architecture should be decided around two coupled but distinct problems:

```text
I-003 — Can ASK-AI prove and govern the right knowledge truth?

I-004 — Can ASK-AI acquire the right evidence for the task efficiently,
        know when it is insufficient, and correct the gap safely?
```

The strongest current architecture hypothesis remains a **Multi-Substrate Adaptive Evidence Architecture**, but it is not yet frozen.

The strongest current differentiation hypothesis remains an **Evidence Intelligence control plane** in which retrieval is driven by explicit evidence objectives and runtime sufficiency truth rather than generic relevance alone.

Both hypotheses must survive post-I-002 production evidence and ASK-AI-specific A0–A5 experiments before becoming architecture authority.
