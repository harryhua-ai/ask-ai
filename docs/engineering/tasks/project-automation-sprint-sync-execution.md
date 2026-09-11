# PROJECT-AUTOMATION-SPRINT-SYNC — Execution Report

> **SUPERSEDED (semantics):** the transitional additive Sprint rule documented below (absence → preserve) was
> retired by `PROJECT-AUTOMATION-SPRINT-AUTHORITY-HARDENING` after its three prerequisites completed; Sprint is now
> an authoritative dimension (absence → clear). See
> `docs/engineering/tasks/project-automation-sprint-authority-hardening.md`. The body below is preserved as the
> historical record of the Sprint Sync execution.

Status: **MERGED / BOOTSTRAPPED / ACTIVE**
Branch: `project-automation/sprint-sync-20260911` · Candidate `12fefbd` · Pre-merge `origin/main` = `7f5acf6` · Final `origin/main` = `859eea7`

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
untouched. Rationale: at candidate time the increment could not run `bootstrap --apply`, so labels for the 11 existing
holders did not exist yet; absent→clear semantics would have let the first reconcile-apply erase all 11 manual Sprint
values un-recoverably. Clearing Sprint is not expressible in v1 (future: `sprint:none` or flipping to absent-clear
after bootstrap derives the labels — see Transitional authority below).

## RED evidence

`tests/project_automation/test_sprint_sync.py` written first: 19 tests covering canonical mapping, already-correct →
zero mutation, Sprint/Iteration independence, conflicts fail-closed, unknown key fail-closed, mutation-failure
isolation, reconcile detect/repair, additive no-false-drift, bootstrap derivation. RED: collection error
(`FieldConfig` has no `sprints`) then iterative failures — full suite `6 failed, 99 passed` immediately before GREEN.

## Implementation delta

7 automation files, +112/−23 (scope audit vs pre-merge main `7f5acf6`): `labels.py` (sprint prefix + conflicts),
`model.py` (`FieldConfig.sprints`+`sprint_by_slug`, `ItemState.sprint_slug`, `sprint_title_slug`), `queries.py`
(items/context fetch Sprint), `mapping.py` (additive desired), `planner.py` (`set_sprint`, `UNKNOWN_SPRINT` finding,
per-field isolation), `reconcile.py` (`WRONG_SPRINT` fixable, `UNKNOWN_SPRINT_LABEL` report-only), `service.py`
(fetch/parse, apply, verification, bootstrap derivation, ensure-labels). Workflows untouched. Historical corrective
Issues #4/#20/#21/#29/#34/#45/#47 untouched at candidate stage (no live Issue mutation of any kind).

## GREEN / test results

Candidate: **105 passed** (86 baseline incl. DraftIssue restoration, ID regeneration, completed iterations,
serializer — all retained green — + 19 sprint tests). After the ensure-labels slug fix (below): **107 passed**
(+2 regression tests for `canonical_labels()` sprint slug derivation).

## Pre-merge gate (execution start)

`origin/main` re-read: unchanged at `7f5acf6`; candidate lineage exactly `7f5acf6..12fefbd`, ff-eligible. Drift
classification at gate: `bootstrap --dry-run` plan contained **additions only** (the 11 `sprint:bug-fix-2026-09`
labels); zero absent→clear Sprint semantics exist; `reconcile --dry-run` showed zero sprint-class drift. Gate PASS.

## Merge

`7f5acf6..12fefbd → main`, fast-forward, normal push (no force), verified three ways (local rev-parse, ls-remote,
GitHub API). Workflows (`project-sync.yml`, `project-reconcile.yml`, `project-labels.yml`) active on main.

## Bootstrap execution (incl. one incident, fixed on main)

**Incident:** first `ensure-labels` created the WRONG canonical label `sprint:bug-fix-sprint` — it derived the slug
from the iteration code-prefix rule instead of `sprint_title_slug`. Bootstrap then failed closed ("label not found",
0 applied — no partial damage). **Fix on main:** `service.py` gained `canonical_labels()` using `sprint_title_slug`
for the sprint prefix; 2 regression tests added; committed as `859eea7` (suite 107 passed); bogus label deleted;
ensure-labels re-run → correct `sprint:bug-fix-2026-09` created.

**BEFORE capture:** all 11 holders snapshotted to `/tmp/sprint_before.json` — every one already had Project
Sprint = Bug Fix Sprint — 2026-09; none had the label; iteration/priority/status labels already mirrored the
Project; issue states and unrelated labels recorded.

**`bootstrap --apply` → result: BOOTSTRAPPED, 13 labels applied:**
- `sprint:bug-fix-2026-09` on #4/#21/#26/#27/#28/#29/#31/#32/#34/#45/#47 (the 11 Sprint holders);
- `iteration:i-ux-001` on #41 and #47 — mirroring concurrent, already-accepted live Project assignments
  (bootstrap derives ALL missing control labels, not only sprint ones; these two are mirrors of accepted state,
  not new authority).

## Actions convergence

13 label-add events → `project-sync.yml` runs; the concurrency group collapsed pending runs to the latest, as
designed (idempotent): run **34603316005 = success, result `NO_CHANGE`** (label⇄Project already converged), 3
earlier queued runs `cancelled` by the group (known harmless semantics).

## AFTER verification (all 11 holders)

Per holder, all checks green: Issue has `sprint:bug-fix-2026-09`; Project Sprint = `Bug Fix Sprint — 2026-09`;
Iteration/Priority/Status values unchanged vs BEFORE; issue state unchanged; unrelated labels unchanged (BEFORE
set is a subset). Evidence: `/tmp/sprint_after.json`.

## Reconcile (dry-run — apply deliberately NOT run)

Run **34603777587**, result `DRY_RUN`: **Sprint drift = 0** (no `WRONG_SPRINT`, no `UNKNOWN_SPRINT*`). The 13
non-Sprint findings are entirely the unrelated I-000 governance task's territory — 4× `WRONG_ITERATION`
(#8/#11/#15/#24, repair would set `I-000 — Pre-Iteration Foundation`) and 9× `MISSING_FROM_PROJECT`
(#9/#10/#12/#13/#14/#16/#17/#18/#22) — **reported, NOT repaired**. `reconcile --apply` was deliberately not
dispatched because it would have auto-repaired exactly those findings, and repairing unrelated I-000 iteration
drift is outside this task's boundary (belongs to the I-000 assignment task). Skipped-by-design items unchanged:
14 DraftItems without Issue authority; #44 without control metadata.

## Semantic-equivalence gate (bidirectional)

- Project Sprint holders (11): #4/#21/#26/#27/#28/#29/#31/#32/#34/#45/#47
- `sprint:bug-fix-2026-09` label holders (11): identical set — **BIDIRECTIONAL EQUAL** (no only-in-Project, no
  only-in-labels, no Sprint-value mismatches)
- No Project item carries any other Sprint value; no issue carries any foreign `sprint:*` label
  (`sprint:bug-fix-sprint` bogus label deleted after the slug fix; label list contains exactly one sprint label).

## Scope / side-effect audit (execution phase)

Mutations limited to: main commits `12fefbd`→(merge) and `859eea7` (slug fix + tests); repo labels +13 net (11
sprint + 2 iteration mirrors; bogus `sprint:bug-fix-sprint` created then deleted); Sprint field values untouched
by automation (sync run NO_CHANGE); zero Iteration mutations, zero full-replace, zero DraftItem changes, zero
Issue body/state edits, zero production/deploy changes. Additive Sprint semantics remain ACTIVE; absent→clear is
NOT implemented (hard boundary honored).

## Transitional authority (explicit)

The additive Sprint semantics are **TRANSITIONAL**, not the final authority model. The bootstrap step above has now
completed governance sequence items (1) and (2): existing live Sprint assignments are backfilled into Issue
`sprint:*` labels, and Issue metadata ⇄ Project Sprint are proven semantically equivalent. What remains before the
additive deviation can be retired is a **separate, future tightening task** that (a) implements absent→clear (or a
`sprint:none` marker) and (b) re-verifies the equivalence gate. Until that task is accepted, reconcile-apply must
continue to leave absent-sprint items untouched. Recorded also in docs/engineering/project-automation.md
(Role A review amendment).

PROJECT-AUTOMATION-SPRINT-SYNC = MERGED / BOOTSTRAPPED / ACTIVE
