# #71 REMEDIATION = CANDIDATE READY (implementation complete; NOT merged, NOT deployed, NO production mutation)

Track: ISSUE_71_REMEDIATION (authorized) · Base: `origin/main f4e6751` · Candidate: `remediation/issue71-membership-reconciliation-20260915` · Full report: `docs/engineering/tasks/issue71-membership-reconciliation-remediation.md` (candidate branch)

## What was implemented (frozen requirements 1-18)

1. **Authoritative membership reconciliation for GitHub sources** — `GitHubConnector.membership_source_ids()`: per-branch unconditional `git fetch + reset --hard`, then a path-only walk applying the ingestion-identical filter face (`file_types` + exclusion policy + technical safety). This is the authoritative in-scope membership snapshot; it does **not** trust the remote-SHA "no change" verdict that swallowed the 08-19 rename during the production blackout.
2. **Set-difference reconciliation every round** — `scripts/sync.py::_reconcile_membership_for_source` runs in `_sync_one` on **both** paths: no-change rounds (SHA short-circuit) and normal rounds. `stale_set = ledger serving (active/missing_candidate) − authoritative`; retired via the existing `tombstone_document` semantics (logical delete; immediate exit from the serving projection; physical purge stays GC-only). Correctness has **zero** dependence on git event windows or `fetch_deleted` history. Upstream re-appearance auto-restores via the existing activation path.
3. **Atomic + kill-safe** — retirement is a single transaction (kill ⇒ full rollback, no half-retired state); the persisted currency truth is written **only after** that commit. Any reconciliation failure ⇒ `SyncLog.status=partial` (window does not advance), `membership_status=failed`, ledger untouched.
4. **Idempotent convergence** — repeated rounds re-derive truth; stale set converges to ∅ (R3/S7).
5. **Persisted authoritative-currency truth** — 5 additive columns on `data_sources` (`membership_status` ∈ {current, stale, failed, unsupported}, `membership_checked_at`, `membership_stale_detected`, `membership_stale_retired`, `membership_detail` JSONB). Migration `scripts/migrate_add_membership_currency.py`: purely additive, idempotent, no backfill (legacy rows read `unknown`, never degraded).
6. **Health semantics** — `/admin/data-sources` returns the persisted truth; `/admin/sync-health` gains a **separate** `currency` dimension (read-only from persisted columns — no live GitHub enumeration for rendering); `currency=degraded` ⇒ overall `ACTION_REQUIRED` (same tier as connectivity/consistency). Admin UI: source badge shows **成员漂移** (stale) / **对账失败** (failed) — never 正常 — while drift is unresolved; health panel renders an 上游成员对账 card. PG↔Weaviate `consistency` remains its own dimension.
7. **Counter hygiene** — `stale_detected` / `stale_retired` / `membership_status` are separately observable in `delta_counts`; orphan-vector operations moved out of `items_new`/`items_deleted` into additive `ledger_rebuilt_count` (document) / `orphan_vectors_retired` (chunk) keys. `items_deleted` = document tombstones (window-detect + membership).
8. **Authorized correction mechanism** — `scripts/reconcile_membership.py`: dry-run default producing an exact, JSON-serializable plan (per-path + chunk counts); `--apply` **recomputes the stale population from authoritative truth at execution time** (nothing hard-coded) and retires via the same tombstone semantics, then persists truth. Not executed against production.
9. **Rename lineage** (`set_successor`) intentionally not wired (P2 per authorization): old identity retires, new identity ingests, no stale double-serving — proven in R2/S2.
10. **Scope** — filesystem / woocommerce / web_crawl: zero forced change (optional capability via `getattr`; Protocol untouched). They now persist `membership_status=unsupported` (neutral 不适用, not degraded). Scope-expansion findings for Role A: web_crawl's W6 snapshot diff is the same semantics and could unify; filesystem (os.walk) and woocommerce (API list-all) are feasible follow-ups.

## Verification

- **Acceptance (RED→GREEN)**: 32 backend tests + 5 UI tests, all RED pre-implementation (module/column/behavior missing), all GREEN post:
  - delete (R1/S1) · rename/move (R2/S2) · blackout-missed deletion (S1) · remote-SHA no-change (S1) · stale provenance out of serving projection (S6: generation ordinals [0,1]→[0]) · currency health degradation (H1/H4) · Admin false-healthy prevention (H1 + UI mapping tests) · kill-safe (R6/S5: atomic rollback, truth=failed, SyncLog=partial) · convergence (R3/S7) · unrelated healthy docs untouched (R1/R2/S2/S6/C2) · **exact #71 NE503-class reproduction** (S6: stale path + i18n twin + deleted successor with blackout + SHA short-circuit ⇒ all retired, serving excludes them).
- **Regression**: full `pytest` suite + admin `vitest` (549/549) + `tsc -b` clean — final counts in the branch report. Counter-semantics updates in 5 legacy assertions mandated by requirement 13 (orphan ops out of `items_*`), plus shared test-conftest runs the idempotent migration (create_all does not add columns to existing test DBs).
- **Lint**: repo-wide ruff baseline identical to main (284 = 284) — zero new debt.

## Deployment / correction implications (Role A decisions, not executed)

- Migration is deploy-bridge compatible (additive, idempotent).
- After deploy, each GitHub source's next cron round auto-reconciles its stale set (I1/I2 convergence by design); wiki-documents-local's 24 investigation-era rows are expected to retire on the first round, with the corpus-wide number recomputed at runtime.
- Manual authorized correction remains available via `scripts/reconcile_membership.py` (dry-run plan → review → `--apply`) under independent PROD_MUTATION authorization.
- Operational note: during a reconciliation round the source reports `partial` + drift badge until completed; `stale_retired` is the audit trail.

## Boundaries respected

No merge to main · no deploy · no production reconciliation · no production mutation · #71 remains open. STOP at CANDIDATE READY.

**Labels**: implementation behavior claims above are PROVEN by the committed tests; production-corpus numbers referenced from the #71 investigation comment (5673543854) and recomputed at execution time by design.
