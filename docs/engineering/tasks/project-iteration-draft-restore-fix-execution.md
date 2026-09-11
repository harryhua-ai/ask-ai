# PROJECT-ITERATION-DRAFT-RESTORE-FIX — Execution Report

Status: **CANDIDATE READY** (narrow corrective; no merge, no live Iteration mutation)
Branch: `project-automation/draft-restore-fix-20260911` · Baseline: `origin/main` = `faa9bf2`

## Defect

`LiveIterationOps.get_item_assignments()` (scripts/project_automation/service.py) skipped
`__typename == "DraftIssue"` when snapshotting item→iteration assignments. Because
`updateProjectV2Field(iterationConfiguration)` full-replaces the iteration set and regenerates every ID, a
`project-iteration-create.yml` run would have restored Issue assignments but silently orphaned all DraftIssue
assignments — 14 I-001 draft items exist on the live Project, so this was a real data-integrity risk.
(Note: the same skip-class bug appeared in the manual model-correction of 2026-09-11 and was repaired ad hoc there;
the live automation adapter retained it.)

## Live read-only evidence (no mutation)

Fresh GraphQL read: **14 DraftIssue items, all assigned to I-001** — every one of them would have been orphaned by
the next iteration creation.

## RED evidence (tests written before the fix)

`tests/project_automation/test_draft_iteration_restore.py` — 4 tests, all failing pre-fix:
1. adapter-level: `get_item_assignments()` must include DraftIssue assignments (the direct defect);
2. transaction-level: I-001/I-UX-001/v1.6.0 + normal Issue assignments + 14 DraftIssue items on I-001 → create
   v1.7.0 → fake regenerates every ID and models GitHub orphaning truthfully (independent of the adapter under
   test) → previously: drafts dangling, `restored == 3`;
3. fail-closed: a failing DRAFT restore must raise RestorationFailure naming the draft item;
4. post-run truthful readback must agree 100% with pre-mutation semantic assignments.

RED run: `4 failed, 77 passed`.

## Fix (narrow)

`get_item_assignments()` no longer filters by content type — the snapshot covers **every** Project item carrying an
Iteration value. `fetch_items` already supplied draft item IDs to the transaction, and
`updateProjectV2ItemFieldValue` accepts draft item IDs (identical mutation path). Everything else unchanged:
semantic slug → regenerated ID remapping, exactly-once configuration mutation, 100% restoration verification,
fail-closed semantics, no persisted ephemeral IDs.

## GREEN / test results

`81 passed` (77 existing — ID regeneration, partial restoration failure, semantic verification, duplicate iteration
refusal, mapping/reconcile/labels/transport — all retained and green — + 4 new DraftIssue regression tests).

## Scope audit

Changed files: `scripts/project_automation/service.py` (+3/−3, the fix only) and the new test file. No workflow
changes, no architecture changes, no live Project/Issue mutations, no iteration created, no activation steps run.

## Candidate

Branch `project-automation/draft-restore-fix-20260911`; commit SHA in the final response.

PROJECT-ITERATION-DRAFT-RESTORE-FIX = CANDIDATE READY
