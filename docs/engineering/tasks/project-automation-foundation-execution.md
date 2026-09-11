# PROJECT-AUTOMATION-FOUNDATION — Execution Report

Status: **CANDIDATE READY** (Role A Review Fix applied; pending independent re-review)
Branch: `project-automation/foundation-20260911` · Base: `origin/main` = `39723c2`
Reviewed candidate: `8874bf0` → verdict CHANGES REQUIRED → **Role A Review Fix section at the end of this document is the authoritative delta.** The original baseline below (four Iterations incl. v1.5.0) is retained verbatim as history but is **SUPERSEDED** — v1.5.0 is a Release, not an Iteration.

---

## 0. Authorization gate

Engineering was authorized only after the ITERATION / RELEASE MODEL CORRECTION completed. Verified before mutation:
`origin/main` fetched = `39723c2` (accepted); Project re-read consistent — 44 items, Iteration field = exactly
{I-001, v1.5.0, I-UX-001, v1.6.0}, assignment counts {I-001: 15, v1.5.0: 8, I-UX-001: 8, v1.6.0: 5, none: 8},
open set {#7,#23,#25,#28,#30,#31,#46,#48}. No Project mutation was in flight. **GATE = PASS.**

## 1. Starting baselines

- Repository: `origin/main` = `39723c2` (Trace A R1 / v1.5.0 acceptance report). Worktree:
  `.worktrees/project-automation-foundation`, branch `project-automation/foundation-20260911`.
- Project snapshot (authoritative, also committed as test fixture
  `tests/project_automation/fixtures/project_snapshot_20260911.json`):

| Field | Type | Values / options (IDs observed 2026-09-11) |
|---|---|---|
| Status | single_select | Backlog `f75ad846` · Discovery `61e4505c` · In progress `47fc9ee4` · In review `df73e18b` · Acceptance `263c01bb` · Done `98236657` |
| Priority | single_select | P0 `79628723` · P1 `0a877460` · P2 `da944a9c` |
| Iteration | iteration | I-001 `0b032198` 09-07+14d · v1.5.0 `8376a678` 09-10+14d · I-UX-001 `8a6c9634` 09-21+14d · v1.6.0 `cb63f30f` 10-05+14d |
| Sprint | iteration | Bug Fix Sprint — 2026-09 `162b44df` (untouched by this task) |
| Initiative / Work Type | single_select | 5 / 7 options (untouched) |

Field IDs: Status/Priority/Iteration resolved live per run; never persisted (contract §3). Sprint kept as a separate
iteration field; **no Release↔Iteration overlap encoded** (§17).

## 2. Architecture

```
User / Role A ──► GitHub Issue (body + canonical control labels = AUTHORITY)
                        │  issues events
                        ▼
              GitHub Actions (deterministic synchronizer, PAT-scoped)
                        │  GraphQL (read config → plan diff → mutate → verify)
                        ▼
              GitHub Project v2 (DERIVED PROJECTION only)
```

- `scripts/project_automation/labels.py` — closed control vocabulary
  (`iteration:<key>`, `priority:p0|p1|p2`, `status:backlog|ready|in-progress|in-review`), slug normalization,
  conflict detection, closed-set validation (crafted/malformed labels surface, never act).
- `model.py` — Project state dataclasses; semantic iteration identity = title code-token slug
  (`v1.6.0`, `i-ux-001`), tolerant of ID regeneration and theme renames.
- `mapping.py` — authority→projection: closure overrides status labels; reopen recomputes (never stays Done);
  open without `status:*` → Backlog; absent `priority:*`/`iteration:*` → clear; conflicts → fail safe.
- `planner.py` — diff desired vs actual → minimal mutation list (idempotent by construction); per-field isolation
  (one field's unknown/conflict never blocks others); findings carry the blocked field.
- `reconcile.py` — drift taxonomy: MISSING_FROM_PROJECT, WRONG_PRIORITY/ITERATION/STATUS, CLOSED_NOT_DONE,
  OPEN_BUT_DONE (auto-repairable); CONFLICTING_LABELS, UNKNOWN_CONTROL_LABEL, UNKNOWN_ITERATION_LABEL,
  UNKNOWN_PROJECT_OPTION, ACTUAL_OPTION_UNKNOWN, NO_CONTROL_METADATA, DRAFT_NO_AUTHORITY (report-only).
- `iteration_txn.py` — the full-replace hazard transaction (§8): PRE-SNAPSHOT → MUTATE EXACTLY ONCE → RE-RESOLVE
  by semantic slug → RESTORE every prior assignment → VERIFY 100% semantic equivalence, FAIL CLOSED otherwise.
- `queries.py` — static GraphQL templates; variables inlined as JSON literals in a single pass (injection-safe;
  value content never re-scanned).
- `transport.py` — `gh api graphql` with caller token; missing/invalid token → clean AUTHENTICATION ERROR.
- `service.py` / `cli.py` — fetch/plan/apply/verify orchestration; CLI subcommands `sync`, `reconcile`,
  `iteration-create`, `bootstrap`, `ensure-labels`; `--dry-run` default, `--apply` explicit; JSON reports +
  GITHUB_STEP_SUMMARY; exit 0/1/2 (ok / hard error / visible findings).

## 3. Workflow files

- `.github/workflows/project-sync.yml` — Workflow A: `issues` [opened, edited, labeled, unlabeled, closed, reopened]
  + `workflow_dispatch(issue_number)`; issues with zero control labels exit without effect.
- `.github/workflows/project-iteration-create.yml` — Workflow B: dispatch-only (key/theme/start_date/duration);
  runs the transaction; creates the `iteration:<key>` label on success.
- `.github/workflows/project-reconcile.yml` — Workflow C: dispatch (+ weekly Monday 06:00 UTC audit), `dry_run` input.

## 4. Authentication model

User-owned Projects v2 are unreachable by `GITHUB_TOKEN` (GitHub-documented; treated as unproven-by-assumption per
§10). Required secret **`PROJECT_SYNC_TOKEN`**: classic PAT `repo` + `project` scopes (or fine-grained PAT with
Projects Read/Write). Absent token → immediate clean `AUTHENTICATION ERROR` (proven live — see §7 step 8 local proof:
empty token produced exactly that error before any API call). No credentials committed; no permission broadened.

## 5. Concurrency model

Single exclusive group `project-automation` (`cancel-in-progress: false`) across A/B/C: iteration configuration
mutation can never race reconciliation or a sync write; routine per-issue syncs are low-frequency PM events, so
global serialization costs nothing and is trivially provable. Workflow A never mutates configuration.

## 6. Test evidence (RED → GREEN)

- RED: 7 test files written first; collection failed (`ModuleNotFoundError: project_automation`) — captured before
  implementation existed.
- GREEN: **69 passed** (`.venv/bin/python -m pytest tests/project_automation -q`) covering every §14 required class:
  priority mapping · status mapping · closed→Done override · reopen behavior (label-driven + no-silent-Done) ·
  iteration semantic resolution · ID-regeneration tolerance · unknown iteration · duplicate/conflicting labels ·
  idempotent sync · drift detection (real-snapshot fixture) · ID regeneration/remap transaction · partial restoration
  failure → FAIL CLOSED · verification-lying transport → FAIL CLOSED · duplicate iteration key refused BEFORE
  mutation · malformed/untrusted metadata (slug validation, GraphQL injection escaping, `$`-in-value, unknown
  variable → CONFIG ERROR) · draft safety.
- No unit test touches the production Project (pure logic + fake transport).

## 7. Controlled runtime acceptance (live Project, operator token; contract §15)

Temporary test issue **#49** + temporary labels; v1.6.0/historical data untouched throughout; net-zero proven:

1. `sync --apply`: issue not in Project → membership added + Status=In progress + Priority=P2 → **CONVERGED**.
2. Immediate re-run → **NO_CHANGE** (idempotent).
3. `iteration:v1.6.0` → Iteration=v1.6.0 (**live semantic resolution**); label removed → `clear_iteration` →
   Iteration empty. Net-zero on v1.6.0 membership.
4. `iteration:v9.9.9` → **exit 2, UNKNOWN_ITERATION finding**, no configuration touched, other fields unaffected.
5. `priority:p1` + `priority:p2` → **exit 2, METADATA CONFLICT**, Priority left P2 (no nondeterminism).
6. Close → Status=Done (observed idempotent with the Project's built-in closed→Done automation — no fighting);
   Reopen → **CONVERGED back to In progress** per label (never stuck Done).
7. Project-wide `reconcile --dry-run`: **zero drift**; 30 member issues skipped NO_CONTROL_METADATA (pre-bootstrap),
   14 draft items DRAFT_NO_AUTHORITY; exit 0.
8. Token-absence path proven locally: empty `GH_TOKEN` → immediate `[AUTHENTICATION ERROR]` before any API call.
9. Cleanup: test item removed from Project (`deleteProjectV2Item`), issue #49 deleted, all six temporary labels
   deleted — verified by label list.

**Before/after verification**: AFTER snapshot vs gate-check BEFORE snapshot — **all issue items identical**
(30×: state, Iteration, Priority, Status) and **Iteration field identical including IDs** (no configuration mutation
occurred during acceptance; #25/#28/#30/#31/#48 and all historical assignments preserved — contract §16).

## 8. Bootstrap (one-time migration; contract §19)

Strategy: accepted Project/Issue state → canonical labels → semantic-equivalence verification → enable sync.
`bootstrap --dry-run` executed against the live Project (read-only): **26 issues planned** — 22 `iteration:*` +
24 `priority:*` + 8 `status:*` (exactly the 8 open Backlog issues; closed issues intentionally get no status label),
**needs_review = []**, contradicting existing labels = []. `--apply` is deliberately left as the post-acceptance
step so Role A owns the moment labels become authority; it is auditable (per-issue report) and reversible
(remove the added labels).

## 9. Changed files

```
.github/workflows/project-sync.yml                     new
.github/workflows/project-iteration-create.yml         new
.github/workflows/project-reconcile.yml                new
scripts/project_automation/__init__.py                 new
scripts/project_automation/errors.py                   new
scripts/project_automation/labels.py                   new
scripts/project_automation/model.py                    new
scripts/project_automation/mapping.py                  new
scripts/project_automation/planner.py                  new
scripts/project_automation/reconcile.py                new
scripts/project_automation/iteration_txn.py            new
scripts/project_automation/queries.py                  new
scripts/project_automation/transport.py                new
scripts/project_automation/service.py                  new
scripts/project_automation/cli.py                      new
tests/project_automation/conftest.py                   new
tests/project_automation/test_labels.py                new
tests/project_automation/test_mapping.py               new
tests/project_automation/test_iteration_resolution.py  new
tests/project_automation/test_planner.py               new
tests/project_automation/test_reconcile.py             new
tests/project_automation/test_iteration_txn.py         new
tests/project_automation/test_transport.py             new
tests/project_automation/fixtures/project_snapshot_20260911.json  new
docs/engineering/project-automation.md                 new (operating contract)
docs/engineering/tasks/project-automation-foundation-execution.md  new (this report)
```

Zero application-code changes; zero Issue bodies/states changed; zero production artifacts touched.

## 10. Scope audit

Included and delivered: sync infrastructure, canonical labels, deterministic mapping, iteration-creation workflow,
reconciliation workflow, bootstrap, tests, documentation. Not done (per §20): no product implementation, no Issue
requirement edits, no closes, no ROADMAP changes, no Project redesign, no new fields/options/iterations created
(existing six fields preserved), no bots beyond the three workflows, no LLM logic, no production deployment.
Release/Iteration boundary respected: no Release field or overlapping iteration (§17).

## 11. Residual risks

1. **`status:ready` requires the Project to gain a `Ready` Status option** (none exists today). Adding one via
   `updateProjectV2Field(singleSelectOptions)` is a full-replace of the option list and risks regenerating option IDs
   (same hazard family as iteration IDs) — deliberately NOT attempted. Until the option exists, `status:ready`
   surfaces a visible `UNKNOWN_OPTION` finding and changes nothing. Maintainer path: add the option via UI, or
   authorize a snapshot+restore migration like Workflow B's.
2. **Actions-runner wiring is unproven pre-merge**: GitHub refuses `workflow_dispatch` for workflow files that don't
   exist on the default branch (`HTTP 404: workflow not found`), and `PROJECT_SYNC_TOKEN` is not yet configured.
   The exact CLI/GraphQL path is proven live (§7); first post-merge dispatch proves checkout/python/secret wiring.
   Expected first-run failure without the secret is a clean AUTHENTICATION ERROR by design.
3. Project's built-in automation (closed→Done) coexists with Workflow A — observed idempotent (sync verifies rather
   than fights). Re-check after merge that both remain consistent on reopen.
4. Draft project items have no Issue authority and are permanently out of automation scope (reported, not drift).

## 12. Commits

- Code commit: `6ed5253` — all scripts, tests, fixtures, workflows (24 files, +2405 lines).
- Docs commit: `8874bf0` — operating contract + original report (`/docs/` gitignored; `add -f` per evidence convention).
- Review-fix commit: the branch tip (see Role A Review Fix section).

---

# ROLE A REVIEW FIX (supersedes the baseline above where they conflict)

## Previous reviewed candidate

`8874bf0` — verdict CHANGES REQUIRED: the candidate's authorization gate passed against a superseded Project model in
which `v1.5.0 — Answer Intelligence Release 1` existed as an Iteration. An intermediate attempt to apply this review
fix was correctly returned **BLOCKED** because at that moment the live Project still carried v1.5.0 as an Iteration
(8 items) and the review forbids repairing the model inside the automation task.

## Why the previous gate was invalid

The first candidate's gate validated against the state produced by the earlier "Iteration / Release Model Correction"
task, which itself had directed creating a v1.5.0 historical iteration. Role A's frozen governance supersedes that:
**Iteration = development timebox; Release = shipped version.** Therefore v1.5.0 = Release ≠ Iteration, and the
authoritative baseline is the corrected Project created by the (second) model-correction run — not the four-iteration
model the candidate was built and tested against.

## Corrected repository baseline

`origin/main` = `39723c2` (unchanged throughout; the correction was Project-only).

## Corrected Project baseline (fresh live read at review-fix start)

- Iterations exactly: **I-001 — Answer Intelligence Foundation** `659fde78` (2026-09-07 +14d, 17 items incl. #26/#27 by
  INC-3 lineage) · **I-UX-001 — Widget Experience Corrective** `ccecdb22` (2026-09-21 +14d, 8 items) ·
  **v1.6.0 — Knowledge Integrity & Source Truth** `89b82cdb` (2026-10-05 +14d, 5 items). **No v1.5.0 Iteration.**
- v1.6.0 membership intact: #25/#28/#30/#31/#48. Unassigned: #4/#21/#29/#34/#45/#47 (sprint-developed; delivery history
  lives in Issue comments/Release notes), #5/#19/#20/#41/#44 (NEEDS REVIEW), open backlog #7/#23/#46.
- 44 items; Status options (no "Ready"); Priority P0/P1/P2; Sprint field untouched.

## Files changed (review fix)

```
tests/project_automation/fixtures/project_snapshot_20260911.json  rebaselined from corrected live state (3 iterations; counts 17/8/5/14; governance marker added)
tests/project_automation/test_iteration_resolution.py             neutral timebox replaces v1.5.0 entry
tests/project_automation/test_iteration_txn.py                    neutral timebox replaces v1.5.0 entry (mechanics unchanged)
tests/project_automation/test_planner.py                          neutral slug replaces v1.5.0
tests/project_automation/test_mapping.py                          v1.5.0 conflict fixture → i-002; status:ready tests flipped to reserved semantics
tests/project_automation/test_release_iteration_boundary.py       NEW — Release ≠ Iteration regression boundary
scripts/project_automation/labels.py                              status:ready moved to RESERVED set (recognized intent, not active vocabulary)
scripts/project_automation/mapping.py                             STATUS_MAP drops ready; RESERVED_STATUS_NOTE surfaced in errors()
scripts/project_automation/service.py                             sync emits UNSUPPORTED_STATUS_RESERVED finding (field-isolated)
scripts/project_automation/reconcile.py                           RESERVED_STATUS_LABEL report-only drift class
docs/engineering/project-automation.md                            corrected iteration examples; Release≠Iteration boundary; reserved status; activation boundary
docs/engineering/tasks/project-automation-foundation-execution.md this section
```

## Fixture correction

`project_snapshot_20260911.json` regenerated from the corrected live Project: 3 iterations (`i-001`/`i-ux-001`/
`v1.6.0`), 44 items with assignment counts {i-001: 17, i-ux-001: 8, v1.6.0: 5, none: 14}, plus a `model` field
recording the corrected governance. A repository-wide grep confirms **zero remaining v1.5.0-as-Iteration assumptions**
in `scripts/` and `tests/`.

## Ready-status correction

`status:ready` is **RESERVED / UNSUPPORTED**: the Project has no `Ready` Status option, and adding one via
`updateProjectV2Field(singleSelectOptions)` is an option-ID full-replace hazard (same family as iteration IDs), so it
was not attempted. Behavior: the label is recognized as explicit control intent (not "unknown"), produces a visible
`UNSUPPORTED_STATUS_RESERVED` finding / `RESERVED_STATUS_LABEL` reconcile entry, never defaults silently to Backlog,
and causes **no Status mutation** until a future authorization adds the option.

## Test result

**77 passed** (baseline 69 + 8 new) — `.venv/bin/python -m pytest tests/project_automation -q`. New coverage:
release version does not resolve as an Iteration even though v1.5.0 exists as a GitHub Release; `release:`/`tag:`
are not control prefixes; source-scan guard proving no automation module touches Release/tag APIs;
`status:ready` reserved semantics (visible finding, no mutation, no Backlog fallback); corrected-fixture drift tests.
Explicitly re-verified GREEN: ID-regeneration protection, idempotency, conflicts fail-safe, unknown iteration
fail-safe, closed→Done, reopen behavior. No tests were deleted.

## Bootstrap dry-run result (live, corrected model, read-only)

26 issues planned: **16 `iteration:*` + 24 `priority:*` + 8 `status:*`**. **Hard acceptance: `iteration:v1.5.0` count
= 0**; distinct iteration labels = {`iteration:i-001`, `iteration:i-ux-001`, `iteration:v1.6.0`}; needs_review = [];
contradicting existing labels = []. (Iteration adds dropped 22→16 because six former v1.5.0 issues are now correctly
unassigned.) `bootstrap --apply` remains NOT executed — gated behind Role A acceptance.

## Live read-only reconciliation result

`reconcile --dry-run` over the live Project: **zero drift**, zero fixable findings; 30 member issues skipped
(NO_CONTROL_METADATA — pre-bootstrap), 14 draft items (no Issue authority). Exit 0.

## Project / Issue / production mutations during this review fix

NONE. Live access was limited to read-only GraphQL/CLI reads plus the two `--dry-run` commands. No test Issues or
labels were created; no configuration was touched.

## Activation status

**AUTOMATION NOT ACTIVE.** IMPLEMENTATION ACCEPTED ≠ AUTOMATION ACTIVE. Activation remains the later gate:
candidate accepted → merge to main → `PROJECT_SYNC_TOKEN` configured/verified → `bootstrap --apply` → first real
Issue event → Action succeeds → convergence independently verified. No secret was created; nothing merged.

## Residual risks (updated)

1. `status:ready` remains reserved until the `Ready` option is authorized (option-ID full-replace hazard documented).
2. Actions-runner wiring still provable only post-merge (workflow files absent from default branch; `gh workflow run`
   returns 404 for non-default refs) + `PROJECT_SYNC_TOKEN` prerequisite — unchanged from `8874bf0`.
3. Coexistence with the Project's built-in closed→Done automation remains observed-idempotent; re-verify at activation.
4. The six unassigned sprint-era issues (#4/#21/#29/#34/#45/#47) carry their delivery history in Issue comments and
   the v1.5.0 Release notes only — by design under the corrected governance; a future dev-timebox iteration may claim
   them by explicit Product decision, not by this automation.

## New candidate SHA

See final response (branch tip of `project-automation/foundation-20260911`).

Final status: **PROJECT-AUTOMATION-FOUNDATION = CANDIDATE READY**
