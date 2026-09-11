# PROJECT AUTOMATION MERGE + ACTIVATION — Report

Result: **PROJECT AUTOMATION = ACTIVE**
Merge: `39723c2..3dffa3b` (fast-forward, three-way verified) · Activation completed 2026-09-11 after
`PROJECT_SYNC_TOKEN` was configured by the operator.

---

## Part 1 — Merge (completed in the prior activation attempt)

- Starting main SHA: `39723c2`; pre-merge gate PASS (no drift, ff-integrable, accepted tree intact at `3dffa3b`).
- **Final main SHA after merge: `3dffa3b6539659167aab031974c8b69d0b0b4097`** — verified three ways (local fetch,
  `git ls-remote`, GitHub API). Workflows `project-sync.yml` / `project-iteration-create.yml` /
  `project-reconcile.yml` visible and active on the default branch.
- First activation attempt stopped at the token gate (repo had zero Actions secrets); fail-closed behavior proven by
  run `34592047785` (`AUTHENTICATION ERROR`, zero mutation). The superseded PARTIAL report commit was `2bc9e02`.

## Part 2 — Token gate (now PASS)

`gh secret list --repo harryhua-ai/ask-ai` shows **`PROJECT_SYNC_TOKEN`** (configured 2026-09-11T11:18:14Z; value
never read/exposed). Verified credential contract (least privilege, docs-verified): classic PAT, scopes
`project` (user Projects v2 read/write) + `public_repo` (public-repo issues/labels); fine-grained PATs cannot access
user-owned Projects and were ruled out.

## Part 3 — Step 1: safe auth probe

- Dispatch `project-sync.yml` issue_number=7 (no control labels).
- Run **34593490990** — **success**, `"result": "SKIPPED_NO_CONTROL_METADATA"`, zero Issue mutation, zero Project
  mutation.

## Step 2 — bootstrap --apply

- First run fail-fast: canonical labels did not exist yet (`priority:p0 not found`) — the accepted `ensure-labels`
  step had not been run first. No partial state (0 labels applied).
- `ensure-labels`: created the 9 canonical labels (`priority:p0/p1/p2`, `status:backlog/in-progress/in-review`,
  `iteration:i-001/i-ux-001/v1.6.0`).
- **`bootstrap --apply`**: **48 labels applied** across 26 issues (16 `iteration:*` + 24 `priority:*` + 8
  `status:*`; +1 `priority:p0` on #4 from the pre-fix run = full plan).
- Hard acceptance: **`iteration:v1.5.0` = 0**; iteration labels limited to {i-001, i-ux-001, v1.6.0};
  needs_review = []; contradicting metadata = []; no Issue body/state changes.
- Semantic equivalence: post-apply `bootstrap --dry-run` plans **zero additions**; `reconcile --dry-run` zero drift.
- Narrow fix required and committed: `gh_cli_json` tolerated non-JSON success output of `gh issue edit`
  (label application worked; response parsing crashed after the mutation).

## Step 3 — real event acceptance (Issue #48: P0, Backlog, v1.6.0)

Selected v1.6.0 Backlog issue #48; before-state: Status=Backlog, Priority=P0, Iteration=v1.6.0; labels
{priority:p0, status:backlog, iteration:v1.6.0}.

| Action | Event | Run | Result | Live effect |
|---|---|---|---|---|
| swap `status:backlog` → `status:in-progress` | issues.unlabeled + issues.labeled | `34594038100` (+ `34594038458`) | **CONVERGED** (set_status) + NO_CHANGE (idempotent double-run), both success | Status: Backlog → **In progress**; Priority/Iteration unchanged |
| restore original labels | issues.unlabeled + issues.labeled | `34594244725` (+ `34594245914`) | **CONVERGED** + NO_CHANGE, both success | Status: In progress → **Backlog**; Priority/Iteration unchanged |

Restored state verified: labels exactly {priority:p0, status:backlog, iteration:v1.6.0}; Project
{Backlog, P0, v1.6.0} — identical to accepted state. Product scope untouched.

Concurrency note: the bootstrap label storm showed GitHub replacing PENDING runs in a concurrency group (several
`cancelled` runs) even with `cancel-in-progress: false` — harmless by design (runs are idempotent re-verifications;
final state was independently verified by reconcile).

## Step 4 — reconcile

Dispatched `project-reconcile.yml` (apply mode): run **34594359495** — **success**, `"drifts": []`,
`"result": "NO_DRIFT"`, `needs_attention: []`. No wrong Iteration/Priority/Status, no closed/open mismatch, no
unknown/conflicting metadata.

## Step 5 — final audit (independent live re-read)

- Iteration set exactly {I-001 2026-09-07, I-UX-001 2026-09-21, v1.6.0 2026-10-05}; **no Release-as-Iteration
  regression** (no v1.5.x iteration).
- Assignments: I-001 = 17 (issues #32/#26/#27 + 14 drafts — 14/14 drafts verified), I-UX-001 = 8
  (#6/#33/#36–#40/#43), v1.6.0 = #25/#28/#30/#31/#48 exactly, unassigned = 14 (6 sprint-era + 5 NEEDS REVIEW +
  #7/#23/#46 outside v1.6.0 as required).
- 44 items total, unchanged. Production ASK-AI untouched (deploy-production.yml not dispatched; no application code
  changed).

## Side-effect audit

Issue bodies/states unchanged (label-only operations on #4/#48 + bootstrap label additions); Project fields changed
only via automation runs above; #4's `priority:p0` matches its accepted Project state; all other Issues received
labels reproducing their accepted Project state exactly.

## Automation fix committed with this report

`gh_cli_json` non-JSON success-output tolerance (scripts/project_automation/service.py) — required for
`bootstrap --apply`/`ensure-labels`; suite re-run: 77 passed.

## Final activation verdict

- candidate merged to main ✅ · workflows active on default branch ✅ · PROJECT_SYNC_TOKEN usable ✅ ·
- bootstrap apply successful ✅ · first real Issue-triggered workflow succeeded ✅ · Project converged correctly ✅ ·
- restore/reconcile zero drift ✅ · historical assignments intact ✅ · v1.6.0 membership intact ✅ ·
- no production mutation ✅

**PROJECT AUTOMATION = ACTIVE**
