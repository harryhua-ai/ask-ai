# KB-OPS-V163-002 — Design Recovery Review

**Status:** REVIEW REQUIRED — NOT YET AUTHORIZED FOR IMPLEMENTATION  
**Iteration:** v1.6.3  
**Supersedes for planning purposes:** KB-OPS-V163-001 once approved  
**Repository baseline reviewed:** current `main` frontend implementation after v1.6.3 deployment  
**Recovered accepted visual references:**

- `references/data-source-operations-original.webp`
- `references/technical-insights-answer-gaps-original.webp`

## 1. Purpose

This review reconstructs the intended Admin Knowledge Operations product from the recovered accepted design references, then reconciles it with the current repository truth.

The goal is explicitly **not** to redraw the product around the current implementation.

Every recovered design element is classified as:

- **KEEP** — still valid and should remain part of the design baseline.
- **ADAPT** — product intent remains valid, but the representation must be updated to current authoritative data/architecture.
- **DEFER** — useful but not required for the current v1.6.3 convergence scope.
- **INVALIDATED BY NEW TRUTH** — should not be implemented because later authoritative product/engineering truth made it incorrect.
- **NEW REQUIREMENT** — the recovered design reveals a product capability not currently modeled by accepted backend/frontend contracts; it must receive its own contract before implementation.

## 2. Current repository truth that constrains the recovered design

The current Admin frontend is a shared application, not a standalone Knowledge Operations product area.

Current routes include:

- `/` business overview
- `/data-sources`
- `/data-sources/:sourceId`
- `/conversations`
- `/analytics`
- `/system`
- configuration/admin routes

Current Sidebar groups pages under **运营** and **配置**.

Current source workspace truth already exposes:

- source identity/config
- sync status/history
- five-dimensional source health
- authoritative document ledger
- document lifecycle and serving truth
- document current version
- generation truth and generation failure evidence
- source-level generation lists

Current Technical Insights truth already exposes:

- technical KPI and health
- stage percentiles and trends
- anomaly/failure kinds
- degradation evidence
- sync incidents
- generation events
- coverage gaps and gap trends
- conversation drill-down

These capabilities are **inputs** to the recovered design. They do not authorize the UI to replace the recovered operator workflow with raw backend telemetry.

## 3. Recovered product model

The recovered design is organized around an operator loop:

`DETECT → UNDERSTAND → ACT → VERIFY → OBSERVE → RESOLVE`

This is materially different from the current production emphasis:

`DISPLAY TRUTH → DISPLAY STATUS → DISPLAY LOGS`

The new baseline must preserve the correctness of the current truth plane while restoring the operator workflow from the accepted visual design.

---

# 4. Data Source Operations reference

Reference:

`data-source-operations-original.webp`

## 4.1 Data Source list

Recovered intent:

- source name/type
- operator-facing status
- knowledge quantity
- **needs-attention count as a first-class column**
- recent sync
- compact actions
- search/filtering
- add source

### Classification

**KEEP**

The primary list must answer:

1. Which sources need attention?
2. How many knowledge items are affected?
3. What is the operator-facing state?
4. When was the source last synchronized?

### Adaptation to current truth

**ADAPT**

Current backend exposes multiple health dimensions and historical reliability. These must support the operator-facing status but must not replace it with raw synchronization metrics.

No frontend-only recomputation of authoritative backend health is allowed.

## 4.2 Source detail as a knowledge workspace

Recovered hierarchy:

1. source identity
2. operator state
3. latest sync summary
4. total knowledge + needs-attention count
5. prominent attention banner
6. knowledge-content table
7. local remediation workflow

### Classification

**KEEP**

This becomes the primary Source Detail design hierarchy.

Current production ordering — configuration → five health cards → ledger → generations → sync cards — is not the target hierarchy.

### Current truth adaptation

**ADAPT**

The current lifecycle/version/generation/health data must be used as evidence behind this workflow.

Raw evidence remains available but is secondary.

## 4.3 Knowledge-content issue expansion

Recovered interaction:

- expand an affected knowledge row
- explain the problem in operator language
- show source-content state
- show current valid version
- show how much of the item is currently serving
- show previous automatic recovery attempts
- allow a remediation action
- after action, show verification result

### Classification

**KEEP PRODUCT INTENT**
+
**NEW REQUIREMENT FOR REMEDIATION CONTRACT**

Current repository provides explanation/evidence and read-only truth, but the full row-level remediation/verification workflow is not yet an accepted product contract.

Implementation must not invent mutation semantics.

A separate remediation action contract must define:
- which issue classes are safely reprocessable;
- what operation is executed;
- idempotency/concurrency;
- post-action verification;
- failure state;
- RBAC.

## 4.4 Sync status and recent activity

Recovered interaction:

- last successful sync
- next scheduled sync
- most recent result
- synchronization reliability
- chronological recent-activity timeline
- exceptional events emphasized over routine normal runs

### Classification

**KEEP**

### Current truth adaptation

**ADAPT**

The current `sync_runs`, sync status, generation events, and source health provide stronger evidence than existed when the design was created.

Routine no-change runs should be compressed.
Technical counters remain expandable evidence.

## 4.5 Edit Data Source drawer

Recovered interaction:

- edit source without leaving the operational context
- name/connection/type/auto-sync/cadence
- save/cancel

### Classification

**KEEP INTERACTION PATTERN**

### Scope note

The current `DataSources.tsx` editor is broad and supports GitHub/filesystem/WooCommerce/web crawl/discovery policy.

v1.6.3 should not be forced to rewrite all source editing internals merely to satisfy visual convergence.

The accepted behavior should be:

- source workspace retains context;
- edit opens a drawer/panel or equivalent context-preserving interaction;
- full editor capability remains authoritative.

## 4.6 Knowledge Settings drawer

Recovered concepts:

- temporal role, e.g. CURRENT → HISTORICAL
- freshness requirement
- policy-level semantics distinct from sync cadence

### Classification

**NEW REQUIREMENT**

The current frontend/source configuration does not establish this policy model as authoritative product truth.

`sync_interval` must NOT be treated as equivalent to a freshness requirement.

Before implementation, Product/Engineering must define:
- temporal-role truth model;
- freshness policy truth;
- persistence;
- lifecycle/serving implications;
- authorization.

## 4.7 High-risk knowledge-setting change preview

Recovered interaction:

- preview before high-impact mutation
- old → new policy
- estimated affected knowledge counts
- explicit statement that persistent knowledge is not deleted
- confirmation before mutation

### Classification

**KEEP GOVERNANCE PRINCIPLE**
+
**NEW REQUIREMENT FOR PREVIEW API/SEMANTICS**

No UI may fabricate affected counts.

A mutation-preview contract is required before this interaction can be implemented.

---

# 5. Technical Insights / Answer Gaps reference

Reference:

`technical-insights-answer-gaps-original.webp`

## 5.1 Technical Insights domain structure

Recovered design explicitly places:

- 技术性能
- 回答缺口

as tabs under the shared **技术洞察** product area.

### Classification

**KEEP**

This recovered accepted reference materially changes the provisional v1.6.3 assumption that these two areas must be split into separate top-level domains.

Issue #57 must be revised before implementation.

The shared parent mental model is:

> Diagnose why real user questions are not being answered well.

Technical Performance answers system/runtime causes.
Answer Gaps answers knowledge/content causes.

## 5.2 Answer Gap issue queue

Recovered table fields:

- question/topic
- related-question count
- impacted-answer count
- reason taxonomy
- workflow status
- recency

### Classification

**KEEP**

Current production's representative-question/type/count/status table is incomplete relative to the accepted design.

## 5.3 Reason taxonomy

Recovered examples include:

- 知识缺失
- 服务知识不完整
- 内容过期
- 检索异常
- 生成异常
- 引用异常
- 内容冲突

### Classification

**KEEP AS PRODUCT TAXONOMY DIRECTION**
+
**ADAPT TO AUTHORITATIVE CURRENT EVIDENCE**

The UI may only assign a reason when current authoritative data supports it.

No frontend heuristic may silently classify an issue.

If a unified backend classification is absent, the UI must present `未分类` / evidence-unavailable rather than infer.

## 5.4 Issue workflow state

Recovered states include:

- 需要处理
- 观察中
- 已解决

### Classification

**KEEP PRODUCT INTENT**
+
**NEW REQUIREMENT FOR STATE AUTHORITY**

Current gap storage primarily exposes open/resolved semantics.

The intermediate OBSERVING state and transition rules require a dedicated product/data contract.

## 5.5 Diagnosis side panel

Recovered panel contains:

- issue title/severity
- related-question count
- impacted-answer count
- recency
- diagnosis conclusion
- representative/typical questions
- related data source
- export conversations
- remediation completion → begin observation
- diagnosis details

### Classification

**KEEP**

This is a central part of the accepted workflow and is not equivalent to the current simple `/conversations?q=...` drill-down.

### Data-source drill-down

**KEEP**

Current source workspace route can satisfy the related-source navigation.

### Conversation evidence

**KEEP / ADAPT**

Current conversation search deep-link is valid evidence access, but the recovered design expects a diagnosis context panel rather than forcing all operator understanding into a separate page.

### Export related conversations

**NEW REQUIREMENT unless an authoritative export surface already exists**

Do not invent CSV export client-side without a defined evidence/privacy contract.

## 5.6 “Content repaired, begin observation”

Recovered behavior:

- operator confirms content has been corrected and synchronized;
- system begins observation;
- future evidence determines whether the issue is actually resolved.

### Classification

**KEEP PRODUCT INTENT**
+
**NEW REQUIREMENT**

This requires formal observation semantics and cannot be represented by an immediate `resolved` toggle.

---

# 6. Reconstructed Knowledge Issue model

The recovered references repeatedly assume an operator-facing entity that is broader than any single existing backend table.

Conceptually:

`Knowledge Issue`

may be supported by evidence from:

- document lifecycle
- serving incompleteness
- sync/reconciliation
- generation failures
- stale knowledge
- coverage gaps
- retrieval anomalies
- generation anomalies
- citation anomalies
- content conflicts

### Classification

**NEW PRODUCT REQUIREMENT — NOT YET AN IMPLEMENTATION CONTRACT**

The design strongly implies this projection, but the repository must not invent a new persistence model merely because the UI suggests one.

Role A must decide whether v1.6.3:

A. builds a read-only issue projection from existing truth, or  
B. introduces a persisted Knowledge Issue model.

This is a material architecture/product lifecycle decision and must be frozen before B implementation.

---

# 7. Visual interaction grammar recovered from the designs

The references establish more than styling.

## KEEP

- dense operational tables for scan-first lists;
- expanded row for local issue diagnosis/remediation;
- right-side drawer for context-preserving configuration/diagnosis;
- modal only for high-risk confirmation;
- strong selected navigation state;
- primary blue actions;
- green healthy/resolved;
- red action-required/destructive;
- amber intermediate/stale/pending;
- exception-first visual priority;
- normal telemetry compact;
- technical evidence secondary.

These are part of Design Conformance, not optional polish.

---

# 8. Issue impact (#52–#60)

## #52 — Knowledge Operations IA

**AMEND BEFORE IMPLEMENTATION.**

Do not mechanically impose a new Overview/Sources/Documents/Issues/Settings top-level navigation if that conflicts with the recovered shared Admin IA.

The recovered references preserve the existing broader Admin structure and embed Knowledge Operations within it.

## #53 — Data Sources list

**KEEP, strengthen with recovered reference.**

The needs-attention count and operator-state model become explicit acceptance requirements.

## #54 — Source Detail

**KEEP, materially expand.**

Add attention-first hierarchy and recovered local issue-remediation interaction.

Do not reduce the task to terminology cleanup.

## #55 — Document Inspector

**KEEP, reposition.**

Truth inspection remains valuable, but it is evidence supporting diagnosis/remediation rather than the entire source-workspace product.

## #56 — Source History

**KEEP.**

Recovered Activity Timeline becomes the primary reference.

## #57 — Technical Insights IA

**CURRENT ISSUE DIRECTION IS INVALIDATED BY RECOVERED ACCEPTED DESIGN.**

Do not implement the split until the issue is rewritten.

Technical Performance + Answer Gaps remain tabs under Technical Insights unless User/Role A explicitly changes the recovered design.

## #58 — Technical Insights UX

**AMEND.**

Progressive disclosure remains valid, but the stronger requirement is a diagnosis workflow and issue side panel.

## #59 — Knowledge Gaps

**EXPAND.**

The accepted scope includes issue queue semantics, cause, impact, recency, diagnosis, evidence, and observation workflow — subject to new backend authority contracts.

## #60 — Visual hierarchy

**KEEP and bind directly to both recovered images.**

---

# 9. Hard stop before implementation

Until this recovery review is approved:

**#52–#60 = DESIGN HOLD**

B must not begin UI implementation from KB-OPS-V163-001 alone.

Required next decisions:

1. Approve/reject this recovered interpretation.
2. Decide Knowledge Issue architecture:
   - projection vs persisted entity.
3. Decide whether remediation/observation is in v1.6.3 or split into a later iteration.
4. Revise #52, #54, #57, #58, #59 accordingly.
5. Freeze the approved document as `KB-OPS-V163-002`.
6. Then authorize B execution with the recovered images as hard visual references.

