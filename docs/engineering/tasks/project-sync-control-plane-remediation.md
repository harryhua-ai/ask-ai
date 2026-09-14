# Project Sync Control-Plane Remediation

## 1. Baseline

| Item | Evidence |
|---|---|
| Repository | `harryhua-ai/ask-ai` |
| Authoritative issue | #69 — `[Governance] Project Sync control-plane audit + dynamic Project field reconciliation` |
| Real acceptance issue | #68 — `[v1.6.3] Conversation Review...` |
| Fresh baseline | `origin/main` fetched on 2026-09-14 |
| `BASE_SHA` | `94ddb64825ae873eac0a4bd2d45377172fd355e2` |
| Branch | `codex/project-sync-control-plane-remediation-20260914` |
| Worktree | `/Users/harryhua/Documents/GitHub/ask-ai-project-sync-remediation-20260914` |
| Implementation commit | `f7bda2a1aed7b79d00633200b6b6ce110646cc58` |
| Existing V1.6.3-R3 worktrees | Left untouched |

The pre-change live Project was read through GraphQL. Project #2 is
`PVT_kwHOAgcvyM4Bisg3`; its authoritative fields were:

- Iteration: `v1.6.4` existed with id `935f5c79`.
- Priority: `P0`, `P1`, `P2`.
- Status: `open`, `In progress`, `Done`.
- Issue #68: label `v1.6.4`, Project Iteration unset, Status `open`.

The historical failure was Project Sync workflow run #228, database id
`34825613010`, on `main`: the job completed green while printing
`SKIPPED_NO_CONTROL_METADATA`, with empty mutations and findings.

## 2. Root cause

The failure path was:

1. `scripts/project_automation/service.py::sync_issue()` fetched the live
   Project context and Issue labels.
2. `scripts/project_automation/labels.py::parse_control_labels()` only
   recognized namespaced labels such as `iteration:v1.6.0`; a bare `v1.6.4`
   label was ignored.
3. `sync_issue()` saw `control.has_any == false` and returned
   `{"result": "SKIPPED_NO_CONTROL_METADATA", "mutations": [], "findings": []}`
   before resolving Project Iterations.
4. `scripts/project_automation/cli.py::main()` returned 0 because the report
   had no findings.
5. `.github/workflows/project-sync.yml` invoked the CLI without an explicit
   failure guard. GitHub therefore reported SUCCESS even though the requested
   Project state was never verified.

The defect was not a missing `v1.6.4` case. It was the absence of a live-schema
control-intent pass before the no-control early return, combined with a result
and exit contract that treated a skip as success.

## 3. Pre-change control-plane audit matrix

| Project field / control | Existing accepted labels | Parser / mapping source | Dynamic or hard-coded | Pre-change skip behavior | Conflict behavior | Mutation behavior | Read-back behavior | Exit semantics | Defect / risk |
|---|---|---|---|---|---|---|---|---|---|
| Iteration | `iteration:<slug>` only | `labels.parse_control_labels`; `mapping.resolve_iteration`; `planner.plan_sync` | Live iteration list for prefixed slug, but no bare exact-name discovery | Any bare exact Iteration label was treated as ordinary metadata and returned green skip | Prefixed conflicts were findings; bare labels were invisible | Set/clear Iteration via GraphQL when prefixed intent was recognized | `sync_issue` re-read items and compared semantic slug | CLI returned 0 for the silent bare-label skip | #68 could never reach the resolver; no dynamic exact-name contract |
| Priority | `priority:p0`, `priority:p1`, `priority:p2` | `labels.py::PRIORITY_VALUES`; `mapping.py::PRIORITY_MAP`; live options in planner | Parser vocabulary was hard-coded; planner option lookup was live | Unknown namespaced values could be retained as parser `unknown` but were not converted into a service finding | Multiple values became a finding | Set or clear Priority | Sync re-read and compared if not field-blocked | Findings returned 2, but ignored unknown priority could be green | Project option changes could drift from source vocabulary |
| Status | `status:backlog`, `status:in-progress`, `status:in-review` | `labels.py::STATUS_VALUES`; `mapping.py::STATUS_MAP` | Hard-coded canonical mapping, live option existence checked by planner | No status namespace selected an implicit `Backlog` target | Multiple status labels became a finding | Set Status, including closure → `Done` | Sync re-read and compared | Findings returned 2; no explicit shell guard | Live Project currently has `open/In progress/Done`, so old `Backlog/In review` assumptions are stale |
| `ready` | `status:ready` | `labels.py::STATUS_RESERVED`; `service.py` reserved finding | Explicitly reserved, not a Project option | Recognized, visible finding; not silently mutated | Conflicts with other status labels are reported | No Status mutation | No successful read-back because it fails validation | Non-zero when the finding reaches CLI | Correctly reserved, but required explicit audit |
| `blocked` | None | No parser or mapping in the repository | Not implemented | Ordinary label / no control intent | No control conflict | No Project mutation | No read-back needed for ordinary metadata | 0 as legitimate no-op | Must not be inferred as Status control without a product contract |
| `schedule:current/next/backlog` | None in the pre-change repository | No parser or mapping found in source/history | Absent | Ordinary labels / no control intent | None | None | None | 0 | Compatibility was not implemented despite the governance contract requiring it to be audited |
| Unknown ordinary labels | `bug`, `frontend`, `backend`, `ux`, `security`, etc. | No control namespace match | N/A | Silent skip | N/A | None | N/A | 0 | Correct no-op behavior, but the old skip result was too ambiguous |
| Conflicting controls | Multiple values within an explicit namespace | `labels.py::MetadataConflict`, `service.py`, `reconcile.py` | Static namespace plus live options | Recognized conflicts produced findings; no reliable all-or-nothing guard before membership mutation | Field-scoped findings | Other fields could be planned/applied before the finding | Blocked field was excluded from comparison | Usually 2, but workflow semantics were implicit | A recognized conflict must fail closed without a green mutation run |
| Project/API read failure | N/A | `transport.GhCliTransport.graphql`; `fetch_context/fetch_items` | Live | Exception path | N/A | None or partial prior mutation | Failure exception | CLI 1 | Must never be converted to a successful report |
| Mutation failure | N/A | `service.apply_plan` and transport | Live | Exception path | N/A | Earlier mutations could already have happened | No successful result | CLI 1 | Failure must remain non-zero and visible |
| No-op mutation | Correct existing Project value | `planner.plan_sync` | Live | Returned `NO_CHANGE` after verification | N/A | No GraphQL mutation | Re-read occurred | 0 | Result did not distinguish verified idempotence from skip |

## 4. Frozen Contract implementation mapping

- Dynamic Iteration discovery is implemented by
  `mapping.resolve_live_control_labels()`: a bare Issue label is control intent
  only when it exactly equals one live Iteration title. `resolve_iteration()`
  still supports the existing `iteration:<slug>` compatibility path.
- No version whitelist or `VERSION_TO_ITERATION` map was added. A source scan
  of `scripts/project_automation` and the Project Sync workflows contains no
  `v1.6.4` or `VERSION_TO_ITERATION` special case.
- Multiple exact Iteration matches, duplicate semantic Iterations, conflicting
  prefixed/bare/schedule targets, and unresolved namespaced targets become
  field-scoped findings.
- `schedule:current`, `schedule:next`, and `schedule:backlog` now resolve from
  the live Iteration timeline. `backlog` requests a cleared Iteration. An
  explicit Iteration and schedule target must agree or the plan fails.
- Priority labels retain their namespace, while legality is decided by the
  live Priority options. A future live option such as `P3` is accepted without
  changing source code; a missing `P999` option is `UNKNOWN_OPTION`.
- Status labels retain their namespace and canonical compatibility mapping.
  Explicit values are validated against live Status options. For an open Issue
  with no explicit status label, the legacy default `Backlog` is retained when
  present; the current live Project's authoritative `open` option is used as
  the equivalent fallback. `status:ready` remains reserved and fails closed.
- Plain `ready` and `blocked` remain ordinary labels because the repository has
  no authoritative mapping for them; no Project mutation is inferred.
- `sync_issue()` now emits `NO_CONTROL_INTENT`, `APPLIED`,
  `ALREADY_CONVERGED`, `DRY_RUN`, or `FAILED_VALIDATION`. Exceptions remain
  classified by the CLI as non-zero failures.
- Recognized findings are checked before adding membership or applying field
  mutations, so a missing target or conflict cannot partially make a green
  Project change.
- Project item membership is required to be unique. Post-mutation item
  resolution is also required to be unique.
- Every applied sync mutation is followed by a fresh Project item read. The
  report includes `requested`, `before`, `after`, `applied`, and
  `read_back.verified`; mismatches raise `VerificationFailure`.
- Reconciliation mutations now receive the same fresh-item read-back checks.
- CLI failure results and findings return non-zero. Both Project Sync and
  Project Reconcile wrappers explicitly use `set -euo pipefail` and do not
  swallow failures.

## 5. Changed files

| File | Why it changed |
|---|---|
| `scripts/project_automation/labels.py` | Added schedule namespace and retained raw Priority/Status values for live option validation. |
| `scripts/project_automation/mapping.py` | Added live exact-name Iteration resolution, schedule resolution, conflict detection, and schema-compatible desired mappings. |
| `scripts/project_automation/model.py` | Made option matching normalized and retained Iteration id/title for authoritative read-back. |
| `scripts/project_automation/service.py` | Connected live control resolution, fail-before-mutation validation, unique item checks, dynamic status fallback, structured results, sync/reconcile read-back, and live Priority label derivation. |
| `scripts/project_automation/reconcile.py` | Removed a stale unused import while preserving existing drift semantics. |
| `scripts/project_automation/cli.py` | Made `FAILED_*` result classes explicitly non-zero and cleaned the import block. |
| `.github/workflows/project-sync.yml` | Explicitly propagates CLI failure through the shell wrapper. |
| `.github/workflows/project-reconcile.yml` | Explicitly propagates reconciliation failure through the shell wrapper. |
| `tests/project_automation/test_control_plane_contract.py` | Added dynamic Iteration, future-name, conflict, schedule, live Priority, ordinary-label, API, mutation, read-back, and structured-result coverage. |
| `tests/project_automation/test_cli_workflow_contract.py` | Added CLI exit and both workflow wrapper contract tests. |
| `tests/project_automation/test_closed_issue_event_audit.py` | Updated the existing convergence assertion to the new required `APPLIED` result name; the regression behavior remains covered. |
| `docs/engineering/tasks/project-sync-control-plane-remediation.md` | This required audit and delivery report. |

No V1.6.3-R3 product UI, backend RAG, conversation review, data-source
behavior, or unrelated workflow files were changed.

## 6. RED evidence

Before the implementation, the new contract test module failed during
collection with:

```text
ImportError: cannot import name 'resolve_live_control_labels'
from project_automation.mapping
```

This was the intended RED gate: the test referenced the required live-schema
resolver before that production interface existed.

The pre-change live reproduction was also confirmed locally:

```json
{
 "issue": 68,
 "result": "SKIPPED_NO_CONTROL_METADATA",
 "mutations": [],
 "findings": []
}
```

That same behavior is present in Actions run #228's log.

## 7. GREEN and regression evidence

Executed in the isolated worktree after `uv sync --extra dev`:

```text
uv run pytest tests/project_automation -q
134 passed in 0.08s

uv run ruff check <changed project-automation sources/tests> --ignore EXE001
All checks passed!

git diff --check
exit 0
```

The suite retains the existing project automation tests and adds the new
control-plane/CLI workflow coverage. The future-name test uses
`never-before-seen` from an injected live-schema fixture; no real Project
iteration was created for testing.

## 8. Workflow exit semantics

The CLI-to-workflow contract is now:

| Case | CLI/report result | Exit |
|---|---|---:|
| Valid control intent converges | `APPLIED` or `ALREADY_CONVERGED` | 0 |
| Ordinary labels only | `NO_CONTROL_INTENT` | 0 |
| Recognized target missing | `FAILED_VALIDATION` with finding | 2 |
| Conflicting controls | `FAILED_VALIDATION` with finding | 2 |
| API/mutation/read-back exception | `ERROR`/classified exception | 1 |

The tests invoke `cli.main()` for success, validation failure, and transport
failure, and parse both YAML wrappers to assert `set -euo pipefail` plus the
absence of `|| true`. The real acceptance run below exercised the success path
through GitHub Actions rather than only through Python.

## 9. #68 real GitHub E2E evidence

The implementation branch was pushed before dispatch. Project Sync was then
triggered with `workflow_dispatch` and `issue_number=68`:

| Evidence | Value |
|---|---|
| Issue | #68 |
| Label | `v1.6.4` |
| Workflow | Project Sync |
| Run number | `231` |
| Run database id | `34828411875` |
| Run URL | https://github.com/harryhua-ai/ask-ai/actions/runs/34828411875 |
| Head SHA | `f7bda2a1aed7b79d00633200b6b6ce110646cc58` |
| Workflow conclusion | `success` |
| Requested Iteration | `v1.6.4` |
| Mutation result | `APPLIED`; `set_iteration`; iteration id `935f5c79` |
| Read-back result | `verified: true` |
| Actual Iteration from job read-back | `v1.6.4` |
| Actual Iteration from independent GraphQL read | `v1.6.4` (id `935f5c79`) |

The run log contains no `SKIPPED_NO_CONTROL_METADATA`. It shows:

```json
"mutations": [{"kind": "set_iteration", "iteration_id": "935f5c79", "iteration_title": "v1.6.4"}],
"findings": [],
"read_back": {"verified": true},
"result": "APPLIED"
```

The independent post-run Project GraphQL read returned the #68 item with:

```json
{
  "iterationId": "935f5c79",
  "title": "v1.6.4",
  "status": "open",
  "priority": null
}
```

## 10. Scope audit

### Changed

Only the Project automation implementation, its workflows, its tests, and this
required engineering report were changed. The implementation branch is based
on the fresh `origin/main` SHA listed above.

### Expected/supporting

The changed Python files, workflow wrappers, control-plane tests, and report
are all directly required by Issue #69. The existing closed-issue regression
test was updated only for the mandated structured result name.

### Forbidden/unrelated

No V1.6.3-R3 Wave 1 worktree, product UI, backend RAG path, conversation review
implementation, data-source product behavior, unrelated CI, production
deployment, issue closure, or merge was touched.

## 11. Residual risks

- GitHub Actions emits an existing Node.js 20 deprecation warning from
  `actions/checkout@v4`/`actions/setup-python@v5`; it did not affect the run.
- `status:ready` remains intentionally unsupported until the Project has an
  authorized Ready option. Plain `ready` and `blocked` are intentionally not
  interpreted as Project controls because no authoritative mapping exists in
  this repository.
- The full repository test suite was not used as the acceptance gate because
  this remediation is isolated to the Project automation control plane; the
  complete affected suite and lint checks passed. Backend/data-layer tests would
  require their separate database/runtime environment and are outside this
  scope.
- Reconciliation still reports non-fixable findings as `needs_attention`; the
  CLI exits non-zero even if another independent drift was repaired in the same
  run.

## 12. Final verdict

`CANDIDATE READY`

All required control-plane, dynamic Iteration, fail-closed, read-after-write,
workflow exit, regression, scope, report, and #68 real GitHub acceptance gates
passed. This branch is intentionally not merged, neither issue is closed, and
no production deployment was performed. It is ready for Role A Independent
Review.
