# ASK-AI Product Roadmap

> Authoritative planning view for the next development cycle. Engineering task contracts and production gates remain separately frozen per task.
>
> Updated: 2026-09-06

## Product Goal

ASK-AI should provide product/support answers that are **correct, grounded, fast enough to feel conversational, operationally trustworthy, and safe to run in production**.

The current product has reached a stable v1.1.x production baseline. The next major cycle should improve experience and operational maturity without weakening the correctness, evidence, release, or production-safety contracts already accepted.

---

## Current Product State

### Production baseline

- **Production release:** `v1.1.2`
- **Accepted source SHA:** `cdbcad38fc3512561e12c71ff6eda067d06257b5`
- **Comparison Evidence Correctness:** production accepted and complete.
- **Knowledge stale-ledger production repair:** complete; `knowledge-support-cases` returned to HEALTHY at `179 documents / 481 expected chunks / 481 actual chunks / missing=0 / mismatch=0 / orphan=0`.
- **Issue #19:** closed as completed after v1.1.2 production acceptance.
- **Issue #25:** open, P1/Backlog, implementation NOT AUTHORIZED; scope remains Filesystem Source Retirement pending Planner Discovery/Contract.

### Accepted contracts that must not regress

- exact-product evidence boundaries and sibling-product isolation;
- comparison evidence contract and fail-closed behavior;
- citation/evidence validation and truthful insufficiency responses;
- Configured vs Effective model-runtime semantics and explicit Apply;
- production release identity through immutable tag + `RELEASE.json`;
- controlled production mutation / rollback gates;
- knowledge consistency truth surfaces and reconciliation semantics.

---

## Current Frontier

# v1.2.0 — Reliability, Performance & Operations

**Lifecycle:** PLANNING / DISCOVERY

**Iteration objective:**

Move ASK-AI from a correct and production-capable V1 baseline to a system that is also measurably responsive, operationally truthful, and resilient to routine source/config lifecycle changes.

This is a major iteration, not a single feature. It is organized around three product outcomes:

1. **Fast answers** — materially improve TTFT and total answer latency while preserving grounding/correctness.
2. **Trustworthy operations** — Admin health/runtime surfaces must reflect current truth and production tooling must be difficult to misuse.
3. **Complete lifecycle semantics** — routine source deletion/config lifecycle operations must not require manual database intervention.

### v1.2.0 Exit Criteria

The iteration is ready for production release only when:

- representative answer benchmark has frozen baseline and post-change p50/p95 for TTFT and end-to-end latency;
- ordinary grounded product Q&A is materially faster than the current ~20–30s slow-path examples without correctness regression;
- current Knowledge Health is semantically separated from historical reliability/runtime fallback evidence;
- production migration tooling cannot silently prefer test-only DSNs;
- filesystem source-confirmed removal has a safe, auditable lifecycle contract and accepted implementation if Discovery proves it feasible for this release;
- Issue #5 exact-product grounding and v1.1.2 comparison correctness regression suites remain green;
- production acceptance proves release identity, runtime health, and representative real queries under the normal production topology.

---

## Active Initiatives

### I1 — Answer Performance / TTFT

**Issue:** #23 — Answer performance: reduce LLM generation TTFT and end-to-end response latency  
**Priority:** P0/P1 Candidate  
**Role in v1.2.0:** PRIMARY INITIATIVE

**Why now**

Correctness is now substantially stronger, but observed requests can still spend ~18s before the first visible token and ~30s end-to-end. This is a direct user-experience gap and a meaningful competitive weakness.

**Discovery first**

Freeze a production-representative benchmark and measure at least:

- TTFT p50/p95;
- end-to-end p50/p95;
- provider/model actually selected;
- intent/rewrite latency;
- retrieval/rerank/pruning latency;
- prompt/context size;
- generation duration and output size;
- warm/cold and provider/network effects;
- simple fact / how-to / troubleshooting / comparison / no-evidence query classes.

**Contract direction**

Optimize only after root contributors are measured. Provider/model/routing, preprocessing parallelism, conditional bypass, context caps, prompt compression, connection reuse, and streaming behavior remain implementation options rather than frozen HOW.

**Hard boundary**

No speed gain may come from weakening grounding, citations, product isolation, comparison evidence, or truthful abstention.

**Next Gate:** `I1-DISCOVERY → PERFORMANCE CONTRACT`

---

### I2 — Current Knowledge Health Truth

**Issue:** #21 — Admin: current Knowledge Health can show Severe after data has recovered  
**Priority:** P0/P1  
**Role in v1.2.0:** HIGH-PRIORITY CORRECTNESS / ADMIN TRUST

**Goal**

Make the top-level health state answer the operator's immediate question: **is knowledge currently complete, fresh, and usable?**

Historical run reliability and successful GPU→CPU fallback remain visible evidence but must not masquerade as current knowledge failure.

**Discovery must determine**

- exact backend health derivation;
- frontend severity derivation;
- which historical/runtime fields dominate current state;
- convergence semantics after recovery;
- interaction with duplicate-content REPORT facts and reconciliation state.

**Next Gate:** `I2-DISCOVERY → HEALTH-SEMANTICS CONTRACT`

---

### I3 — Production Database Resolution Safety

**Issue:** #20 — Ops: remove production TEST_DATABASE_URL override that can misroute migration scripts  
**Priority:** P1  
**Role in v1.2.0:** EARLY SAFETY HARDENING

**Goal**

Remove ambiguity between production and test database resolution so an operator or automation cannot accidentally point migration tooling at a test/dev DSN in production mode.

**Expected scope**

- establish authoritative production DSN resolution;
- prove whether production needs `TEST_DATABASE_URL`;
- add fail-closed production-mode guard semantics;
- execute any production environment cleanup through a separate config-change gate.

**Next Gate:** `I3-DISCOVERY / CONTRACT → IMPLEMENTATION`

---

### I4 — Filesystem Source Retirement

**Issue:** #25 — Filesystem sources do not retire ledger entries when source files disappear  
**Priority:** P1 / Backlog / Requires Contract  
**Role in v1.2.0:** STRUCTURAL DATA-LIFECYCLE INITIATIVE

**Current truth**

The one-time stale-ledger incident is repaired and closed. #25 is future prevention, not unfinished production repair.

**Frozen scope for this iteration**

Filesystem sources only.

Do not silently expand this implementation into GitHub, Web Crawl, WooCommerce, or a generic cross-connector lifecycle redesign.

**Required semantics before implementation**

- authoritative discovery completeness must be explicit;
- temporary failure/partial discovery must preserve existing data;
- retirement requires source-confirmed removal, not vector absence;
- retirement must be idempotent and auditable;
- ledger/vector/query visibility semantics must be explicit;
- include/exclude/file-type policy changes must not be confused with confirmed deletion.

**Next Gate:** `I4-DISCOVERY → RETIREMENT CONTRACT`

---

## Queued Initiatives

These remain valid P1 work, but they are not the core v1.2.0 frontier unless capacity remains after the four initiatives above or Discovery changes the ordering.

### Q1 — Provider credential deletion lifecycle

**Issue:** #4 — Admin: LLM provider credential delete button does not work  
**Priority:** P1

UI action is currently a dead-end while the backend DELETE endpoint exists. Before implementation, explicitly freeze behavior when a provider is still referenced by routing chains.

### Q2 — Read-only system/runtime observability

**Issue:** #7 — Admin: add read-only system and hardware runtime observability  
**Priority:** P1

Useful operator capability, but not required to begin the answer-performance benchmark because #23 owns request-path latency telemetry. Keep this read-only; no restart/kill/shell controls.

### Q3 — Runtime-managed Widget allowed origins

**Issue:** #6 — Admin: manage Widget allowed origins safely without redeploy  
**Priority:** P1

Requires an authoritative runtime policy contract so site authorization and browser CORS cannot become divergent truths.

---

## Recommended Execution Plan

### Phase 0 — Iteration Discovery & Baselines

Run Planner-led Discovery in parallel where safe:

- **D1:** #23 production latency benchmark and bottleneck decomposition;
- **D2:** #21 Knowledge Health derivation / UI truth trace;
- **D3:** #20 production/test DSN resolution audit;
- **D4:** #25 filesystem retirement lifecycle discovery.

**Output:** four independent Frozen Task Contracts. No broad v1.2 implementation starts before each initiative is individually ready.

### Phase 1 — Safety & Truth First

Recommended implementation order:

1. **#20 production DB resolution safety** — small blast radius, high release-safety value.
2. **#21 Knowledge Health truth** — operator-facing correctness and trust.

Each gets independent candidate review and production gate where applicable.

### Phase 2 — Primary Performance Initiative

Execute #23 using the frozen benchmark and SLO contract.

Expected engineering loop:

`baseline → hypothesis → one optimization class → benchmark → quality regression → next hypothesis`

Do not combine several latency optimizations into one unmeasurable patch.

### Phase 3 — Filesystem Lifecycle Correctness

Implement #25 only after the destructive-boundary contract is accepted.

This phase requires stronger acceptance than ordinary feature work because false retirement is data loss. Production activation must prove both:

- confirmed deletion retires correctly;
- incomplete/failed discovery never causes destructive retirement.

### Phase 4 — Consolidation / Optional P1 Admin Work

If the core v1.2 exit criteria are already satisfied and capacity remains, select from #4, #7, #6 in that order of defect/operational value before optional convenience work.

Do not automatically pull all queued P1 work into v1.2.0.

### Phase 5 — Release Candidate / Production Acceptance

Before v1.2.0 release:

- full regression + Admin/widget builds;
- Issue #5 and comparison-correctness dedicated regression;
- frozen latency benchmark rerun with p50/p95 comparison to baseline;
- production-like source lifecycle tests;
- immutable tag/image identity gate;
- controlled production activation;
- real representative asks and Admin health acceptance;
- rollback proof.

---

## Dependencies / Ordering

```text
v1.1.2 production baseline
        |
        +--> #20 DB resolution safety --------+
        |                                      |
        +--> #21 Knowledge Health truth -------+--> v1.2 RC
        |                                      |
        +--> #23 latency Discovery -> optimize +
        |                                      |
        +--> #25 retirement Discovery -> impl -+

Queued after core exits / capacity:
#4 -> #7 -> #6
```

No direct implementation dependency exists between #23 and #25; they can use separate Executor worktrees after their contracts are frozen. Integration/release still requires one accepted mainline candidate.

---

## Completed / Accepted

Recent durable milestones:

- **v1.0.0** — CamThink V1 production release.
- **v1.1.0** — shared discovery/runtime/GPU-capacity production release.
- **v1.1.1** — explicit Model Runtime Apply hotfix; production accepted.
- **v1.1.2** — Comparison Evidence Correctness hotfix; production accepted.
- **T-COMPARISON-EVIDENCE-CORRECTNESS** — COMPLETE.
- **KNOWLEDGE-STALE-LEDGER-PROD-REPAIR** — COMPLETE / HEALTHY.
- **Issue #19** — CLOSED / COMPLETED.

---

## Open Product / Architecture Questions

The next Discovery cycle should answer, not assume:

1. What production TTFT and total-latency SLO is realistic across representative query classes?
2. Which portion of slow TTFT is provider/model latency vs ASK-AI's own serial preprocessing/context/generation contract?
3. What is the authoritative semantic formula for **current Knowledge Health** versus historical reliability?
4. What constitutes an **authoritative complete filesystem discovery** sufficient to confirm removal?
5. Should cross-connector retirement become a later umbrella initiative after filesystem semantics are proven, or remain connector-specific?

---

## Overall Progress

```text
V1 Product / Correctness Baseline       [##########] 100%
v1.1 Runtime / Release Hardening        [##########] 100%
v1.1.2 Comparison Correctness           [##########] 100%
Stale-Ledger Production Repair          [##########] 100%

v1.2 Discovery                          [#---------]  10%  CURRENT
v1.2 Safety & Health Truth              [----------]   0%
v1.2 Answer Performance                 [----------]   0%
v1.2 Filesystem Retirement              [----------]   0%
v1.2 RC / Production Acceptance         [----------]   0%
```

The **current frontier is v1.2 Discovery**, not implementation of any single open issue yet.
