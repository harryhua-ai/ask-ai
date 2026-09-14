# V1.6.3-R3 Wave 2 Integration Report

执行日期：2026-09-14（Asia/Shanghai）
模式：INTEGRATION EXECUTION；仅推送 integration branch，不 merge、deploy、tag 或关闭 Issue。

## Baselines

- 生产基线（只读、未触碰）：`v1.6.3-r2 @ fd5ca39d7ee1097abe10de513ce7e595f159270a`。
- Fresh `origin/main`：`d89a0d198cdc1fa9e82b5525fbbba6d3d14e286c`。
- Previous integration candidate：`66695db047be2241a175bebd7930aa75a1142529`。
- Previous implementation/evidence commit：`ffc16d2edc8dc7a1690f0b119011914e0814d6ab`。
- Planning baseline：`a2f80f8be4fed092452bb854462ce19f7432fa17`。
- Accepted exact refs：
  - A `d0682311180a55070fd6739c18f5baab739b7429`
  - B `59494801ab457fddbaf913d83d2ff264d3a8d27f`
  - C `ace3ba3061cd1f76a469c4c89c4db007b453ad30`
  - D predecessor `3adce90a6e71e11efd60a9ed5fa21eeb32a30e59`
  - D closure `3316193fad5e4a6ae0ec6a60f89c47f06a392169`

Fresh gate executed `git fetch origin --prune`; all accepted refs and the planning baseline still exist. Previous integration and remote branch both resolved to `66695db...` before remediation.

## Integration topology

The previous candidate used cherry-picked local equivalents, so its ancestry did not contain the accepted exact SHAs. The remediation used a local-only rebuild branch from fresh main:

1. root: `origin/main` at `d89a0d1...`;
2. direct `--no-ff` merge of exact A → local merge `fb267cf`;
3. direct `--no-ff` merge of exact B → local merge `00aa917`;
4. direct `--no-ff` merge of exact C → local merge `fc6718b`;
5. direct `--no-ff` merge of exact D closure (which contains exact D predecessor) → local merge `2b08cd0`;
6. reapply only previously audited integration-support hunks, then add the updated report/evidence.

The only merge conflict was the known B/D mechanical overlap in `deploy/prod/migrations.json`. Resolution retained both migrations in deterministic order; no implementation conflict was found.

Accepted SHA proof on the rebuilt tree: `git merge-base --is-ancestor` returned YES for exact A, B, C, D predecessor, and D closure. The first-parent chain starts at fresh main, so current #69 governance work is physically contained rather than described-only.

## Main drift resolution

The fresh-main delta from old main `94ddb64825ae873eac0a4bd2d45377172fd355e2` to `d89a0d1...` is:

- `f7bda2a fix(project-automation): reconcile live Project control metadata`;
- `fd3cc53 docs(project-automation): record control-plane remediation evidence`.

Changed paths are limited to `.github/workflows/project-*`, `scripts/project_automation/*`, `tests/project_automation/*`, and the #69 task document. There is zero path overlap with the accepted A/B/C/D union, so this is orthogonal governance drift. It is retained by using fresh main as the rebuild root; no #69 file was edited.

## Accepted implementation containment/equivalence

- A/B: Admin data-source detail consumes persisted `delta_counts` with document as the unit; `新增/更新/淘汰` semantics remain explicit, while legacy/no-delta remains unavailable rather than inferred.
- #62: cron not-due skips, due executes, manual bypasses due gate, and persisted `next_run_at` remains authoritative.
- #63: list uses abbreviated real Conversation ID, detail uses full real ID, and copy control remains available.
- #64: valid `frontmatter_slug` maps to canonical Wiki; missing/empty/invalid authority preserves GitHub blob; repository-path guessing and fake/empty clickable URLs remain suppressed; answer/SSE and Admin/Widget parity remain covered.
- #67: generation sentinel is presented as technical evidence, not serving truth; no denominator is invented and retrieval consistency semantics are unchanged.
- normal GitHub, Website, and WooCommerce citation paths remain unchanged.

Tree-equivalence audit after support reapplication: accepted UI paths and Widget paths have no diff against the previous candidate; runtime differences are limited to the already-audited compatibility/lint hunks listed below plus fresh-main governance files. No product behavior was rewritten to satisfy ancestry.

## Migration manifest

The final manifest retains, in order:

```text
scripts/migrate_add_site_launcher_presentation.py
scripts/migrate_p1_lifecycle_foundation.py
scripts/migrate_add_track_c_product.py
scripts/migrate_add_sync_delta_counts.py
scripts/migrate_add_frontmatter_slug_property.py
```

The fail-closed planner was run against final implementation candidate `ab9e63ab7ec9fe5394b029626aa8a9a9d1125a72` and exited 0 (`PLAN SOURCE: manifest@ab9e63ab7ec9`). B migration is additive/idempotent `sync_log.delta_counts JSONB`; unknown legacy values remain NULL. D migration is additive/idempotent Weaviate schema property creation only; it does not backfill objects. Runtime fallback is the closure for existing objects with absent authority. No production migration was executed.

## Gate results

| Gate | Result | Evidence |
|---|---|---|
| Contract/topology | PASS | fresh main root; exact A/B/C/D containment; deterministic manifest |
| Functional truth | PASS | combined candidate suite 99 passed; API parity suite 38 passed |
| Engineering | PASS WITH BASELINE/ENVIRONMENT EXCEPTIONS | compileall and changed-path ruff pass; admin/widget tests/builds pass |
| Interaction | PASS WITH CONTROLLED MODEL STUB | real local PG, Weaviate, auth/API; only unavailable BGE model manager stubbed locally |
| Visual candidate | `VISUAL_CANDIDATE_READY = YES` | tree-identical UI/runtime visual paths; 10 screenshots at 1536×1024, DPR 1 reused with equivalence proof |
| Release readiness | PASS | planner exit 0; no merge/deploy/tag/production migration |

## Runtime evidence

- Candidate backend/admin smoke used the local Postgres 16 `:5432`, Weaviate `:8080`, real auth/API, and the local seeded data-source/conversation records. `/health` returned `status=ok`, `git_sha=ab9e63ab7ec9fe5394b029626aa8a9a9d1125a72`, and `app_mode=development`. The BGE model weights were unavailable with `HF_HUB_OFFLINE=1`, so only model loading was replaced with a no-op runtime stub.
- The controlled #64 fixture used UUID `b2c00000-0000-4000-8000-000000000064`, showed one canonical-slug citation and one legacy blob citation in Admin, then was deleted by exact UUID and verified absent. No other local row was deleted.
- #67 diagnostics visibly state that generation counts are technical evidence and that the migration sentinel is not serving count truth; knowledge coverage remains unknown without a denominator.

## Visual evidence

The previous screenshots are reused because topology remediation changes Git history plus orthogonal #69 files only; accepted UI/runtime visual paths are tree-identical. All ten files were independently verified as PNG `1536 x 1024`, DPR 1, CSS-pixel screenshots:

- `output/playwright/v163-r3-wave2/01-data-sources-list.png`
- `output/playwright/v163-r3-wave2/02-data-source-detail-identity.png`
- `output/playwright/v163-r3-wave2/03-knowledge-row-actions.png`
- `output/playwright/v163-r3-wave2/04-sync-status-activity-delta.png`
- `output/playwright/v163-r3-wave2/05-health-diagnostics-collapsed.png`
- `output/playwright/v163-r3-wave2/06-health-diagnostics-expanded.png`
- `output/playwright/v163-r3-wave2/07-conversation-review-list-id.png`
- `output/playwright/v163-r3-wave2/08-conversation-detail-full-id.png`
- `output/playwright/v163-r3-wave2/09-citation-rendering.png`
- `output/playwright/v163-r3-wave2/10-issue64-citation-rendering.png`

Visual status is candidate-only; Role A retains final visual acceptance authority.

## Test evidence

- Candidate functional suites: `99 passed, 35 warnings`.
- API parity suites: `38 passed, 4 warnings`.
- Admin: `65 files / 545 tests passed`; TypeScript build exit 0; Vite build exit 0.
- Widget: `14 files / 183 tests passed`; build exit 0.
- `python -m compileall -q backend scripts`: exit 0.
- changed-path ruff: `All checks passed!` after removing one duplicate import exposed by the topology rebuild.
- `git diff --check`: exit 0.
- Full repo ruff remains baseline-red with 285 unrelated errors; no changed-path error remains.
- Full pytest remains baseline/environment-exception-only: `2 failed, 2673 passed, 8 skipped, 277 warnings, 4 errors`. The failures are the unmodified stale `-rN` tag-validation assertion and offline/missing-BGE lifespan/model errors; no new candidate-caused failure was observed.

## Scope audit

- No merge to main, deploy, release/tag, production migration, Issue closure, #68 change, or project-state mutation.
- Accepted #64 semantics were not reopened or redesigned.
- No backfill guessing and no hardcoded `/resources` route.
- Website, WooCommerce, normal GitHub, provenance retention, answer/SSE parity, and Admin/Widget parity remain within the accepted test contract.

## Remaining exceptions

- Role A final acceptance is still required.
- Full pytest requires local `BAAI/bge-m3` weights or network access, and the unmodified deploy tag-validation test needs baseline maintenance.
- Full-repo ruff baseline remains at 285 errors; candidate changed paths are clean.

## Verdict

`WAVE2_INTEGRATION_REMEDIATION = CANDIDATE READY`

- previous candidate SHA: `66695db047be2241a175bebd7930aa75a1142529`
- final candidate SHA (implementation/evidence commit): `ab9e63ab7ec9fe5394b029626aa8a9a9d1125a72`
- implementation/evidence predecessor: `ffc16d2edc8dc7a1690f0b119011914e0814d6ab`
- branch: `integration/v163-r3-wave2-20260914`
- report path: `reports/v163-r3-wave2-integration-20260914.md`
- final report-only commit SHA: recorded by the pushed branch HEAD after this report is finalized; it does not change implementation semantics.

---

## Wave 2 — Admin Operations Remediation (Role B, this cycle)

执行日期：2026-09-14（Asia/Shanghai）
范围：A Admin action discoverability；B current-data-source bulk knowledge repair；C Admin-configurable Conversation ID policy。
模式：NARROW REMEDIATION；仅复用 `integration/v163-r3-wave2-20260914`，不新开 Track、不 merge、不 deploy、不做 production migration、不关闭 Issue。

### Fresh gate and candidate identity

- Fresh `origin/main`: `d89a0d198cdc1fa9e82b5525fbbba6d3d14e286c`.
- Old candidate before this remediation: `c830f2b0b83ad24d9a071e42d22790afbb34439d`.
- Previous integration candidate: `66695db047be2241a175bebd7930aa75a1142529`.
- Branch: `integration/v163-r3-wave2-20260914`.
- Implementation/evidence commit: `edba4cf71ef3b998eb3a558529dfd99cedcbc5b7`.
- Final pushed SHA: recorded after the report commit and remote verification in the handoff below.

Fresh gate used `git fetch origin --prune`; the worktree was clean before remediation, `origin/main` was unchanged from the accepted planning baseline, and no merge/deploy/tag/production mutation was performed.

### A — Admin action discoverability

`admin/src/pages/DataSources.tsx` now exposes page-level `同步全部` and each enabled row's routine `详情` / `编辑` / `同步` controls directly at desktop width. Existing state guards remain authoritative: disabled sources keep `同步` disabled; active/pending syncs cannot be double-triggered; overflow is retained only for `同步记录` and destructive `删除`. The detail page's `返回列表` is also a direct top-right button and is not hidden inside the page-action overflow.

The real local Admin browser at `http://127.0.0.1:18230` showed 11 data sources, direct page/row actions, a disabled sync control for the disabled source, and the secondary-only row overflow menu. Screenshot evidence:

- `output/playwright/v163-r3-wave2-admin-remediation/01-data-sources-direct-actions.png`
- `output/playwright/v163-r3-wave2-admin-remediation/02-data-source-overflow-secondary-only.png`
- `output/playwright/v163-r3-wave2-admin-remediation/03-data-source-detail-bulk-action.png`

### B — Bulk repair semantics

`POST /api/admin/data-sources/{source_id}/documents/repair-all` is editor/admin-only and is scoped to the selected current data source. Eligibility is derived from the existing authoritative attention/lifecycle truth:

- includes `missing_candidate` / `discovered` and active documents whose current version is unresolved;
- excludes healthy active documents with a resolvable current version;
- excludes `superseded` and `deleted` retired objects;
- orders by `doc_source_id` for bounded deterministic processing;
- returns per-item `succeeded` / `failed` status, task id and error evidence, plus aggregate `eligible` / `succeeded` / `failed` counts;
- returns 409 for an in-flight same-source repair (process lock plus database `FOR UPDATE NOWAIT` guard);
- is truthful when vector/embedding dependencies are unavailable (503), never manufacturing success;
- uses deterministic `bulk-repair-v1:{source_id}:{doc_source_id}` task keys and existing single-document repair execution for idempotence and provenance/audit retention;
- returns a zero aggregate for an already healthy source without touching the vector stack.

The Admin detail page shows `一键修复全部 N 项`, truthful pending state, and the returned aggregate `已修复 X 项，Y 项仍需处理`; it invalidates the authoritative document/truth/source queries after completion. The live `ne301` detail view showed one attention item and the direct `一键修复全部 1 项` control.

### C — Conversation ID policy

Investigation confirmed the previous runtime generated new IDs with direct `uuid.uuid4()` calls in both new-conversation branches; existing `Conversation.id` values are persisted UUID primary keys and are not rewritten. The remediation adds:

- `conversation_id_policies` ORM table plus additive/idempotent `scripts/migrate_add_conversation_id_policy.py`;
- migration manifest entry `scripts/migrate_add_conversation_id_policy.py`; table creation uses `CREATE TABLE IF NOT EXISTS`, and the fixed `default` row uses `ON CONFLICT DO NOTHING` with default `uuid4`;
- `GET/PUT /api/admin/system/conversation-id-policy`; read access is viewer/editor/admin, write access is editor/admin, invalid strategies return 422;
- `backend/services/conversation_id.py` with RFC 9562 UUIDv7 generation, persisted active-strategy loading, authoritative UUIDv4 default only when the policy row is absent, and fail-closed errors for invalid/unreadable policy;
- both new-conversation paths in `backend/api/routes.py` now use the service; ordinary attachment UUIDs are unchanged;
- Admin System Info control with explicit “当前生效” text, v4/v7 selection, save feedback, preview, and `仅影响新建对话，已有 Conversation ID 不会改变` contract.

The migration is bounded to one fixed policy row, source/config-authoritative, idempotent, and performs no historical Conversation ID backfill. Existing list/detail/copy behavior remains the canonical persisted-ID contract.

Live browser evidence logged in this cycle: authenticated local admin opened `/admin/system`, read current `uuid4`, saved `uuid7` and observed a version-7 preview, then restored `uuid4`; no production account or production database was touched. Screenshots:

- `output/playwright/v163-r3-wave2-admin-remediation/04-conversation-id-policy.png`
- `output/playwright/v163-r3-wave2-admin-remediation/05-conversation-id-policy-saved.png`

### Regression and acceptance evidence

Frontend:

- Targeted Admin tests: `4 passed, 83 passed` (`DataSourcesConvergence`, `DataSources`, `DataSourceDetailConvergence`, `ConversationIdPolicy`).
- `npm run build`: passed (`tsc -b` and Vite build); Vite emitted only the existing chunk-size warning.

Backend, run as isolated pytest groups because some legacy API tests intentionally replace process-global `app.state` fixtures:

- Track C bulk repair + policy + UUID service: `28 passed, 4 warnings`.
- route/reliability/admin-channel compatibility: `20 passed, 4 warnings`.
- data-source/discovery/website/system/conversation parity: `48 passed, 4 warnings`.
- The combined all-in-one invocation produced 42 fixture-contamination failures (`get_current_user` saw an `AsyncMock` coroutine); this was reproduced, traced to cross-module `app.state.session_factory` replacement, and the three isolated groups all passed. No candidate failure remains.
- `python -m compileall -q backend scripts tests/api/admin/test_conversation_id_policy.py tests/services/test_conversation_id.py`: passed.
- Changed-path `ruff check`: passed.
- `git diff --check`: passed.

Acceptance coverage includes:

- new policy path and old Conversation IDs remain stable;
- list/detail/copy canonical behavior through existing conversation regressions;
- Admin/editor/viewer RBAC for policy and bulk repair;
- bulk partial success, retired/healthy exclusion, idempotence/concurrency, truthful dependency failure;
- normal GitHub, Website and WooCommerce source behavior unchanged;
- Widget and Admin/API parity preserved;
- provenance/audit retained by reusing existing repair task execution;
- prior #64 authoritative Wiki citation closure remains untouched: valid frontmatter slug emits canonical Wiki route; absent/invalid authority stays on proven provenance fallback, with no guessed `/resources` URL and no empty/fake clickable URL. Existing #64/NE503 SDK regression evidence remains in the accepted predecessor/closure and was not reopened in this admin-only cycle.

Concrete #64 reproduction evidence retained from the accepted Track D closure: `pytest -q tests/pipeline/test_canonical_url.py -k legacy_ne503_sdk_resources_without_slug` covers `docs/6-neoeyes-ne503-series/3-sdk/reference.md` and `docs/6-neoeyes-ne503-series/4-application-guide/3-resources.md`; before closure those legacy objects guessed `/docs/neoeyes-ne503-series/sdk/reference` and `/docs/neoeyes-ne503-series/application-guide/resources`, while after closure both resolve to their original GitHub blob provenance URLs when `frontmatter_slug` is absent. The same fixture is asserted for Admin and Widget plus `answer()` and `stream_answer()` parity. The valid new-ingest case asserts frontmatter slug propagation to the canonical Wiki route. This cycle's Admin changes do not alter that path.

### Changed files

- Admin: `admin/src/hooks/useConversationIdPolicy.ts`, `admin/src/hooks/useDataSourceKnowledge.ts`, `admin/src/pages/DataSourceDetail.tsx`, `admin/src/pages/DataSources.tsx`, `admin/src/pages/SystemInfo.tsx`.
- Admin tests: `admin/tests/ConversationIdPolicy.test.tsx`, `admin/tests/DataSources.test.tsx`, `admin/tests/FinalPolish.test.tsx`, `admin/tests/dataSources/DataSourceDetailConvergence.test.tsx`, `admin/tests/dataSources/DataSourcesConvergence.test.tsx`.
- Backend: `backend/api/admin/data_sources.py`, `backend/api/admin/schemas.py`, `backend/api/admin/system.py`, `backend/api/routes.py`, `backend/db/models.py`, `backend/services/conversation_id.py`.
- Migration/manifest: `scripts/migrate_add_conversation_id_policy.py`, `deploy/prod/migrations.json`.
- Backend tests: `tests/api/admin/test_conversation_id_policy.py`, `tests/api/admin/test_data_sources_track_c.py`, `tests/api/admin/test_system_runtime.py`, `tests/services/test_conversation_id.py`.
- Fresh browser evidence: `output/playwright/v163-r3-wave2-admin-remediation/` (five PNGs).

### Scope audit and non-actions

No merge, deploy, tag/release, production migration execution, Issue closure, or new Track was performed. No #64 citation, Wiki ingestion, normal GitHub, Website, WooCommerce, or Widget serving implementation was altered beyond Admin action placement and the generic bulk-repair control. The migration file is included in the manifest but was not executed against production.

### Cycle verdict

`V163_R3_ADMIN_OPERATIONS_REMEDIATION = CANDIDATE READY`

- old SHA: `c830f2b0b83ad24d9a071e42d22790afbb34439d`
- implementation/evidence SHA: `edba4cf71ef3b998eb3a558529dfd99cedcbc5b7`
- final pushed SHA: recorded after this report commit and remote verification
- branch: `integration/v163-r3-wave2-20260914`
- report: `reports/v163-r3-wave2-integration-20260914.md`

---

## Role A Narrow Fix — Conversation ID fail-closed remediation

执行日期：2026-09-14（Asia/Shanghai）
范围：仅修复 Role A 指出的 Conversation ID 静默 fallback 阻塞缺陷；不重开 Items A/B，不改变 uuid4/uuid7 选项，不改 Admin UI，不 merge/deploy/tag，不执行 production migration，不关闭 Issue。

### Candidate identity

- Previous reviewed candidate SHA: `c71d7ef3a1258b88c5f38240b8c2ba93cbec1a0c`.
- Previous implementation/evidence SHA: `edba4cf71ef3b998eb3a558529dfd99cedcbc5b7`.
- Narrow-fix implementation/evidence SHA: `600ec1485a4353d7ba8e9854a465fc47fb86c8eb`.
- Branch: `integration/v163-r3-wave2-20260914`.

### Exact fail-closed semantics

`backend/services/conversation_id.py` now distinguishes the only allowed default from all failures:

- readable policy store + no `default` row → authoritative initial default `uuid4`;
- readable store + persisted `uuid4` → UUIDv4;
- readable store + persisted `uuid7` → UUIDv7;
- persisted but invalid strategy → `ConversationIdPolicyError`, with no generator call;
- policy session/query/storage failure → `ConversationIdPolicyError`, with no generator call;
- Admin policy GET surfaces the same invalid-policy condition as explicit HTTP 503 instead of displaying a guessed default.

`backend/api/routes.py` resolves the ID before constructing the SSE response in both the normal and budget-declined creation paths. A policy-resolution failure is converted to HTTP 503 (`Conversation ID 生成策略不可用,拒绝创建新对话`), before RAG execution, `Conversation`/`Trace` persistence, or any `conversation_id` event. Existing `Conversation.id` values are never read-modified-written by this path.

No migration or backfill was introduced by this narrow fix; the existing policy migration remains additive/idempotent and was not executed against production.

### Tests and regression results

- Conversation policy/service/route affected suite: `20 passed, 4 warnings`.
- Track C bulk repair + Conversation ID policy + UUID service suite: `31 passed, 4 warnings`.
- Route/reliability/Admin-channel compatibility suite: `21 passed, 4 warnings`.
- Data-source/discovery/website/system/conversation Admin regression suite: `48 passed, 4 warnings`.
- Frontend targeted Admin suite from the same candidate: `4 files, 83 tests passed`; Admin build passed.
- Changed-path `ruff check`: passed; backend `compileall`: passed; `git diff --check`: passed.

The explicit new regression family covers valid uuid4/uuid7, readable no-row authoritative default, invalid persisted strategy, unreadable policy store, route-level no-stream/no-persist/no-return behavior, and an existing Conversation ID remaining byte-for-byte unchanged. The accepted #64 NE503 SDK/resources reproduction remains unchanged: valid frontmatter authority emits canonical Wiki URL; absent authority retains proven GitHub blob provenance and never guesses `/resources`.

### Final-candidate browser evidence

The real local Admin browser used backend `/health` SHA `600ec1485a4353d7ba8e9854a465fc47fb86c8eb`, local Postgres/Weaviate/auth, and seeded local records. All screenshots below are PNG `1536×1024`, DPR 1:

- `output/playwright/v163-r3-wave2-admin-remediation/01-data-sources-direct-actions.png`
- `output/playwright/v163-r3-wave2-admin-remediation/02-data-source-overflow-secondary-only.png`
- `output/playwright/v163-r3-wave2-admin-remediation/03-data-source-detail-bulk-action.png`
- `output/playwright/v163-r3-wave2-admin-remediation/04-bulk-repair-running-duplicate-disabled.png`
- `output/playwright/v163-r3-wave2-admin-remediation/05-bulk-repair-result.png`
- `output/playwright/v163-r3-wave2-admin-remediation/06-conversation-id-policy.png`
- `output/playwright/v163-r3-wave2-admin-remediation/07-conversation-id-policy-saved.png`
- `output/playwright/v163-r3-wave2-admin-remediation/08-conversation-review-list.png`
- `output/playwright/v163-r3-wave2-admin-remediation/09-conversation-detail-full-id-copy.png`

The bulk repair running screenshot captures the existing button disabled as `一键修复中…`; the result is the real local partial outcome `已修复 0 项，1 项仍需处理`. Conversation Review list/detail screenshots show abbreviated versus full canonical IDs and the copy control. The saved local policy was restored to uuid4 after evidence capture.

### Narrow-fix verdict

`V163_R3_ADMIN_OPERATIONS_REMEDIATION_FIX = CANDIDATE READY`

- previous SHA: `c71d7ef3a1258b88c5f38240b8c2ba93cbec1a0c`
- implementation/evidence SHA: `600ec1485a4353d7ba8e9854a465fc47fb86c8eb`
- final pushed SHA: recorded after this report commit and remote verification
- report path: `reports/v163-r3-wave2-integration-20260914.md`
