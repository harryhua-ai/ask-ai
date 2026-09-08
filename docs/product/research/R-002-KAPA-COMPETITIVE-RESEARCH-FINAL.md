# R-002 — Kapa.ai Competitive Research Final

**Status:** RESEARCH CLOSED — ROADMAP DECISION INPUT READY  
**Repository:** `harryhua-ai/ask-ai`  
**Research branch:** `research/r001-knowledge-retrieval-architecture`  
**Date:** 2026-09-08  
**Implementation authorization:** NONE  
**Production mutation:** NONE  
**Benchmark mutation:** NONE

## 1. Executive conclusion

Kapa.ai is no longer best understood as a documentation chatbot. Its current public product model is an ingestion and retrieval platform for technical/product knowledge, exposed through prebuilt answer experiences, Retrieval API, Hosted MCP, and an Agent SDK.

The competitive lesson for ASK-AI is not to clone Kapa or to adopt a fashionable RAG framework. The relevant target is to build a stronger evidence-oriented control plane on top of trustworthy enterprise knowledge.

Kapa establishes that the following are now table stakes or near-table-stakes for this category: broad multi-source ingestion, automatic freshness, product/version scoping, hybrid retrieval and reranking, cited answers, uncertainty handling, analytics, Retrieval API/MCP, agent-facing knowledge, and enterprise governance.

ASK-AI's strongest potential differentiation is therefore not generic RAG. It is the explicit chain:

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

Public Kapa material reviewed in R-002 does not establish direct equivalents of ASK-AI's explicit EvidencePlan, required evidence slots, runtime CoverageReport, missing-slot corrective retrieval, or the same formal post-generation claim-evidence validation contract. Those internals remain UNKNOWN rather than presumed absent.

R-002 is closed because remaining unknowns are not publicly verifiable enough to justify blocking product planning. They remain explicit non-blocking unknowns.

---

## 2. Kapa product model

Current public evidence supports this model:

```text
Technical / Product Knowledge Sources
        ↓
Managed Ingestion + Continuous Sync
        ↓
Unified Knowledge Base
        ↓
Retrieval Infrastructure
        ↓
Single-pass / Agentic Retrieval + Reranking + Context Optimization
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

Kapa explicitly describes itself as an ingestion and retrieval system. It positions the same knowledge layer behind documentation assistants, support experiences, internal assistants, MCP, Retrieval API, and product agents.

This validates Agent Context as a current competitive category, not a speculative future feature.

---

## 3. Knowledge ingestion, representation, freshness and scope

### 3.1 Proven public capabilities

Kapa publicly supports a broad set of technical/product knowledge sources including websites/documentation, GitHub/code, PDFs, support systems, Slack/community content, knowledge bases, files, OpenAPI and related technical sources.

Sources are automatically refreshed/re-indexed as upstream content changes.

Kapa supports product/version scoping through source groups. Public semiconductor material explicitly describes scoping by product family, part number and silicon revision, including a two-level grouping model with a Global group for shared sources.

Kapa also publicly describes ingestion-time conversion of non-text technical content such as PDFs and images into retrieval-ready representations.

### 3.2 Structured/live data boundary

Kapa explicitly states that generic SQL/database structured data is not an out-of-box connector because schemas vary. For product agents, its Agent SDK supports custom tools that query a customer's database using the customer's own logic and authentication.

This is important for ASK-AI. It leaves room for a deliberate architecture in which stable domain-aware connectors expose first-class connector-native structured truth — e.g. WooCommerce Product → Variant → SKU → Price → Stock → Attributes — with provenance, freshness and lifecycle semantics.

ASK-AI should not generalize this into 'ingest every database'. The opportunity is domain-governed structured knowledge where semantics and authority are stable enough to justify first-class representation.

---

## 4. Retrieval architecture

### 4.1 Publicly established Kapa retrieval capabilities

Public Kapa material establishes:

- sparse and embedding-based retrieval;
- hybrid retrieval;
- reranking;
- multiple search iterations in agentic retrieval;
- query decomposition;
- source URL preservation/citations;
- single-pass and agentic retrieval modes;
- context pruning/optimization between retrieval and generation.

Therefore a static `BM25 + vector + reranker` architecture alone is no longer an adequate strategic target for ASK-AI.

### 4.2 Agentic retrieval

Kapa's agentic retrieval is materially more than a marketing rename for one hybrid query: public descriptions include decomposition and multiple search iterations.

However, public evidence does not establish the internal stopping policy, semantic sufficiency representation, evidence-role planning, exact retry budget, reflection mechanism, or whether retrieval is explicitly driven by required evidence slots.

These remain UNKNOWN.

### 4.3 Context pruning

Kapa's published research adds a small-model pruning stage after retrieval/reranking and before generation. Its reported experiment removed about 68% of retrieved context while retaining about 96% of required-context recall, with reported net query-cost reduction and roughly sub-second-to-one-second additional latency depending on configuration. These are Kapa's own experimental claims, not independent benchmark results.

Architecture lesson for ASK-AI:

> optimize final-answer utility per latency/cost, not Recall@K in isolation.

ASK-AI should evaluate context utility optimization, but protect required EvidencePlan slots and CoverageReport invariants rather than blindly copy an extra LLM call.

---

## 5. Answer grounding, citations and uncertainty

Kapa publicly targets cited, source-backed answers and explicit uncertainty / 'I don't know' behavior when sources do not cover a question.

Recent Kapa guidance explicitly distinguishes source lists, answer-level citations and claim-level citations, identifying claim-level passage support as the strongest verifiable form. It also describes citation faithfulness as something that must be evaluated rather than assumed from RAG.

This materially narrows any simplistic ASK-AI claim that citation validation itself is unique.

The more defensible ASK-AI differentiation hypothesis is the integrated runtime evidence contract:

```text
EvidencePlan
→ explicit required roles/slots
→ CoverageReport
→ supported partial-answer semantics
→ claim/citation validation
```

Whether Kapa has an internal equivalent integrated contract is UNKNOWN.

---

## 6. Knowledge operations and observability

Kapa has mature conversation/product analytics including conversation review, source analytics, top questions and coverage-gap analysis. Public material supports source/page-level visibility into knowledge usage and answer contribution.

Therefore ASK-AI must not claim that basic source analytics or content-level inspection are unique.

The narrower potential ASK-AI differentiation from Issue #30 is deeper pipeline truth:

```text
upstream object
→ discovered
→ admitted / excluded
→ fetched / parsed
→ document ledger
→ indexed
→ retrieval eligible
→ retired / deleted / stale
```

That is a diagnosability/lifecycle objective rather than merely usage analytics. Public Kapa material reviewed does not establish equivalent end-to-end item-state observability. Status: UNKNOWN.

---

## 7. Agent Context and action model

Kapa exposes retrieval through Hosted MCP and an HTTP Retrieval API, and its Agent SDK adds orchestration, streaming, knowledge search and custom tools.

Kapa's own product-agent observations show knowledge retrieval serving at least three functions:

1. answer questions native tools cannot answer;
2. contextualize native-tool output;
3. teach the agent product semantics so it can select/use the correct tool.

Therefore Agent Context should not be reduced to conversational memory. For ASK-AI, the strategic concept should include:

```text
Agent Context Platform
├── governed product knowledge retrieval
├── product semantics for tool planning
├── evidence/provenance context
├── MCP / Retrieval API interfaces
├── persistent cross-session context where justified
└── future associative memory where justified
```

Kapa's Agent SDK executes product tools in the customer's application context and can reuse existing permissions/RBAC; approval-gated actions are supported. This is relevant precedent for future ASK-AI agent-action boundaries.

---

## 8. Enterprise and deployment

Publicly established Kapa enterprise capabilities include SOC 2 Type II, GDPR, encryption, SSO, SCIM, advanced access controls, audit logs, retention controls, PII masking/protection and regional/EU hosting on enterprise plans.

Kapa publicly describes its managed data path as ingestion → US-based Google Cloud PostgreSQL → transformation → Weaviate on Google Cloud → LLM synthesis, while enterprise/regional offerings can alter hosting constraints.

Public material also states that VPC deployment is available to discuss for requirements that need it.

Therefore:

- SSO/RBAC/audit/retention/regional hosting are enterprise table stakes, not ASK-AI differentiation;
- it is no longer accurate to treat VPC/private deployment as wholly absent from Kapa;
- general self-host/on-prem/customer-owned full-stack deployment remains not publicly established by the reviewed material and is therefore UNKNOWN.

ASK-AI's potential enterprise differentiation should be framed more precisely around customer control, inspectability, model/provider choice, knowledge/evidence governance and operational transparency — not merely 'enterprise security'.

---

## 9. Competitive classification

### TABLE STAKES

ASK-AI should assume these capabilities are required to compete, not differentiators:

- multi-source technical/product ingestion;
- continuous source freshness;
- product/version/source scoping;
- strong sparse+dense/hybrid retrieval;
- reranking;
- grounded citations;
- uncertainty handling;
- source/conversation analytics;
- Retrieval API;
- MCP access;
- agent-facing knowledge retrieval;
- enterprise identity/access/audit/retention controls at mature stage.

### STRATEGIC PARITY

ASK-AI should experimentally reach competitive capability in:

- query decomposition;
- multi-step retrieval;
- adaptive/multi-route retrieval;
- multi-source evidence retrieval;
- context utility optimization;
- production evaluation discipline;
- knowledge-for-agent-planning semantics.

### DIFFERENTIATION BETS

Evidence currently supports investigating, not yet claiming, differentiation in:

- explicit EvidencePlan as retrieval objective;
- required evidence-role/slot planning;
- CoverageReport as per-request evidence sufficiency truth;
- missing-slot-driven corrective retrieval;
- partial-supported-answer semantics grounded in coverage truth;
- connector-native structured truth with explicit authority/freshness/lifecycle;
- deep source-item pipeline observability;
- integrated claim/evidence validation contract;
- self-hosted/customer-controlled architecture and model/provider control;
- unified evidence control plane across answers and agent context.

### NON-GOALS

Do not make roadmap decisions merely to:

- match Kapa's connector count;
- copy Kapa UI;
- adopt GraphRAG/LightRAG because they are newer;
- introduce unbounded agentic retrieval loops;
- add LLM calls solely to make retrieval 'agentic';
- reproduce every Kapa deployment surface before core evidence quality is proven.

---

## 10. Implications for ASK-AI initiatives

### I-003 — Knowledge Intelligence & Operations

Should own:

- Source Content Inventory / pipeline truth;
- provenance;
- freshness and lifecycle;
- source authority;
- product/version isolation;
- connector-native structured truth;
- governed domain entities/relations;
- derived-knowledge lifecycle/reconciliation;
- knowledge/index health and rebuild semantics.

Kapa research strengthens the case that knowledge representation/freshness are first-order product capabilities, while also showing that generic source analytics and version scoping are already competitive requirements.

### I-004 — Adaptive Retrieval Intelligence

Should own:

- Retrieval Policy Engine;
- sparse/dense/hybrid evolution;
- structured retrieval;
- graph traversal where measured useful;
- hierarchical/global retrieval where measured useful;
- multi-route retrieval;
- EvidencePlan-aware retrieval;
- CoverageReport-driven corrective retrieval;
- bounded agentic retrieval;
- context utility optimization;
- explicit latency/cost budgets.

Kapa research materially raises the minimum bar: query decomposition and iterative retrieval must be treated as competitive reality.

### I-005 — Agent Context Platform

Should be broader than memory:

- product knowledge retrieval;
- evidence/provenance delivery to agents;
- product semantics for agent tool planning;
- MCP / Retrieval API surfaces;
- persistent context and cross-session state;
- future associative memory where justified.

### I-006 — Platform / Enterprise

Should treat SSO, SCIM, RBAC/access controls, audit, retention and regional hosting as table stakes. Differentiation should focus on controllability, deployment sovereignty where demanded, inspectability and governance rather than checkbox parity alone.

---

## 11. Architecture principles learned from Kapa research

1. **Final-answer gain > retrieval novelty.**
2. **Knowledge ingestion and representation are product capabilities, not plumbing.**
3. **No single retrieval mode should have architectural privilege.**
4. **Agentic retrieval should be bounded and evidence-driven, not agentic for its own sake.**
5. **Retrieval must optimize generator context utility as well as recall.**
6. **Product/version isolation is table stakes.**
7. **Knowledge retrieval is also agent planning context.**
8. **Citations require faithfulness evaluation; links alone are insufficient.**
9. **Structured/live operational truth may be better queried through governed native tools or connector-native representations than flattened into text.**
10. **Enterprise differentiation must exceed generic security/compliance checkboxes.**

---

## 12. Roadmap constraints produced by R-002

R-002 constrains future planning as follows:

- Do not position ASK-AI as merely a Kapa-like chatbot.
- Do not claim Hybrid RAG/reranking/citations/MCP/version scoping as strategic differentiation.
- Do not freeze GraphRAG, LightRAG or a graph database as the target architecture.
- Do not freeze unrestricted Agentic RAG as the default retrieval architecture.
- Preserve a replaceable multi-substrate retrieval architecture.
- Evaluate Kapa-parity capabilities against ASK-AI's own Benchmark, not vendor claims.
- Require evidence that a new retrieval mechanism improves final answer/evidence quality enough to justify latency, cost and operational complexity.
- Treat EvidencePlan + CoverageReport + RetrievalPolicy as the leading ASK-AI control-plane differentiation hypothesis until experiments prove or disprove it.
- Treat connector-native structured truth and deep knowledge-pipeline observability as I-003 hypotheses requiring real product evidence.
- Treat Agent Context as a strategic product surface, not only an internal implementation feature.

---

## 13. Remaining non-blocking unknowns

The following are not established by current public evidence and must not be guessed:

1. Kapa's exact internal semantic stopping policy for agentic retrieval.
2. Whether Kapa internally represents required evidence roles/slots equivalent to EvidencePlan.
3. Whether Kapa has a per-request sufficiency object equivalent to CoverageReport.
4. Whether corrective retrieval is explicitly driven by missing semantic evidence slots.
5. Exact internal reflection/retry/budget policy for multi-step retrieval.
6. Exact internal claim-validation architecture beyond public claim-level citation/faithfulness guidance.
7. Full item-level ingestion/index lifecycle state exposed internally or in Admin.
8. Full ACL propagation semantics from heterogeneous upstream systems into retrieval eligibility.
9. Full self-host/on-prem/customer-owned deployment availability beyond publicly discussed VPC/regional options.
10. Long-term direction for first-class structured/native data beyond custom Agent SDK tools and specialized source formats.

These unknowns are **NON-BLOCKING** for ASK-AI architecture planning. If a future ASK-AI decision depends specifically on one of them, reopen a targeted R-002 verification task rather than restarting broad competitor research.

---

## 14. Final research disposition

```text
R-002_KAPA_RESEARCH = CLOSED

PRODUCT POSITIONING RESEARCH       = SUFFICIENT
KNOWLEDGE / INGESTION RESEARCH     = SUFFICIENT
RETRIEVAL ARCHITECTURE RESEARCH   = SUFFICIENT
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

The next product/architecture research artifact should be **R-001C — ASK-AI Capability Gap & Architecture Decision Framework**, combining R-001/R-001A/R-001B, this closed R-002 research, current ASK-AI repo reality, Issues #26–#31, and post-I-002 production Benchmark evidence when available.

---

## 15. Public evidence base

Primary/current Kapa sources used across R-002 phases include:

- https://docs.kapa.ai/
- https://www.kapa.ai/
- https://www.kapa.ai/product/connect
- https://www.kapa.ai/product/deploy
- https://www.kapa.ai/solutions/mcp
- https://www.kapa.ai/solutions/product-agent-sdk
- https://www.kapa.ai/solutions/in-product-agent
- https://www.kapa.ai/solutions/for-semiconductor
- https://www.kapa.ai/security
- https://www.kapa.ai/pricing
- https://www.kapa.ai/blog/introducing-kapa-for-agents
- https://www.kapa.ai/blog/how-we-prune-rag-context
- https://www.kapa.ai/blog/how-we-index-images-for-rag
- https://www.kapa.ai/blog/knowledge-base-search-in-ai-agents
- https://www.kapa.ai/library/how-to-make-an-ai-assistant-give-source-backed-answers

Vendor benchmark/performance statements are treated as Kapa claims unless independently verified.