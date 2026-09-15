# INC-WEB-EMBED-413 REMEDIATION Report — Admin Repair System-Owned Recovery Routing

- Date: 2026-09-15 (Asia/Shanghai)
- Status: **INC_WEB_EMBED_413_REMEDIATION = CANDIDATE READY**
- Base candidate: `57410396a8fed964def0ee200611cf928bd30bc3` (root cause findings accepted, not reopened)
- Remediation branch: `inc/web-embed-413-20260915` (same track, worktree `.worktrees/inc-web-embed-413-20260915`)
- Remediation commit: the tip of `inc/web-embed-413-20260915` carrying this report
- Report path: `reports/inc-web-embed-413-remediation-20260915.md`
- Boundaries honored: no deploy, no corrective-migration execution, zero production contact.

## 1. Blocker addressed

Role A blocker: admin single/bulk repair treated an authoritative persisted chunk over
`max_chunk_chars` as a **terminal** repair failure ("须经 sync 源重建恢复") — honest but
not product-conformant. The administrator must not sequence `repair → failed → click Sync`
manually.

**Frozen product truth implemented**: the administrator only chooses 修复此知识 /
一键修复全部; the system owns the mechanism selection:

| classification | detection | mechanism |
|---|---|---|
| REPLAYABLE | current version + complete persisted copies + all to-replay texts within the embedding character contract | persisted-copy replay (unchanged cheap path) |
| REBUILD_REQUIRED | no current version / no persisted copies / authoritative set missing rows / text over `max_chunk_chars` | authoritative source rebuild requested via the **existing** sync handoff seam |
| UNRECOVERABLE | real upstream failure (embed failure, write failure, verify inconsistency, handoff DB failure) | truthful `failed` task |

## 2. The seam (narrowest existing orchestration point — no duplicated rebuild logic)

`backend/services/sync_requests.py` → `sync_requests` table → `scripts/sync_executor_loop.py`
(claim FOR UPDATE SKIP LOCKED, serial drain, MAX_TOTAL_ATTEMPTS bounded retries) →
`scripts/sync.py --source <id>`.

The seam gained one **flavor**: `sync_requests.kind`:

- `NULL` — existing incremental sync semantics (legacy rows unaffected, zero backfill);
- `"rebuild"` — executor appends `--reindex` to the runner argv → **the already-accepted
  P1-E full generation rebuild path** (`fetch_all → build_generation(force_rebuild=True) →
  verify → atomic activation`), where `_enforce_char_limit` applies (acceptance 6).
  Scope is explicitly source-scoped; healthy knowledge is not corrupted (rebuild is the
  accepted reconstruction path with serving projection intact during rebuild); repeated
  rebuilds converge (new clean versions; subsequent syncs classify UNCHANGED).

Concurrency/idempotency preserved:

- dedup key = `(source_id, kind)`: an in-flight rebuild coalesces duplicate rebuild
  requests (`already-running`, same request id — acceptance 7); it does **not** get swallowed
  by an in-flight plain sync (whose healthy-verifier run would not rebuild the oversized
  document), and vice versa. Distinct-key requests are drained serially by the executor —
  no concurrent sync on the source is introduced.
- `submit_sync_request` raises `ValueError` on unknown kinds (never silently downgraded to
  a plain sync — that would fake the handoff).

## 3. Changed files

| file | change |
|---|---|
| `backend/db/models.py` | `SyncRequest.kind` nullable column (additive). |
| `backend/db/session.py` | `ensure_sync_request_kind_column` (ADD COLUMN IF NOT EXISTS) wired into `init_db` (house pattern; test DBs get the column automatically). |
| `scripts/migrate_add_sync_request_kind.py` | **New** idempotent additive migration; registered in `deploy/prod/migrations.json` (executes via the authorized deploy bridge; **not** executed now). |
| `backend/services/sync_requests.py` | `submit_sync_request(..., kind=None)` + kind-aware `find_active_request` dedup; unknown kind → `ValueError`. |
| `scripts/sync_executor_loop.py` | `build_runner_argv(..., kind=None)` appends `--reindex` for `"rebuild"`; `run_runner`/`execute_request` pass `req.kind` through. All existing executor semantics (claim, recovery retries, attempts cap, finalize) untouched. |
| `backend/services/document_repair.py` | `execute_repair_task` classification: REPLAYABLE → replay (unchanged); no-version / no-persisted-copies / authoritative-set-incomplete / over-contract → `_request_source_rebuild` (handoff submit + task `status="rebuild_requested"`, `stage="rebuild_request"`, `result={repair_mode: source_rebuild_requested, reason, detail, sync_request_id, sync_request_state, rebuild_path}`); zero embed calls on the rebuild route; handoff DB failure → truthful `failed`. |
| `backend/api/admin/data_sources.py` | repair-all aggregates: `failed = eligible - succeeded - rebuild_requested`; items carry `sync_request_id`. |
| `backend/api/admin/schemas.py` | `BulkDocumentRepairOut.rebuild_requested: int = 0`; `BulkDocumentRepairItem.sync_request_id: int | None`; status comment now includes `rebuild_requested`. |

## 4. Tests (all RED before remediation implementation, GREEN after)

`tests/api/admin/test_data_sources_track_c.py`:

- `test_u8_repair_oversized_routes_to_source_rebuild_without_embed` (remediates the
  Fix-3-era terminal-fail test) — oversized eligible doc + single repair →
  `rebuild_requested`, `reason=persisted_text_over_contract`, `max_length` in detail,
  **zero embed calls**, exactly one `sync_requests` row `kind="rebuild"` pending. *(1, 5)*
- `test_u14_bulk_mixed_routes_replay_rebuild_and_truthful_failure` — mixed bulk:
  replayable → `succeeded` via cheap replay; oversized → `rebuild_requested` with
  `sync_request_id`; embedder-failing doc → truthful `failed`; aggregates
  (`succeeded/failed/rebuild_requested`) exact; exactly one rebuild request row for the
  source; every text that reached the embedder ≤ contract. *(2, 4, 5, 10)*
- `test_u8_repair_no_current_version_routes_to_rebuild` — no-version eligible doc routes
  to the rebuild handoff (system owns mechanism; was terminal refusal).
- `test_u8_repair_rebuild_submit_failure_is_honest_failure` — handoff write failure →
  task `failed` with the real error; never faked. *(9)*
- `test_u8_repair_healthy_replay_creates_no_rebuild_request` — healthy replayable doc
  still uses the cheap replay path and creates **no** rebuild request. *(3)*
- `test_u14_bulk_repair_returns_authoritative_aggregate_and_excludes_healthy` — updated to
  the frozen truth: the no-version attention doc is now `rebuild_requested` (was `failed`),
  retired/healthy remain excluded. *(8)*

`tests/scripts/test_sync_executor_loop.py`:

- `build_runner_argv` `kind="rebuild"` → argv contains `--reindex`; default kind does not. *(6)*
- `test_submit_sync_request_dedups_by_source_and_kind` — same-key dedup coalesces;
  distinct keys do not block each other. *(7)*
- `test_execute_request_passes_rebuild_kind_to_runner` — `req.kind` reaches the runner
  (flavor never dropped in transit).

`tests/db/test_migrate_sync_request_kind.py` — legacy shape (no kind column) → migration
adds it; idempotent re-run; legacy rows NULL.

## 5. Acceptance map

1. Oversized + single repair → rebuild handoff (test 1). ✓
2. Oversized + repair-all → included automatically, `rebuild_requested` item, request row created by the operation itself — no second manual Sync (tests 2, 10). ✓
3. Healthy replayable → cheap replay, no rebuild request (test 5). ✓
4. Mixed bulk → truthful aggregate incl. genuinely failed item (test 2). ✓
5. No oversized text reaches the embedder (tests 1, 2: zero calls / ≤contract assertion). ✓
6. Rebuild = accepted ingestion path (`sync.py --reindex` → `build_generation(force_rebuild=True)`; `_enforce_char_limit` enforced since #45; existing builder char-contract tests cover the path). ✓
7. Duplicate/concurrent repair bounded: task idempotency keys + source FOR UPDATE NOWAIT + `(source_id, kind)` request dedup + serial executor + MAX_TOTAL_ATTEMPTS (existing) + dedup test. ✓
8. Retired/non-eligible excluded (unchanged eligibility formula; updated u14 assertions). ✓
9. Real unrecoverable failures stay failed: embed failure → `failed` (test 2); handoff DB failure → `failed` (test 4). ✓
10. RED→GREEN proof that repair-all handles an eligible oversized legacy document without a second manual Sync (test 2: the operation creates the `kind="rebuild"` request row itself). ✓

## 6. Verification

- Targeted: Track C suite 27/27; executor suite 13/13; migration test green; wave2 obligations + golden regression + sync run core green (1154 passed across admin+scripts+services).
- Full CI-equivalent regression: see "Full regression" below.

## 7. Boundaries

No deploy; corrective migration still registered-but-not-executed; zero production
contact; admin credential remediation untouched.
