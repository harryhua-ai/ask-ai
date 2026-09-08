# R-002A — Kapa.ai Competitive Architecture Deep Dive — Phase 2

**Status:** RESEARCH IN PROGRESS — PHASE 2 FINDINGS  
**Parent:** `R-002-KAPA-COMPETITIVE-ARCHITECTURE-DEEP-DIVE.md`  
**Date:** 2026-09-08  
**Implementation authorization:** NONE  
**Production mutation:** NONE  
**Benchmark mutation:** NONE

## 1. Phase 2 questions

This phase deepens the areas that most directly affect ASK-AI roadmap decisions:

1. What is Kapa's actual agent-facing retrieval contract?
2. How much adaptive/agentic behavior is publicly proven?
3. How does Kapa scope knowledge by source/product/version?
4. What knowledge operations and observability are productized?
5. What enterprise/security capabilities are already table stakes?
6. Where does ASK-AI still have plausible architectural differentiation?

Public evidence is classified as:

- **PROVEN PUBLIC CAPABILITY**
- **KAPA CLAIM**
- **INFERENCE**
- **UNKNOWN**

---

## 2. Agent-facing retrieval contract

### 2.1 Retrieval is now a first-class product surface — PROVEN PUBLIC CAPABILITY

Kapa's current agent product exposes both a hosted MCP server and Retrieval API. The product page describes the output as a small set of ranked, cited chunks returned in roughly two seconds rather than a generated answer-only interface.

Public examples show:

```text
https://api.kapa.ai/retrieval
```

for the retrieval-oriented product surface, while Kapa also retains its older/generated-answer Chat API:

```text
POST /query/v1/projects/{project_id}/chat/
POST /query/v1/threads/{thread_id}/chat/
```

The Chat API uses `X-API-KEY`, accepts an `integration_id`, supports thread continuation, and can return at least `answer`, `is_uncertain`, and relevant source information in documented integration examples.

The coexistence of retrieval and answer APIs is strategically relevant: Kapa can be either the agent's knowledge tool or the end-to-end answer engine.

### 2.2 Source scoping — PROVEN PUBLIC CAPABILITY

Kapa's public Chat API examples expose `source_ids_include`, allowing a caller to constrain which sources may answer a query.

Kapa also exposes source groups at the product level. Current product material says source groups can target assistants to particular products or versions.

Therefore Kapa has at least two scoping layers:

```text
Project / unified knowledge base
        ↓
Source groups / product-version targeting
        ↓
Per-query source inclusion where API supports it
```

The exact interaction between source groups, retrieval API, ACLs and agentic search is not established by public evidence.

### 2.3 Multi-turn context — PROVEN PUBLIC CAPABILITY

Kapa's Chat API exposes thread continuation. Integration guidance explicitly recommends preserving `thread_id` so follow-up messages retain conversation context.

This is productized multi-turn state, not merely a stateless search API.

### 2.4 Uncertainty is an external contract — PROVEN PUBLIC CAPABILITY

Kapa exposes `is_uncertain` in public integration guidance. External workflows can use it to decide whether to auto-send an answer or route to a human.

This is important competitive evidence: uncertainty is not only internal telemetry; it is usable by downstream automation.

ASK-AI should therefore treat machine-consumable answer/evidence sufficiency as a product surface, not only an internal trace concern.

---

## 3. What Kapa 'agentic retrieval' publicly proves

### 3.1 Proven mechanism

Current Kapa MCP material explicitly states that the server wraps the Retrieval API and runs a multi-step pipeline with:

```text
multiple search iterations
embedding-based retrieval
sparse retrieval
query decomposition
reranking
```

Results retain `source_url` traceability.

This establishes that Kapa's agentic retrieval is materially beyond a single `query → vector top-k` pass.

### 3.2 What is still not proven

Public evidence reviewed in Phase 1–2 still does NOT establish direct equivalents of:

```text
ASK-AI EvidencePlan
required evidence slots
role-specific required/optional evidence
CoverageReport as per-request evidence truth
missing_required as a control signal
CoverageReport-driven targeted corrective retrieval
formal source-authority hierarchy
claim-level post-generation evidence validation
```

These remain `UNKNOWN`, not `ABSENT`.

### 3.3 Architectural interpretation — INFERENCE

Kapa appears to have moved from a fixed retrieval pipeline toward an adaptive search procedure, but public materials describe the mechanism primarily in retrieval-operation terms:

```text
decompose
search repeatedly
hybrid retrieve
rerank
return chunks
```

ASK-AI's strongest potential differentiation remains an **evidence-objective control plane**:

```text
Task Understanding
→ EvidencePlan
→ Retrieval Policy
→ Evidence Composition
→ CoverageReport
→ targeted corrective action
→ Response Strategy
→ Claim Validation
```

The difference is potentially:

```text
Kapa public model:
search until useful context is found

ASK-AI target hypothesis:
search against an explicit evidence objective and know which required evidence remains missing
```

This is a hypothesis until Kapa internal semantics are known and ASK-AI experiments prove product value.

---

## 4. Context optimization is a real competitive architecture dimension

Kapa's July 2026 research adds a listwise small-LLM pruning stage after reranking. The model sees the query and the full retrieved set together, then grades chunks as Essential / Contributing / Supporting / Tangential / Unrelated.

Kapa's reported selected operating point:

```text
~68% chunks removed
~96% required-context recall preserved
~34% net query cost reduction
~0.7 s added latency
```

These are **KAPA CLAIMS** from its own production/evaluation set.

The architectural lesson is stronger than the exact numbers:

> Pointwise relevance ranking and set-level answer utility are different problems.

This is highly relevant to ASK-AI because INC-5 already reasons about evidence roles and CoverageReport. A future ASK-AI context optimizer should therefore be evaluated against evidence sufficiency, not just generic relevance.

Recommended R-001 addition:

```text
Context Utility Optimization
```

as an explicit I-004 experiment dimension.

Potential ASK-AI experiment arms:

1. existing rerank/prune baseline;
2. evidence-role-aware deterministic pruning;
3. listwise model-based pruning;
4. hybrid: required EvidencePlan slots protected + listwise pruning of surplus context.

Do not adopt Kapa's extra LLM call without measured answer-quality/cost/latency benefit.

---

## 5. Knowledge model, product/version scoping and structured truth

### 5.1 Product/version scoping — PROVEN PUBLIC CAPABILITY

Kapa states that connected sources can be organized into source groups to keep answers scoped to the right product or version. Field-service positioning goes further and describes answers scoped to model, revision and configuration.

This means product/version isolation is already a competitive expectation for technical knowledge systems.

### 5.2 Structured database ingestion — IMPORTANT LIMIT

Kapa's current Connect FAQ says SQL databases are not supported out of the box because schemas vary. Instead, its Agent SDK can expose custom tools that query customer databases with customer-owned logic/auth.

This is strategically important for ASK-AI.

Kapa's public architecture is strongest around managed ingestion of documents/content. For arbitrary live structured truth, it often delegates to an agent tool rather than normalizing all structured systems into its managed knowledge base.

ASK-AI's connector-native structured knowledge direction therefore remains meaningful, particularly for systems such as WooCommerce where the connector contract itself can define authoritative structured product/variation truth.

Potential differentiation:

```text
Kapa public pattern for arbitrary DB truth:
Agent custom tool → live database

ASK-AI target for supported connectors:
Connector-native structured truth
→ governed knowledge substrate
→ provenance/freshness/lifecycle
→ evidence retrieval
```

Neither is universally superior. ASK-AI should use first-class structured ingestion only where a connector has stable domain semantics and material answer value.

### 5.3 Graph architecture — no public evidence of core dependence

Phase 2 still found no public evidence that Kapa's core product architecture depends on GraphRAG, a generic Knowledge Graph, LightRAG or graph traversal as the universal retrieval substrate.

This reinforces R-001's decision not to equate modern retrieval with graph adoption.

`Graph = candidate substrate/capability`, not roadmap identity.

---

## 6. Knowledge Operations / observability

### 6.1 Kapa is substantially productized in conversation analytics — PROVEN PUBLIC CAPABILITY

Current analytics include:

- Dashboard metrics;
- full Conversations review/export;
- Coverage Gaps;
- Top Questions;
- Source Analytics;
- scheduled email/Slack reports;
- user satisfaction/tracking on widget deployments;
- Intent Tags;
- up to 20 Custom Tags;
- Activity API for aggregate metrics.

Coverage Gaps clusters recurring uncertain conversations into a Finding plus AI-generated Recommendation.

### 6.2 Source Analytics is deeper than previously captured

Kapa states that Source Analytics provides a tree view from top-level source down to individual pages and shows what fraction of questions each content item answers.

Kapa also publicly describes conversation review surfaces where operators can inspect sources considered/used for an answer and use an `Improve this answer` workflow.

Therefore ASK-AI should NOT claim that Kapa lacks page-level source observability in general.

### 6.3 But Issue #30 remains potentially differentiated

What remains unproven publicly is a Kapa equivalent of ASK-AI Issue #30's proposed **pipeline-state inventory**:

```text
upstream exists
→ connector discovered
→ admitted / excluded
→ fetched
→ parsed / ledgered
→ indexed
→ searchable
→ retired / deleted
```

Kapa Source Analytics answers primarily:

> Which indexed content is being referenced and what questions does it serve?

ASK-AI #30 asks an additional operations question:

> Why is a known upstream item absent or unusable, and at which pipeline stage did that happen?

Potential differentiation should therefore be stated narrowly:

```text
NOT:
Kapa lacks source observability

POSSIBLE:
ASK-AI can expose deeper source-item pipeline truth and lifecycle diagnostics
```

This remains subject to direct Kapa dashboard inspection.

---

## 7. Enterprise / security reality

Kapa's current public Enterprise offering already includes:

```text
SOC 2 Type II
GDPR
SSO
SCIM
advanced access controls
audit logs
data-retention controls
EU / regional hosting
PII masking / zero-data-retention options
```

Its security material states that knowledge is processed into a US Google Cloud PostgreSQL database and Weaviate vector database, encrypted in transit/at rest, with external model providers including Cohere, OpenAI, Voyage and Anthropic under agreements preventing training on customer data.

Enterprise customers can customize retention and request deletion.

### 7.1 Self-host / on-prem — still UNKNOWN / no public proof found

Phase 2 did not find current public evidence of a general Kapa self-hosted/on-prem distribution. Public positioning repeatedly emphasizes hosted API/MCP and managed infrastructure.

Do not convert lack of public evidence into a categorical statement that Kapa cannot support private deployment arrangements.

### 7.2 ASK-AI implication

Enterprise security basics cannot be treated as long-term differentiation:

```text
SSO
SCIM
RBAC/access controls
audit logs
retention
regional hosting
PII handling
```

are competitive table stakes.

ASK-AI's stronger possible enterprise differentiation is instead:

```text
self-hosted / customer-controlled deployment
inspectable knowledge/evidence control plane
customer-owned model/provider routing
explicit provenance / lifecycle truth
operational transparency
```

These need roadmap/economic validation; they are not automatic wins.

---

## 8. Pricing / economic positioning

Kapa's public pricing is now tiered as:

```text
14-day Free Trial
Growth — production API/MCP, continuous sync, analytics, integrations
Enterprise — SSO/SCIM/access controls/audit/retention/regional hosting
```

Public list prices are not shown for Growth/Enterprise; both are sales-led.

Kapa's value proposition explicitly bundles the operational burden of:

```text
Ingest
Index
Retrieve
Operate
```

including connector maintenance, complex crawling, PDF/image conversion, incremental indexing, chunking, embeddings/storage, hybrid retrieval, context tuning, infrastructure/model migrations and analytics.

This matters for ASK-AI positioning. A self-hosted product cannot win merely by saying "you own the software"; it must make the operational burden acceptably low or expose control customers materially value.

---

## 9. Revised competitive classification

### TABLE STAKES — do not treat as differentiation

- multi-source ingestion;
- automatic freshness/incremental indexing;
- product/version scoping;
- hybrid sparse+dense retrieval;
- reranking;
- citations/source traceability;
- uncertainty / abstention;
- conversation history;
- Retrieval API;
- MCP;
- conversation analytics;
- coverage-gap analytics;
- source analytics;
- enterprise SSO/SCIM/access controls/audit/retention;
- PDF/image-aware ingestion increasingly becoming expected.

### STRATEGIC PARITY — ASK-AI should reach equivalent product capability, implementation may differ

- adaptive/multi-step retrieval;
- query decomposition;
- high-recall multi-source retrieval;
- agent-facing knowledge tool;
- source/product/version control;
- knowledge quality feedback loop;
- context-size/cost optimization;
- production evaluation discipline.

### PLAUSIBLE DIFFERENTIATION — must be proven, not claimed yet

1. **Evidence-objective control plane**
   - explicit EvidencePlan;
   - required/optional evidence roles;
   - CoverageReport as runtime evidence truth;
   - missing-slot-driven corrective retrieval.

2. **Claim-level evidence governance**
   - explicit claim/evidence validation after generation;
   - inspectable evidence lineage.

3. **Connector-native structured truth**
   - supported domain connectors can preserve exact records/relations rather than flatten everything into text.

4. **Deep knowledge pipeline observability**
   - upstream/discovery/admission/ledger/index/searchability/lifecycle truth at item level.

5. **Self-hosted / controllable architecture**
   - deployment, provider, data and evidence control where customer need justifies it.

### NON-GOALS / DO NOT COPY BLINDLY

- copying Kapa UI/branding;
- adopting an extra LLM pruning call without ASK-AI benchmark proof;
- chasing connector count as a vanity metric;
- treating GraphRAG as mandatory because retrieval is becoming agentic;
- implementing every enterprise control before product demand;
- replacing ASK-AI's explicit evidence semantics with generic agent loops.

---

## 10. Roadmap impact after Phase 2

### I-003 — Knowledge Intelligence & Operations

Phase 2 strengthens I-003, with recommended capability sequence:

```text
G1 Source Content Inventory / Pipeline Observability
G2 Lifecycle / Freshness / Authority
G3 Connector-native Structured Truth
G4 Governed Domain Relations / Derived Knowledge
G5 Rich Knowledge Representation (image/table/tool where justified)
G6 Structured / Graph substrate experiments
```

Important refinement:

- Kapa already has strong Source Analytics.
- ASK-AI #30 should focus on **pipeline truth and diagnosability**, not merely page popularity/usage analytics.

### I-004 — Adaptive Retrieval Intelligence

Phase 2 strengthens and expands the proposed scope:

```text
Retrieval Policy Engine
Frontier Hybrid
Structured Retrieval
Graph Retrieval where justified
Hierarchical/Global Retrieval where justified
Parallel / Sequential Multi-Route Retrieval
CoverageReport-driven Corrective Retrieval
Bounded Agentic Retrieval
Context Utility Optimization / Pruning
Quality / Latency / Cost budgets
Retrieval-policy observability
```

### I-005 — Agent Context Platform

Phase 2 confirms that MCP/API alone will be table stakes by the time ASK-AI reaches I-005.

I-005 must therefore be stronger than "add MCP":

```text
Governed product knowledge context
+ agent planning semantics
+ source/version scope
+ machine-consumable sufficiency/uncertainty
+ persistent/cross-session context
+ controlled tool/context interfaces
```

---

## 11. Architecture correction from competitive evidence

The current target hypothesis remains valid but should be refined:

```text
                 Knowledge Truth Plane
          documents / native structured / derived
                       ↓
                 Evidence Control Plane
 Task Understanding → EvidencePlan → Coverage Truth
                       ↓
                Retrieval Policy Engine
                       ↓
 lexical | dense | structured | graph | hierarchical | native
                       ↓
           Context Utility Optimization
                       ↓
             Evidence Composition
                       ↓
                  Generation
                       ↓
            Claim/Citation Validation
                       ↓
      Answer Surface / Retrieval API / MCP / Agents
```

The new element relative to R-001B is explicit **Context Utility Optimization** between retrieval and final generation/context delivery.

It should remain optional/experimental until ASK-AI measurements justify it.

---

## 12. Questions still open after Phase 2

Highest-value unknowns now are narrower:

1. Does Kapa expose or internally maintain evidence sufficiency more structured than `is_uncertain`?
2. Does Kapa agentic retrieval choose different retrieval substrates or mainly iterate hybrid search?
3. How exactly are query decomposition, iteration stopping and search budgets controlled?
4. Does the Retrieval API expose retrieval trace/iteration metadata, scores or only final chunks?
5. How deep is Kapa's source-item sync/admin inventory in the actual dashboard?
6. How are deletions, retirement and stale derived/indexed state represented operationally?
7. How does product/version scoping interact with one unified project and source groups?
8. Are access controls source-aware at retrieval time or primarily project/deployment-level?
9. Does Kapa have private/VPC/on-prem deployment options not publicly documented?
10. How are structured datasheets represented internally versus ordinary text chunks?
11. Does Kapa have any graph/relationship substrate not publicly disclosed?
12. What are actual Growth/Enterprise economics at ASK-AI-relevant scale?

These unknowns no longer block moving toward ASK-AI Capability Gap consolidation, provided they remain explicitly UNKNOWN.

---

## 13. Phase 2 conclusion

Phase 2 materially changes the competitive interpretation in four ways.

### Finding 1

Kapa is farther ahead in productization than a "RAG chatbot" comparison suggests. Retrieval API, hosted MCP, source/version scoping, uncertainty contracts, analytics, source analytics and enterprise governance are already product surfaces.

### Finding 2

Kapa's public agentic retrieval is real multi-step retrieval, but current public evidence still does not prove an EvidencePlan/CoverageReport-equivalent evidence-objective control plane.

### Finding 3

ASK-AI should not attempt to differentiate on generic hybrid retrieval, MCP, citations, analytics or enterprise basics. Those are table stakes.

### Finding 4

The strongest ASK-AI differentiation hypothesis is now narrower and more coherent:

> **A controllable evidence-intelligence architecture that knows what evidence a task requires, preserves authoritative structured and unstructured truth, can prove what evidence is present or missing, adaptively retrieves against that objective, and exposes the same governed context to humans and agents.**

This hypothesis now needs to be tested against ASK-AI's post-I-002 production failures rather than expanded with more broad competitive research.

## 14. Recommended next research artifact

Proceed to:

```text
R-001C — ASK-AI Capability Gap & Architecture Decision Framework
```

Inputs:

```text
R-001 / R-001A / R-001B architecture research
+
R-002 / R-002A Kapa competitive reality
+
current ASK-AI repo architecture
+
Issues #26–#31
+
post-I-002 Benchmark when available
```

R-001C should classify each capability as:

```text
TABLE STAKES
STRATEGIC PARITY
DIFFERENTIATION BET
NON-GOAL
```

and map it to:

```text
Observed failure
→ Required capability
→ Existing ASK-AI capability
→ Gap
→ Candidate architecture capability
→ I-003 / I-004 / I-005 owner
→ Experiment required
→ Benchmark evidence required
```

**Phase 2 status: COMPLETE enough for consolidation; remaining Kapa unknowns remain tracked rather than blocking decision preparation.**
