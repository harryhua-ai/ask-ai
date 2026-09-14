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
