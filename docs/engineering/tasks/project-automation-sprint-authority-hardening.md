# PROJECT-AUTOMATION-SPRINT-AUTHORITY-HARDENING — Execution Report

Status: **CANDIDATE READY** (semantics promotion; awaiting independent Role A review — not merged, no live mutation)
Branch: `project-automation/sprint-authority-hardening-20260911` · Baseline `origin/main` = `98ab795`
Task independence: orthogonal to TB-P1 Production Migration / Runtime Acceptance (that track's 3 commits since the
accepted Sprint Sync state touch only migration scripts/tests/report — zero file overlap with project automation).

## Objective

Promote Sprint synchronization from transitional additive semantics (absence → preserve) to authoritative
bidirectional semantics (absence → clear), mirroring Iteration. Prerequisites were satisfied by the accepted
SPRINT-SYNC execution: labels bootstrapped, equivalence proven, drift zero.

## Phase 1 — Fresh gate (PASS)

- `origin/main` re-fetched: `98ab795` (accepted Sprint Sync state `0377653` + 3 TB-P1 commits, no automation overlap).
- Live Sprint state independently recomputed via direct `fieldValues` probe (name-based lookup deliberately avoided):
  Project Sprint holders = 11 (#4/#21/#26/#27/#28/#29/#31/#32/#34/#45/#47), all on `Bug Fix Sprint — 2026-09`
  (`162b44df`); `sprint:*` label holders = the same 11; **missing = 0, extra = 0, conflicts = 0, multi = 0,
  unknown = 0**; the only Sprint value in use has the canonical label `sprint:bug-fix-2026-09`
  (`sprint_title_slug("Bug Fix Sprint — 2026-09") == "bug-fix-2026-09"`).
- Gate PASS → proceed. (Investigation note: an initial naive probe reported 0 holders — a parsing bug in the probe
  itself, filtered on an unrequested `__typename`; re-verified with the `number` discriminator before any conclusion.)

## Phase 2 — RED (evidence)

New `tests/project_automation/test_sprint_authority.py` — the 12 required cases:
absent+populated→clear_sprint; absent+empty→zero mutation; valid+empty→set; valid+wrong→correct;
valid+correct→zero; multiple→fail-closed (no set AND no clear); unknown→fail-closed (existing value preserved);
clear isolates Iteration/Priority/Status; sprint failure isolates other dimensions; reconcile detects
populated-without-label as deterministic `WRONG_SPRINT` planning the clear; bootstrap derivation stable;
DraftItem untouched. `test_sprint_sync.py` transitional-encoding tests updated to authoritative semantics
(incl. `test_iteration_label_never_mutates_sprint`, whose fixture now carries the sprint label so the tested
invariant — Iteration changes never mutate Sprint — is isolated from the new clear-on-absence authority).

RED run: **21 failed, 100 passed** (all 21 failures are the not-yet-implemented authoritative contract:
`sprint_clear` attribute / `clear_sprint` mutation absent).

## Phase 3 — Narrow implementation

Only the transitional rule was removed; mapping/planning mechanics mirror Iteration exactly:

- `mapping.py`: `DesiredProjection.sprint_touch` → `sprint_clear`; `resolve_desired` Sprint branch →
  valid key = set; `has_sprint_label` with no resolvable key (conflict/unknown format) = fail-safe no-touch;
  absent label = clear authority.
- `planner.py`: `desired_sprint_clear` parameter; `clear_sprint` mutation when item Sprint populated; set/clear
  branches mutually exclusive; `UNKNOWN_SPRINT` fail-closed unchanged (also under clear intent).
- `reconcile.py`: `clear_sprint → WRONG_SPRINT` (mirrors `clear_iteration → WRONG_ITERATION`); call sites updated.
- `service.py`: `apply_plan` handles `clear_sprint` via the existing `CLEAR_FIELD` mechanism with the Sprint field
  id; sync verification extended (clear → expect empty) and the sprint expected-slug helper corrected
  (`iteration_slug` → `sprint_title_slug` — latent wrong-helper bug, value-coincident for the current single
  Sprint); sprint added to requested/before/after reports.

NOT altered: Iteration authority semantics, Priority, Status, iteration transaction, DraftIssue restoration,
completedIterations handling, Release ≠ Iteration boundary, Project field definitions, Sprint values themselves,
workflows. Unknown/conflicting sprint metadata remains fail-closed.

## Phase 4 — GREEN / regression / live dry-runs

- Full Project Automation suite: **121 passed** (baseline at `98ab795` = 107; +14 new authority tests = the 12
  required cases plus 2 supplementary reconcile-equivalence assertions; `test_sprint_sync.py` keeps its 21 tests
  with the transitional encodings updated to authoritative).
- Focused transaction/DraftIssue/completedIterations: 20 passed (`test_draft_iteration_restore.py`,
  `test_iteration_txn.py`, `test_iteration_resolution.py`).
- Lint: ruff finding set byte-identical to baseline extracts (6 pre-existing findings; the only delta is F841's
  line number shifting 348→358 from added lines). `py_compile` clean.
- `bootstrap --dry-run` (live, read-only): `DRY_RUN`, **zero planned additions** — sprint dimension semantically
  stable post-transition (no sprint adds, no sprint contradictions; the 4 `iteration:i-000` contradictions on
  #8/#11/#15/#24 are the pre-existing I-000 governance line, untouched by this task).
- `reconcile --dry-run` (live, read-only, running the AUTHORITATIVE candidate code): `DRY_RUN`, **Sprint drift = 0**
  — no `WRONG_SPRINT`, no `UNKNOWN_SPRINT*`, **no `clear_sprint` planned anywhere**. The 13 non-Sprint drifts are
  byte-equivalent to the accepted Sprint Sync reconcile (4× WRONG_ITERATION + 9× MISSING_FROM_PROJECT, all I-000
  territory). The STOP condition (authoritative semantics unexpectedly planning Sprint clears) did not trigger.

## Phase 5 — Documentation

`docs/engineering/project-automation.md`: transitional paragraph replaced with the final authority contract
(absence → clear; multiple/unknown → fail closed, value preserved) recording that the transition became safe only
after bootstrap + proven equivalence + zero drift; Role A table gains "Take out of the Sprint". The Sprint Sync
execution report carries a SUPERSEDED banner pointing here (history preserved).

## Hard boundaries honored

No live Sprint mutation, no reconcile apply, no bootstrap apply, no Sprint value create/delete/rename, no Iteration
definition change, no iteration full-replace, no I-000 drift repair, no unrelated reclassification, no TB-P1
touch, no architecture broadening. All live operations were read-only dry-runs through the candidate code.

## Scope audit (delta vs `origin/main` = `98ab795`)

- `scripts/project_automation/mapping.py` — sprint authority rule + field rename
- `scripts/project_automation/planner.py` — clear_sprint branch + param rename + kind docstring
- `scripts/project_automation/reconcile.py` — clear_sprint drift mapping + 2 call sites
- `scripts/project_automation/service.py` — clear apply + verification + report fields
- `tests/project_automation/test_sprint_authority.py` — NEW, 12 required cases
- `tests/project_automation/test_sprint_sync.py` — transitional encodings updated to authoritative
- `docs/engineering/project-automation.md` — authority contract
- `docs/engineering/tasks/project-automation-sprint-sync-execution.md` — SUPERSEDED banner
- `docs/engineering/tasks/project-automation-sprint-authority-hardening.md` — this report

PROJECT-AUTOMATION-SPRINT-AUTHORITY-HARDENING = CANDIDATE READY
