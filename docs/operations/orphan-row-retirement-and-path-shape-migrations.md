# Scope-external orphan rows: manual retirement and path-shape migrations

Issue #113 (P2, non-blocking). This document is the operational note required by
AC4 of the frozen contract: how path-shape migrations systematically create
"scope-external orphan" rows, how to detect them, and the two sanctioned ways to
close them out. It does not authorize any production data change by itself.

## What a scope-external orphan row is

A ledger row (`documents`) in lifecycle `missing_candidate` whose
`metadata_['absence'].policy_reason` is non-null (`include_dirs` /
`file_types` / `technical_safety` / `exclusion_policy`). The value is the A-3
classification persisted by the last complete authoritative discovery
(`FilesystemConnector.policy_absence_reason`): the identity is outside the
admin's current filter policy, so its absence is **not** counted as file loss.

**Scope-exclusion is not evidence of physical loss.** The classification is a
pure path-shape/filter verdict — the file may still be on disk, or the
classification may be stale (whitelist relaxed without a discovery re-run).
Physical absence is proven separately, at retirement time, by a server-side
existence check against the current source root
(`FilesystemConnector.physical_absence_evidence`).

Per the frozen A-3 semantics (v1.6.4 Track A), policy-absent rows:

- keep serving from their last active generation (grace presentation),
- have their consecutive-absence counter frozen at zero every sync round,
- can therefore never auto-retire via A-2 while they stay out of scope.

This is mechanically correct — "admin scope-external absence must not be
mistaken for source deletion" — but it means that when the underlying files are
provably gone, the row needs an explicit operator exit. That exit is Issue #113's
manual retire action (which now proves the "provably gone" premise server-side
before withdrawing anything).

## Why path-shape migrations create these rows at scale

Any change to the upload root or to the relative-path shape re-classes every
legacy row at once. The 2026-09-22 production incident (v1.6.4-r2): the upload
root gained an `ask-ai-local-data/` segment, and the re-created source's
`include_dirs` whitelist listed only the new shape. 179 legacy rows whose
identities still used the old shape (`knowledge-support-cases/main/2025.2/...`,
no upload-root segment) fell outside the whitelist and became policy-absent in a
single discovery. Their files were already physically lost (pre-#100 uploads
landed in the backend container's ephemeral layer), so repair was impossible and
the source page showed a permanent "179 项知识需要处理" banner whose
repair-all could never succeed.

Migration checklist (additive segment / prefix change to upload roots):

1. Expect every ledger row whose stored `source_id` no longer matches the new
   path shape to become scope-external at the next complete discovery. This is
   a classification effect, not data loss; rows keep serving during grace.
2. Treat the `include_dirs` whitelist as **part of the migration**: extend it
   with the legacy prefixes (or plan the retirement of the legacy rows) in the
   same change window.
3. After extending the whitelist, absence becomes in-scope again; A-2 unfreezes
   and retires genuinely-gone rows after two consecutive complete-discovery
   confirmations (`RETIRED=N`, immediate service withdrawal, GC eligibility at
   `retired_at + 7d`). This is exactly how the 2026-09-22 incident was closed
   (7 legacy prefixes added; two confirmation rounds retired 179 rows; 243
   active rows kept serving; no downtime).

## Detection

- `GET /api/admin/data-sources/{id}/documents` returns, since Issue #113:
  - `attention_scope_external_orphan_count` — rows in the attention bucket that
    are scope-external orphans (repair can never fix them), and
  - `attention_repairable_count` — the repairable remainder (equal to what
    repair-all will actually process), plus per-row `absence_policy_reason`.
- The source detail banner splits the two classes and offers the truthful
  action for each: repair for repairable rows, explicit retirement for orphans.
  repair-all no longer includes scope-external orphan rows in its eligibility.

## Closing orphan rows out (two sanctioned paths)

1. **Whitelist extension (preferred when the files may return or the identity
   shape is the only problem).** Extend `include_dirs` with the legacy prefixes
   via the normal source editor. If files are back, rows restore automatically;
   if files are gone, A-2 retires them after two confirmations with a full
   audit trail (`metadata_['retirement'].reason = discovery_confirmed_absence`).
2. **Manual explicit retirement (when the files are provably gone and extending
   the whitelist is wrong or unwanted).** Admin-only API:
   `POST /api/admin/data-sources/{id}/documents/retire` with
   `{"confirm": true, "reason": "<operator justification>", "doc_source_ids":
   [...]}` (or `"all_scope_external": true`). Requirements and effects:
   - admin role required (viewer/editor get 403);
   - `confirm=true` and a non-empty `reason` are hard 400 gates;
   - eligibility is server-adjudicated per row, in three gates:
     1. **DB classification** — only `missing_candidate` rows with a non-null
        `policy_reason`. Active rows and in-scope missing rows are refused per
        row (manual action never bypasses A-2);
     2. **current-classification reconciliation** — the persisted
        `policy_reason` must be reproduced by the **current** source config
        (`policy_absence_reason` replay). If the whitelist was relaxed (or any
        filter changed) since the last discovery, the classification is stale
        and retirement is refused: re-run discovery first;
     3. **physical absence proof** — a server-side existence check on the
        absolute path resolved from the **current** source root
        (`physical_absence_evidence`; DB metadata is not trusted). A file
        still on disk (`present`) is refused as recoverable; anything that
        cannot be proven (root unavailable, alien identity, connector type
        without the probe, probe failure) is refused as `UNKNOWN` — fail-closed.
     The passing proof is written into the audit record
     (`evidence.physical_absence`: method / root / resolved_path / checked_at).
   - retirement reuses the existing primitive (`confirm_absence_retirement`):
     immediate service withdrawal, GC eligibility at `retired_at + 7d`;
   - audit trail per row in `documents.metadata_['retirement']`:
     `reason=manual`, `actor=admin:<email>`, `evidence.policy_reason`,
     `evidence.justification` (the operator's reason),
     `evidence.physical_absence`, `retired_at`, `gc_eligible_at`. The source
     detail inspector projects this record.
   - idempotent: already-retired rows return `already_retired` with the audit
     record untouched.

Banner copy treats this class as "scope-external excluded (existence unknown)";
it never claims the files are lost — the loss claim is established per row by
the retirement adjudication above.

Limitation to keep in mind: the proof anchors on the **current** `root_path`.
If the upload root itself was migrated and files may still exist under the old
root, check that location manually before retiring (the probe cannot see a root
the source no longer points at).

The Admin UI (source detail page) exposes the same action: a per-row
"退休" button on orphan rows, and a banner-level "退休 N 项孤儿知识" flow with
an explicit confirmation strip that requires the reason text.

## Prohibited

- Weakening A-3 policy-absence classification or the A-2 consecutive
  confirmation threshold (frozen; guarded by
  `tests/scripts/test_fs_disappearance_retirement.py` and
  `tests/scripts/test_lifecycle_composition_u82_u25.py`).
- Automatic or implicit retirement of scope-external rows (the action must be
  manual, explicit, and audited).
- Direct production DB mutation as the product solution (the 2026-09-22 close-out
  was a manual ops action executed before this capability existed; do not repeat
  it — use the API/UI path above).
- Touching GC timing or tombstone semantics (7-day window is frozen, §8a).
