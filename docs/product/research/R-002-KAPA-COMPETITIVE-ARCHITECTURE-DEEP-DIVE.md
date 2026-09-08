# R-002 — Kapa.ai Competitive Architecture Deep Dive

**Status:** RESEARCH IN PROGRESS — DECISION INPUT ONLY  
**Repository:** `harryhua-ai/ask-ai`  
**Research branch:** `research/r001-knowledge-retrieval-architecture`  
**Date:** 2026-09-08  
**Implementation authorization:** NONE  
**Production mutation:** NONE  
**Benchmark mutation:** NONE

## 1. Purpose

Kapa.ai is a direct benchmark for ASK-AI. R-002 exists to prevent roadmap and architecture decisions from being driven only by internal intuition or frontier papers.

R-001 asks:

> What is the best evidence-backed knowledge/retrieval architecture ASK-AI should target?

R-002 asks:

> What has the strongest direct benchmark already productized, what appears to be its real architecture and operating model, what is table stakes, and where can ASK-AI differentiate rather than merely clone it?

R-002 must distinguish:

- **PROVEN PUBLIC CAPABILITY** — supported by current Kapa documentation/product material;
- **KAPA CLAIM** — benchmark/performance statement published by Kapa itself;
- **INFERENCE** — architecture implication inferred from public evidence;
- **UNKNOWN** — not established by public evidence.

No Kapa marketing claim should be silently promoted into independent fact.

---

## 2. Executive finding — current competitive position

Kapa in 2026 is no longer best modeled as a documentation chatbot.

Its current public positioning is approximately:

```text
Knowledge Sources
      ↓
Managed Ingestion / Sync
      ↓
Unified Technical Knowledge Base
      ↓
Managed Retrieval Pipeline
      ↓
Agentic Retrieval / Context Pruning
      ↓
┌──────────────────────────────────────┐
│ Retrieval API                        │
│ Hosted MCP                           │
│ Prebuilt Agents / Answer experiences │
└──────────────────────────────────────┘
      ↓
Customer-facing agents
Internal agents
Coding agents
Support workflows
```

Kapa documentation explicitly describes the product as an **ingestion and retrieval system**: ingestion builds and maintains a unified knowledge base from many source types; agentic retrieval searches it; customers expose it to agents through MCP/API; Prebuilt Agents cover cases where customers do not want to build the agent themselves.

This means ASK-AI's strategic direction toward:

```text
Knowledge Platform
+
Intelligent Answer Engine
+
Agent Context Platform
```

is directionally validated by a direct benchmark, but it also means Agent Context is becoming competitive reality rather than a distant speculative feature.

**Source:** https://docs.kapa.ai/  
**Source:** https://www.kapa.ai/blog/introducing-kapa-for-agents

---

## 3. Product positioning

### 3.1 Current public positioning — PROVEN PUBLIC CAPABILITY

Kapa currently positions itself around technical/product knowledge retrieval for both humans and agents.

Public use cases include:

- knowledge for in-product agents;
- documentation Ask AI;
- support automation;
- public MCP server;
- internal/company knowledge;
- Slack/Discord/community answers;
- competitor intelligence;
- RFP answering.

Kapa therefore spans three product surfaces:

```text
A. Managed Knowledge / Retrieval Infrastructure
B. Prebuilt Answer / Support Experiences
C. Agent Context Infrastructure
```

This is materially broader than a widget-only competitor definition.

### 3.2 Strategic implication for ASK-AI — INFERENCE

ASK-AI should not define its addressable product as:

```text
self-hosted Kapa-like chatbot
```

A more defensible long-term framing is:

```text
Self-hosted / controllable
Enterprise Knowledge Intelligence
+
Evidence-grounded Answer Engine
+
Agent Context Infrastructure
```

However, this remains an ASK-AI strategy hypothesis and must be reconciled with user demand, deployment economics and post-I-002 evidence.

---

## 4. Knowledge ingestion and freshness

### 4.1 Source breadth — PROVEN PUBLIC CAPABILITY

Kapa publicly advertises 20+/30+ source types depending on surface/current page, including categories such as:

- documentation/websites;
- GitHub/code;
- API specifications;
- PDFs;
- support tickets;
- Slack/community threads;
- Confluence;
- Notion;
- Google Drive;
- Zendesk;
- Intercom;
- YouTube;
- S3 and others.

The exact connector count varies across current Kapa pages, so R-002 should not freeze a precise count as competitive truth without a canonical connector inventory.

### 4.2 Automatic freshness — PROVEN PUBLIC CAPABILITY

Kapa states that connected knowledge is automatically synchronized and re-indexed as source content changes. In February 2026 it specifically announced automatic sync for web crawls, which had previously remained more manual than other connectors.

**Source:** https://www.kapa.ai/blog/every-kapa-data-source-now-syncs-automatically---including-web-crawls

### 4.3 Version awareness — PROVEN PUBLIC CAPABILITY, DETAILS INCOMPLETE

Kapa's current Connect product page states that it versions products so answers remain scoped to the right product/version.

The public material reviewed in this phase does not yet establish the full underlying identity/version/lifecycle contract.

**Status:** further research required.

### 4.4 Image knowledge — PROVEN PUBLIC CAPABILITY / RESEARCH DIRECTION

Kapa's June 2026 research describes an ingestion-time image pipeline:

```text
image
→ filter/classify
→ VLM caption/transcription with surrounding context
→ separate text caption chunk
→ normal retrieval/rerank
→ cite original image URL
```

Their reported design deliberately avoids query-time multimodal processing. Their experiments report statistically significant answer-quality improvement across three customer projects with roughly +1–6% per-query cost and sub-second TTFT impact; these are Kapa's own experimental results, not independent verification.

This is relevant to ASK-AI because technical product knowledge often contains load-bearing diagrams, tables, screenshots and schematics.

**Source:** https://www.kapa.ai/blog/how-we-index-images-for-rag

### 4.5 ASK-AI gap implication

Kapa's public emphasis reinforces that **ingestion quality, freshness and representation are first-order product capabilities**, not backend plumbing.

This supports the current I-003 direction:

```text
Knowledge Inventory
Knowledge Authority
Knowledge Lifecycle
Structured Knowledge
Derived Knowledge Governance
```

But public evidence reviewed so far does NOT prove that Kapa exposes the item-level source pipeline observability proposed in ASK-AI Issue #30.

That remains a potential ASK-AI differentiation area pending deeper UI/docs investigation.

---

## 5. Retrieval architecture

### 5.1 Managed baseline pipeline — PROVEN PUBLIC CAPABILITY

Kapa publicly describes its managed retrieval pipeline as including:

- chunking;
- embedding;
- hybrid search;
- reranking;
- evaluation/continuous tuning.

Its MCP product page further describes agentic retrieval as a multi-step retrieval pipeline using:

- embedding-based retrieval;
- sparse retrieval;
- multiple search iterations;
- query decomposition;
- reranking;
- source URL traceability.

**Source:** https://www.kapa.ai/solutions/mcp  
**Source:** https://www.kapa.ai/

### 5.2 Single-pass and agentic retrieval coexist — PROVEN PUBLIC CAPABILITY

Kapa's context-pruning research explicitly states that its retrieval exists in several forms, including both agentic and single-pass paths.

This is strategically important: Kapa does not publicly present one universal retrieval paradigm as optimal for every query.

This aligns with R-001's current multi-substrate/adaptive-policy hypothesis.

### 5.3 Agentic retrieval — PARTIALLY PROVEN, INTERNAL DETAILS UNKNOWN

Publicly established components include:

```text
query decomposition
multiple search iterations
embedding + sparse retrieval
reranking
```

Kapa claims its agentic retrieval returns the right source almost 2× more often than web search or a DIY RAG pipeline on a benchmark consisting of four customer projects and 30 human-annotated multi-source production questions per project.

This must be classified as:

```text
KAPA CLAIM
```

not independent benchmark truth.

The public evidence reviewed so far does NOT establish whether Kapa's agentic retrieval has direct equivalents of:

- ASK-AI EvidencePlan;
- explicit required evidence slots;
- CoverageReport-style sufficiency truth;
- missing-slot-driven corrective retrieval;
- formal evidence authority hierarchy;
- bounded iteration budgets exposed as a semantic contract;
- claim-level post-generation evidence validation.

These remain **UNKNOWN**.

### 5.4 Context pruning — PROVEN PUBLIC CAPABILITY + KAPA EXPERIMENTAL CLAIM

Kapa added a model-based pruning stage between retrieval and generation:

```text
retrieval
→ rerank
→ small-LLM context pruning
→ generator
```

Kapa reports approximately:

- 68% retrieved-context removal;
- 96% required-context recall preservation;
- ~34% per-query cost reduction net of pruning cost;
- ~0.7 s pruning latency in its chosen configuration.

It is enabled by default in the Product Agent SDK's knowledge search and optional in Retrieval API/MCP according to Kapa's research post.

This provides a concrete competitive architecture lesson:

> retrieval quality should be optimized together with generator context utility and cost, not only Recall@K.

**Source:** https://www.kapa.ai/blog/how-we-prune-rag-context

### 5.5 ASK-AI implication

Kapa strengthens the case for R-001B's proposed:

```text
Retrieval Policy Engine
+
quality / latency / cost optimization
+
selective advanced retrieval
```

It also introduces **Context Optimization / Pruning** as an architecture option that should be explicitly evaluated in R-001 rather than omitted.

This does not mean ASK-AI should copy Kapa's extra LLM pruning call. ASK-AI should benchmark whether an equivalent stage produces sufficient final-answer utility per latency/cost.

---

## 6. Evaluation discipline

### 6.1 Kapa methodology — PROVEN PUBLIC RESEARCH PRACTICE

Kapa's May 2026 evaluation guidance recommends:

1. representative questions from real production-like sources;
2. manually verified test cases;
3. explicit marking criteria rather than free-form golden-answer similarity;
4. separate factuality and uncertainty scoring;
5. LLM-as-judge with strong models;
6. multiple judge runs;
7. frozen indexed source set during comparisons.

Kapa suggests roughly 100 questions as a reasonable starting point, including 10–20% intentionally unanswerable questions to measure uncertainty behavior.

**Source:** https://www.kapa.ai/blog/how-to-properly-evaluate-ai-assistants-for-technical-documentation

### 6.2 Competitive implication

ASK-AI's Benchmark v1 is already more formal than a vibe test and includes repeated runs, hard/evidence/experience dimensions and failure taxonomy.

Potential improvements to investigate after post-I-002 rerun:

- stronger explicit marking criteria per case;
- separate uncertainty calibration score;
- frozen-source-set architecture experiments;
- architecture-arm evaluation on identical source snapshots;
- final-answer utility as the primary decision metric rather than retrieval novelty.

This should be treated as benchmark methodology refinement, not an immediate mutation of the currently frozen Benchmark v1.

---

## 7. Knowledge operations and analytics

### 7.1 Conversation analytics — PROVEN PUBLIC CAPABILITY

Kapa publicly lists:

- dashboard metrics;
- conversation review/export;
- Coverage Gaps;
- Top Questions;
- Source Analytics;
- scheduled Email/Slack reports;
- user satisfaction/tracking for widget deployments.

### 7.2 Coverage Gaps — PROVEN PUBLIC CAPABILITY

Kapa defines Coverage Gaps as recurring clusters of uncertain answers, producing a finding and AI-generated recommendation for improving knowledge/content.

This is a product-level feedback loop:

```text
production conversations
→ uncertain answers
→ cluster recurring gaps
→ recommendation
→ improve documentation / product knowledge
```

**Source:** https://www.kapa.ai/product/analyze

### 7.3 Important distinction from ASK-AI CoverageReport

Kapa's public **Coverage Gaps** analytics should not be conflated with ASK-AI's per-request `CoverageReport`.

Current evidence supports:

```text
Kapa Coverage Gaps
= post-hoc analytics over uncertain conversations
```

ASK-AI CoverageReport:

```text
= runtime evidence-coverage truth for a specific EvidencePlan
```

Whether Kapa has an internal equivalent runtime sufficiency representation is UNKNOWN.

### 7.4 ASK-AI competitive implication

Kapa appears materially more productized today in analytics and knowledge-gap operations.

ASK-AI Issue #30 goes in a complementary direction: item-level knowledge inventory and pipeline truth.

Potential differentiation hypothesis:

```text
Kapa strength:
conversation-level knowledge gap analytics

ASK-AI opportunity:
conversation gap
+
source-item pipeline observability
+
evidence-plan coverage truth
+
source/derived knowledge lifecycle truth
```

This requires validation against Kapa's actual Admin UI before claiming differentiation.

---

## 8. Agent Context Platform

### 8.1 Hosted MCP + Retrieval API — PROVEN PUBLIC CAPABILITY

Kapa exposes its knowledge retrieval through:

- hosted MCP;
- Retrieval API;
- Product Agent SDK / agent integrations.

It explicitly targets Claude Code, Codex, ChatGPT, Cursor, VS Code and custom agents.

This makes agent-context delivery a present competitive capability, not a future-only concept.

### 8.2 Knowledge as agent planning context — PROVEN KAPA OBSERVATION

Kapa analyzed 1,192 conversations with its own internal product agent. That agent had around 30 native tools plus one `search_knowledge_base` tool.

Kapa reports three roles for knowledge search:

1. fallback when native tools cannot answer a product question;
2. contextualize what native tools return;
3. teach the agent enough product semantics to select/use the correct native tool.

The third role is strategically important:

```text
Knowledge Retrieval
≠ only Answer Context

Knowledge Retrieval
= Agent Planning Context too
```

**Source:** https://www.kapa.ai/blog/knowledge-base-search-in-ai-agents

### 8.3 ASK-AI I-005 implication

I-005 should not be defined only as persistent conversational memory.

A stronger future framing is:

```text
Agent Context Platform

A. Product knowledge retrieval
B. Product semantics for tool planning
C. Persistent / cross-session context
D. Governed agent-facing context APIs / MCP
E. Future associative memory where justified
```

This is a research implication, not a frozen roadmap contract.

---

## 9. Security / enterprise productization

### 9.1 Publicly established

Kapa publicly states:

- SOC 2 Type II;
- GDPR compliance;
- public/external and private/internal project modes;
- private/internal sources such as Zendesk/Confluence/internal docs can be used.

**Source:** https://www.kapa.ai/security

### 9.2 Still to investigate

R-002 has not yet established the current detailed Kapa position on:

- self-hosting / on-prem;
- VPC/private deployment;
- RBAC granularity;
- tenant isolation model;
- SSO/SAML/SCIM;
- audit logs;
- data residency;
- retention controls;
- encryption/key ownership;
- source-level permissions / ACL-aware retrieval;
- enterprise policy enforcement.

These are important because ASK-AI's self-hosted/control-plane direction may create differentiation if Kapa remains primarily managed SaaS, but no such conclusion should be frozen until researched.

---

## 10. Competitive Capability Matrix — Phase 1

Legend:

- `STRONG` — clearly productized/publicly evidenced
- `PARTIAL` — capability exists but scope/details incomplete
- `UNKNOWN` — public evidence insufficient
- ASK-AI status reflects current accepted architecture/repo knowledge and may change after post-I-002 production benchmark.

| Capability | Kapa 2026 | ASK-AI current | Initial implication |
|---|---|---|---|
| Multi-source ingestion | STRONG | PARTIAL | TABLE STAKES gap |
| Automatic source freshness | STRONG | PARTIAL | TABLE STAKES / I-003 |
| Source/product version awareness | PARTIAL | PARTIAL | deeper comparison needed |
| Hybrid sparse+dense retrieval | STRONG | STRONG baseline | parity area, not differentiator |
| Reranking | STRONG | STRONG baseline | parity area |
| Multi-step / agentic retrieval | STRONG public positioning | NOT YET as generalized policy | I-004 strategic gap |
| Query decomposition | PROVEN | partial/current task understanding differs | I-004 experiment |
| Context pruning | PROVEN | not equivalent | evaluate, do not copy blindly |
| Image knowledge ingestion | preview/research proven | gap/unknown | I-003 experiment candidate |
| Retrieval API | STRONG | current APIs exist but not equivalent productized retrieval surface | productization gap |
| Hosted/public MCP | STRONG | future direction | I-005 competitive priority |
| Prebuilt answer agents | STRONG | Widget/answer engine exists | compare surfaces |
| Conversation analytics | STRONG | PARTIAL | productization gap |
| Coverage-gap analytics | STRONG | different primitives exist | investigate parity/differentiation |
| Per-request evidence plan | UNKNOWN | STRONG accepted primitive | possible differentiation |
| Per-request explicit evidence coverage truth | UNKNOWN | STRONG accepted primitive | possible differentiation |
| Claim/evidence validation | UNKNOWN | STRONG accepted primitive | possible differentiation |
| Source-item pipeline inventory | UNKNOWN | identified gap #30 | possible differentiation after implementation |
| Connector-native structured commercial truth | UNKNOWN | identified gap #28 | investigate Kapa data model |
| Governed domain relation graph | UNKNOWN | research only | no competitive conclusion yet |
| Self-hosted deployment | UNKNOWN in this phase | strategic ASK-AI characteristic | high-priority research |
| Persistent agent memory | UNKNOWN / not established | future I-005 | separate from retrieval context |

---

## 11. Table Stakes / Strategic Parity / Differentiation / Non-goals — Phase 1

### TABLE STAKES

Capabilities where Kapa demonstrates that a serious technical-knowledge platform is expected to be strong:

- broad source ingestion;
- reliable automatic synchronization/freshness;
- high-quality parsing/chunking/indexing;
- hybrid retrieval + reranking;
- citations/source traceability;
- production evaluation discipline;
- conversation analytics;
- uncertainty/knowledge-gap analysis;
- API-based retrieval access;
- agent/MCP integration.

ASK-AI should not market ordinary hybrid RAG or citations as strategic differentiation.

### STRATEGIC PARITY

Capabilities ASK-AI likely needs, but need not copy Kapa's implementation:

- multi-step/adaptive retrieval;
- query decomposition where beneficial;
- context optimization/pruning;
- image/diagram/table knowledge representation;
- retrieval as an agent tool;
- production quality analytics;
- source/version freshness semantics.

### POSSIBLE DIFFERENTIATION — NOT YET PROVEN

Current hypotheses:

1. **EvidencePlan-driven retrieval** — explicit declaration of required evidence roles before retrieval/composition.
2. **CoverageReport runtime truth** — explicit evidence sufficiency rather than only post-hoc uncertain-answer analytics.
3. **Claim–evidence validation** — post-generation claim/citation validation with stable evidence identity.
4. **Governed structured/native knowledge authority** — connector-native truth > explicit authoritative relation > inferred relation.
5. **Source-item pipeline observability** — upstream/discovery/ledger/index/eligibility truth visible to operators.
6. **Self-hosted / customer-controlled deployment** — only if Kapa research confirms a meaningful deployment/control gap.
7. **Retrieval policy controlled by evidence need** — missing EvidencePlan slots drive bounded corrective retrieval rather than generic iterative search.

Every item above requires proof that Kapa does not already provide an equivalent capability internally/product-wise.

### NON-GOALS

Do not copy features merely because Kapa has them.

Reject roadmap-by-checklist behavior such as:

```text
Kapa has X
→ ASK-AI must build X
```

Adoption must be justified by ASK-AI target users, real failure evidence, benchmark lift, product strategy and operating cost.

---

## 12. Architecture implications for R-001

R-002 Phase 1 strengthens several R-001 conclusions.

### 12.1 Single universal RAG path is not the strategic target

Kapa itself publicly operates both single-pass and agentic retrieval forms.

This supports:

```text
low-cost path
+
adaptive advanced path
```

rather than forcing every question through the most sophisticated retrieval mechanism.

### 12.2 Retrieval must optimize generator utility

Context pruning shows that `retrieved` does not mean `should enter generator context`.

R-001 should explicitly add:

```text
Context Utility / Pruning
```

as a candidate capability between retrieval/rerank and Evidence Composition/Generation.

For ASK-AI this must be reconciled with INC-5 Evidence Selection and CoverageReport so pruning cannot silently remove required evidence.

### 12.3 Agentic retrieval should remain bounded and inspectable

Kapa demonstrates commercial demand for agentic retrieval, but public material does not establish a reason for ASK-AI to adopt an unrestricted agent loop.

ASK-AI's preferred research direction remains:

```text
EvidencePlan
→ Retrieval Policy
→ retrieve
→ Evidence Composition
→ CoverageReport
→ if incomplete: bounded corrective retrieval
```

### 12.4 Ingestion innovation is as important as retrieval innovation

Kapa's image work and automatic sync investment reinforce I-003's strategic importance.

A frontier retrieval layer cannot compensate for missing, stale or badly represented source truth.

---

## 13. Roadmap implications — Phase 1

Current recommended sequence remains:

```text
I-002 — Intelligent Answer Engine
        ↓
I-003 — Knowledge Intelligence & Operations
        ↓
I-004 — Adaptive Retrieval Intelligence
        ↓
I-005 — Agent Context Platform
        ↓
I-006 — Platform / Enterprise
```

R-002 changes the urgency/definition of several horizons:

### I-003

Should explicitly evaluate:

- ingestion quality as product capability;
- automatic freshness and source lifecycle;
- multimodal/image-derived knowledge;
- product/version scoping;
- source-item observability;
- structured/native truth.

### I-004

Should explicitly evaluate:

- multi-step retrieval;
- query decomposition;
- adaptive route selection;
- context pruning/utility;
- bounded corrective retrieval;
- quality/latency/cost Pareto.

### I-005

Should be broadened from "memory" into **Agent Context Platform**:

- retrieval tool for agents;
- MCP / retrieval API;
- product semantics for tool planning;
- persistent context/memory as a separate capability.

### I-006

Must be informed by deeper Kapa enterprise/deployment research before scope is frozen.

---

## 14. Critical unknowns for R-002 Phase 2

The following questions are high priority because they determine whether current ASK-AI differentiation hypotheses are real.

### Knowledge architecture

1. Does Kapa maintain first-class structured entities/relationships or primarily enriched chunks/metadata?
2. How does Kapa model product/version/source identity?
3. Does it support connector-native structured records distinct from text chunks?
4. What are delete/retirement/reconciliation semantics?
5. Is there item-level source inventory/observability?

### Retrieval control

6. What exactly constitutes Kapa's agentic retrieval loop?
7. What are its stop conditions and budgets?
8. Does it route between retrievers/substrates or mainly iterate hybrid search?
9. Does it represent evidence requirements/sufficiency explicitly?
10. How does context pruning interact with multi-part evidence needs?

### Answer correctness

11. How are uncertainty and refusal decided at runtime?
12. Is there claim-level citation/evidence validation?
13. How are multi-source conflicting facts resolved?
14. How are current vs historical facts handled?
15. Does Kapa distinguish source authority classes?

### Agent platform

16. What exactly does Retrieval API return: chunks, synthesized answer, metadata, scores, provenance?
17. What tools does hosted MCP expose?
18. Can customers constrain sources/versions/permissions per query?
19. Does Kapa provide persistent agent/session memory or only retrieval context?
20. How mature are agent SDK/action patterns beyond retrieval?

### Enterprise

21. Self-host/on-prem/VPC options?
22. RBAC / SSO / SCIM?
23. ACL-aware retrieval?
24. audit logs / retention / residency?
25. tenant and source isolation?

### Product economics

26. pricing model and major scaling dimensions;
27. ingestion/indexing cost model;
28. query/retrieval limits;
29. operational ownership split between Kapa and customer;
30. switching/export portability.

---

## 15. Research plan

### Phase 1 — Public architecture/product evidence

**Status: COMPLETE for initial pass**

Sources reviewed include current Kapa documentation, product pages and 2026 applied-research posts covering:

- product positioning;
- ingestion/retrieval architecture;
- Agent Context;
- MCP;
- context pruning;
- image indexing;
- RAG evaluation;
- knowledge-base search in agents;
- analytics/coverage gaps;
- automatic source synchronization;
- security overview.

### Phase 2 — Deep product/docs/API investigation

**Status: NEXT**

Investigate the 30 critical unknowns above using current official Kapa documentation and product surfaces.

Priority order:

```text
Retrieval API / MCP contract
→ source/version/lifecycle model
→ analytics/admin observability
→ agentic retrieval semantics
→ enterprise/deployment/security
→ pricing/economics
```

### Phase 3 — ASK-AI direct comparison

After Phase 2 and post-I-002 production Benchmark:

```text
Kapa capability
vs
ASK-AI accepted capability
vs
ASK-AI observed production failure
```

Classify each capability:

```text
TABLE STAKES
STRATEGIC PARITY
DIFFERENTIATION
NON-GOAL
UNKNOWN
```

### Phase 4 — Roadmap reconciliation

Feed R-002 into:

```text
R-001C — ASK-AI Capability Gap & Architecture Decision Framework
```

Then use R-001 + R-002 + post-I-002 Benchmark to freeze I-003/I-004 architecture direction.

---

## 16. Current decision state

```text
Kapa as direct benchmark = CONFIRMED
Kapa as simple chatbot benchmark = OUTDATED
Agent Context as competitive category = CONFIRMED
Broad ingestion/freshness = TABLE STAKES
Hybrid retrieval/reranking = TABLE STAKES
Agentic/adaptive retrieval = STRATEGIC PARITY TARGET
Context pruning = EXPERIMENT INPUT
Image-derived knowledge = I-003 EXPERIMENT INPUT
Conversation/coverage analytics = STRATEGIC PARITY AREA
EvidencePlan differentiation = HYPOTHESIS
CoverageReport differentiation = HYPOTHESIS
Claim-validation differentiation = HYPOTHESIS
Source-item observability differentiation = HYPOTHESIS
Self-host/control differentiation = UNKNOWN PENDING RESEARCH
Target ASK-AI architecture freeze = NOT READY
```

R-002 is not complete. Phase 1 establishes the competitive architecture baseline; Phase 2 must resolve the highest-value unknowns before R-001C and roadmap freeze.
