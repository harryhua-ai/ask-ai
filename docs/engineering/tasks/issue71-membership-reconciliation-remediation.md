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

## 8. Run record

- Worktree: `ask-ai/.worktrees/issue71-membership-20260915` (branch `remediation/issue71-membership-reconciliation-20260915`, base `origin/main f4e6751`)
- Candidate full suite: 2720 passed / 4 failed (order-flakes, disjoint from candidate surface) / 8 skipped — 3807s
- Main baseline full suite (same day): 2689 passed / 4 failed (disjoint flake set: recovery_semantics) / 7 skipped — 3574s
- vitest: 549/549 · admin `tsc -b`: clean · ruff: 284=284 parity with main
- Implementation + tests + reports force-added under `/docs/` (gitignored path, per report dual-landing protocol) in commit `2472720` on the candidate branch.
