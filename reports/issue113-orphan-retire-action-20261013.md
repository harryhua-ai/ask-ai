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
