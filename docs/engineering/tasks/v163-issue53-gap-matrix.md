# Issue #53 GAP_MATRIX — Data Sources list as operator knowledge surface

- Executor: Trace Executor (GAP_MATRIX phase, contract role-a-execution-contract:v1, BATCH 2, GAP_ONLY_IMPLEMENTATION, IMPLEMENTATION_AUTHORIZED=YES_AFTER_GAP_MATRIX)
- BASELINE: `b338c3c7eeaf` (origin/main, v1.6.3-r4 production tree)
- CANDIDATE_BRANCH: `agent/53/fa864a60` (lane-3, investigation mode)
- CANDIDATE_SHA: (docs-only evidence commit on lane branch; see PRESERVE record)
- CHANGE_BUDGET (proposed, NOT implemented): `admin/src/pages/DataSources.tsx` (attention-reason scan surface, ~10-20 lines) + `admin/tests/DataSources.test.tsx` (1 focused case). Zero backend, zero new endpoints, zero lib additions.
- PRODUCTION_ACCESS: none
- STATUS: GAPS_FOUND (1 PARTIAL row; everything else SATISFIED / DEPENDENCY / PENDING_IMPLEMENTATION; 0 MISSING, 0 SUPERSEDED)

## Authoritative inputs consumed

1. Issue body acceptance (7 checkboxes) + KB-OPS-V163-002 Frozen Amendment section.
2. All 4 comments; final `role-a-execution-contract:v1` governs (REQUIRED_FIRST=matrix; only PARTIAL/MISSING authorize edits; consume #81 vocabulary and #82 sync-delta truth).
3. Recovery references (branch `docs/v163-design-baseline-20260912`, @5593d6be):
   - `docs/product/design/admin-knowledge-ops/DESIGN_RECOVERY_REVIEW_V002.md` (KB-OPS-V163-002, §4.1 list, §4.5 drawer, §7 grammar, §10 frozen scope, §11 conformance gate)
   - `docs/product/design/admin-knowledge-ops/references/data-source-operations-original.png` (inspected read-only)
   - `docs/engineering/tasks/v163-b1-data-source-operations-contract.md` (B1 frozen contract)
4. Current tree truth: admin/src/pages/DataSources.tsx, DataSourceDetail.tsx, admin/src/lib/{dataSourceOps,syncDeltaPresentation,sourceEditorModel}.ts, admin/src/hooks/useDataSources.ts, admin/src/types/api.ts.

## Context: current tree already contains the B1 convergence

The r4 tree contains the B1 convergence (`336c7f5`), P1-P4 design remediation (`2f0bc06`), wave1 (`d068231`), wave2 (`edba4cf`) and #71 membership truth (`c556652`). The list page (admin/src/pages/DataSources.tsx:49-54) is already organized as: 名称/类型/状态/知识数量/需处理(一等列)/最后同步/操作 + exception-first sort + state/type filters + compact ⋯ actions. The matrix below is judged against the non-superseded acceptance, not against the pre-B1 complaint text.

## current→target matrix

Status legend: SATISFIED / PARTIAL / MISSING / SUPERSEDED / DEPENDENCY / PENDING_IMPLEMENTATION.

### A1 — Attention state AND reason visible without entering the detail page — PARTIAL

- Current evidence:
  - State scan-visible: operator-state badge (admin/src/pages/DataSources.tsx:409-437) + 需处理 first-class column with destructive red count (:447-460), fed by backend attention-summary projection (:144-151, hooks/useDataSources.ts:91-97).
  - Reason NOT scan-visible as authoritative breakdown: badge hover title carries only 30d historical reliability + last_sync_error (:384-393); the count tooltip is generic ("X 项知识需要处理", :451-455). The authoritative per-source reason projection `attentionReasonClasses(lifecycle_counts, attention_count)` (admin/src/lib/dataSourceOps.ts:181-204: missing-in-grace / discovered-not-ingested / current-version-missing classes) is rendered ONLY in the detail banner (admin/src/pages/DataSourceDetail.tsx:300-302, :486-493).
  - Data already fetched: attention-summary items carry `lifecycle_counts` per source (dataSourceOps.ts:24-32, consumed only as attention_count today).
- Target: B1 frozen contract — "Make attention reason visible at list/detail level where authoritative"; Issue acceptance checkbox 1; reference panel 1 keeps single-row density, so reason belongs in the row's title/secondary micro-text, not a new column.
- Note for Role A: if category-level state labels (同步失败/成员漂移/对账失败/过期) + hover titles are judged sufficient, A1 could be closed as JUSTIFIED DIFFERENCE (reference panel 1 shows no reason text in list). Recorded as PARTIAL because the authoritative input is present and unrendered.

### A2 — Healthy / degraded / needs-attention semantics operator-readable — SATISFIED

- Current evidence: operatorStateOf vocabulary maps backend-authoritative values only (admin/src/lib/dataSourceOps.ts:84-158): 正常 / 需处理 / 恢复中 / 过期 / 部分覆盖 / 降级 / 成员漂移 / 对账失败 / 同步失败 / 删除失败 / 已禁用 / 已排除 / 待分类 (evidence-absent never defaults healthy, :152-157); tone→color grammar (toneVariant, :160-175: green ok / red attention+failed / amber intermediate / outline disabled); operator filter groups (DataSources.tsx:62-71).
- Target ref: RECOVERY_REVIEW_V002 §4.1 operator-facing status; §7 grammar (red action-required, amber intermediate/stale, green healthy); Frozen Amendment "operator-facing state first-class".

### A3 — Freshness / serving impact / reconciliation consume authoritative backend truth only — SATISFIED

- Current evidence:
  - Freshness: 最后同步 relative time from backend last_sync (DataSources.tsx:461-469, relativeTime dataSourceOps.ts:42-64); backend folds freshness into authoritative overall — `freshness == "stale" → overall STALE` (backend/api/admin/sync_runs.py:440-479) → 「过期」 badge (dataSourceOps.ts:84-89, :131-137); policy-level freshness_overdue (backend-persisted, types/api.ts:211) surfaces as detail banner (DataSourceDetail.tsx:451-473).
  - Serving impact: 在服(含宽限) count from attention-summary serving_count (DataSources.tsx:439-445); detail serving truth from documents aggregation + chunk projection (DataSourceDetail.tsx:437-445, :717-726, :815-838).
  - Reconciliation: persisted membership_status column → 成员漂移 / 对账失败 states, never presented 正常 (dataSourceOps.ts:116-127; types/api.ts:216; #71).
  - Zero frontend health recomputation: module-level frozen discipline (dataSourceOps.ts:1-10); no health math in admin/src (grep-verified).
- Target ref: Frozen Amendment "authoritative backend truth only; do not infer health in the frontend"; RECOVERY §4.1 ADAPT clause.

### A4 — Knowledge quantity / recent sync = scan context; raw reliability / config telemetry secondary — SATISFIED

- Current evidence: 知识数量 (DataSources.tsx:438-446) and 最后同步 (:461-469) are context columns; 30d historical reliability demoted from column to badge hover title (DSH-02, :152-159, :384-390; column-header regression locked in admin/tests/DataSources.test.tsx:1280-1282); source URL/location moved into name title (:398-406); config editing收敛为 context-preserving drawer (:560-566, SourceEditorDrawer §4.5).
- Target ref: Frozen Amendment scan-level-context clause; RECOVERY §4.1/§4.5.

### A5 — Actions remain available but visually secondary — SATISFIED

- Current evidence: 操作 column = compact h-7 ghost/outline buttons 详情/编辑/同步 (DataSources.tsx:470-509); destructive 删除/重试删除 collapsed into ⋯ dropdown with destructive styling and separator (:510-541); routine 同步全部 = page-header outline button (:295-306); primary page action = 添加数据源 (:307). No capability removed (dropdown keeps 同步记录/重试删除/删除).
- Target ref: RECOVERY §4.5 KEEP INTERACTION PATTERN; §7 "normal telemetry compact", "primary blue actions"; reference panel 1 ⋯ column.

### A6 — Fast scanning for "what needs attention now" — SATISFIED

- Current evidence: TONE_PRIORITY exception-first sort (failed→attention→intermediate→unclassified→disabled→ok; DataSources.tsx:73-80, :210-216); 需处理 first-class red-count column (:447-460); 状态 filter with 需处理 option (:62-71); attention-summary 5s polling while syncs active (:145-147).
- Target ref: RECOVERY §4.1 "The primary list must answer: which sources need attention? how many knowledge items affected? …"; reference panel 1.

### D1 — Source-type (类型) column vocabulary — DEPENDENCY (#81), not a #53 frontend gap

- Current truth on baseline: SOURCE_TYPE_OPERATION_LABELS maps github/local_git → "Wiki" (content-classification word, wrong for connector type; admin/src/lib/sourceEditorModel.ts:106-116), rendered by list 类型 cell (DataSources.tsx:408).
- DEPENDENCY candidate: `origin/agent/81/e2191d2d` @ `25c67e6` — presentation-only fix (github/local_git → canonical 「代码仓库」; fail-visible for unknown types), touches sourceEditorModel.ts + 3 test files; vitest 555/555; zero backend diff.
- Integration-order meaning: merge #81 before #53 final acceptance evidence; #53 must NOT re-fix (would duplicate/conflict). All matrix rows touching 类型 rendering inherit this dependency.

### D2 — Sync-delta / reconciliation truth — DEPENDENCY (#82), not a #53 frontend gap

- Current truth: frontend already consumes the corrected contracts — delta_counts with unit=document gate and fail-visible LEGACY_DELTA_UNAVAILABLE (admin/src/lib/syncDeltaPresentation.ts:31-54; consumed in dataSourceOps.ts:324-349) and persisted membership_status (D-A3). Remaining incorrectness is backend truth, not presentation.
- DEPENDENCY candidate: `origin/agent/82/727767cd` @ `2a33209` — backend-only (connectors/github.py branch-scope backfill, membership_currency authority−ledger reconciliation, scripts/sync.py serving-only count truth + tests; zero admin/src diff).
- Integration-order meaning: land #82 before #53 final UI evidence/screenshots so 成员漂移/对账失败/最后同步/同步活动 displays reflect corrected truth; requires no frontend change, only re-verification of rendered states.

### P1..P4 — Implementation-phase acceptance — PENDING_IMPLEMENTATION (not counted as current gaps)

- P1 Focused tests: existing suites cover the converged list (admin/tests/DataSources.test.tsx 43 cases; dataSources/DataSourcesConvergence.test.tsx 20; dataSourceOps.test.ts; dataSourceOpsMembership.test.ts; syncDeltaPresentation.test.ts). r5 must add focused tests for whatever row is implemented (only A1 qualifies).
- P2 UI evidence: implementation screenshots + Difference Ledger, DEFECT=0 (B1 contract Acceptance; RECOVERY §11 items 1-8).
- P3 Regression: vitest / tsc / build / pytest green on candidate tree.
- P4 Frozen-reference comparison / Design Conformance Gate before merge/deploy, incl. post-deploy production parity (Issue acceptance checkbox 7; RECOVERY §11 item 9). Hard reference: references/data-source-operations-original.png.

### SUPERSEDED rows: none

No non-superseded acceptance criterion maps to superseded v001 semantics. The DESIGN HOLD comment is itself superseded by the Frozen Amendment + lifecycle review; nothing to implement from it.

## Statistics

SATISFIED 5 (A2, A3, A4, A5, A6) · PARTIAL 1 (A1) · MISSING 0 · SUPERSEDED 0 · DEPENDENCY 2 (D1→#81, D2→#82) · PENDING_IMPLEMENTATION 4 (P1-P4)

## Minimal change boundary proposal (A1 only; NOT implemented in this phase)

- File boundary (admin/src only):
  - `admin/src/pages/DataSources.tsx` — in the 需处理 cell (and/or state badge title), render `attentionReasonClasses(summary.lifecycle_counts, attentionCount)` (already-fetched attention-summary payload; pure presentation projection of backend bucket counts — no recomputation of health, no new endpoint, no new hook). Keep it as hover title or one-line truncated secondary text to preserve the ~36-41px single-row density locked by A-P1-03.
- Tests: extend `admin/tests/DataSources.test.tsx` (existing attention-summary fixtures at :1118-1130) with one case asserting the authoritative reason classes render at list level (missing_candidate / discovered / suspended projections).
- Expected acceptance: focused vitest case(s) + tsc + build; UI evidence via P2 Difference Ledger and P4 Design Conformance Gate at r5 (hard ref data-source-operations-original.png).
- Alternative for Role A: rule A1 a JUSTIFIED DIFFERENCE (reference list shows no reason text; category-level state labels + hover titles suffice) → then the proposal becomes "zero frontend change; matrix alone completes #53 presentation scope, with D1/D2 merges + P1-P4 evidence gates".

## LIMITATIONS

- Static code-truth investigation only; no live render or screenshots in this phase (P2/P4 are implementation-phase deliverables by design).
- "Operator-readable" judgments are code/vocabulary-level; final conformance authority is Role A's visual gate.
- #82 has multiple candidate branches (agent/82/{642e501f,70c86e29,727767cd}); the coordinator-nominated `727767cd`@`2a33209` was used as the DEPENDENCY candidate.
- Reference PNG inspected read-only from the docs baseline branch; no pixel-level conformance performed here.
