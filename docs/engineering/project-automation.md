# GitHub Projects Automation — Historical Operating Contract (已停用)

> **状态：已停用｜历史说明（2026-10-15）**
>
> The three Project-only workflow files below have been removed from `.github/workflows`. After this change reaches
> the default branch, Issue events, the weekly schedule, and `workflow_dispatch` no longer have Project automation
> workflows to run. The former Action entrypoints cannot create new Project writes.
>
> GitHub Project #2 and its existing items, fields, and labels are retained; this change does not call the Project
> API. The CLI and automation code remain for historical and offline regression reference. Do not invoke their write
> commands unless separately authorized. Restoring any Project Actions workflow requires future independent User
> authorization and review. All sections below describe the retired behavior and are not current operating instructions.

Historical model: **Issue (body + control labels) = authority → GitHub Actions = deterministic synchronizer → Project
= derived projection.** The Project was never an independent Source of Truth.

Project: [@harryhua-ai's ask-ai project](https://github.com/users/harryhua-ai/projects/2) (number 2, user-owned).

---

## For Role A / humans — historical reference (已停用)

The following were the former planning instructions; they do not describe a current automation path.

Routine planning = edit the Issue only. Add/remove canonical labels; the Project converges automatically
(`project-sync.yml` runs on opened/edited/labeled/unlabeled/closed/reopened).

| You want | Do this (labels on the Issue) |
|---|---|
| Put in v1.6.0 | `iteration:v1.6.0` |
| Put in any existing iteration | `iteration:i-001` / `iteration:i-ux-001` (key = iteration title's code token, lowercased) |
| (Iteration unmanaged / preserve) | **Absence of Iteration authority is PRESERVE, not clear (R2, 2026-09-15):** an Issue with no `iteration:*`/bare-Iteration-title label keeps whatever Iteration its Project item already holds — removing an `iteration:*` label does NOT clear the Project value, and no automated clear command exists (one would require a separate product decision) |
| Set priority | `priority:p0` · `priority:p1` · `priority:p2` (remove to clear) |
| Open / In Progress | `status:backlog` → Project Status **open** · `status:in-progress` → **In progress** |
| In Review / Ready | `status:in-review` / `status:ready` — **RESERVED**: no matching Status option; visible finding, **NO Status mutation** |
| Done | close the Issue (closure always wins; stale status labels are ignored) |
| Reopen | reopen + keep/adjust a `status:*` label; a reopened Issue never stays Done (no label → open) |

Governance boundary: **Iteration = development timebox; Release = shipped version.** GitHub Releases/tags are never
mapped to Project Iterations and `release:*`/tag metadata is not control input. Iterations are created only via
Workflow B; v1.5.0 is a Release, not an Iteration.

Rules of the road:

- **Never put two labels of the same prefix with different values** (`priority:p0` + `priority:p1`) — this is a visible
  `METADATA CONFLICT`; the conflicting field stays untouched until you remove one.
- `iteration:<key>` only works for **existing** iterations. Missing iteration → visible `UNKNOWN ITERATION` failure.
  Never create iterations from Issue events; use Workflow B below.
- An Issue enters the Project when it first receives a canonical control label.
- The label vocabulary is closed. Other `status:*`/`priority:*` values (e.g. `status:discovery`) are reported as
  unrecognized and change nothing.

## For maintainers — historical reference (已停用)

### Workflows

| Historical file name | Former trigger | Former purpose | Current status |
|---|---|---|---|
| `.github/workflows/project-sync.yml` | Issue events + `workflow_dispatch` (issue_number) | Workflow A: converge one Issue's Iteration/Priority/Status. Idempotent; verified after write. | Removed from `.github/workflows`; inactive after merge to the default branch. |
| `.github/workflows/project-iteration-create.yml` | `workflow_dispatch` only | Workflow B: privileged iteration creation with fail-closed full-replace protocol. | Removed from `.github/workflows`; inactive after merge to the default branch. |
| `.github/workflows/project-reconcile.yml` | `workflow_dispatch` + weekly Monday 06:00 UTC audit | Workflow C: detect/repair drift; report ambiguity. | Removed from `.github/workflows`; inactive after merge to the default branch. |

Historically, all three shared one exclusive concurrency group `project-automation` (no cancellation). No current
Project workflow uses this group.

### Label vocabulary (canonical in the historical model)

`iteration:<key>` (key = slug of iteration title code token) · `priority:p0|p1|p2` · `status:backlog|in-progress`
(mutation-capable values; `status:in-review` is RESERVED — see below)

**Sprint retired (product decision, 2026-09-15):** the Project Sprint field was intentionally deleted and is no
longer part of the governance schema. `sprint:*` is NOT a control label anymore — existing `sprint:*` labels on
historical Issues are inert ordinary metadata, the automation neither reads nor writes any Sprint field, and no
Sprint value is ever created. Required Project schema: **Iteration + Priority + Status** only.

**Scheduling labels — SCHEDULE ≠ PRODUCT ITERATION (frozen invariant, 2026-09-15 drift fix):** `schedule:current`,
`schedule:next`, and `schedule:backlog` express execution-scheduling intent only. They **never write, clear, or
conflict with the product Iteration** — in particular, `schedule:current` does NOT mean "assign the calendar-current
iteration" (that defect moved #61-#67 and #71-#76 from v1.6.3 to I-001).

**Iteration persistence (R2, frozen invariant: PRODUCT ITERATION IS PERSISTENT PROJECT TRUTH):** only explicit
authority — `iteration:<key>` or a bare label exactly equal to a live Iteration title — may mutate the product
Iteration. Absence of Iteration control metadata means **UNMANAGED/PRESERVE**, regardless of schedule state:
an existing Iteration value is never overwritten, never cleared, and never guessed from the calendar.

**Reserved / unsupported:** `status:ready` and `status:in-review` — the live Project Status options are
**open / In progress / Done** (probed 2026-09-15, #85 vocabulary realignment; the former `Backlog` option was
renamed to `open` and `In review` was removed). Neither `Ready` nor `In review` exists as an option. Both labels are
recognized as explicit control intent and yield a visible `UNSUPPORTED_STATUS_RESERVED` finding with **no Status
mutation** (and never a guessed nearest option) until an option is authorized by a separate decision (adding it via
`singleSelectOptions` is a full-replace hazard and is forbidden without a snapshot/restore plan).

### Project mapping (derived, resolved live every run)

| Label / state | Project value |
|---|---|
| `iteration:<key>` | Iteration whose title code token slug-equals `<key>` (live Iteration field only: I-001 / I-UX-001 / v1.6.0) |
| `priority:p0/p1/p2` | Priority option P0/P1/P2 |
| `status:backlog` | Status option **open** |
| `status:in-progress` | Status option **In progress** |
| `status:in-review` | **RESERVED** — visible finding, no mutation (no `In review` Status option) |
| (no `iteration:*` / bare-Iteration-title label) | **UNMANAGED/PRESERVE** — existing Iteration untouched; never cleared, never calendar-guessed |
| `schedule:current/next/backlog` | **No Project field write** — scheduling intent only; Iteration convergence suspended (existing Iteration preserved, none guessed) |
| `status:ready` | **RESERVED** — visible finding, no mutation (no `Ready` Status option) |
| Issue CLOSED | Status = Done (overrides any status label) |
| Issue OPEN without `status:*` | Status = open |

No Project field/option/iteration/item ID is ever hardcoded; IDs are re-resolved per run and tolerated to regenerate.

### Authentication (historical secret requirement — retired)

`PROJECT_SYNC_TOKEN` was required by the removed Actions workflows. Those workflows no longer require a repository
secret; do not create or refresh one for the retired automation.

User-owned Projects v2 are **not** accessible to the repository `GITHUB_TOKEN`.

- Secret: **`PROJECT_SYNC_TOKEN`** (Actions secret on `harryhua-ai/ask-ai`).
- Token: classic PAT with **`repo`** + **`project`** scopes, or fine-grained PAT with **Projects: Read/Write**.
- Missing/invalid token → the job fails immediately with a clean `AUTHENTICATION ERROR`.

### Iteration creation safety (historical Workflow B)

GitHub's `updateProjectV2Field(iterationConfiguration)` full-replaces the iteration set and **regenerates every
iteration ID**, orphaning item values (observed twice on this Project). Workflow B therefore runs a transaction:

```
PRE-SNAPSHOT (all iterations + every item→iteration semantic assignment)
→ MUTATION (single updateProjectV2Field, all existing iterations re-passed verbatim)
→ RE-RESOLVE (fetch regenerated IDs, match by semantic title-code slug)
→ RESTORE (re-point every previously-assigned item to the regenerated ID)
→ VERIFY (100% semantic equivalence + new iteration exists) — else FAIL CLOSED
```

Semantic identity = the iteration title's code token (`v1.6.0`, `i-ux-001`), stable across ID regeneration and theme
renames. New iteration naming follows the existing convention `<KEY> — <THEME>`, 14-day duration, Monday start.

### Failure semantics

`CONFIGURATION ERROR` · `AUTHENTICATION ERROR` · `METADATA CONFLICT` · `UNKNOWN ITERATION` ·
`PROJECT MUTATION FAILURE` · `RESTORATION FAILURE` · `VERIFICATION FAILURE`

CLI exit codes: `0` success/no-change · `1` hard error · `2` visible findings needing attention (conflict, unknown
iteration/option). Job summary lists Issue, requested state, findings.

### Reconciliation (historical Workflow C)

Auto-repairs deterministic drift: missing membership, wrong Priority/Iteration/Status, closed ≠ Done, reopened still
Done (reopened Issues converge to their `status:*` label, or `open` when unlabeled).
Reports without guessing: conflicting labels, unknown control labels, unknown iteration labels, unknown Project options,
draft items (no Issue authority), Project members without control labels (not opted in).

### Bootstrap / migration (historical, one-time, auditable, reversible)

`python3 scripts/project_automation/cli.py bootstrap --dry-run` then `--apply`:

1. accepted current Project state → canonical control labels on every member Issue;
2. semantic-equivalence verification (labels reproduce the accepted state exactly);
3. only then does continuous synchronization engage.

Dry run is read-only. Apply is reversible: remove the added labels (each run's report lists exactly what was added).
Status quo preserved: closed Issues need no `status:*` label; `Discovery`/`Acceptance` statuses are surfaced as
`needs_review` (no canonical label is invented).

### Local operations (historical; do not use for Project writes)

The CLI examples and Project mutation tests belong to the former operating model. The code remains for historical and
offline regression reference. It can still write Project data if separately invoked with a valid token; do not invoke
`--apply` without future independent User authorization and review.

### Retirement boundary (2026-10-15)

The three workflow files are removed in this change. Once the change reaches the default branch, GitHub has no
Project-only workflow definition for the former Issue events, weekly schedule, or manual dispatch inputs. This retires
the automation entrypoints; it does not delete the Project or alter its historical data. Any restoration requires
future independent User authorization and review.
