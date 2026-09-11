# Project Automation — Operating Contract

Deterministic GitHub automation so routine Project maintenance needs only an Issue edit:
**Issue (body + control labels) = authority → GitHub Actions = deterministic synchronizer → Project = derived projection.**
The Project is never an independent Source of Truth.

Project: [@harryhua-ai's ask-ai project](https://github.com/users/harryhua-ai/projects/2) (number 2, user-owned).

---

## For Role A / humans

Routine planning = edit the Issue only. Add/remove canonical labels; the Project converges automatically
(`project-sync.yml` runs on opened/edited/labeled/unlabeled/closed/reopened).

| You want | Do this (labels on the Issue) |
|---|---|
| Put in v1.6.0 | `iteration:v1.6.0` |
| Put in any existing iteration | `iteration:i-001` / `iteration:i-ux-001` (key = iteration title's code token, lowercased) |
| Put in a Sprint | `sprint:bug-fix-2026-09` (key = Sprint title normalized, minus the redundant word "sprint"; **authoritative**: removing the label clears Sprint) |
| Take out of any iteration | remove the `iteration:*` label |
| Take out of the Sprint | remove the `sprint:*` label (Sprint is cleared, same authority as Iteration) |
| Set priority | `priority:p0` · `priority:p1` · `priority:p2` (remove to clear) |
| Backlog / In Progress / In Review | `status:backlog` · `status:in-progress` · `status:in-review` |
| Done | close the Issue (closure always wins; stale status labels are ignored) |
| Reopen | reopen + keep/adjust a `status:*` label; a reopened Issue never stays Done (no label → Backlog) |

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

## For maintainers

### Workflows

| File | Trigger | Purpose |
|---|---|---|
| `.github/workflows/project-sync.yml` | Issue events + `workflow_dispatch` (issue_number) | Workflow A: converge one Issue's Iteration/Priority/Status. Idempotent; verified after write. |
| `.github/workflows/project-iteration-create.yml` | `workflow_dispatch` only | Workflow B: privileged iteration creation with fail-closed full-replace protocol. |
| `.github/workflows/project-reconcile.yml` | `workflow_dispatch` (+ weekly Monday 06:00 UTC audit) | Workflow C: detect/repair drift; report ambiguity. |

All three share one exclusive concurrency group `project-automation` (no cancellation) — iteration configuration
mutation can never race reconciliation or sync.

### Label vocabulary (canonical)

`iteration:<key>` (key = slug of iteration title code token) · `priority:p0|p1|p2` · `status:backlog|in-progress|in-review` · `sprint:<key>` (key = full Sprint title normalized, redundant "sprint" word dropped; Sprint and Iteration are independent dimensions)

**Reserved / unsupported:** `status:ready` — the Project has no `Ready` Status option. The label is recognized as
explicit control intent and yields a visible `UNSUPPORTED_STATUS_RESERVED` finding with **no Status mutation** until
the option is authorized by a separate decision (adding it via `singleSelectOptions` is a full-replace hazard and is
forbidden without a snapshot/restore plan).

### Project mapping (derived, resolved live every run)

| Label / state | Project value |
|---|---|
| `iteration:<key>` | Iteration whose title code token slug-equals `<key>` (live Iteration field only: I-001 / I-UX-001 / v1.6.0) |
| `priority:p0/p1/p2` | Priority option P0/P1/P2 |
| `status:backlog/in-progress/in-review` | Status option Backlog/In progress/In review |
| `sprint:<key>` | Sprint value whose normalized full title equals `<key>` (authoritative: absent label = Sprint cleared; multiple/unknown = fail closed, value preserved) |

**Sprint authority (final):** `sprint:<key>` behaves as a normal authoritative dimension, mirroring Iteration —
one valid label sets Sprint, no label clears it, multiple or unknown labels fail closed with the existing Sprint
value preserved. This became safe only after, in order: (1) the historical Sprint assignments were bootstrapped
into Issue `sprint:*` labels; (2) bidirectional Issue⇄Project equivalence was proven (11=11, missing/extra/
conflicts/unknown all zero); (3) Sprint drift reached zero under both the transitional and the authoritative
reconcile. The earlier transitional rule (absence → preserve Sprint) protected pre-bootstrap manual values and is
RETIRED — removing a `sprint:*` label now clears Sprint on the next sync/reconcile. Sprint and Iteration remain
independent dimensions: a Sprint label never mutates Iteration and vice versa.
| `status:ready` | **RESERVED** — visible finding, no mutation |
| Issue CLOSED | Status = Done (overrides any status label) |
| Issue OPEN without `status:*` | Status = Backlog |

No Project field/option/iteration/item ID is ever hardcoded; IDs are re-resolved per run and tolerated to regenerate.

### Authentication (required secret)

User-owned Projects v2 are **not** accessible to the repository `GITHUB_TOKEN`.

- Secret: **`PROJECT_SYNC_TOKEN`** (Actions secret on `harryhua-ai/ask-ai`).
- Token: classic PAT with **`repo`** + **`project`** scopes, or fine-grained PAT with **Projects: Read/Write**.
- Missing/invalid token → the job fails immediately with a clean `AUTHENTICATION ERROR`.

### Iteration creation safety (Workflow B)

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

### Reconciliation (Workflow C)

Auto-repairs deterministic drift: missing membership, wrong Priority/Iteration/Status, closed ≠ Done, reopened = Done.
Reports without guessing: conflicting labels, unknown control labels, unknown iteration labels, unknown Project options,
draft items (no Issue authority), Project members without control labels (not opted in).

### Bootstrap / migration (one-time, auditable, reversible)

`python3 scripts/project_automation/cli.py bootstrap --dry-run` then `--apply`:

1. accepted current Project state → canonical control labels on every member Issue;
2. semantic-equivalence verification (labels reproduce the accepted state exactly);
3. only then does continuous synchronization engage.

Dry run is read-only. Apply is reversible: remove the added labels (each run's report lists exactly what was added).
Status quo preserved: closed Issues need no `status:*` label; `Discovery`/`Acceptance` statuses are surfaced as
`needs_review` (no canonical label is invented).

### Local operations

```bash
GH_TOKEN="$(gh auth token)" python3 scripts/project_automation/cli.py <sync|reconcile|bootstrap|ensure-labels|iteration-create> ...
# every command accepts --dry-run (default) / --apply; full test suite:
.venv/bin/python -m pytest tests/project_automation -q
```

### Activation boundary (IMPLEMENTATION ACCEPTED ≠ AUTOMATION ACTIVE)

Merging this automation does NOT activate it. The activation gate sequence is:

```
candidate accepted → merge to main → PROJECT_SYNC_TOKEN configured/verified
→ bootstrap --apply → first real Issue event → GitHub Action succeeds
→ Project convergence independently verified → AUTOMATION ACTIVE
```

Until that chain completes, the Project remains manually governed and this document describes the target model only.
