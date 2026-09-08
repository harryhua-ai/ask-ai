# R-002 — Kapa.ai Competitive Research

**Status:** RESEARCH CLOSED — AUTHORITATIVE ROADMAP DECISION INPUT  
**Authority:** AUTHORITATIVE  
**Repository:** `harryhua-ai/ask-ai`  
**Research branch:** `research/r001-knowledge-retrieval-architecture`  
**Date:** 2026-09-08  
**Implementation authorization:** NONE  
**Production mutation:** NONE  
**Benchmark mutation:** NONE

**Supersedes:**
- `R-002-KAPA-COMPETITIVE-ARCHITECTURE-DEEP-DIVE.md`
- `R-002A-KAPA-COMPETITIVE-DEEP-DIVE-PHASE-2.md`
- `R-002-KAPA-COMPETITIVE-RESEARCH-FINAL.md`

This document is the single source of truth for Kapa.ai competitive research used by R-001C and subsequent ASK-AI product/architecture planning. Earlier phase documents remain available through Git history only.

---

## 1. Research purpose and decision question

Kapa.ai is a direct benchmark for ASK-AI. R-002 exists to prevent roadmap and architecture decisions from being driven only by internal intuition, isolated implementation details, or frontier research papers.

R-001 asks:

> What is the best evidence-backed knowledge/retrieval architecture ASK-AI should target?

R-002 asks:

> What has a strong direct benchmark already productized, what appears to be its real product/architecture model, what is now table stakes, what requires strategic parity, and where can ASK-AI build defensible differentiation rather than merely clone Kapa?

R-002 uses four evidence classes:

- **PROVEN PUBLIC CAPABILITY** — supported by current Kapa documentation, product material, API guidance, or technical research;
- **KAPA CLAIM** — performance, benchmark, quality, cost, or adoption statement published by Kapa itself and not independently verified here;
- **INFERENCE** — architecture or product implication derived from public evidence;
- **UNKNOWN** — not established by public evidence and must not be guessed.

No Kapa marketing claim is silently promoted into independent fact. Lack of public evidence is not treated as proof that a capability is absent.

---

## 2. Executive conclusion

Kapa.ai is no longer best understood as a documentation chatbot. Its current public product model is an ingestion and retrieval platform for technical/product knowledge, exposed through prebuilt answer experiences, Retrieval API, Hosted MCP, and an Agent SDK.

A useful competitive abstraction is:

```text
Technical / Product Knowledge Sources
        ↓
Managed Ingestion + Continuous Sync
        ↓
Unified Knowledge Base
        ↓
Retrieval Infrastructure
        ↓
Single-pass / Agentic Retrieval
        + Reranking
        + Context Optimization
        ↓
┌───────────────────────────────────────────┐
│ Prebuilt answer/support experiences       │
│ Retrieval API                             │
│ Hosted MCP                                │
│ Product Agent SDK                         │
└───────────────────────────────────────────┘
        ↓
Customers / Employees / AI Agents
```

The competitive lesson for ASK-AI is not to clone Kapa or adopt a fashionable RAG framework. The relevant target is a stronger evidence-oriented control plane on top of trustworthy enterprise knowledge.

Kapa establishes that the following are now table stakes or near-table-stakes for this category:

- broad multi-source ingestion;
- continuous freshness/synchronization;
- product/version/source scoping;
- sparse+dense/hybrid retrieval;
- reranking;
- cited answers;
- uncertainty handling;
- conversation/source analytics;
- Retrieval API and MCP;
- agent-facing knowledge retrieval;
- enterprise access/governance controls.

ASK-AI's strongest potential differentiation is therefore not generic RAG. It is the explicit runtime evidence chain:

```text
Knowledge Truth
→ Task Understanding
→ EvidencePlan
→ Retrieval Policy
→ Evidence Composition
→ CoverageReport
→ Controlled Corrective Retrieval
→ Generation
→ Claim / Citation Validation
→ Human Answer / Agent Context
```

Public Kapa material reviewed in R-002 does not establish direct equivalents of ASK-AI's explicit EvidencePlan, required evidence slots, runtime CoverageReport, missing-slot-driven corrective retrieval, or the same integrated claim/evidence validation contract. These internals remain **UNKNOWN**, not presumed absent.

R-002 is closed because remaining unknowns are not publicly verifiable enough to justify blocking product planning.

---

## 3. Kapa product model and positioning

### 3.1 Publicly established product surfaces

Kapa currently positions itself around technical/product knowledge retrieval for both humans and agents. Public use cases include:

- documentation Ask AI;
- in-product AI agents;
- support automation;
- public MCP server;
- internal/company knowledge;
- Slack/Discord/community answers;
- competitor intelligence;
- RFP answering;
- product agents that combine knowledge retrieval with native tools.

This supports three major Kapa product surfaces:

```text
A. Managed Knowledge / Retrieval Infrastructure
B. Prebuilt Answer / Support Experiences
C. Agent Context Infrastructure
```

Kapa explicitly describes itself as an ingestion and retrieval system, not only an answer widget.

### 3.2 Strategic implication for ASK-AI

ASK-AI should not define its addressable product as:

```text
self-hosted Kapa-like chatbot
```

The stronger long-term framing is:

```text
Enterprise Knowledge Truth
+
Evidence-grounded Answer Intelligence
+
Agent Context Infrastructure
```

This direction is competitively validated, but it must still be proven against ASK-AI's own users, benchmark evidence, deployment economics, and architecture experiments.

---

## 4. Knowledge ingestion, representation, freshness and scope

### 4.1 Source breadth — PROVEN PUBLIC CAPABILITY

Kapa publicly supports a broad set of technical/product knowledge sources including categories such as:

- websites/documentation;
- GitHub/code;
- API specifications/OpenAPI;
- PDFs and files;
- support systems/tickets;
- Slack/community content;
- Confluence;
- Notion;
- Google Drive;
- Zendesk;
- Intercom;
- YouTube;
- object/file storage and related technical sources.

Public connector counts vary across pages and time, so R-002 does not freeze an exact connector-count claim.

### 4.2 Continuous freshness — PROVEN PUBLIC CAPABILITY

Kapa states that connected sources are automatically synchronized and re-indexed as upstream content changes. Its 2026 material explicitly expanded automatic sync coverage to web crawls.

Competitive implication:

> Freshness is a product capability, not backend plumbing.

ASK-AI cannot treat sync correctness, update semantics, deletion, and stale-content handling as secondary implementation details.

### 4.3 Product/version scoping — PROVEN PUBLIC CAPABILITY

Kapa supports source groups to target assistants or retrieval toward particular products or versions. Public field-service/semiconductor material describes scoping by product family, part number, model, revision, and configuration, including shared/global sources.

This makes product/version isolation **table stakes**, not differentiation.

The exact internal identity/lifecycle contract remains not fully public.

### 4.4 Image and non-text knowledge representation — PROVEN PUBLIC CAPABILITY / KAPA CLAIMS

Kapa's published 2026 image-ingestion research describes an ingestion-time architecture:

```text
image
→ filter/classify
→ VLM caption/transcription using surrounding context
→ separate text caption chunk
→ normal retrieval/rerank
→ cite original image URL
```

The design deliberately avoids query-time multimodal processing for the default path.

Kapa reports across three customer projects:

- statistically significant answer-quality lift;
- roughly +1–6% per-query cost;
- sub-second TTFT impact;
- image-placement accuracy in the mid/high-90% range.

These are **KAPA CLAIMS**, not independently verified benchmark results.

Architecture lesson:

> Knowledge representation quality is a first-order answer-quality variable.

Technical product knowledge often contains load-bearing diagrams, screenshots, schematics, tables, and visual instructions. ASK-AI should treat rich representation as an I-003 experiment/roadmap capability where real evidence justifies it.

### 4.5 Structured/live data boundary — PROVEN PUBLIC CAPABILITY / IMPORTANT LIMIT

Kapa publicly states that generic SQL/database structured data is not supported as a universal out-of-box source because schemas vary. For product agents, the Agent SDK can expose custom tools that query customer databases using customer-owned logic and authentication.

This creates an important architectural distinction:

```text
Kapa public pattern for arbitrary live DB truth:
Agent custom tool → customer database
```

ASK-AI has a plausible alternative for supported domain connectors:

```text
Connector-native structured truth
→ governed knowledge substrate
→ explicit provenance/freshness/lifecycle
→ evidence retrieval
```

For example:

```text
WooCommerce
Product
→ Variant
→ SKU
→ Price
→ Stock
→ Attributes
→ source variation identity
→ observed_at / freshness
```

ASK-AI should **not** generalize this into "ingest every database". The opportunity is domain-governed structured knowledge where semantics and authority are stable enough to justify first-class representation.

### 4.6 ASK-AI implication

Kapa research strengthens the I-003 direction:

```text
Knowledge Inventory
Knowledge Authority
Knowledge Lifecycle
Product / Version Scope
Connector-native Structured Truth
Derived Knowledge Governance
Rich Knowledge Representation
```

---

## 5. Retrieval architecture

### 5.1 Managed retrieval baseline — PROVEN PUBLIC CAPABILITY

Public Kapa material establishes:

- chunking;
- embeddings;
- sparse retrieval;
- dense/embedding retrieval;
- hybrid retrieval;
- reranking;
- source URL preservation;
- single-pass retrieval;
- multi-step/agentic retrieval;
- context pruning/optimization.

Therefore a static strategic target of only:

```text
BM25 + Vector + Reranker
```

is no longer sufficient for ASK-AI.

### 5.2 Single-pass and agentic retrieval coexist — PROVEN PUBLIC CAPABILITY

Kapa does not publicly present one universal retrieval paradigm as optimal for every query. Its research and product surfaces support both single-pass and agentic/multi-step retrieval.

This supports R-001's current direction:

> No retrieval substrate or control mode receives architectural privilege without measured value.

### 5.3 Agentic retrieval — PROVEN MECHANISM, INTERNAL CONTROL UNKNOWN

Kapa's Hosted MCP/Retrieval product material publicly describes a multi-step retrieval pipeline with:

```text
query decomposition
multiple search iterations
embedding-based retrieval
sparse retrieval
reranking
source URL traceability
```

This establishes that Kapa's "agentic retrieval" is materially more than a marketing rename for one hybrid query.

Kapa also reports that agentic retrieval returns the right source nearly 2× more often than web search or a DIY RAG pipeline in a benchmark built from four customer projects with 30 human-annotated multi-source production questions per project. This is a **KAPA CLAIM**.

Public evidence does **not** establish Kapa's exact internal:

- stopping policy;
- semantic sufficiency representation;
- evidence-role planning;
- retry/search budget;
- reflection mechanism;
- required-slot-driven retrieval;
- formal source-authority hierarchy.

These remain **UNKNOWN**.

### 5.4 Evidence-objective control plane — ASK-AI differentiation hypothesis

Kapa's public model can be summarized conservatively as:

```text
decompose
→ search repeatedly
→ hybrid retrieve
→ rerank
→ return/use chunks
```

ASK-AI's stronger target hypothesis is:

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

Potential distinction:

```text
generic adaptive retrieval:
search until useful context is found

ASK-AI target:
search against an explicit evidence objective
and know which required evidence remains missing
```

This remains a **DIFFERENTIATION BET**, not a proven market advantage, until ASK-AI experiments and production benchmarks demonstrate final-answer value.

### 5.5 Graph architecture — no evidence of universal requirement

R-002 found no public evidence that Kapa's core product architecture depends on GraphRAG, LightRAG, a generic Knowledge Graph, or graph traversal as the universal retrieval substrate.

This reinforces the R-001 principle:

```text
Graph = candidate substrate/capability
Graph ≠ roadmap identity
```

ASK-AI should evaluate graph traversal when it improves specific relational, multi-hop, or global tasks, not because modern RAG is assumed to require a graph database.

---

## 6. Context utility optimization

### 6.1 Kapa context-pruning pipeline — PROVEN PUBLIC CAPABILITY

Kapa's 2026 research adds a listwise small-model pruning stage:

```text
retrieval
→ rerank
→ small-model context pruning
→ generation
```

The pruning model sees the query and retrieved set together and grades chunks using categories such as:

- Essential;
- Contributing;
- Supporting;
- Tangential;
- Unrelated.

### 6.2 Reported operating point — KAPA CLAIM

Kapa reports approximately:

```text
~68% retrieved chunks removed
~96% required-context recall retained
~34% net per-query cost reduction
~0.7 s pruning latency in selected configuration
```

These are vendor-published experimental results.

### 6.3 Architecture lesson

Pointwise relevance ranking and set-level answer utility are not the same problem.

ASK-AI should explicitly evaluate **Context Utility Optimization** in I-004, but should not blindly copy an extra LLM call.

Candidate ASK-AI experiment arms:

```text
A. current rerank/prune baseline
B. evidence-role-aware deterministic pruning
C. listwise model-based pruning
D. required EvidencePlan slots protected + listwise pruning of surplus context
```

Decision metrics must include:

- final answer quality;
- evidence/required-slot coverage;
- unsupported claims;
- TTFT/E2E;
- LLM calls;
- token cost;
- operational complexity.

Core rule:

> Optimize final-answer utility per latency/cost, not Recall@K in isolation.

---

## 7. Answer grounding, citations and uncertainty

### 7.1 Grounded answer behavior — PROVEN PUBLIC CAPABILITY

Kapa publicly targets source-backed answers, citations, and explicit uncertainty/"I don't know" behavior where knowledge does not cover the question.

Public integration guidance exposes an `is_uncertain` signal that downstream workflows can use to auto-send an answer or route to a human.

Competitive implication:

> Machine-consumable confidence/sufficiency behavior is a product surface, not merely internal telemetry.

### 7.2 Claim-level citation and citation faithfulness — PROVEN PUBLIC POSITIONING

Recent Kapa guidance distinguishes:

- source lists;
- answer-level citations;
- claim-level citations;
- citation faithfulness evaluation.

Kapa identifies claim-level passage support as the strongest verifiable citation form and explicitly argues that faithfulness must be evaluated rather than assumed from retrieval.

This materially narrows any simplistic ASK-AI claim that citation validation alone is unique.

### 7.3 ASK-AI differentiation hypothesis

The more defensible differentiation hypothesis is the integrated runtime evidence contract:

```text
EvidencePlan
→ explicit required roles/slots
→ CoverageReport
→ supported partial-answer semantics
→ claim/citation validation
```

Whether Kapa has an internal equivalent integrated contract is **UNKNOWN**.

---

## 8. Evaluation discipline

Kapa's public evaluation guidance recommends:

1. representative questions drawn from real production-like usage;
2. manually verified test cases;
3. explicit marking criteria rather than free-form golden-answer similarity;
4. separate factuality and uncertainty scoring;
5. strong-model LLM judging;
6. multiple judge runs;
7. frozen indexed source sets during comparisons;
8. inclusion of deliberately unanswerable questions to test abstention/uncertainty.

Kapa suggests roughly 100 questions as a practical starting scale and around 10–20% intentionally unanswerable cases. These are Kapa's recommended practices, not universal standards.

ASK-AI Benchmark v1 is already materially more formal than a vibe test. Potential future refinements after the frozen post-I-002 rerun include:

- stronger per-case marking criteria;
- explicit uncertainty calibration;
- frozen-source-set architecture experiments;
- identical source snapshots across architecture arms;
- final-answer utility as primary decision metric.

Do **not** mutate the frozen Benchmark v1 before the authorized rerun.

---

## 9. Knowledge operations, analytics and observability

### 9.1 Kapa analytics — PROVEN PUBLIC CAPABILITY

Kapa publicly exposes mature analytics including:

- dashboard metrics;
- full conversation review/export;
- Coverage Gaps;
- Top Questions;
- Source Analytics;
- scheduled Email/Slack reporting;
- user satisfaction/tracking;
- intent/custom tagging;
- aggregate activity metrics/API surfaces.

### 9.2 Coverage Gaps — PROVEN PUBLIC CAPABILITY

Kapa's Coverage Gaps groups recurring uncertain conversations into findings and recommendations for improving documentation or product knowledge.

Conceptually:

```text
production conversations
→ uncertain answers
→ cluster recurring gaps
→ finding/recommendation
→ improve content/knowledge
```

This is **not equivalent** to ASK-AI's per-request `CoverageReport`.

```text
Kapa Coverage Gaps
= post-hoc analytics over uncertain conversations

ASK-AI CoverageReport
= runtime evidence-coverage truth for one EvidencePlan
```

Whether Kapa has a private/internal runtime sufficiency object equivalent to CoverageReport is **UNKNOWN**.

### 9.3 Source Analytics depth — PROVEN PUBLIC CAPABILITY

Kapa's Source Analytics includes a tree view from higher-level sources down to individual pages and visibility into how content contributes to answers/questions. Conversation review can expose sources considered/used and supports answer-improvement workflows.

Therefore ASK-AI must **not** claim:

> Kapa lacks source observability.

### 9.4 ASK-AI Issue #30 — narrower differentiation opportunity

The stronger ASK-AI opportunity is deeper pipeline-state truth:

```text
upstream object exists
→ connector discovered
→ admitted / excluded
→ fetched
→ parsed / ledgered
→ indexed
→ retrieval eligible
→ retired / deleted / stale
```

This answers a different operational question:

> Why is a known upstream item missing or unusable, and at which lifecycle/pipeline stage did it fail?

Public Kapa material reviewed in R-002 does not establish equivalent end-to-end item-state observability. Status: **UNKNOWN**.

Potential differentiation should therefore be stated narrowly as:

```text
POSSIBLE:
ASK-AI can expose deeper source-item pipeline truth
and lifecycle diagnostics.
```

Not:

```text
Kapa lacks source observability.
```

---

## 10. Agent-facing retrieval contract and Agent Context

### 10.1 Retrieval is a first-class product surface — PROVEN PUBLIC CAPABILITY

Kapa exposes knowledge through at least:

- Hosted MCP;
- Retrieval API;
- generated-answer Chat API;
- Product Agent SDK / agent integrations.

The coexistence of retrieval and answer surfaces means Kapa can be either:

```text
agent knowledge tool
```

or:

```text
end-to-end answer engine
```

### 10.2 Chat API details — PROVEN PUBLIC CAPABILITY

Public examples show a generated-answer API with project and thread surfaces such as:

```text
POST /query/v1/projects/{project_id}/chat/
POST /query/v1/threads/{thread_id}/chat/
```

Public integration guidance uses API-key authentication, supports integration metadata, multi-turn thread continuation, uncertainty, and relevant source information.

Per-query source constraints such as `source_ids_include` are also publicly documented in integration examples.

Exact Retrieval API schema details are not fully frozen by this research because public documentation surfaces evolve.

### 10.3 Multi-turn state — PROVEN PUBLIC CAPABILITY

Kapa's Chat API exposes thread continuation, making multi-turn context a productized capability rather than only stateless retrieval.

### 10.4 Knowledge as agent planning context — PROVEN KAPA OBSERVATION

Kapa analyzed 1,192 conversations of an internal product agent with roughly 30 native tools plus a knowledge-search tool.

Kapa reports three recurring functions for knowledge retrieval:

1. answer questions native tools cannot answer;
2. contextualize native-tool results;
3. teach the agent enough product semantics to select/use the correct native tool.

The third role is strategically important:

```text
Knowledge Retrieval
≠ only Answer Context

Knowledge Retrieval
= Agent Planning Context too
```

### 10.5 Tool/action model — PROVEN PUBLIC CAPABILITY

Kapa's Agent SDK can run product tools in the customer's application context and can reuse customer permissions/RBAC. Approval-gated actions are supported.

This is a relevant precedent for future ASK-AI agent-action boundaries.

### 10.6 ASK-AI I-005 implication

I-005 should not be defined as merely "persistent memory" or "add MCP".

A stronger concept is:

```text
Agent Context Platform
├── governed product knowledge retrieval
├── product semantics for tool planning
├── evidence/provenance delivery
├── source/product/version scope
├── machine-consumable sufficiency/uncertainty
├── MCP / Retrieval API surfaces
├── persistent cross-session context where justified
└── future associative memory where justified
```

---

## 11. Enterprise, security and deployment

### 11.1 Established enterprise capabilities — PROVEN PUBLIC CAPABILITY

Public Kapa enterprise/security material establishes capabilities including:

- SOC 2 Type II;
- GDPR;
- encryption in transit/at rest;
- SSO;
- SCIM;
- advanced access controls;
- audit logs;
- retention controls;
- PII masking/protection;
- regional/EU hosting options;
- private/internal project modes.

Public security material describes managed storage/processing using Google Cloud PostgreSQL and Weaviate, with multiple external model/embedding providers and agreements preventing customer-data training.

### 11.2 VPC/private deployment — PUBLICLY DISCUSSED

Current public material states that VPC deployment can be discussed where requirements demand it.

Therefore it is no longer correct to frame private/VPC deployment as wholly absent from Kapa.

### 11.3 Full self-host/on-prem — UNKNOWN

R-002 did not establish a generally available customer-owned full-stack/self-host/on-prem Kapa distribution.

This must remain:

```text
UNKNOWN — NOT PUBLICLY ESTABLISHED
```

not:

```text
UNSUPPORTED
```

### 11.4 Competitive implication

The following are enterprise table stakes, not differentiation:

```text
SSO
SCIM
RBAC/access controls
audit logs
retention
regional hosting
PII handling
```

ASK-AI's potential enterprise differentiation should be framed around:

- customer control;
- inspectability;
- model/provider choice;
- knowledge/evidence governance;
- deployment sovereignty where demanded;
- operational transparency.

These are hypotheses requiring product/economic validation, not automatic wins.

---

## 12. Pricing and operational value model

Kapa's public packaging is tiered around trial, production/growth, and enterprise surfaces. Public list pricing for higher tiers is not consistently exposed and should not be treated as a stable competitive fact.

Its value proposition bundles the operational burden of:

```text
Ingest
→ Index
→ Retrieve
→ Operate
```

including connector maintenance, crawling, PDF/image conversion, incremental indexing, chunking, embeddings/storage, hybrid retrieval, context tuning, infrastructure/model migrations, and analytics.

This matters for ASK-AI:

> A self-hosted or controllable product cannot win merely because customers own the software. It must keep operational burden acceptably low or expose control that customers materially value.

---

## 13. Competitive capability matrix

Legend:

- **STRONG** — clearly productized/publicly evidenced;
- **PARTIAL** — capability exists but public scope/details are incomplete;
- **UNKNOWN** — public evidence insufficient;
- ASK-AI status reflects current accepted architecture/product state and still requires post-I-002 benchmark reconciliation.

| Capability | Kapa 2026 | ASK-AI current/target interpretation | Competitive meaning |
|---|---|---|---|
| Multi-source ingestion | STRONG | PARTIAL | Table-stakes gap |
| Automatic freshness | STRONG | PARTIAL | I-003 table stakes |
| Product/version scoping | STRONG | PARTIAL | Table stakes |
| Hybrid sparse+dense retrieval | STRONG | STRONG baseline | Parity, not differentiation |
| Reranking | STRONG | STRONG baseline | Parity |
| Query decomposition | STRONG | Partial/different semantics | I-004 parity target |
| Multi-step/agentic retrieval | STRONG | Not generalized yet | I-004 strategic parity |
| Context pruning/optimization | STRONG | No equivalent frozen capability | Experiment, do not copy blindly |
| Image knowledge representation | PROVEN research/product direction | Gap/partial | I-003 experiment candidate |
| Retrieval API | STRONG | APIs exist, not equivalent product surface | Productization gap |
| Hosted MCP | STRONG | Future direction | I-005 table stakes |
| Agent planning context | STRONG evidence | Future direction | I-005 strategic capability |
| Uncertainty signal | STRONG | Evidence coverage exists internally | Consider product surface |
| Claim-level citation guidance | STRONG public position | INC-6 claim validation | Not unique alone |
| Conversation analytics | STRONG | Weaker/product gap | Table stakes |
| Source Analytics | STRONG | Issue #30 is deeper/different | Do not claim Kapa lacks observability |
| Runtime EvidencePlan equivalent | UNKNOWN | ACCEPTED foundation | Differentiation hypothesis |
| Runtime CoverageReport equivalent | UNKNOWN | ACCEPTED foundation | Differentiation hypothesis |
| Missing-slot corrective retrieval | UNKNOWN | Future I-004 | Differentiation hypothesis |
| Connector-native structured truth | Limited/generic DB delegated to tools | Future I-003 | Differentiation hypothesis |
| Full item lifecycle pipeline truth | UNKNOWN | Future I-003/#30 | Differentiation hypothesis |
| Enterprise SSO/SCIM/audit/retention | STRONG | Future maturity work | Table stakes |
| VPC/private deployment discussion | PROVEN | Self-host/control direction | Not uniquely ASK-AI |
| Full self-host/on-prem distribution | UNKNOWN | Core ASK-AI direction | Possible differentiator, validate demand |

---

## 14. Competitive classification

### 14.1 TABLE STAKES

ASK-AI should assume these are required to compete rather than differentiators:

- multi-source technical/product ingestion;
- continuous source freshness/incremental indexing;
- product/version/source scoping;
- strong sparse+dense/hybrid retrieval;
- reranking;
- grounded citations/source traceability;
- uncertainty/abstention behavior;
- conversation history;
- source/conversation analytics;
- Retrieval API;
- MCP access;
- agent-facing knowledge retrieval;
- enterprise identity/access/audit/retention controls;
- increasingly, rich PDF/image-aware ingestion.

### 14.2 STRATEGIC PARITY

ASK-AI should experimentally reach competitive capability in:

- query decomposition;
- adaptive/multi-step retrieval;
- high-recall multi-source retrieval;
- multi-route retrieval;
- context utility optimization;
- knowledge-quality feedback loops;
- production evaluation discipline;
- knowledge-for-agent-planning semantics.

Implementation does not need to match Kapa's implementation.

### 14.3 DIFFERENTIATION BETS

Evidence supports **investigating**, not yet claiming, differentiation in:

1. **Evidence-objective control plane**
   - explicit EvidencePlan;
   - required/optional evidence roles;
   - CoverageReport as runtime evidence truth;
   - missing-slot-driven corrective retrieval.

2. **Integrated partial-answer semantics**
   - answer supported portion when required evidence is incomplete;
   - expose material gaps without generic refusal;
   - never imply full task resolution when coverage is partial.

3. **Integrated claim/evidence governance**
   - explicit post-generation claim/evidence validation;
   - inspectable lineage from source/chunk through evidence roles to claims.

4. **Connector-native structured truth**
   - preserve exact domain records and relations for supported connectors;
   - explicit provenance, freshness, authority, lifecycle.

5. **Deep knowledge-pipeline observability**
   - upstream/discovery/admission/fetch/ledger/index/searchability/lifecycle truth at item level.

6. **Customer-controlled architecture**
   - self-host/control where demanded;
   - provider/model choice;
   - inspectable evidence control plane;
   - operational transparency.

7. **Unified evidence intelligence across humans and agents**
   - the same governed evidence semantics powering answers, APIs, MCP, and agent context.

### 14.4 NON-GOALS

Do not make roadmap decisions merely to:

- match Kapa connector count;
- copy Kapa UI/branding;
- adopt GraphRAG/LightRAG because they are newer;
- introduce unrestricted agent loops;
- add LLM calls solely to appear agentic;
- replace explicit evidence semantics with generic agent reasoning;
- implement every enterprise checkbox before demand;
- reproduce every Kapa surface before core evidence quality is proven.

---

## 15. Implications for ASK-AI roadmap

### 15.1 I-003 — Knowledge Intelligence & Operations

I-003 should own the **Knowledge Truth Layer**:

```text
Source Content Inventory / Pipeline Truth
Freshness / Lifecycle / Authority
Product / Version Isolation
Provenance
Connector-native Structured Truth
Governed Domain Entities / Relations
Derived Knowledge Lifecycle / Reconciliation
Rich Knowledge Representation where justified
Knowledge / Index Health
Rebuild / Recovery Semantics
```

Recommended internal sequence:

```text
G1 Knowledge Observability Foundation
→ G2 Lifecycle / Freshness / Authority
→ G3 Connector-native Structured Knowledge
→ G4 Governed Domain Relations / Derived Knowledge
→ G5 Rich Representation / Structured-Graph Experiments
```

Important correction from Kapa research:

> #30 should focus on **pipeline truth and diagnosability**, not merely page popularity or usage analytics, because Kapa already has strong Source Analytics.

### 15.2 I-004 — Adaptive Retrieval Intelligence

I-004 should own the retrieval "brain":

```text
Retrieval Policy Engine
Frontier Hybrid
Structured Retrieval
Graph Retrieval where measured useful
Hierarchical / Global Retrieval where measured useful
Parallel / Sequential Multi-Route Retrieval
EvidencePlan-aware Retrieval
CoverageReport-driven Corrective Retrieval
Bounded Agentic Retrieval
Context Utility Optimization
Quality / Latency / Cost Budgets
Retrieval-policy Observability
```

Kapa materially raises the minimum bar: query decomposition and iterative retrieval are current competitive reality.

### 15.3 I-005 — Agent Context Platform

I-005 must be stronger than "add MCP" and broader than conversational memory:

```text
Governed Product Knowledge Context
+ Evidence / Provenance Delivery
+ Product Semantics for Agent Tool Planning
+ Source / Version Scope
+ Machine-consumable Sufficiency / Uncertainty
+ MCP / Retrieval API
+ Persistent / Cross-session Context
+ Controlled Tool / Context Interfaces
+ Future Associative Memory where justified
```

### 15.4 I-006 — Platform / Enterprise

I-006 should treat:

```text
SSO
SCIM
RBAC/access controls
Audit
Retention
Regional hosting
PII controls
```

as table stakes.

Differentiation should focus on controllability, deployment sovereignty where demanded, inspectability, provider/model control, and evidence/knowledge governance.

---

## 16. Architecture principles learned from Kapa research

1. **Final-answer gain > retrieval novelty.**
2. **Knowledge ingestion and representation are product capabilities, not plumbing.**
3. **No single retrieval mode should have architectural privilege.**
4. **Agentic retrieval should be bounded and evidence-driven, not agentic for its own sake.**
5. **Retrieval must optimize generator context utility as well as recall.**
6. **Product/version isolation is table stakes.**
7. **Knowledge retrieval is also agent planning context.**
8. **Citations require faithfulness evaluation; links alone are insufficient.**
9. **Structured/live operational truth may be better represented through governed native connectors/tools than flattened into text.**
10. **Enterprise differentiation must exceed generic security/compliance checkboxes.**
11. **Graph is a substrate, not an architecture identity.**
12. **Unknown competitor internals must remain UNKNOWN; lack of evidence is not evidence of absence.**

---

## 17. Roadmap constraints produced by R-002

R-002 constrains future ASK-AI planning as follows:

- Do not position ASK-AI as merely a Kapa-like chatbot.
- Do not claim Hybrid RAG, reranking, citations, MCP, analytics, or product/version scoping as strategic differentiation.
- Do not freeze GraphRAG, LightRAG, or a graph database as the target architecture.
- Do not freeze unrestricted Agentic RAG as the default retrieval architecture.
- Preserve a replaceable multi-substrate retrieval architecture.
- Evaluate Kapa-parity capabilities against ASK-AI's own Benchmark, not vendor claims.
- Require evidence that a new retrieval mechanism improves final answer/evidence quality enough to justify latency, cost, and operational complexity.
- Treat `EvidencePlan + CoverageReport + RetrievalPolicy` as the leading ASK-AI control-plane differentiation hypothesis until experiments prove or disprove it.
- Treat connector-native structured truth and deep pipeline observability as I-003 hypotheses requiring real product evidence.
- Treat Agent Context as a strategic product surface, not only an internal implementation feature.
- Treat context optimization as an explicit experiment dimension rather than a mandatory extra LLM stage.
- Treat self-host/control as a possible differentiator only when it creates material customer value at acceptable operational cost.

---

## 18. Remaining non-blocking unknowns

The following are not established by current public evidence and must not be guessed:

1. Kapa's exact internal semantic stopping policy for agentic retrieval.
2. Whether Kapa internally represents required evidence roles/slots equivalent to EvidencePlan.
3. Whether Kapa has a per-request sufficiency object equivalent to CoverageReport.
4. Whether corrective retrieval is explicitly driven by missing semantic evidence slots.
5. Exact internal reflection/retry/search-budget policy for multi-step retrieval.
6. Exact internal claim-validation architecture beyond public claim-level citation/faithfulness guidance.
7. Full item-level ingestion/index lifecycle state exposed internally or in Admin.
8. Full ACL propagation semantics from heterogeneous upstream systems into retrieval eligibility.
9. General self-host/on-prem/customer-owned deployment availability beyond public VPC/regional discussion.
10. Long-term direction for first-class structured/native data beyond custom Agent SDK tools and specialized source formats.
11. Exact interaction among source groups, per-query source filters, ACLs, and agentic retrieval.
12. Exact full current Retrieval API response/control schema beyond public product/integration examples.

These are **NON-BLOCKING** for ASK-AI architecture planning. If a future decision depends specifically on one of them, open a targeted R-002 verification task rather than restarting broad competitor research.

---

## 19. Final research disposition

```text
R-002_KAPA_RESEARCH = CLOSED

AUTHORITY
= THIS DOCUMENT

PRODUCT POSITIONING RESEARCH       = SUFFICIENT
KNOWLEDGE / INGESTION RESEARCH     = SUFFICIENT
RETRIEVAL ARCHITECTURE RESEARCH    = SUFFICIENT
ANSWER / CITATION RESEARCH         = SUFFICIENT
KNOWLEDGE OPERATIONS RESEARCH      = SUFFICIENT
AGENT CONTEXT RESEARCH             = SUFFICIENT
ENTERPRISE / DEPLOYMENT RESEARCH   = SUFFICIENT

UNRESOLVED INTERNAL DETAILS
= NON-BLOCKING UNKNOWN

ROADMAP DECISION INPUT
= READY

IMPLEMENTATION AUTHORIZATION
= NONE
```

The next product/architecture research artifact is:

**R-001C — ASK-AI Capability Gap & Architecture Decision Framework**

It should combine:

```text
R-001 / R-001A / R-001B
+
this authoritative R-002 research
+
current ASK-AI repo reality
+
Issues #26–#31
+
post-I-002 production Benchmark evidence when available
```

into a decision framework from observed product failure → required capability → current gap → candidate architecture capability → initiative ownership → experiment → decision readiness.

---

## 20. Public evidence base

Primary/current Kapa sources used across R-002 phases include:

- https://docs.kapa.ai/
- https://www.kapa.ai/
- https://www.kapa.ai/product/connect
- https://www.kapa.ai/product/analyze
- https://www.kapa.ai/product/deploy
- https://www.kapa.ai/solutions/mcp
- https://www.kapa.ai/solutions/product-agent-sdk
- https://www.kapa.ai/solutions/in-product-agents
- https://www.kapa.ai/solutions/for-dev-tools
- https://www.kapa.ai/security
- https://www.kapa.ai/blog/introducing-kapa-for-agents
- https://www.kapa.ai/blog/every-kapa-data-source-now-syncs-automatically---including-web-crawls
- https://www.kapa.ai/blog/how-we-index-images-for-rag
- https://www.kapa.ai/blog/how-we-prune-rag-context
- https://www.kapa.ai/blog/how-to-properly-evaluate-ai-assistants-for-technical-documentation
- https://www.kapa.ai/blog/knowledge-base-search-in-ai-agents

Source URLs are retained for traceability. Kapa changes its public product and documentation over time; future decisions that depend on a time-sensitive Kapa capability should perform targeted re-verification rather than assuming this 2026-09-08 snapshot is permanently current.
