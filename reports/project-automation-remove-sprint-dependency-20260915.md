# PROJECT AUTOMATION — REMOVE SPRINT DEPENDENCY — Delivery Report (2026-09-15)

**Verdict: PROJECT_AUTOMATION_SPRINT_REMOVAL = CANDIDATE READY**
Track: **C** of the v1.6.3-r4 parallel execution. Branch `fix/project-automation-sprint-removal-20260915`, candidate SHA `ac810d0` (tip `7b3e870` incl. docs/report commits).
**Scope: governance automation only. No application/RAG/runtime change, no live Project mutation beyond the authorized deliverable items, no merge, no tag, no deployment.**

---

## 1. Product decision (frozen, accepted as given)

The Project **Sprint** field was intentionally deleted by the Product Owner and is **no longer part of the required ASK-AI Project governance schema**. Not restored, not recreated, not questioned. Required schema is now **Iteration + Priority + Status**.

## 2. Baseline

- `origin/main` at fetch: `f4e6751` (unchanged during the track).
- **Track base is `fix/project-iteration-drift-20260915` tip `361b067`** (the Iteration Drift R2 candidate): Track C's frozen contract requires the R2 semantics (schedule never owns Iteration; absence = PRESERVE), which live on that not-yet-merged candidate. Track C therefore **stacks on the drift-fix candidate** — integration ordering constraint for Role A: merge drift-fix first, then this branch. No conflicting file regions: drift-fix touched labels/mapping + tests; Sprint removal touches queries/model/planner/service/reconcile + tests (overlap: labels.py/mapping.py — sequential commits, zero conflicts by construction).
- Isolated worktree: `/Users/harryhua/Documents/GitHub/ask-ai-wt-sprint` (no shared worktree).

## 3. Dependency inventory (investigation before deletion)

| Reference | Classification | Action |
|---|---|---|
| `queries.py` `PROJECT_CONTEXT`: `field(name: "Sprint")` | **REQUIRED RUNTIME DEPENDENCY** — GitHub hard-errors the whole query when the field is absent (live: run `34927298633`, 2026-09-15T04:03Z) | removed |
| `queries.py` `PROJECT_ITEMS`: `fieldValueByName(name: "Sprint")` | REQUIRED (references deleted field) | removed |
| `model.py` `sprint_title_slug`, `FieldConfig.sprints/sprint_by_slug`, `ItemState.sprint_slug` | RUNTIME CAPABILITY (obsolete) | removed |
| `labels.py` `SPRINT_PREFIX`, `sprint_key`, `has_sprint_label`, parse/validation | RUNTIME CAPABILITY (obsolete) — `sprint:*` becomes an ordinary label; historical `sprint:*` labels on ~15 closed issues are inert metadata | removed |
| `mapping.py` `DesiredProjection.sprint_key/sprint_touch` + sprint block | RUNTIME CAPABILITY (obsolete) | removed |
| `planner.py` sprint params, `UNKNOWN_SPRINT`, `set_sprint` | RUNTIME CAPABILITY (obsolete) | removed |
| `service.py` sprint context/items resolution, `apply_plan` set_sprint, sprint verification, reconcile read-back, bootstrap/derive/canonical sprint lines | RUNTIME CAPABILITY (obsolete) | removed |
| `reconcile.py` `UNKNOWN_SPRINT_LABEL` / `WRONG_SPRINT` mappings + args | RUNTIME CAPABILITY (obsolete) | removed |
| `tests/project_automation/test_sprint_sync.py` | TEST-ONLY (sprint capability contract) | deleted (21 tests retired) |
| fixture payloads in `test_closed_issue_event_audit.py`, `test_control_plane_contract.py`, `test_schedule_iteration_boundary.py` | TEST-ONLY | cleaned (no simulated Sprint field; removed stale `plan_sync` sprint kwargs) |
| `docs/engineering/project-automation.md` | DOCUMENTATION-ONLY | Sprint rows/paragraphs replaced by a retirement note |
| `docs/engineering/tasks/project-automation-sprint-sync-execution.md` | HISTORICAL RECORD | untouched |
| `.github/workflows/project-sync.yml`, `project-reconcile.yml`, `project-iteration-create.yml` | inspected: **zero Sprint references** (all call `cli.py` only); Workflow B's transaction touches the Iteration field exclusively | no change |

Rationale for clean removal over optional-legacy retention: the Product Owner deleted the field, so a retained capability could only ever produce `UNKNOWN_SPRINT`-style failures or dead abstractions; the task prefers deletion of obsolete complexity.

## 4. RED evidence (commit `fb4231a`; suite run on `origin/main`-lineage code)

`SprintLessProjectTransport` reproduces live GitHub exactly: any query containing `field(name: "Sprint")` raises the live error string. **9/9 target-contract tests failed:**

```
FAILED test_red1_context_discovery_succeeds_without_sprint_field        (fetch_context raises)
FAILED test_red2_sync_issue_completes_without_sprint_field              (sync_issue raises)
FAILED test_red3_reconcile_completes_without_sprint_field               (reconcile raises)
FAILED test_red4_no_query_document_references_sprint_field              (Sprint still in both documents)
FAILED test_control4_iteration_field_still_resolves_without_sprint
FAILED test_control5_priority_mutation_still_works_without_sprint
FAILED test_control6_status_mutation_still_works_without_sprint
FAILED test_control7_iteration_r2_preserve_semantics_without_sprint
FAILED test_control8_explicit_iteration_authority_works_without_sprint
```

## 5. Implementation (commit `ac810d0`)

See §3 "removed" column. Smallest coherent change; no new abstraction; no application/runtime file touched.

## 6. GREEN / regression evidence

Full `tests/project_automation/` suite after removal: **`139 passed, 0 failed`** (= drift-R2 suite 151 − 21 retired sprint-capability tests + 9 new schema tests). Includes:

- all 9 sprint-less-schema contract tests GREEN (RED-1..4 + CONTROLS 4–8);
- **Iteration R2 non-regression**: the complete `test_schedule_iteration_boundary.py` suite (schedule-never-writes, absent-authority-PRESERVE, explicit/bare authority wins, idempotency, closed-issue preservation) plus `test_control_plane_contract.py` (incl. `test_sync_schedule_label_never_rewrites_iteration`, `test_sync_without_iteration_authority_preserves_existing_iteration`) all green;
- Status/Priority/membership/closed-event/CLI-workflow/iteration-transaction/release-boundary contracts all green.

## 7. Live validation (authorized dispatch; performed)

Safety argument: `workflow_dispatch` of `project-sync.yml` is scoped to ONE issue; #71 is converged and the candidate code plans **zero mutations** for it (proven by CONTROL-7/R2 tests), so unrelated Project mutation is impossible. `project-reconcile` was **NOT** dispatched (it ranges over all issues → cannot guarantee no unrelated mutation).

- Run `34930690439` (2026-09-15T04:55Z, ref `fix/project-automation-sprint-removal-20260915`, head `7b3e870`): **conclusion = success**, report `"result": "ALREADY_CONVERGED"`, `"mutations": []`, `"applied": []`.
- The identical dispatch failed at 04:03Z with the Sprint schema error → **the live failure is fixed end-to-end**.
- Fresh post-run reads: #71 Iteration = v1.6.3 / Status = open (unchanged); this also completes the live validation deferred from the Iteration Drift fix task.

## 8. Governance issue / Project state

- **Issue #79** created: "Project automation fails closed when the Project Sprint field is absent (hard schema dependency)" — labels `bug`, `priority:p1`, `iteration:v1.6.3`, `schedule:current`.
- Added to **Project 2**, **Iteration = v1.6.3** (item `247387728`), independently re-read: Status=open, Iteration=v1.6.3. (Membership was added manually because the live automation on `main` is broken by exactly this defect.)
- #71–#78 not touched; no other item mutated.

## 9. Candidate

- Branch: `fix/project-automation-sprint-removal-20260915` (stacked on `fix/project-iteration-drift-20260915` @ `361b067`)
- Commits: `fb4231a` (RED) → `ac810d0` (**fix candidate**) → `7b3e870` (docs) → report commit
- Merge to `main`: **NOT performed**. No `v1.6.3-r4` tag. No deployment. No production reindex/resync. Wiki untouched. Tracks A (#75 review) and B (#72 implementation) not touched.

## 10. Remaining observations (report-only)

- On `main` (unfixed), ALL governance automation remains fail-closed until this candidate (or equivalent) integrates — the weekly Monday 06:00 UTC reconcile and every issue-event sync will keep erroring at schema load. Integration urgency is governance-availability, not data corruption (fail-closed = no writes).
- Historical `sprint:*` labels on closed issues remain as inert metadata; removal/renaming is out of scope and not needed.
- The two cancelled sync runs of 03:58Z (issue #77) predate the Sprint deletion and are unrelated.
