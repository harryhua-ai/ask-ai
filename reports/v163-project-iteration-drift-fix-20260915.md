# V163_PROJECT_ITERATION_DRIFT_FIX — Delivery Report (2026-09-15)

**Verdict: CANDIDATE READY (R2)** — branch `fix/project-iteration-drift-20260915`.
R1 candidate `09356e3` (schedule guard) → **R2 candidate `ddeda4c`** (absence-of-authority preserves; Role A review correction) → report commit on top.
**Scope: project-governance automation only. No application/runtime/backend/frontend change, no release/tag, no deployment, no merge.**

---

## R2 ADDENDUM (Role A review: CHANGES REQUIRED → resolved)

**Finding accepted**: R1 still contained the documented "absent label = clear authority" rule — an Issue with NO
`iteration:*` AND NO `schedule:*` label produced `iteration_clear=True` → `clear_iteration`, violating
**PRODUCT ITERATION IS PERSISTENT PROJECT TRUTH**.

**R2 correction** (`mapping.py::resolve_desired`): only explicit Iteration authority — `iteration:<key>` or a bare
label exactly equal to a live Iteration title — may mutate the product Iteration. Absence of Iteration control
metadata means **UNMANAGED/PRESERVE** regardless of schedule state; label removal never clears; no automated clear
command is introduced (the planner's clear capability remains, producer-less, for a future explicit product decision).

Required RED→GREEN evidence (commit `9085334` RED: **6/6 failed** → `ddeda4c` GREEN):

| Case | Scenario | Result |
|---|---|---|
| A | Iteration=v1.6.3, no `iteration:*`, no `schedule:*` → zero Iteration mutation | RED fail → GREEN pass |
| B | Iteration=v1.6.4, same → zero Iteration mutation | RED fail → GREEN pass |
| C | No existing Iteration, no `iteration:*` → remain unset, zero mutation (`iteration_clear=False`) | RED fail → GREEN pass |
| D | `schedule:current` removed from an Issue at v1.6.3 → v1.6.3 unchanged | RED fail → GREEN pass |
| E | Closed Issue at v1.6.3, no schedule label → Iteration remains v1.6.3 (closure→Done semantics intact) | RED fail → GREEN pass |
| F | Weekly reconcile, no explicit Iteration authority → **zero drift at all** | RED fail → GREEN pass |

Legacy expectations re-based on the invariant: `test_mapping.py` absent→**preserve** (was clear),
`test_release_iteration_boundary.py` absence→`iteration_clear is False`, `test_planner.py` clear test renamed to a
producer-less mechanism-capability test. Docs updated: "Take out of any iteration → remove the label" row replaced
by **UNMANAGED/PRESERVE** semantics; Iteration persistence invariant documented alongside SCHEDULE ≠ PRODUCT ITERATION.

**Full project_automation suite after R2: `150 passed, 0 failed`** (144 R1 + 6 R2).

### R2 re-verification (second Role A review receipt — same CHANGES REQUIRED text)

The review text corresponds to the R1 candidate (`09356e3`), where the `absent → iteration_clear=True →
clear_iteration` path did exist. At the R2 tip it is **proven removed**:

- Static: `grep` over `scripts/project_automation/` — `iteration_clear` is assigned `False` in **all three**
  `resolve_desired` authority branches (`mapping.py:138/140/142`); no production code assigns `True`. The only
  `True` occurrences are test-side explicit `plan_sync(..., desired_iteration_clear=True)` capability calls,
  which bypass the authority layer by design; the planner clear capability remains **producer-less**.
- Dynamic: required cases A–F pass (6/6), R1 boundary tests RED-1..7 + authority invariants pass (9/9),
  full suite **151 passed** after adding `test_sync_without_iteration_authority_preserves_existing_iteration`
  (commit `e5003fd`) — the review's exact scenario proven end-to-end through `sync_issue`:
  no `iteration:*` + no `schedule:*` → `ALREADY_CONVERGED`, `requested.iteration_clear=False`, zero mutations.
- Live: #71–#76 re-read fresh — all Iteration = v1.6.3, Status=open, labels unchanged.

---

## 1. Root cause (PROVEN at code + live-log level)

`scripts/project_automation/mapping.py` — `resolve_live_control_labels()` (introduced by `f7bda2a`, the #69/#70
control-plane remediation) **promoted `schedule:*` labels into product-Iteration authority**:

- `schedule:current` / `schedule:next` were resolved through `_schedule_candidates()`, which selected iterations
  **by calendar date** (`startDate <= today < startDate + duration`, fallback "latest started or first") —
  `mapping.py:43-61` (pre-fix).
- With no explicit `iteration:*` label on the Issue, the calendar target was **promoted**:
  `chosen = schedule_target` → `control.has_iteration_label = True` → `resolve_desired()` returned
  `iteration_key = "I-001 — Answer Intelligence Foundation"` → `planner.plan_sync()` emitted a
  **`set_iteration` mutation** whenever the item's live Iteration differed (`planner.py:93-94`).
- `schedule:backlog` set `iteration_clear_override = True` → **`clear_iteration`** — destroying existing ownership.
- Both write paths consume the same resolver: Workflow A `project-sync.yml` (every issue event:
  opened/edited/labeled/unlabeled/closed/reopened) **and** Workflow C `project-reconcile.yml`
  (dispatch + weekly Monday 06:00 UTC), so every event re-applied the wrong value.

The canonical contract (`docs/engineering/project-automation.md`) never listed `schedule:*` as control vocabulary —
Iteration authority is exclusively `iteration:<key>` (or a bare label exactly equal to a live Iteration title).
The remediation `f7bda2a` made the de-facto scheduling labels *active* with calendar semantics, creating the defect.

**Frozen invariant now enforced: SCHEDULE ≠ PRODUCT ITERATION.**

## 2. Incident evidence

| Evidence | Value | Level |
|---|---|---|
| Actions run `34924809106` (2026-09-15T03:23:46Z, issue event, #71) | succeeded → wrote Iteration = I-001 on creation | PROVEN (run exists, conclusion success) |
| Actions run `34926050556` log (2026-09-15T03:43:18Z, #71) | `"before": {"iteration": "v1.6.3"}` → `applied: ["set_iteration" → iteration_id 16508b9b "I-001"]` → `"after": {"iteration": "i-001"}` | **PROVEN — the automation read the existing product Iteration v1.6.3 and overwrote it** |
| Mechanism of #61–#67 drift | Labels `priority:p1, schedule:current`, no `iteration:*` → every sync event (including `closed`) re-resolved calendar-current = I-001 (active 2026-09-07..09-21) and rewrote their manual v1.6.3 assignment | PROVEN (labels + code path + calendar window) |
| Mechanism of #71–#76 drift | Labels `schedule:current` (+`bug`) → same promotion at `opened`/`labeled` events | PROVEN |
| Race between manual/API correction and automation (investigation Q9) | The governance reconciliation (03:41–03:45Z) set Iteration=v1.6.3 via API; run `34926050556` — triggered by the reconciliation's own `bug` label add on #71 — re-applied I-001 at 03:43:18Z, *between* the two manual writes. #71 "needed a second write" because the first correction landed inside the automation's write window | PROVEN |
| Selection basis (investigation Q4) | Current date vs iteration `startDate`/`duration` (calendar). Not title-based, not field-based | PROVEN (code) |
| `schedule:next` / `schedule:backlog` same defect (Q10) | `next` = calendar-next iteration write; `backlog` = `clear_iteration` | PROVEN (code; both guarded now) |
| Other labels that write Iteration (Q8) | Only `iteration:<key>` and bare exact Iteration-title labels — the legitimate authorities, unchanged | PROVEN |

## 3. Before → after semantics

| Scenario | Before (defective) | After (frozen invariant) |
|---|---|---|
| Iteration=v1.6.3, labels `schedule:current` | `set_iteration` → calendar-active I-001 | **No Iteration mutation; v1.6.3 preserved** |
| Iteration=v1.6.4, labels `schedule:current` | `set_iteration` → I-001 | **v1.6.4 preserved** (not hard-coded) |
| Existing Iteration + `schedule:next` | `set_iteration` → calendar-next | **Preserved** |
| Existing Iteration + `schedule:backlog` | `clear_iteration` | **Preserved** |
| No Iteration + `schedule:current` | `set_iteration` → I-001 (calendar guess) | **Leave unset — fail closed, no calendar guessing** |
| Explicit `iteration:v1.6.3` + `schedule:current` (mismatch) | `METADATA_CONFLICT` → FAILED_VALIDATION (sync blocked) | **Explicit Iteration wins; schedule is advisory; no conflict** |
| `iteration:<key>` / bare exact-title authority | works | unchanged (still the only Iteration authority) |
| Absent iteration & schedule labels (documented "remove the label to take out") | absent → clear authority | unchanged (canonical contract mechanism, untouched) |
| Status / Priority / Sprint / membership convergence | as documented | unchanged |

Notes: `schedule:*` remains a recognized control label (`has_any` True) so Issue→Project membership intake and
Status/Priority convergence continue to work for schedule-only issues — only the unauthorized Iteration write was
removed. Malformed `schedule:*` values still surface as visible `UNKNOWN_SCHEDULE` findings and fail closed.

## 4. Changed files (candidate `09356e3`)

| File | Change |
|---|---|
| `scripts/project_automation/labels.py` | `ControlLabels.iteration_suspended` flag (set at parse level when a valid `schedule:*` label is present with no `iteration:*` label); removed `iteration_clear_override` |
| `scripts/project_automation/mapping.py` | Deleted `_schedule_candidates()` and the `today` parameter (the entire calendar-resolution code path); `resolve_live_control_labels()` no longer promotes schedule targets nor raises iteration conflicts with them; explicit Iteration authority unchanged and always wins; `resolve_desired()` honors suspension (no write, no clear) |
| `tests/project_automation/test_schedule_iteration_boundary.py` | NEW — 9 boundary tests (RED-1..RED-7 + 2 authority-preserved invariants) |
| `tests/project_automation/test_control_plane_contract.py` | Schedule tests re-based on the frozen invariant (explicit-iteration-wins replaces the old conflict expectation); NEW service-level regression `test_sync_schedule_label_never_rewrites_iteration` (schedule-only issue converges with ZERO mutations) |
| `docs/engineering/project-automation.md` | Vocabulary + mapping-table entries documenting SCHEDULE ≠ PRODUCT ITERATION and the suspension semantics |

`service.py`, `reconcile.py`, `planner.py`, `queries.py`, `cli.py`, all workflows: **unchanged** (both write paths
cure through the single mapping-layer fix).

## 5. RED → GREEN evidence

**RED (commit `8b8a71b`, pre-fix code): 9/9 failed.**

```
FAILED test_red1_schedule_current_preserves_existing_v163
FAILED test_red2_schedule_current_preserves_existing_v164_not_hardcoded
FAILED test_red3_schedule_next_preserves_existing_iteration
FAILED test_red4_schedule_backlog_preserves_existing_iteration
FAILED test_red5_no_authority_fails_closed_without_guessing
FAILED test_red6_repeated_runs_are_idempotent
FAILED test_red7_converged_schedule_issue_plans_zero_mutations
FAILED test_explicit_iteration_authority_still_wins_over_schedule
FAILED test_bare_exact_title_authority_still_wins_over_schedule
```

Representative RED-1 failure (the incident, reproduced): old code planned
`Mutation(kind='set_iteration', payload={'iteration_id': 'i-001', 'iteration_title': 'I-001 — Answer Intelligence Foundation'})`
for an item already at Iteration `v1.6.3` with label `schedule:current`.
(RED runs executed 2026-09-15, when I-001 is calendar-active — exactly the incident conditions.)

**GREEN (commit `09356e3`): full automation suite `144 passed, 0 failed`**, including the 9 new boundary tests and
all pre-existing contracts (control-plane, mapping, iteration resolution/txn, planner, reconcile, sprint sync,
labels, transport, CLI/workflow contract, closed-issue-event audit, release/iteration boundary).

## 6. Regression audit (§7)

- Issue→Project membership: unchanged — schedule labels still count as control intent (`has_any`), so intake still
  adds membership (covered by existing service tests; `add_membership` path untouched).
- Status synchronization: unchanged — closure-wins, label mapping, live `open` fallback, reserved `status:ready`
  (all existing tests green).
- Priority synchronization: unchanged — absent→clear, `priority:p0/p1/p2` (+ live-option validation).
- Sprint: untouched (`sprint:*` additive semantics; Sprint never participated in the Iteration defect).
- ready/blocked: remain ordinary labels (no mapping) — untouched.
- Reconcile: same `resolve_desired`/`plan_sync` path → schedule-only issues now yield **no** Iteration drift
  (previously `WRONG_ITERATION` repairs re-applied I-001 weekly). No behavior broadened.

## 7. Live Project verification (§8)

- `#71–#76` independently re-read (GraphQL, fresh) after the fix: **all six Iteration = `v1.6.3`**, Status=open,
  labels exactly `#71/#72/#75/#76 = bug+schedule:current`, `#73/#74 = schedule:current`. ✓
- Live no-op re-run attempt: `workflow_dispatch` of `project-sync.yml --ref fix/project-iteration-drift-20260915`
  for #71 (run `34927298633`) — the run **failed closed at schema fetch with ZERO Project mutations** because of an
  orthogonal live incident: the Project's **`Sprint` field was deleted by another actor** between 03:43Z (last
  successful sync) and 04:03Z; `PROJECT_CONTEXT` resolves `field(name: "Sprint")`, which now hard-errors
  (`Could not resolve to a Unions::ProjectV2FieldConfiguration with the name Sprint`). Old code on `main` fails
  identically — this is pre-existing, not introduced by the candidate. Consequence: **no automation write path can
  touch any Iteration until the Sprint schema question is resolved**, and the dispatch re-run should be repeated
  once restored. The zero-mutation write guard itself is proven at unit + service-transport level (§5/§6) and by
  the failed run's evidence that no mutation was attempted (fail-closed behavior working as designed).

## 8. Scope audit (§5)

Authorized surface only: sync/reconcile helper code (`labels.py`, `mapping.py`), automation tests, minimal contract
doc lines. NOT touched: backend/frontend/RAG/migrations, Status/Priority design, iteration configuration,
#71–#76 scope, issue bodies, release tags, deployments. No unrelated Issue was moved between iterations.

## 9. Remaining governance observations (audit-only; not corrected here)

1. **#61–#67**: all CLOSED/Done, Iteration = `I-001` — moved off v1.6.3 by the proven calendar rewrite; **the fix
   prevents recurrence** (schedule labels no longer write Iteration; the weekly reconcile no longer re-applies it).
   Restoration of their v1.6.3 ownership is a separate governance decision (out of scope here).
2. **#68**: title declares `[v1.6.3]` but label + Iteration = `v1.6.4` (its bare `v1.6.4` label is legitimate
   Iteration authority under the contract). Ownership decision belongs to Role A; not touched.
3. **#78** (`[v1.6.3] Authoritative company/support knowledge recall…`, created by another track during this task):
   Project member, labels `bug, schedule:current`, **no Iteration and no `iteration:*` label** — on `main`'s code its
   next event would assign I-001 (defect recurrence); with the fix it stays unset until explicit authority is added.
   Its title/label mismatch should be reconciled by its owners.
4. **`Sprint` field deletion incident (UNPROVEN attribution, PROVEN effect)**: another track actively mutated the
   Project during this task (e.g. runs for #77 at 03:58Z); deleting Sprint broke ALL Project Sync/Reconcile runs
   (old and new code) at context fetch — a fail-visible stop of the entire governance automation. Requires a
   separate decision: restore the Sprint field, or make the Sprint dimension optional in `PROJECT_CONTEXT`.
5. v1.6.3 composition at report time: 16 items, 16 open, 0 closed (#52–#60, #71–#77). Priorities remain unset on
   #71–#76 (unchanged, read-only observation).

## 10. Candidate

- Branch: `fix/project-iteration-drift-20260915` (base `origin/main` = `f4e6751`)
- Commits: `8b8a71b` (R1 RED) → `09356e3` (R1 fix) → `b0d4167` (R1 report) → `9085334` (R2 RED, 6/6 fail) →
  `ddeda4c` (**R2 fix — CANDIDATE**) → `4740cf0` (R2 report addendum) → `e5003fd` (R2 service-level regression)
- Merge to `main`: **NOT performed** — awaiting Role A authorization.
