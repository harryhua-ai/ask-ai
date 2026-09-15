# ISSUE #71 REMEDIATION EXECUTION REPORT

**Track**: ISSUE_71_REMEDIATION (authorized) · **Status**: CANDIDATE READY
**Date**: 2026-09-15 · **Base**: `origin/main f4e6751` · **Candidate branch**: `remediation/issue71-membership-reconciliation-20260915`
**Mode**: implementation authorized; NO merge to main, NO deploy, NO production reconciliation, NO production mutation, #71 left open.

---

## 1. Executive summary

Implements the minimum systemic correction for production defect #71 (stale upstream documents served as current truth while Admin reports 正常/同步完成), per the frozen requirements 1-18 of the authorization:

- **Authoritative membership reconciliation** for GitHub sources: every completed sync round now computes `stale_set = ledger serving membership − authoritative membership` and retires it via the existing `tombstone_document` lifecycle semantics. Correctness does **not** depend on git event windows, `fetch_deleted` history, or whether a deletion event was ever observed (requirements 1-5).
- Reconciliation runs on **every** round — including no-change rounds where `fetch_changes` short-circuited on an unchanged remote SHA (requirement 6; the exact #71 blackout class).
- Reconciliation is **idempotent and convergent** (requirement 7) and **atomic + kill-safe**: the retirement is one transaction; the persisted authoritative-currency truth is written only after that transaction commits (requirement 8).
- Not a citation filter, no URL-HEAD probing, no path special-casing (requirement 9).
- **Persisted authoritative-currency truth** on `data_sources` (additive columns) consumed by `/admin/data-sources` and `/admin/sync-health` as a new, separate `currency` dimension; Admin can no longer display 正常/同步完成 for a source with unresolved drift (requirements 10-12).
- **Counter hygiene**: `stale_detected` / `stale_retired` / `membership_status` are separately observable in `delta_counts`; orphan-vector operations no longer overload `items_new`/`items_deleted` (requirement 13).
- **Authorized correction mechanism** `scripts/reconcile_membership.py`: dry-run default with an exact, JSON-serializable plan; `--apply` re-derives the stale population from authoritative truth at execution time (nothing hard-coded) and retires via tombstone only (requirements 14-16).
- Rename lineage (`set_successor`) intentionally **not** wired — minimum requirement met: old identity retires, new identity ingests, no stale double-serving (requirement 17).
- filesystem / woocommerce / web_crawl: **zero forced changes** — the capability is optional; connectors without it are persisted as `membership_status=unsupported` (neutral, not degraded). Scope-expansion findings reported to Role A in §7 (requirement 18).

## 2. Changed files (exact)

**New (5)**
| File | Purpose |
|---|---|
| `backend/services/membership_currency.py` | Shared reconciliation service: `ledger_active_membership`, `reconcile_membership` (sync ledger session, atomic), `persist_membership_truth` (async truth persistence), frozen status vocabulary `current/stale/failed/unsupported` |
| `scripts/migrate_add_membership_currency.py` | Additive, idempotent migration: 5 columns on `data_sources` (`membership_status`, `membership_checked_at`, `membership_stale_detected`, `membership_stale_retired`, `membership_detail` JSONB) |
| `scripts/reconcile_membership.py` | Authorized correction CLI: dry-run exact plan (default) / `--apply`; recomputes stale population at execution time |
| `tests/services/test_membership_currency.py` | R1-R12 service acceptance (retire semantics, rename, convergence, atomicity, vocabulary) |
| `tests/pipeline/test_sync_membership.py` | S1-S9 sync-round acceptance (SHA-short-circuit round reconciles, rename, failure downgrade, kill-safety, exact #71 NE503-class reproduction, convergence, counter separation) |
| `tests/api/admin/test_membership_health.py` | H1-H5 admin health acceptance (degradation, legacy NULL, failed, unsupported) |
| `tests/scripts/test_reconcile_membership_script.py` | C1-C3 correction-mechanism acceptance (exact plan, tombstone-only apply, truth persistence) |
| `tests/connectors/test_github_membership.py` | M1-M3 connector enumeration contract (filters, branch scoping, no forced capability) |
| `admin/tests/dataSources/dataSourceOpsMembership.test.ts` | UI presentation mapping (成员漂移/对账失败 never 正常; unsupported/NULL neutral) |

**Modified (11)**
| File | Change |
|---|---|
| `backend/connectors/github.py` | New `membership_source_ids()`: per-branch `ensure_cloned + git_sync_branch` (unconditional fetch+reset — independent of SHA short-circuit), path-only walk with the ingestion-identical filter face (`_should_include_path`) |
| `scripts/sync.py` | `_reconcile_membership_for_source()` wired into `_sync_one` in BOTH the no-change branch (before `_handle_no_change`) and the normal path (after `fetch_deleted` tombstones); SyncLog downgraded to `partial` on unresolved drift or reconciliation failure; `items_deleted` = document tombstones (window + membership) with separate delta keys; `_handle_no_change` repair path no longer writes orphan-vector ops into `items_new`/`items_deleted` |
| `backend/services/sync_delta.py` | `build_document_delta` gains additive `ledger_rebuilt_count` (document unit) and `orphan_vectors_retired` (chunk unit) keys |
| `backend/db/models.py` | `DataSource` + 5 additive membership-currency columns |
| `backend/api/admin/schemas.py` | `DataSourceOut` + membership fields; `SourceHealthItem.currency: HealthDimension` |
| `backend/api/admin/data_sources.py` | `_to_out` passes persisted membership truth through |
| `backend/api/admin/sync_runs.py` | New `_currency_dim()` (reads persisted truth only — no live enumeration); `currency` factors into `_overall_health` (degraded ⇒ ACTION_REQUIRED, same tier as connectivity/consistency) |
| `admin/src/types/api.ts` | `DataSource.membership_*`; `SyncHealthItem.currency`; unsupported label |
| `admin/src/lib/dataSourceOps.ts` | `operatorStateOf` gains `membershipStatus`: stale ⇒ 成员漂移 / failed ⇒ 对账失败 (never 正常; priority after 同步失败); unsupported/NULL leave legacy rendering untouched |
| `admin/src/lib/dataSourceObservability.ts` | `unsupported: 不适用` label (neutral) |
| `admin/src/pages/DataSources.tsx`, `admin/src/pages/DataSourceDetail.tsx`, `admin/src/components/dataSources/SourceHealthPanel.tsx` | Pass persisted truth through; health panel renders 上游成员对账 card when present (defensive for cached payloads) |
| `tests/conftest.py`, `tests/api/admin/conftest.py` | Shared test-DB engines run the idempotent migration after `init_db` (create_all does not add columns to existing tables) |
| `tests/pipeline/test_sync_lifecycle.py`, `tests/services/test_sync_delta_counts.py` | Counter assertions updated to requirement-13 semantics (orphan ops no longer in `items_*`; additive delta keys in exact-dict expectation) |

## 3. Design decisions (frozen-requirement traceability)

1. **Authority**: enumeration always does a real `git fetch + reset --hard` per branch inside `membership_source_ids()` — it never trusts the "remote appears unchanged" verdict that caused the #71 blackout swallow. The working tree after reset **is** the authoritative snapshot (requirement 3).
2. **Set-difference, not events**: `stale_set = ledger_serving(active/missing_candidate) − enumeration`. A deletion missed for any reason is caught on the first post-blackout round (requirements 2, 4).
3. **Retirement**: `tombstone_document` only — logical delete, immediate exit from the serving set (the retrieval filter derives active ordinals from `SERVING` documents), physical purge remains GC's exclusive jurisdiction (requirement 5). Re-appearance upstream restores automatically via the existing activation path (`activate_document_version` resets lifecycle to active), so a tombstone can never permanently hide a document that comes back.
4. **Kill-safety**: retirement = one transaction (commit ⇒ atomic; kill ⇒ full rollback, no half-retired state); `persist_membership_truth` runs strictly after it. A failed round persists `membership_status=failed`, downgrades SyncLog to `partial` (window does not advance — the next round re-covers), and healthy documents are untouched (requirement 8).
5. **Counter separation**: `items_deleted` = document tombstones this round (window-detect + membership-retire are both document deletions); `stale_detected` / `stale_retired` / `membership_status` carry the membership truth; `ledger_rebuilt_count` / `orphan_vectors_retired` carry projection-repair counts that previously masqueraded as `items_new`/`items_deleted` (requirement 13).
6. **Health separation**: `currency` is its own dimension read from persisted columns; PG↔Weaviate `consistency` untouched (requirements 10-12).
7. **Optional capability**: `membership_source_ids` is discovered via `getattr`; the `DataSourceConnector` Protocol is unchanged — filesystem/woocommerce/web_crawl require zero modification (requirement 18).

## 4. RED → GREEN evidence

RED (pre-implementation, all failing for feature-missing reasons):
- `tests/services/test_membership_currency.py` → `ModuleNotFoundError: backend.services.membership_currency`
- `tests/scripts/test_reconcile_membership_script.py` → `ModuleNotFoundError: scripts.reconcile_membership`
- `tests/api/admin/test_membership_health.py` → 5× ERROR at setup (`scripts.migrate_add_membership_currency` missing / columns absent)
- `tests/pipeline/test_sync_membership.py` → S1-S9 FAILED (behavior absent)
- `tests/connectors/test_github_membership.py` → M1/M2 FAILED (no `membership_source_ids`)
- `admin/tests/dataSources/dataSourceOpsMembership.test.ts` → 3 failed / 2 passed

GREEN (final):
- backend acceptance: `tests/services/test_membership_currency.py` (12) + `tests/pipeline/test_sync_membership.py` (9) + `tests/api/admin/test_membership_health.py` (5) + `tests/scripts/test_reconcile_membership_script.py` (3) + `tests/connectors/test_github_membership.py` (3) = **32 passed**
- vitest: **549 passed / 0 failed** (549 = 540 baseline + 5 new + 4 added on main since r3 measurement)
- admin `tsc -b`: exit 0

Acceptance-scenario coverage map (authorization list → test):
- delete → R1, S1
- rename/move → R2, S2
- deletion missed across sync blackout → S1 (empty delta round), S6
- remote-SHA no-change → S1 (fetch_changes=[] + fetch_deleted=[] still reconciles)
- stale provenance removed from serving → S6 (`active_generation_ordinals` before [0,1] → after [0])
- authoritative-currency health degradation → H1, H4 (`currency.state=degraded`, overall ≠ HEALTHY)
- Admin false-healthy prevention → H1 + `dataSourceOpsMembership.test.ts` (stale/failed never 正常)
- kill-safe reconciliation → R6, S5 (atomic rollback, truth=failed, SyncLog=partial)
- repeated-sync convergence → R3, S7 (second round stale=0, stable)
- unrelated healthy documents untouched → R1/R2/S2/S6/C2 assertions
- exact #71 NE503-class reproduction → S6 (stale path + i18n twin + deleted successor, blackout + short-circuit, all retired, serving projection excludes them)

## 5. Full regression evidence

- `pytest -q` **candidate full suite**: **2720 passed / 4 failed / 8 skipped** (63 min). The 4 failures are cross-file order/state-dependent aggregate tests (`test_analytics_business.py::test_business_overview_geo_pct_and_90d`, `test_leads.py::test_business_overview_new_leads_semantics`, `test_tech_perf.py::test_tech_perf_returns_kpi`, +1 same-class name truncated by log tail): all pass in isolation AND within the full `tests/api/admin` directory run (465 passed / 0 failed).
- `pytest -q` **pristine main baseline** (`origin/main f4e6751`, same day, same shared DB): **2689 passed / 4 failed / 7 skipped** — a **disjoint** flake set (`tests/scripts/test_recovery_semantics.py` A3/B1/B2/B3, all of which PASSED in the candidate run).
- Verdict: the suite carries ~4 order-flaky failures per full run on both revisions (different sets each run, shared test-DB state sensitivity). **The candidate introduces zero regression signal**: +32 new tests all green; every flake on either revision passes outside full-suite ordering; no candidate-area test appears in either flake set.
- `vitest run` (admin): 549 passed / 0 failed (8 pre-existing fixture failures were caused by the new required `SyncHealthItem.currency` in test fixtures + a worktree environment artifact for `dompurify` resolution; both resolved — fixture-agnostic defensive panel render + root `node_modules` symlink; zero production-code compromises).
- `tsc -b` (admin): clean.
- Test-infra updates required by the additive model (documented, behavior mandated by the authorization): `tests/conftest.py` / `tests/api/admin/conftest.py` run the idempotent migration; 5 assertions in 2 legacy test files updated from the overloaded counter semantics to the requirement-13 semantics.

## 6. Migration / data-correction implications

- **Migration** `scripts/migrate_add_membership_currency.py`: purely additive (5 NULL-initialized columns on `data_sources`; legacy rows read as `unknown`, never degraded). No data rewrite, no backfill, idempotent, deploy-bridge compatible (same pattern as `migrate_add_sync_delta_counts.py`).
- **Automatic correction on deploy**: with this code deployed, the next cron round per GitHub source reconciles its stale set automatically (that is I1/I2 convergence working as designed). For wiki-documents-local this will retire the 24 stale rows found in the #71 investigation (12 en + 12 i18n); the corpus-wide recompute at execution time may differ — by design nothing is hard-coded.
- **Authorized manual correction** (NOT executed): `scripts/reconcile_membership.py --source <id>` produces the exact dry-run plan (per-path + chunk counts, JSON-serializable for review); `--apply` executes with the same tombstone semantics and persists truth. Production execution requires independent PROD_MUTATION_AUTHORIZATION per the header contract.
- **What this changes operationally**: after deployment, `wiki-documents-local` (and any other GitHub source with drift) will report `sync_log.status=partial` + `membership_status` transitions during the reconciliation round; `items_deleted`/`stale_retired` become the audit trail. Admin shows the drift badge until the round completes.
- **Vector cleanup**: tombstoned documents leave the serving set immediately; physical vector purge remains with the existing GC policy (manual CLI, retired-generation retention) — unchanged scope.

## 7. Scope audit (requirement 18) — findings for Role A, NOT implemented

- **The capability is deliberately optional** (getattr discovery; Protocol unchanged). filesystem/woocommerce/web_crawl rounds now persist `membership_status=unsupported` (neutral; health `unsupported: 不适用`; no degradation, no false claim).
- **web_crawl** is structurally closest: its full-round `fetch_deleted` membership diff + `commit_membership_snapshot` (W6) is the same set-difference semantics; a `membership_source_ids()` returning its persisted snapshot ∪ live enumeration would unify the two paths. Estimated effort: small. Reviewable as a follow-up without touching #71's contract.
- **filesystem**: trivial to cover (`os.walk` on `root_path` with the same exclusion filters). **woocommerce**: feasible (API list-all with pagination). Both would move from `unsupported` to real currency truth. Flagged for a future authorized track; zero code changed here.
- **Non-goals kept**: no citation filtering, no URL liveness probing, no NE503 special-casing, no `set_successor`/rename-lineage wiring (P2).



---

## R2 REVIEW REMEDIATION (ROLE A: CHANGES REQUIRED — both blockers corrected)

Role A verdict on R1 (`c556652`): root cause + core design ACCEPTED; two release blockers. No redesign performed; deltas are exactly the two blockers + their regression guards.

### BLOCKER 1 — production migration was not registered — FIXED (commit `e4f7913`)

- **Manifest delta (exact)**: `deploy/prod/migrations.json` `migrations[]` — appended `"scripts/migrate_add_membership_currency.py"` after `scripts/migrate_add_conversation_id_policy.py`. The 6 existing entries are unchanged and in original order. The membership migration is included **exactly once**.
- **Migration planner evidence** (fail-closed parser `scripts/release_migration_plan.py`, run against the FINAL candidate SHA `84173d3`):
  - command: `python3 scripts/release_migration_plan.py --tag v1.6.3-r4 --sha 84173d3… --repo-root .`
  - result: **exit 0**, `PLAN SOURCE: manifest@84173d30e18a`, plan lines = the 6 existing entries + `scripts/migrate_add_membership_currency.py` (last, exactly once).
- **Idempotency + legacy-NULL proof** (scratch database `ask_ai_m71_proof`, dropped afterwards; production untouched):
  1. pre-migration `data_sources` (no membership columns) created; 2 legacy rows inserted;
  2. `migrate(engine)` run **twice** — both runs exit OK ("data_sources membership currency columns present");
  3. after: exactly the 5 membership columns present; both legacy rows retain `membership_status=NULL` and all membership fields NULL (**legacy rows remain NULL/unknown as designed; no backfill**); row count unchanged (2).
- **Regression guard (RED-1)**: `tests/scripts/test_membership_migration_manifest.py`
  - M1: manifest registers `scripts/migrate_add_membership_currency.py` exactly once and every entry exists in-tree — **failed on the R1 candidate** (count 0 == 1 assertion) and passes after registration;
  - M2: the migration's `_EXPECTED_COLUMNS` must equal exactly the `membership_*` columns on the `DataSource` model — a future candidate adding/removing these schema-dependent fields without updating migration+manifest goes red at test time instead of at deploy time.

### BLOCKER 2 — truth persistence was best-effort — FIXED (commit `84173d3`)

Frozen semantics implemented exactly as specified (A–D); no best-effort telemetry remains:

- `persist_membership_truth` now raises the dedicated **`MembershipTruthPersistenceError`** for **every** failure mode (DB write outage; source-row missing). Nothing is swallowed.
- (A) reconcile OK + persist OK → normal result; `current`/`stale` per residual drift (unchanged — S1/S7/R8 stay green).
- (B) retirement committed + truth write fails → round `partial`; `error_detail` contains a deterministic `membership truth persistence failed: …`; `delta_counts` carries **no** `membership_status` claim (no false current); committed tombstones are NOT rolled back; the next round re-derives truth and persists it (convergence proven).
- (C) reconciliation failure → previously accepted fail-closed behavior preserved; if the additional `failed`-truth write also fails, both facts are surfaced in `error_detail` and no membership_status claim is made.
- (D) unsupported connectors: a failed `unsupported`-truth write is equally visible (round `partial`, deterministic error_detail, no fabricated persisted truth).

**RED evidence** — DB-commit-level injection (`_truth_commit_failing_factory`: commit raises only when the session holds a dirty DataSource with `membership_status` set, so SyncLog/SyncRun/schedule writes are unaffected) on the R1 candidate:
- `test_t1_truth_persistence_failure_is_never_success_or_current` — FAILED on R1 with `assert 'success' == 'partial'` (the exact blocker: round reported success/current while truth was not persisted);
- `test_t2_tombstones_survive_failure_then_next_round_establishes_truth` — FAILED on R1 (same root);
- `test_t3_unsupported_truth_persistence_failure_is_visible` — FAILED on R1 (same root).

**GREEN** (post-fix):
- T1: round `partial`; error_detail names truth persistence; delta has no `current`; persisted `membership_status` stays NULL (nothing fabricated);
- T2: tombstones remain `deleted` after the failed-truth round (round `partial`); round 2 (healthy persistence) ⇒ `success`, `membership_status=current`, `stale_detected=0` — next-run re-establishment proven;
- T3: unsupported truth-write failure ⇒ `partial` + visible error, no fabricated `unsupported`;
- R11 updated: missing source row now raises `MembershipTruthPersistenceError` (never silent);
- C4 (new, correction CLI): `apply_plan` under truth-write outage raises the dedicated error; tombstones remain committed; CLI exits 1 with an explicit error;
- RED-5: normal success paths unchanged (S1/S7/R8 green).

### R2 changed files (delta on top of R1)

| File | Change |
|---|---|
| `deploy/prod/migrations.json` | + `scripts/migrate_add_membership_currency.py` (additive position) |
| `backend/services/membership_currency.py` | `MembershipTruthPersistenceError`; `persist_membership_truth` never swallows (row-missing also raises) |
| `scripts/sync.py` | `_membership_truth_persist_failed` unified handling; dedicated-error handling on all three paths (unsupported / reconcile-success / reconcile-failure) |
| `scripts/reconcile_membership.py` | CLI surfaces truth-persistence failure (exit 1; tombstones remain) |
| `tests/scripts/test_membership_migration_manifest.py` | NEW: M1/M2 release-contract guards |
| `tests/pipeline/test_sync_membership.py` | NEW T1/T2/T3 + `_truth_commit_failing_factory` injection helper |
| `tests/services/test_membership_currency.py` | R11 updated to explicit-failure contract |
| `tests/scripts/test_reconcile_membership_script.py` | NEW C4 |

### Harness findings caught by the R2 full-suite run (disclosed, fixed, re-run)

The first R2 full-suite run surfaced **4 candidate-caused failures** in mock-based legacy sync harnesses (tests/scripts/test_sync_coverage.py ×2, test_sync_db.py ×1, test_sync_gap_heal.py ×1) — NOT flakes, and exactly why the full regression was re-run rather than dismissed:

- MagicMock connectors auto-sprout a `membership_source_ids` attribute → the capability check admitted them → reconciliation exploded against mock sessions → rounds downgraded to `partial` against legacy `success` assertions;
- test_sync_db's window test additionally never seeded a `data_sources` row — under the R2 semantics the unsupported-truth write now fails loudly on a missing row (which is the mandated behavior, demonstrated for real against a live DB).

Fixes (commit `b60cba3`, harness-scope only, production code untouched): legacy harnesses declare membership-scope insulation (`pipeline._session_factory = None`, mirroring sibling cases) / seed the DataSource row where the real truth-write path is exercised. The dedicated membership suites (real DB) remain the authority for the new semantics.

### Scope audit (R2)

Untouched as ordered: `membership_source_ids` design, set-difference semantics, tombstone semantics, GitHub-only scope, Admin UX design, #72/#75/#77/#78, production data. No merge, no deploy, no production migration, no production reconciliation, #71 open, no tag created.

## 8. Run record

- Worktree: `ask-ai/.worktrees/issue71-membership-20260915` (branch `remediation/issue71-membership-reconciliation-20260915`, base `origin/main f4e6751`)
- R1 full suite (contended by an accidental concurrent run — timing not comparable): 2720 passed / 4 failed / 8 skipped — 3807s.
- Main baseline full suite (same day, contended): 2689 passed / 4 failed (disjoint flake set: recovery_semantics) / 7 skipped — 3574s.
- **R2 full suite #1** (`84173d3`, uncontended, 151s): **2726 passed / 4 failed / 8 skipped** — all 4 candidate-caused mock-harness failures (detailed in the harness-findings section) → fixed in `b60cba3`.
- **R2 final full suite** (uncontended, 140s): **2721 passed / 7 failed / 3 errors / 7 skipped**. Classification (review bar: independently reproduced on main under equivalent conditions):
  - `test_recovery_semantics` A3/B1/B2/B3 ×4 — reproduced on main full suite, both runs;
  - `test_sync_executor_loop::…bounded_retry` ×1 — reproduced on main, isolation and full-suite;
  - `test_v140_existing_db_upgrade_path` ×1 — failed on MAIN's own uncontended run, absent on candidate (flake-set membership varies run-to-run on main itself);
  - `test_documents_pk` ×3 setup errors, `test_generation_builder`, `test_projection_rebuild` ×2 — shared-test-DB order-churn class; ALL pass in isolation on the candidate;
  - **zero candidate-area failures**; the 4 candidate-caused failures from R2 run #1 are FIXED and absent from the re-run.
- **Main full suite under identical conditions** (f4e6751, uncontended, 130s): **2704 passed / 6 failed / 7 skipped** (recovery ×4 + executor ×1 + v140 ×1) — main carries the same flake class with varying membership.
- vitest: 549/549 · admin `tsc -b`: clean · ruff: parity with main.
- Revision lineage: R1 candidate `c556652` (superseded) · R2 BLOCKER 1 `e4f7913` · R2 BLOCKER 2 `84173d3` · R2 harness insulation `b60cba3` · FINAL `92c1439` (report finalization).
- Migration planner on FINAL SHA `92c1439`: **exit 0**, PLAN SOURCE manifest@92c1439, 7 entries — the 6 prior entries intact and in original order + `scripts/migrate_add_membership_currency.py` last, exactly once.
- Reports force-added under `/docs/` (gitignored path, per dual-landing protocol).
