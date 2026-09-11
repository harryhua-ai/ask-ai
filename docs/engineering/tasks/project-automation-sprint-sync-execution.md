# PROJECT-AUTOMATION-SPRINT-SYNC — Execution Report

Status: **CANDIDATE READY** (narrow increment on ACTIVE automation; no merge, no live mutation)
Branch: `project-automation/sprint-sync-20260911` · Baseline: `origin/main` = `7f5acf6`

## Objective

`sprint:<key>` label → GitHub Project **Sprint** field. Initial canonical mapping:
`sprint:bug-fix-2026-09` → `Bug Fix Sprint — 2026-09`. Sprint and Iteration remain independent dimensions.

## Root cause / existing architecture finding

Sprint support was simply absent (label prefix unrecognized → ignored). Design findings from live inspection:
Sprint is an iteration-type field (`PVTIF_lAHOAgcvyM4Bisg3zhh595g`) whose single value `Bug Fix Sprint — 2026-09`
(`162b44df`) exists as expected; 11 issues (#4/#21/#26/#27/#28/#29/#31/#32/#34/#45/#47) carry it manually; no drafts
carry Sprint. Sprint's distinguishing text sits AFTER the em-dash, so the iteration code-prefix slug does not apply —
Sprint keys use a **full-title slug with the redundant word "sprint" dropped**
("Bug Fix Sprint — 2026-09" → `bug-fix-2026-09`).

**Safety deviation (deliberate):** Sprint authority is **additive** in v1 — an ABSENT `sprint:*` label leaves Sprint
untouched. Rationale: this increment cannot run `bootstrap --apply` (no Issue metadata changes allowed), so labels
for the 11 existing holders do not exist yet; absent→clear semantics would let the first reconcile-apply erase all
11 manual Sprint values un-recoverably. Clearing Sprint is not expressible in v1 (future: `sprint:none` or flipping
to absent-clear after bootstrap derives the labels).

## RED evidence

`tests/project_automation/test_sprint_sync.py` written first: 19 tests covering canonical mapping, already-correct →
zero mutation, Sprint/Iteration independence, conflicts fail-closed, unknown key fail-closed, mutation-failure
isolation, reconcile detect/repair, additive no-false-drift, bootstrap derivation. RED: collection error
(`FieldConfig` has no `sprints`) then iterative failures — full suite `6 failed, 99 passed` immediately before GREEN.

## Implementation delta

7 automation files, +112/−23 (scope audit vs origin/main): `labels.py` (sprint prefix + conflicts), `model.py`
(`FieldConfig.sprints`+`sprint_by_slug`, `ItemState.sprint_slug`, `sprint_title_slug`), `queries.py` (items/context
fetch Sprint), `mapping.py` (additive desired), `planner.py` (`set_sprint`, `UNKNOWN_SPRINT` finding, per-field
isolation), `reconcile.py` (`WRONG_SPRINT` fixable, `UNKNOWN_SPRINT_LABEL` report-only), `service.py` (fetch/parse,
apply, verification, bootstrap derivation, ensure-labels). Workflows untouched. Historical corrective Issues
#4/#20/#21/#29/#34/#45/#47 untouched (no live Issue mutation of any kind).

## GREEN / test results

**105 passed** (86 baseline incl. DraftIssue restoration, ID regeneration, completed iterations, serializer — all
retained green — + 19 sprint tests).

## Live read-only acceptance

- `bootstrap --dry-run`: derives `sprint:bug-fix-2026-09` for exactly the 11 holder issues; zero
  `iteration:v1.5.0`. (Plan size differs from the original 26-issue plan because concurrent governance work has
  since applied most labels live — outside this increment.)
- `reconcile --dry-run`: **zero sprint-class drift** (additive semantics: no sprint labels exist → no Sprint
  mutations). Observed iteration/membership drift belongs to concurrent I-000 assignment work on the live Project —
  reported, not repaired, not caused by this increment.
- Existing behavior verified unchanged: Iteration set exactly {I-001 09-07, I-UX-001 09-21, v1.6.0 10-05}; I-001
  issues #26/#27/#32 + 14/14 DraftIssue assignments intact; v1.6.0 exactly #25/#28/#30/#31/#48; Sprint holders
  unchanged (#4/#21/#26/#27/#28/#29/#31/#32/#34/#45/#47).

## Scope / side-effect audit

No live Project/Issue mutation (read-only GraphQL + two dry-runs). No new field, no new Sprint value, no Iteration
created, no full-replace executed. Historical corrective Issues untouched. Docs updated (label vocabulary + mapping
table). Actions-level validation of the sprint path requires merge (workflows run from main) — STOP at CANDIDATE
READY per the increment contract.

PROJECT-AUTOMATION-SPRINT-SYNC = CANDIDATE READY
