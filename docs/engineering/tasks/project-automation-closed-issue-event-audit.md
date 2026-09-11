# PROJECT-AUTOMATION-CLOSED-ISSUE-EVENT-AUDIT — Execution Report

Status: **CANDIDATE READY** (two real defects found and fixed; awaiting Role A review — not merged)
Branch: `project-automation/closed-issue-event-audit-20260912` · Baseline `origin/main` = `57717ea`

## Question

Did adding `iteration:i-000` to CLOSED issues reliably trigger the ACTIVE project-sync automation and converge
Project Iteration? Answer: **the event chain itself works for CLOSED issues, but two real defects made it
unreliable in exactly this batch-label scenario** — one code defect (class D) and one workflow concurrency defect
(class B). Evidence below is run-level, not inferred from YAML.

## Forensic evidence set

Label events (GitHub Issues API, actor `harryhua-ai`, not a bot → actor filtering excluded early):

- Old batch: `iteration:i-000` added to #8 12:34:46Z, #11 12:34:54Z, #15 12:35:04Z, #24 12:35:16Z (plus ~18 more
  issues across 12:32–12:38Z).
- Recent batch: #20/#21/#34/#45 at 23:26:38–49Z, #44 at 23:29:05Z (2026-09-11).

Actions evidence (workflow `project-sync.yml`, runs inspected via log):

- **Every label event created a run** — classification A (EVENT NOT CREATED) is EXCLUDED. 44 runs exist in the
  12:30–13:30Z window alone; 14 in the 23:23–23:29Z window.
- **CLOSED issues are not excluded anywhere**: successful converged runs for CLOSED #4 (34658096013), #29
  (34658088662), #44 (34658232134) — each applied `set_iteration → I-000` and PASSED post-apply verification.
  #7 (open) converged the same way; no behavioral difference by issue state.
- **Class D confirmed — 4 identical failures**: runs 34599644360 (#8), 34599655896 (#11), 34599672245 (#15),
  34599689927 (#24) all died with `PROJECT MUTATION FAILURE: unknown mutation kind 'add_membership'`. Root cause
  in `service.sync_issue`: for a not-yet-member issue the plan contains the `add_membership` marker; ADD_ITEM is
  executed separately first, then the UNFILTERED plan goes to `apply_plan`, which raises on the marker — **after
  membership was added but before any field was set** (partial application; exactly why #8/#11/#15/#24 became
  members without Iteration, which reconcile later reported as WRONG_ITERATION).
- **Class B confirmed — pending-run replacement drops burst siblings**: the single global concurrency group
  `project-automation` let GitHub cancel every PENDING run when the next event arrived. In the old batch 3 of 4
  executed runs crashed (D) and ~25 sibling runs were cancelled while pending; in the 23:26Z batch the runs for
  #20/#21/#34/#45 (34658093694/34658090812/34658086395/34658083277) were cancelled, so only some issues'
  automation ever executed. Result at audit time: **5 of 22** `iteration:i-000` holders had Project Iteration =
  I-000 (#4/#5/#19/#29/#44); 17 did not (4 crash victims + 13 never-executed runs). The 2 dispatched failures at
  23:35Z (34658662368/34658621604) were operator input errors (`--issue "#4"` → `invalid int value`), which also
  exposed the missing `#` sanitization in the workflow step.
- **Class C excluded**: no run returned SKIPPED_*/unresolved for the sampled issues; local main-code dry-run for
  #20 planned exactly `set_iteration → I-000 (fbbcc5e7)` — completedIterations resolution is correct.

## Failure classification

**B + D (both real), A and C excluded.** Primary code defect: `add_membership` plan leak into `apply_plan` (D).
Primary reliability defect: global concurrency group + GitHub pending-run replacement (B). Both compounded by
per-event run fan-out during batch labeling.

## Fix (narrow)

1. `service.py` `sync_issue`: filter `add_membership` out of the plan before `apply_plan` (membership is applied
   by the preceding ADD_ITEM) — mirrors the existing reconcile-side filter. `apply_plan` stays strict.
2. `project-sync.yml`: concurrency group keyed **per issue** (`project-automation-sync-${{ issue number }}`) —
   the latest run per issue always survives a burst; documented rationale (sync may land inside an
   iteration-create transaction window → overwritten by the transaction's verified restore, re-heals on next
   event/reconcile; no corruption path; iteration-create/reconcile keep their own groups).
3. `project-sync.yml`: dispatch/event issue number sanitized (`${number##\#}`) before the CLI call.

## RED → GREEN

RED (`tests/project_automation/test_closed_issue_event_audit.py`, written first): non-member sync crashed with
the exact live error via a live-shape fake transport (ADD_ITEM dispatch, CLOSED issue, completedIterations
resident I-000); per-issue concurrency and sanitization contract tests failed against the then-current YAML. 4
failed / 3 passed (the passes pin existing correct behavior: trigger types, dry-run plan shape, CLOSED+
completedIteration resolution). GREEN after fix: **full suite 114 passed** (107 baseline + 7 new). Lint: rule
set identical to baseline extracts (zero new findings).

## Controlled live verification (real event chain, main automation, single Issue #20)

Reversible metadata dance on the cancelled-run victim #20 (CLOSED, member, Priority P2/Status Done, no
Iteration):

1. BEFORE captured (issue labels/state + Project fields).
2. `remove iteration:i-000` → run **34659632309** created by the event, executed, `iteration_clear: true`,
   **mutations [] → NO_CHANGE** (nothing to clear) — safe reverse step.
3. `add iteration:i-000` → run **34659685173** → **CONVERGED**, applied exactly `[set_iteration → I-000 —
   Pre-Iteration Foundation]`, post-apply verification PASS.
4. AFTER: Project Iteration = I-000 ✓ · Priority P2 unchanged ✓ · Status Done unchanged ✓ · Sprint none
   unchanged ✓ · Issue state CLOSED ✓ · labels restored exactly `["priority:p2","iteration:i-000"]` ✓.

**CONTROLLED VERIFICATION: PASS** — the full acceptance chain (CLOSED issue + iteration label event → workflow
triggered → automation executes → I-000 resolves from completedIterations → Project Iteration = I-000 →
verification PASS) is proven live.

## Side-effect audit

- Other `iteration:i-000` holders untouched by the dance (#4/#5/#19/#29/#44 re-read: I-000 intact, Sprint values
  intact on #4/#29, Status Done intact).
- The 16 remaining un-synced holders were deliberately NOT touched (bulk repair stays with the I-000 governance
  task; after merge they can be healed by their next label event or a reconcile apply — both out of scope here).
- No reconcile apply, no bootstrap apply, no Sprint/Priority/Status mutations (except #20's own intended
  Iteration set), no iteration definition/creation, no production/deploy/TB-P1 contact.
- OPEN issues, Sprint semantics, DraftIssue handling, completedIterations transaction behavior: unchanged
  (suite green; live observations consistent).

## Changed files (delta vs `origin/main` = `57717ea`)

- `scripts/project_automation/service.py` — add_membership filter in sync_issue
- `.github/workflows/project-sync.yml` — per-issue concurrency group + issue-number sanitization
- `tests/project_automation/test_closed_issue_event_audit.py` — NEW, 7 regression/contract tests
- `docs/engineering/tasks/project-automation-closed-issue-event-audit.md` — this report

Note for Role A: the workflow fixes execute from main only after merge; their live effect (burst survival) is
contract-tested pre-merge and the pre-fix event chain for member issues is live-proven above.

PROJECT-AUTOMATION-CLOSED-ISSUE-EVENT-AUDIT = CANDIDATE READY
