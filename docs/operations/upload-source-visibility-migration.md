# Upload source public visibility migration

This runbook is required before changing production source visibility or
activating a release containing the upload visibility default. The code change
does not edit production data sources, documents, chunks, or vector indexes.

## Impact inventory

| Source identity | Evidence | Current grant | Intended public rights | Disposition |
| --- | --- | --- | --- | --- |
| `knowledge-cb70f5ae` | #125 read-only evidence: enabled filesystem upload source; 247 active documents and 1,097 serving chunks under `ask-ai-local-data`; source `channel_visibility` key absent. Source mount was not directly stat'ed, and the 29 skipped runs do not prove a fresh file enumeration. | No explicit channel grant. Current implementation had inherited `widget` and `api`. | Unresolved; source identity/title and prior exposure are not sufficient evidence of owner intent. | Must be classified by its responsible owner before rollout. Until then, no public channel is assumed. |
| Other `filesystem` sources with `config.upload_mode=true` and no valid explicit grant | Not enumerated in the accepted #125 incident investigation; the repository does not contain a complete production snapshot. | Must be enumerated from a read-only production export at rollout preparation. | Owner decision required per source. | Unresolved entries remain closed; do not infer rights from names, content, or prior exposure. |

The previously deleted `knowledge-support-cases` source is a different identity
from `knowledge-cb70f5ae`; do not count it as the current incident source or
restore it as part of this migration.

## Staged migration

1. Read and export all source IDs, types, enabled flags, `upload_mode`, and
   `channel_visibility` values. Record the export timestamp, query/release
   identity, and a checksum. Do not export customer document contents.
2. Filter to filesystem upload sources whose grant is absent, malformed, or
   contains no valid public channel. Reconcile each row with its responsible
   owner and record the decision as `widget`, `api`, both, or no public grant.
   `api` is public API access; it is not an Admin-only grant. Admin requests
   continue to use the `widget` visitor-equivalent check.
3. Review the complete inventory with the responsible owners. Do not proceed
   while any source has unresolved intended rights. Preserve existing
   explicitly granted public sources as exact-channel grants.
4. Prepare a staged, source-ID-scoped configuration change and its inverse
   from the captured snapshot. Verify both artifacts by diff and checksum.
   No source edit, re-index, bulk disable, deploy, or release is authorized by
   this document; obtain the applicable production change authorization first.
5. After separate authorization, apply the staged configuration in a
   controlled window. Confirm the authoritative source snapshot reflects the
   intended grants. The generation-time guard blocks denied sources
   immediately after its normal cache propagation (30-second TTL); stale
   chunk metadata cannot override that guard. Existing chunk projections must
   be refreshed through the normal authorized sync/re-index process so search
   filtering also reflects the approved grants.

## Pre-release validation

- Verify every upload source is in the signed inventory and has an owner
  decision; unresolved sources have no public grant.
- Exercise widget and API independently for each approved grant, including a
  negative request on the other channel.
- Revoke a grant and verify that the authoritative guard denies the source
  after the documented cache window, including while old chunks still carry
  public channel metadata.
- Verify unknown/ghost sources remain denied, non-upload public sources retain
  their existing default, and Admin probes remain visitor-equivalent to
  Widget.
- Check public answers, sources, citations, traces, and Widget rendering for
  customer identifiers and source titles from denied fixtures.
- Verify stale public links remain marked uncertain and non-clickable without
  excluding all stale sources; separately cover private/dead/retired states.
- Keep the inventory, owner decisions, exact before/after configuration
  artifacts, checksums, validation output, and approval reference together as
  the audit record.

## Rollback

Rollback uses the recorded source-ID-scoped inverse, reviewed against the
owner decisions. Restore only the exact previously approved public grants;
never turn a missing or malformed upload grant into an implicit public grant.
If application rollback would restore the legacy public-default behavior,
retain the fail-closed source configuration and escalate for a corrected
rollback plan instead. Re-run the same channel-specific and stale-projection
checks after any authorized rollback.
