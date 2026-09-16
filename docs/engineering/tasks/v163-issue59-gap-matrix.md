# Issue #59 GAP_MATRIX — Knowledge Gaps: trend/distribution/empty-state coherence

- Executor: Trace Executor (GAP_MATRIX phase, contract `role-a-execution-contract:v1`, BATCH 2, GAP_ONLY_IMPLEMENTATION, IMPLEMENTATION_AUTHORIZED=YES_AFTER_GAP_MATRIX)
- BASELINE: `b338c3c7eeafec9f57176aa82dd743b9f195153d` (origin/main, v1.6.3-r4 production tree), BASELINE_POLICY: exact
- CANDIDATE_BRANCH: `agent/59/3475cf84` (lane-1, investigation mode, zero code changes)
- CANDIDATE_SHA: docs-only evidence commit on lane branch (see PRESERVE record)
- CHANGE_BUDGET (proposed, NOT implemented): see G1 below — 1 backend projection file + 1 API type file + 1 queue empty-state file + 1 focused test file. Zero new endpoints, zero new persistence, zero trend/distribution re-addition.
- LIMITATIONS: reference PNG depicts no empty queue state, so the four-state visual grammar has no frozen pixel reference — G1 UI copy/tones follow §7 grammar and require Role A UI-evidence review (§11) at implementation. Distinguishing "clustering never ran" from "clustered, zero gaps found" would need refresh-provenance truth that does not exist; G1 deliberately does not invent it.
- PRODUCTION_ACCESS: none
- STATUS: GAPS_FOUND (2 PARTIAL rows; 10 SATISFIED; 1 SUPERSEDED; 1 PENDING_IMPLEMENTATION; 0 MISSING)

## Authoritative inputs consumed

1. Issue body acceptance (7 checkboxes) + KB-OPS-V163-002 Frozen Amendment section (in body).
2. All 4 comments; final `role-a-execution-contract:v1` governs (REQUIRED_FIRST=matrix; only PARTIAL/MISSING authorize edits; issue body/comments not treated as data sources).
3. Recovery references (branch `docs/v163-design-baseline-20260912`, @5593d6be):
   - `docs/product/design/admin-knowledge-ops/DESIGN_RECOVERY_REVIEW_V002.md` (= KB-OPS-V163-002 FROZEN; §5.1 domain structure, §5.2 queue, §5.3 reason taxonomy, §5.4 workflow state, §5.5 diagnosis side panel, §7 visual grammar, §10 frozen v1.6.3 scope, §11 conformance gate)
   - `docs/product/design/admin-knowledge-ops/references/technical-insights-answer-gaps-original.png` (inspected read-only: Answer Gaps tab = 7-column queue + 5-tab diagnosis side panel only; NO trend chart, NO distribution card)
4. Current tree truth (verified byte-identical between baseline and working checkout for all gap-surface files): admin/src/pages/Analytics.tsx, admin/src/pages/analytics/{AnswerGapsTab,GapPanel,PanelStats,PanelHistory,GapTopicCell,CauseBadge,StatusBadge,GapCauseFilter,GapStatusFilter,DiagnosisConclusion,GapObservationSection,GapExportCard,relTime}.tsx/.ts, admin/src/lib/gapCause.ts, admin/src/lib/api/techInsight.ts, admin/src/hooks/useAnalytics.ts, backend/api/admin/tech_answer_gaps.py, backend/api/admin/analytics.py, backend/services/{gap_status,gap_taxonomy,gap_observation}.py.

## Context: the r4 tree already contains the B2 Answer Gaps convergence

Issue body's problem text (almost-empty unanswered trend + 「缺口类型分布: 暂无缺口数据，请先执行聚类刷新」 contradicting a populated Coverage Gaps table) describes the PRE-r4 surface. The shipped r4 tree replaced that surface per the recovered hard reference: Analytics.tsx:101-118 renders 技术性能/回答缺口 sibling tabs; the 回答缺口 tab is AnswerGapsTab (7-column queue + diagnosis side panel) only. The B2 execution ledger (`docs/engineering/tasks/v163-b2-technical-insights-execution.md` J11) records the trend/distribution removal as a JUSTIFIED DIFFERENCE against the reference. The matrix below judges the non-superseded acceptance against this tree, not against the pre-r4 complaint.

## current→target matrix

Status legend: SATISFIED / PARTIAL / MISSING / SUPERSEDED / DEPENDENCY / PENDING_IMPLEMENTATION.

### C1 — Trend, distribution, and gap-table states are semantically consistent — SUPERSEDED

- Current evidence: the trend chart (未回答率趋势) and 缺口类型分布 card no longer exist on the Answer Gaps surface; the tab = queue + side panel per the frozen hard reference (Analytics.tsx:117-118; AnswerGapsTab.tsx). `fetchGapTrends`/`fetchCoverageGaps` (admin/src/lib/api/techInsight.ts:97-114) have zero component consumers (grep-verified); `useAnalytics.ts` hooks (useCoverageGaps/useRefreshGaps/useResolveGap) are consumer-less legacy. Backend `GET /analytics/gap-trends` retained but unconsumed.
- Target ref: KB-OPS-V163-002 §5.2 + hard reference PNG (queue + side panel only); B2 ledger J11. Re-adding trend/distribution would implement a SUPERSEDED requirement and re-introduce the very contradiction this Issue reports (RCA: EMPTY/UNKNOWN/STALE/ZERO_STATE_CONFLATION). Surviving-surface consistency is carried by F1 (single projection GET /tech/answer-gaps feeds queue and side panel; single miss_type authority `classify_gap_miss_types` shared with /analytics/coverage-gaps).

### C2 — If clustering/classification is stale or unavailable, the UI explains this without implying there are no gaps — PARTIAL

- Current evidence (unavailable-classification half, SATISFIED): unknown/no cause → 未分类 badge (CauseBadge data-gap-type machine value; gapCause.ts:88-91) + diagnosis conclusion renders the unavailable form 「证据不可用:该缺口暂无权威原因分类,系统不做推断。」 (DiagnosisConclusion.tsx `data-conclusion-kind="unavailable"`; gapCause.ts:86,105-108); 诊断详情 distribution empty → 「无会话证据,分类不可用」 (GapPanel.tsx:274-285).
- Current evidence (stale/no-data-clustering half, MISSING): `GET /tech/answer-gaps` projects only `{items,total,page,size,miss_type_summary}` with `total` = filtered truth (backend/api/admin/tech_answer_gaps.py:204-215). No clustering-availability truth exists in any projection: no gap-cluster total ignoring filters, no clustering coverage horizon (MAX(period_end) is stored per cluster, analytics.py:65-66, but never projected to this surface). Therefore the UI cannot explain stale-derived data without manufacturing it — and currently explains nothing: empty queue shows one generic line (see C3).
- Target ref: Issue acceptance checkbox 2 (non-superseded); contract "Never manufacture zero from missing/unknown backend truth"; Frozen Amendment "Unsupported reason/state/action fields must render as unavailable/unclassified or be omitted; they must not be fabricated".

### C3 — Empty-data, stale-derived-data, and real-zero states are visually distinct — PARTIAL

- Current evidence: queue empty state is a single conflated message 「当前筛选条件下无答案缺口证据(可尝试扩大时间范围)」 (AnswerGapsTab.tsx:170-178). Facets: filtered-empty is weakly handled (filter phrasing + window hint only when `window !== "all"`; note default window is "7d", so an unfiltered page never reaches a pure true-zero render); true-zero, no-data (clustering absent) and stale-incomplete render identically — exactly the RCA verdict EMPTY/UNKNOWN/STALE/ZERO_STATE_CONFLATION (comment 3). All other surface empty states are honest but locally scoped: 无样例问句证据 (GapPanel.tsx:158-160,205-207), 无归属会话证据 (:231-233), 会话证据读取失败 (:227-230), 暂无流转记录…系统不做推断 (PanelHistory.tsx), 涉及用户 证据不可用 / 无归因证据…系统不做猜测 (PanelStats.tsx:76-83,130-141), recency null → 证据不可用 (relTime.ts:7-9).
- Target ref: Issue acceptance checkbox 3; contract four-state distinction; RCA comment 3 ("implementation must preserve server truth and avoid manufacturing 0 from missing data"); §7 grammar (amber intermediate/stale/pending, green healthy/resolved, red action-required).

### C4 — Representative questions and counts remain inspectable — SATISFIED

- Current evidence: queue columns 问题/主题 (GapTopicCell: backend-derived topic primary line via GET /tech/answer-gaps/{id}/topic, representative question + first sample secondary, honest fallback when topic not derivable), 相关提问 (question_clusters.question_count), 影响回答 (COUNT conversations.cluster_id), 最近发生 (MAX conversations.created_at; null → 证据不可用); sortable by questions/impacted/last_seen (AnswerGapsTab.tsx:144-166); side panel 问题描述/典型问题示例 + full 典型问题 tab (GapPanel.tsx:121-208), PanelStats counts + authoritative users aggregate with honest unavailable state.
- Target ref: KB-OPS-V163-002 §5.2 KEEP; §5.5 panel fields; Frozen Amendment queue expansion.

### C5 — Deferred resolve/refresh actions are not silently introduced unless separately authorized — SATISFIED

- Current evidence: no clustering-refresh or resolve control on the surface (legacy `POST /analytics/coverage-gaps/refresh` remains backend-only, analytics.py:227-228; frontend hooks useRefreshGaps/useResolveGap unmounted). The actions that DO exist are separately authorized and backend-authoritative, not invented: OBSERVING state machine (backend/services/gap_observation.py: 3 gates — operator confirmation, sync/reindex evidence, post-sync verification; 409 gates detail passed through verbatim, GapObservationSection.tsx:33-46), status vocabulary open|observing|resolved from backend/services/gap_status.py (IF-1), export per IF-5 contract (tech_export.py router mounted in tech.py:24-39; admin-only, 403 → permission message, privacy note; frontend triggers download only, never generates CSV). Mount points authorized by B2 contract + Wave 1 IF contracts + INT-E-01 (Independent Review option a), documented in file ownership headers.
- Target ref: Frozen Amendment ("does not invent OBSERVING, remediation, export, or new persistence semantics" — satisfied because none is frontend-invented; each has a backend authority contract); §10 "unless an already-authoritative operation already exists".

### C6 — Knowledge-gap presentation remains distinct from runtime/system diagnostics — SATISFIED

- Current evidence: 技术洞察 shell separates 技术性能 (TechPerfTab: KPI/stage percentiles/anomalies/incidents/generation events/source health = system/runtime causes) from 回答缺口 (AnswerGapsTab: knowledge/content causes); system diagnostics remain under /system (SystemInfo.tsx). Gap content never renders runtime telemetry and vice versa.
- Target ref: KB-OPS-V163-002 §5.1 ("Technical Performance answers system/runtime causes. Answer Gaps answers knowledge/content causes"); #57 resolution (shared parent, two tabs).

### C7 — Frozen design screenshots are required before implementation — SATISFIED

- Current evidence: recovered reference committed on the frozen baseline branch (`references/technical-insights-answer-gaps-original.png` + `.webp`, branch docs/v163-design-baseline-20260912); implementation-side evidence in tree: `docs/product/design/admin-knowledge-ops/acceptance/v163-design-acceptance-final-20260913/05-answer-gaps-queue.png`, `06-gap-selected-diagnosis.png`; B2 execution §0/§4: 12 real rendered states compared region-by-region vs ORIGINAL PNG, Visual DEFECT = 0, ledger J1-J12.
- Target ref: KB-OPS-V163-002 §11 conformance gate. Gate discharged for the shipped surface; any G1 delta requires new UI evidence per §11 (see P1).

### F1 — Read-only queue exposes question/topic, related count, impacted-answer evidence, authoritative cause, status, recency + diagnosis context + evidence drill-down — SATISFIED

- Current evidence: all seven queue columns present (AnswerGapsTab.tsx:139-227) backed by the read-only projection GET /tech/answer-gaps (tech_answer_gaps.py docstring: "只读投影,非新持久化 Knowledge Issue 模型"); cause = authoritative miss_type via shared helper `classify_gap_miss_types` (tech_answer_gaps.py:34, analytics.py:83-130 — same authority as /analytics/coverage-gaps); status from backend vocabulary; recency honest-null; diagnosis context = 5-tab side panel (概览/典型问题/相关对话/诊断详情/历史记录, GapPanel.tsx:39); drill-down = /conversations?q= deep links (GapPanel.tsx:166-178,216-223) + gap-conversation rows + related-source cards deep-linking /data-sources/:id (PanelStats.tsx:96-141) + export card.
- Target ref: Frozen Amendment queue expansion; KB-OPS-V163-002 §5.2/§5.5; reference PNG verified against implementation (B2 ledger J1-J12, DEFECT=0).

### F2 — Cause must be authoritative; otherwise render unclassified/unavailable — SATISFIED

- Current evidence: zero frontend heuristic classification (gapCause.ts module docstring: "前端只消费后端权威分类,零 keyword 猜测"); vocabulary = backend gap_taxonomy.py word set incl. U-14 six classes with deterministic evidence rules; null/empty/未分类 → 未分类 neutral badge; unknown machine values pass through verbatim (no invented label) and DiagnosisConclusion flips to `data-conclusion-kind="unavailable"`; cause filter offers authoritative full set + 未分类 (GAP_CAUSE_OPTIONS, GapCauseFilter.tsx).
- Target ref: KB-OPS-V163-002 §5.3 ("If a unified backend classification is absent, the UI must present 未分类/evidence-unavailable rather than infer"); Frozen Amendment.

### F3 — Do not invent OBSERVING/remediation/export/refresh/persistence/mutation semantics — SATISFIED

- Current evidence: OBSERVING = backend state machine with persisted append-only events (gap_observation_events; PanelHistory renders event vocabulary start/recurrence/abort/resolve verbatim, unknown event_type passes through); export = backend IF-5 endpoint + RBAC; refresh = not exposed; persistence = none added frontend-side (projection over question_clusters + conversations only); no row-level remediation/reprocess UI exists (deferred per §10 "NEW REQUIREMENT FOR REMEDIATION CONTRACT").
- Target ref: KB-OPS-V163-002 §5.4/§5.6 (workflow intent), §10 (explicitly NOT authorized to invent), Frozen Amendment. Note: §5.4 marks OBSERVING as requiring state authority — that authority now exists (backend/services/gap_status.py + gap_observation.py), so rendering it is faithful consumption, not invention.

### S2 — Never manufacture zero from missing/unknown backend truth — SATISFIED

- Current evidence: users count three-state (权威计数/证据不可用/加载中, PanelStats.tsx:74-83, `users_available` gate); sources attribution distinguishes "no citation records" vs "citations unmatched to source identity" vs read-failure (:96-141); recency null → 证据不可用 (relTime.ts); `total` is filtered truth, never presented as global zero; pagination honestly absent at totalPages<=1 ("不造第 2 页", AnswerGapsTab.tsx:240-243); load error → LoadError with retry, not empty state (AnswerGapsTab.tsx:129-132).
- Target ref: contract "never manufacture zero"; RCA comment 3; §10 fabrication ban.

### S3 — Representative-question/evidence drill-down preserved — SATISFIED

- Current evidence: representative question remains queue primary/fallback line (GapTopicCell) and panel title; sample questions listed with 查看全部 drill (GapPanel.tsx:134-161); conversation evidence deep-links preserved and extended (per-conversation rows → /conversations?q=question, GapPanel.tsx:235-263).
- Target ref: Frozen Amendment; KB-OPS-V163-002 §5.5 Conversation evidence (KEEP/ADAPT).

### P1 — Focused tests + UI evidence + regression + frozen-reference comparison — SATISFIED (shipped scope) / PENDING_IMPLEMENTATION (G1 delta)

- Current evidence (shipped scope): admin/tests/GapCauseTaxonomy.test.tsx, GapObservationLifecycle.test.tsx, TechInsightConvergence.test.tsx, TrackFEvidence.test.tsx, admin/src/lib/gapCause.test.ts; backend tests/api coverage for the projection; 12-state rendered screenshots + visual difference ledger (DEFECT=0).
- Target ref: contract ISSUE-SPECIFIC ACCEPTANCE last bullet. Any implementation of G1 must add: RED-first focused empty-state tests (4 states), regression run of the existing gap suites, and new rendered-UI evidence for the new states compared against §7 grammar (no frozen PNG exists for empty states — Role A UI-evidence review required, §11).

## Minimal-change boundary proposal (only PARTIAL rows; NOT implemented)

### G1 — covers C2 + C3 (four-state coherent empty/availability presentation)

Rules honored: projects EXISTING authoritative columns only (no new persistence, no new endpoint, no refresh-run provenance invented, no zero manufactured); re-adds nothing SUPERSEDED.

- EXPECTED files:
  1. `backend/api/admin/tech_answer_gaps.py` (~10-15 lines in the existing GET handler return block, :204-215): add read-only `availability` object computed from existing `QuestionCluster` columns over ALL gap clusters ignoring filters/window — `gap_clusters_total` (COUNT) and `classification_covered_through` (MAX(period_end), null = 无聚类覆盖真值). Zero new tables/endpoints.
  2. `admin/src/lib/api/techInsight.ts` (~6 lines): extend `AnswerGapList` with optional `availability` (backward-compatible).
  3. `admin/src/pages/analytics/AnswerGapsTab.tsx` (~30-45 lines, empty-state block :170-178 only): branch into four visually distinct renders keyed on client filter truth + server availability truth —
     - filtered-empty (any of status/cause/q set, or window-scoped with gap_clusters_total>0 in scope): current phrasing + 扩大时间范围 hint (neutral);
     - true-zero (no filters, window=all, gap_clusters_total>0): distinct green/neutral real-zero state, may say 「当前没有答案缺口」;
     - no-data/unclustered (gap_clusters_total===0): 「暂无缺口聚类证据:可能尚未执行聚类,或最近一次聚类未发现缺口;出现未回答问题聚合后会在此呈现」 — explicitly must NOT imply there are no gaps;
     - stale-derived (classification_covered_through present and behind the requested window start): amber stale banner 「聚类证据覆盖至 {date},此后数据尚未聚合」 without implying absence of gaps.
     Recommended implementation shape: `data-gap-empty-state={filtered|zero|no-data|stale}` attribute + distinct tone per §7 grammar.
  4. `admin/tests/TechInsightConvergence.test.tsx` or new focused `admin/tests/AnswerGapsEmptyStates.test.tsx` (4 cases, RED-first): one per state asserting distinct data-state value + copy + absence of fabricated "0".
- CONDITIONAL: none.
- FORBIDDEN: re-adding trend/distribution cards (SUPERSEDED, C1); refresh/聚类刷新 buttons or resolve toggles; new persistence or refresh-provenance truth; observation-window semantic changes; any file outside the four above; unrelated cleanup.
- Acceptance method: RED (single-message empty state reproducible in tests today) → GREEN (4 distinct states) → regression of GapCauseTaxonomy/GapObservationLifecycle/TechInsightConvergence/TrackFEvidence + backend answer-gaps tests → rendered-UI screenshots of all four states (1440×900 @1x per §11) with difference ledger entries classified by Role A.
- Explicitly NOT proposed (recorded for Role A): distinguishing "clustering never ran" from "clustered with zero gaps" would require new refresh-provenance persistence — out of scope per §10/Frozen Amendment; the no-data copy honestly covers both without fabricating which.

## Verification notes

- Baseline equivalence: `git diff b338c3c7 HEAD --stat` over the gap-surface files is empty; lane worktree at b338c3c7. All cited line numbers valid at baseline.
- Reference PNG inspected read-only (extracted from origin/docs/v163-design-baseline-20260912): confirms queue+side-panel-only target (no trend/distribution), 7 queue columns, 5 panel tabs, red 诊断结论 card, export card + privacy note, 内容补充完成后 + 开始观察 CTA — all present in the current tree.
- Old-surface strings 「缺口类型分布」/「暂无缺口数据，请先执行聚类刷新」 no longer exist in admin/src (grep-verified; only backend schema docstring 聚类刷新结果 remains).
