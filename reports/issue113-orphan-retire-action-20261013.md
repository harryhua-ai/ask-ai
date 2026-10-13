# Issue #113 Execution Report — Scope-External Orphan Retirement Action

- Role: B (executor)
- Date: 2026-10-13
- Claim: `harryhua-ai-20261013T125236-4655f692`
- Branch: `agent/113/0e4907e3` (base 92ee793)
- Contract: `ght contract-digest 113` = `e727c7bcf198c474eaec4cd693e77909dcfeed7b778ace6f4758d2d426d3d93b`

## What was delivered

Manual, explicit, auditable retirement for `missing_candidate` rows whose
absence is classified scope-external (A-3 policy-absence), plus truthful
Needs-Attention banner classification. No automatic retirement of out-of-scope
rows; A-2/A-3 semantics untouched.

## AC evidence

### AC1 — Admin API + UI retire action (confirm + audit + existing semantics)

- Endpoint: `POST /api/admin/data-sources/{id}/documents/retire`
  (`backend/api/admin/data_sources.py`, `retire_scope_external_documents`).
  - RBAC: admin only (`require_role("admin")`); viewer/editor → 403.
  - Hard gates: `confirm=true` and non-empty `reason` → 400 otherwise.
  - Modes: explicit `doc_source_ids` (deduplicated, order-preserving) or
    `all_scope_external: true` (server selects eligible rows).
  - Eligibility is server-adjudicated from `documents.metadata_['absence'].
    policy_reason` (the A-3 classification persisted at last complete
    discovery). Active rows, in-scope missing rows, foreign ids → per-row
    `refused` with reason; `DELETED` without a retirement record is refused
    (audit-rewrite protection).
  - Mutation reuses `confirm_absence_retirement` (lifecycle→deleted = immediate
    service withdrawal; `gc_eligible_at = retired_at + 7d`), `reason=manual`
    (closed vocabulary), `actor=admin:<email>`, evidence carries
    `policy_reason` + operator `justification` + mode. Absence state cleared.
    Single transaction; idempotent (`already_retired`, record untouched).
  - UI: row-level `退休` button on orphan rows (prompt for reason) and a
    banner-level retire flow with an explicit confirmation strip requiring the
    reason text (`admin/src/pages/DataSourceDetail.tsx`,
    `useBulkDocumentRetire`).
- Tests: `tests/api/admin/test_issue113_orphan_retire_action.py`
  - `test_retire_scope_external_orphans_with_a6_audit` (audit fields, 7d GC
    window, absence cleared, per-row status),
  - `test_retire_all_scope_external_mode`,
  - `test_retire_idempotent_on_already_retired`,
  - negatives: `test_retire_requires_explicit_confirmation`,
    `test_retire_requires_reason`, `test_retire_viewer_and_editor_forbidden`,
    `test_retire_refuses_active_inscope_and_unknown_rows` (asserts the in-scope
    row's A-2 absence state is preserved byte-for-byte).

### AC2 — Banner distinguishes repairable vs scope-external orphan

- `GET /documents` additive fields:
  `attention_scope_external_orphan_count`, `attention_repairable_count`,
  per-row `absence_policy_reason` (`backend/api/admin/schemas.py`).
- repair-all eligibility now excludes scope-external orphans
  (`_bulk_repair_eligibility` + `_scope_external_orphan_predicate`); the
  repairable count equals what repair-all will actually process.
  `test_repair_all_excludes_scope_external_orphans` proves orphans never enter
  the batch while in-scope missing rows remain repair-eligible.
- Frontend: `bannerActionsOf` + `attentionReasonClasses(..., orphanCount)` in
  `admin/src/lib/dataSourceOps.ts`; banner shows repair CTA only for the
  repairable count and a retire CTA for orphans (all-orphan case renders no
  repair button at all — the 179/179 production shape).
  Tests: `admin/src/lib/dataSourceOps.test.ts` (6 cases incl. clamp).

### AC3 — A-2/A-3 semantics unchanged

- No change to `backend/services/document_lifecycle.py`,
  `backend/connectors/filesystem.py` (`policy_absence_reason` byte-identical),
  A-2 constant, lifecycle vocabulary, GC timing, tombstone semantics.
- The retire endpoint consumes the existing retirement primitive only.
- Regression: `tests/scripts/test_fs_disappearance_retirement.py` +
  `tests/scripts/test_lifecycle_composition_u82_u25.py` — 11 passed;
  `test_issue25_lifecycle_detail.py` + `test_data_source_attention_summary.py`
  — 11 passed; repair-all suites — 10 passed; workspace/gate/track-C — 56
  passed.

### AC4 — Path-shape migration documentation

- `docs/operations/orphan-row-retirement-and-path-shape-migrations.md`: what
  scope-external orphan rows are, why upload-root/path-shape migrations create
  them at scale (2026-09-22, 179 rows), the migration checklist (whitelist is
  part of the migration; extension unfreezes A-2), detection via the new
  classification counts, the two sanctioned close-out paths, and the
  prohibited list.

## Test numbers

| Suite | Result |
| --- | --- |
| `tests/api/admin/test_issue113_orphan_retire_action.py` (new) | 9 passed |
| A-2/A-3 lifecycle regression (scripts) | 11 passed |
| `test_issue25_lifecycle_detail.py` + `test_data_source_attention_summary.py` | 11 passed |
| `test_bulk_repair_bounded_idempotency.py` + `test_repair_all_lock_progress.py` | 10 passed |
| workspace + repair gate + track C | 56 passed |
| admin vitest (`dataSourceOps.test.ts` + `dataSourceLifecycle.test.ts`) | 15 passed |
| `tsc -b` (admin + widget) | clean |

RED evidence: all 9 backend cases and 6/7 frontend cases failed before
implementation (404 on missing endpoint / missing schema fields / missing
helper); GREEN after.

## Known limitations

- Eligibility is adjudicated from the persisted A-3 classification (last
  complete discovery). If the whitelist was extended but no sync has run since,
  the endpoint will still retire an eligible row the admin explicitly confirms;
  this is documented in the endpoint docstring and the operations doc.
- `attention_scope_external_orphan_count` uses a Postgres JSONB predicate
  (admin API tests and production are Postgres-only by convention).
- Cross-directory pytest runs (tests/scripts + tests/api/admin in one
  invocation) hit a pre-existing shared-DB schema conflict (`relation users
  does not exist`) that reproduces on the clean base; run suites per
  directory (also per the repo's own operational guidance).
- This change delivers the capability only; no existing production row was
  retired and no production DB/reindex was touched.

---

# R2 Delta — physical absence proof (A REQUEST_CHANGES, 2026-10-13)

Reviewer blocking family: **configuration-policy exclusion is not evidence of
physical file loss.** The persisted `metadata_['absence'].policy_reason` was
treated everywhere as "file provably gone", so a row whose file still exists on
disk (excluded by `include_dirs`, or stale after a whitelist relaxation without
a discovery re-run) could be withdrawn by an admin bulk-retire and become
physically GC-eligible after 7 days. Fix keeps all R1 guarantees (explicit
admin confirm, per-row A-6 audit, active/in-scope refusal, A-2/A-3 frozen,
7-day GC timing, non-destructive whitelist path) and adds server-side proof.

## Mechanism (three server-side gates per row, fail-closed, in adjudication order)

1. **DB classification** (unchanged): `missing_candidate` ∧ non-null persisted
   `policy_reason`; `DELETED`+record → `already_retired`; active/in-scope →
   refused.
2. **Stale-classification guard** (new): the persisted `policy_reason` must be
   reproduced by the **current** source config
   (`FilesystemConnector.policy_absence_reason` replay at execution time —
   the connector is rebuilt from the DB row's current config, so any config
   change between the admin's confirmation and execution is caught).
   Mismatch (whitelist relaxed, filter dimension changed, connector without
   A-3 adaptation) → refused; operator must re-run discovery.
3. **Physical absence proof** (new): actual existence check on the absolute
   path resolved from the **current** source root — new duck-typed connector
   capability `FilesystemConnector.physical_absence_evidence(source_id)`
   (A-3 `policy_absence_reason` untouched; it deliberately never stats the
   filesystem). Verdicts:
   - `verified_absent` — root enumerable ∧ identity parses to a path inside
     the resolved root (symlink/`..` containment enforced, dangling symlinks
     count as present) ∧ `lexists` false → only then retired; proof persisted
     in the A-6 record as `evidence.physical_absence`
     (`method`/`root`/`resolved_path`/`checked_at`).
   - `present` → refused ("文件仍在盘上"): recoverable document, exclusion is
     not loss.
   - `unknown` (root unavailable — reuses the #100 fail-closed check; alien
     identity; path escaping the root; connector type without the probe, e.g.
     non-filesystem; probe exception; malformed evidence) → refused honestly;
     no withdrawal without proof.

`all_scope_external` selection stays DB-classified but every selected row goes
through gates 2–3; unverified rows come back per-row `refused` with an
actionable reason (never silently dropped, never in the mutating set).

## Honesty of banner/counts

- Banner line copy is now
  `N 项为范围外排除(超出知识源范围,存在性未知;显式退休前服务端会验证物理缺失)`
  — no "文件已丢失" claim anywhere in the banner/confirm/row copy; the loss
  claim is established per row only by the retirement adjudication and its
  audit record.
- `attention_scope_external_orphan_count` semantics documented as
  "scope-external **excluded** (existence unknown)"; schema/ops docs updated.
  A persistent "verified missing" count does not exist by design: verification
  is a point-in-time act at retirement, materialized in the response statuses
  and `metadata_['retirement'].evidence.physical_absence`.

## Files touched in R2

- `backend/connectors/filesystem.py` — new `physical_absence_evidence`
  (+ docstring boundary note on `policy_absence_reason`; A-3 logic untouched).
- `backend/connectors/base.py` — protocol docstring: optional capability note
  (Issue #113 pattern, like Issue #91).
- `backend/api/admin/data_sources.py` — `_build_retire_connector`,
  `_probe_physical_absence_batch`, `_verify_retire_readiness` (threadpool off
  the event loop), endpoint gates + evidence; docstrings de-absolutized
  (`_scope_external_orphan_predicate`, `_bulk_repair_eligibility`).
- `backend/api/admin/schemas.py` — count semantics docstrings.
- `admin/src/lib/dataSourceOps.ts`, `admin/src/pages/DataSourceDetail.tsx`,
  `admin/src/hooks/useDataSourceKnowledge.ts`,
  `admin/src/types/dataSourceWorkspace.ts` — copy/comments.
- `docs/operations/orphan-row-retirement-and-path-shape-migrations.md` —
  three-gate close-out path + proof-anchoring limitation (current `root_path`
  only; migrate-then-retire needs a manual old-root check).
- `tests/api/admin/test_issue113_orphan_retire_action.py` — fixture now
  provides a real enumerable root + config that reproduces the persisted
  classification; 5 new cases (see below).

## Test evidence (RED → GREEN)

New backend contract tests (all RED on a460e2d before the fix, GREEN after):

| Case | Proves |
| --- | --- |
| `test_retire_refuses_present_but_excluded_file` | file recreated on disk under an excluded prefix → `refused` ("仍在盘上"), row byte-identical, no retirement record |
| `test_retire_refuses_stale_classification_after_whitelist_relaxation` | whitelist relaxed without discovery → refused "分类陈旧" |
| `test_retire_refuses_when_source_root_unavailable` | root gone → refused UNKNOWN, row untouched |
| `test_retire_refuses_when_source_config_invalid` | config without `root_path` → refused UNKNOWN |
| `test_retire_bulk_mixed_states_adjudicates_per_row` | one bulk call: verified-absent retires; present / stale / path-escape identity / active / in-scope all refused per row with reasons; zero mutation spread |
| `test_retire_scope_external_orphans_with_a6_audit` (extended) | positive: verifiably-lost file retires with `evidence.physical_absence` (method/root/resolved_path/checked_at) in the audit record |

RED evidence: exactly the 6 contract-bearing cases failed on a460e2d
(8 unchanged passed); GREEN after the fix.

## R2 test numbers

| Suite | Result |
| --- | --- |
| `tests/api/admin/test_issue113_orphan_retire_action.py` (14 cases = 9 R1 + 5 new, 1 extended) | 14 passed |
| A-2/A-3 lifecycle regression (`test_fs_disappearance_retirement.py` + `test_lifecycle_composition_u82_u25.py`) | 11 passed |
| full `tests/api/admin/` directory | 539 passed, 4 failed — all 4 (`test_gap_export` ×2, `test_gap_observation`, `test_tech_answer_gaps`) reproduce identically on clean base a460e2d (pre-existing gap-window flakes, unrelated) |
| admin vitest `src/lib/dataSourceOps.test.ts` (single file, timeout-bounded) | 8 passed (7 R1 + 1 new negative-copy case) |
| admin vitest `tests/dataSources` + `DataSourcesAttentionReason` + `dataSourceLifecycle` | 197 passed, 25 failed — all 25 (`DataSourceDetailConvergence` 17, `DataSourceDetailTrackC` 7, `DataSources` 1) reproduce identically on clean base a460e2d (pre-existing mock drift from R1, unrelated to R2 copy changes) |
| `tsc -b` (admin) | clean |

## R2 known limitations

- The physical proof anchors on the **current** `root_path` resolution. If the
  upload root itself was migrated and files may still exist under the old root,
  the probe cannot see them; operators must verify the old location manually
  before retiring (documented in the ops doc).
- Only `filesystem` implements `physical_absence_evidence`; other source types
  refuse with UNKNOWN. In practice only filesystem rows can carry a non-null
  persisted `policy_reason` (woo always returns None, git/web never enter A-3
  reconciliation), so no legitimate flow regresses.
- The stale-classification guard compares classification **values**; a
  no-op config edit that reproduces the same classification does not block
  retirement (the classification, not the config bytes, is the truth).
- Pre-existing failures noted above (4 pytest / 25 vitest) are inherited from
  the base and out of R2 scope; no new failures introduced.
- No production row was retired; no production DB/reindex touched.

---

# R3 Delta — unsound absence-proof edges closed (A REQUEST_CHANGES, round 2)

Reviewer verdict on R2: direction and closed-loop evidence all stand; two
unsoundness points plus one same-family concurrency hazard remained in the
**physical absence proof** (one invariant family: destructive retirement
requires absence proof that is *valid, current, and identity-matched to the
source*). Same claim / branch / PR; this delta hardens exactly those edges.
All R1/R2 guarantees preserved (admin confirm+reason gates, per-row A-6 audit,
idempotency, 7-day GC, A-2/A-3 frozen byte-identical, active/in-scope refusal,
scope-excluded honest copy, repair-all exclusion).

## Blocker 1 — filesystem `unknown` was folded into `verified_absent`

R2's probe used `os.path.lexists`, which collapses **every** `OSError` into
`False`: an unreadable nested parent directory (`EACCES`/`EPERM`), a denied
mount, or an `EIO` fault all read as "file absent", so a *physically existing,
recoverable* file under an inaccessible subdirectory could be certified lost
and retired (physically GC-eligible after 7 days).

Fix (`FilesystemConnector.physical_absence_evidence`): the probe now calls
`os.lstat` (module alias `_lstat`, the deterministic test seam) and classifies
by errno — **only `ENOENT` yields `verified_absent`**; every other `OSError`
(`EACCES`, `EPERM`, `EIO`, `ELOOP`, `ENOTDIR`, …) yields `unknown` with an
actionable detail. `present` semantics unchanged (any existing node, including
dangling symlinks). Probe method token updated `filesystem.lexists` →
`filesystem.lstat`. The A-3 classifier (`policy_absence_reason`) remains
byte-identical — it still never touches the disk.

## Blocker 2 — checking only the current root never proved a historical loss

The filesystem ingestion chain persists the ingestion-time source root into
row provenance (`RawDocument.metadata['root']` → `documents.metadata_['root']`),
but R2 deliberately ignored it and probed only the *current* `root_path`.
Kill scenario: legitimate legacy content under old root A; current root B
healthy with no same-relative identity; persisted policy reason replays
unchanged → the server certifies `verified_absent` against B and authorizes
retirement/GC while the original file still sits under A.

Fix (server-side, covers the row's actual authoritative original location):

- current root == historical root → single-point check (all R2 flows);
- different → the same probe (same errno classification) runs against the
  historical root: `present` at the historical location → refused
  ("文件仍在盘上(历史摄取位置 …)"); `unknown` → refused;
  both `verified_absent` → eligible, and the A-6 proof gains
  `historical_absence` (`root`/`resolved_path`/`verdict`);
- provenance missing/malformed (non-string, relative, empty) or the
  historical root itself unreachable → honest `UNKNOWN` refusal.

No new migration pipeline, no automatic old-root scanning: only the location
the row itself records is checked.

## Same-family concurrency check — probe/commit race fenced at the persistence point

The endpoint loaded `DataSource`/`Document` without row locks, probed in a
threadpool, then committed retirements in the same session; a concurrent
source-config update, discovery restore, or file return could invalidate the
"current" classification/proof while the transaction still wrote stale ORM
state. Fix (minimal mechanism, no full-source locking, no new lifecycle
states) — a re-verification boundary at the only mutating point:

1. **Config fingerprint fence** — the fingerprint of the config fields the
   gates consume (`to_source_config` payload, sha256, sort_keys) is recorded
   before probing; immediately before commit the row is re-read
   (`populate_existing`) and the fingerprint compared. Drift → the whole
   batch is rejected with `409` and **zero writes** (rollback; retry against
   the current config is expected to succeed).
2. **Row-state fence** — staged rows are re-read with `populate_existing` and
   re-classified; a concurrent discovery restore (or delete) is refused
   per row and is **never overwritten** by stale in-session ORM state
   (stale-write protection); retirement mutates only the refreshed objects.
3. **Physical re-verification** — the probe batch (including the historical
   root check) re-runs at the commit boundary; a file that returns between
   the first probe and commit is caught and that row refused
   ("提交前复验未通过").

## RED → GREEN evidence (all RED on 43885fdd before this fix, GREEN after)

| Case | Proves |
| --- | --- |
| `test_physical_absence_permission_denied_is_unknown_not_verified_absent` (connector, chmod 000 nested dir + existing file; skipped for root) | nested permission failure must be `unknown`, never `verified_absent` |
| `test_physical_absence_errno_classification_table` (connector, deterministic `_lstat` injection) | `EACCES`/`EIO` → unknown; genuine absence (`ENOENT`) still `verified_absent` |
| `test_retire_refuses_when_nested_dir_permission_denied` (API, end-to-end) | R2 code retired the physically-present file (RED `retired=1`); now refused UNKNOWN, row untouched |
| `test_retire_refuses_when_file_still_at_historical_root` | old root migrated but file still there → refused "仍在盘上(历史…)" (RED: retired) |
| `test_retire_allows_when_historical_root_also_verified_absent` | migration close-out positive: both roots proven → retires, proof carries `historical_absence` |
| `test_retire_refuses_when_historical_root_provenance_missing` | row without provenance → UNKNOWN refusal (RED: retired on current-root check alone) |
| `test_retire_rejects_batch_when_source_config_changes_during_adjudication` | config committed between probe and commit (deterministic `run_coroutine_threadsafe` inside the probe seam) → 409, zero mutation, retry succeeds |
| `test_retire_refuses_row_restored_during_adjudication` | concurrent discovery restore between probe and commit → row refused, restore not overwritten (RED: stale ORM wrote `deleted` over it) |
| `test_retire_refuses_when_file_returns_before_commit` | file reappears after first probe → second probe at the persistence point catches it, row refused (RED: retired with one probe call) |

## Files touched in R3

- `backend/connectors/filesystem.py` — `physical_absence_evidence` rewritten:
  lstat + errno classification (Blocker 1), optional `root=` historical-root
  check (Blocker 2), `_ensure_dir_enumerable` parameterization; probe method
  token `filesystem.lstat`. `policy_absence_reason` / `fetch_*` untouched.
- `backend/connectors/base.py` — capability docstring: R3 verdict discipline
  (ENOENT-only absence; `root=` historical provenance).
- `backend/api/admin/data_sources.py` — `_source_config_fingerprint`,
  `_historical_root_of`, `_merge_provenance_probe`; `_probe_batch_for_request`
  now merges the provenance probe (still threadpool, pure read);
  `_verify_retire_readiness` carries `historical_absence` in the proof and
  points present-refusals at the historical location; endpoint persistence
  point fenced (fingerprint 409 / row re-read / re-probe). Docs/comments.
- `docs/operations/orphan-row-retirement-and-path-shape-migrations.md` —
  gates 4–5 (historical provenance, persistence fence) and the superseded
  "check the old root manually" limitation replaced.
- `tests/api/admin/test_issue113_orphan_retire_action.py` — fixtures carry
  ingestion-root provenance (`_absence_meta(..., root=...)`); 7 new R3 cases.
- `tests/connectors/test_filesystem.py` — 2 new errno-classification cases.

## R3 test numbers

| Suite | Result |
| --- | --- |
| `tests/api/admin/test_issue113_orphan_retire_action.py` (21 = 14 R2 + 7 new) | 21 passed |
| `tests/connectors/test_filesystem.py` (16 = 14 + 2 new) | 16 passed |
| `tests/connectors/` directory | 247 passed |
| A-2/A-3 lifecycle regression (`test_fs_disappearance_retirement.py` + `test_lifecycle_composition_u82_u25.py`) | 11 passed |
| `tests/services/test_document_lifecycle.py` + `test_lifecycle_gc.py` (+ the 11 above) | 28 passed |
| adjacent R2 suites (`test_issue25_lifecycle_detail` + `test_data_source_attention_summary` + `test_bulk_repair_bounded_idempotency` + `test_repair_all_lock_progress`) | 21 passed |
| full `tests/api/admin/` directory | 546 passed, 4 failed — the same 4 as R2 baseline (`test_gap_export` ×2, `test_gap_observation`, `test_tech_answer_gaps`), reproduced identically on clean 43885fdd |
| admin vitest `src/lib/dataSourceOps.test.ts` (single file) | 8 passed (frontend untouched in R3) |
| `ruff check` on changed files | clean (`ruff format` baseline of these files unchanged from HEAD — repo does not enforce the formatter) |

## R3 known limitations

- The file-return race is narrowed to the window between the persistence-point
  re-probe and `COMMIT`; closing it fully would require serializable
  isolation or row locks on the source scan, both out of the minimal-mechanism
  mandate. The fence converts the realistic race (file returns during
  adjudication) into a per-row refusal.
- The config fingerprint covers the `to_source_config` payload the gates
  consume; a concurrent write that reproduces the identical fingerprint (e.g.
  a no-op PATCH) does not block — the classification/proof values, not config
  bytes, are the truth (same stance as R2's stale-classification guard).
- Historical-root equality is string/`normpath`-normalized (both spellings
  originate from the same `expanduser()` construction path); symlinked aliases
  of the same directory are treated as different roots and checked both —
  fail-closed direction.
- Rows without `metadata['root']` provenance (or with an unreachable
  historical root) can no longer be retired until provenance is established;
  this is the mandated fail-closed cost for legacy rows.
- Only `filesystem` implements the probe; other source types keep refusing
  with UNKNOWN (unchanged from R2; only filesystem rows can carry a non-null
  persisted `policy_reason`).
- Pre-existing failures (4 pytest in `tests/api/admin`, 25 vitest in the
  broader dataSources suites) are inherited from the base and out of R3
  scope; no new failures introduced.
- No production row was retired; no production DB/reindex touched; no new
  lifecycle states; A-2/A-3 byte-identical.
