"""SCHEDULE ≠ PRODUCT ITERATION boundary tests (v1.6.3 drift fix, 2026-09-15).

Live incident (PROVEN, Actions run 34926050556 log 2026-09-15T03:43:18Z):
Issues #61-#67 and #71-#76 carried only ``schedule:current`` (no ``iteration:*``
label) and Project Sync rewrote their product Iteration v1.6.3 to the
calendar-active iteration I-001 — the run log shows
``before.iteration = "v1.6.3"`` and ``applied: ["set_iteration"] → I-001``.

Frozen invariant: a ``schedule:*`` label expresses execution scheduling intent
ONLY. It must never write, clear, or conflict with the product Iteration —
not from the calendar-current iteration, not from any other heuristic.
Iteration authority remains ``iteration:<key>`` (and a bare label exactly
equal to a live Iteration title).
"""
from project_automation.mapping import resolve_desired, resolve_live_control_labels
from project_automation.model import FieldConfig, IssueAuthority, ItemState, IterationDef, OptionDef
from project_automation.planner import plan_sync

# Mirrors the live Project 2 Iteration field at incident time: on 2026-09-15 the
# calendar-active iteration is I-001 (2026-09-07 + 14d); the product iterations
# v1.6.3 / v1.6.4 both start later. The code under test must not read the
# calendar at all — these dates exist to prove the old behavior was date-driven.
CONFIG = FieldConfig(
    status_options=[OptionDef("s-open", "open"), OptionDef("s-done", "Done")],
    priority_options=[OptionDef("p1", "P1")],
    iterations=[
        IterationDef("i-001", "I-001 — Answer Intelligence Foundation", "2026-09-07", 14),
        IterationDef("v163", "v1.6.3", "2026-11-02", 14),
        IterationDef("v164", "v1.6.4", "2026-11-16", 14),
    ],
)


def plan_for(labels, *, iteration=None, priority=None, status="open"):
    """Full pipeline: live control resolution → desired projection → mutations."""
    item = ItemState(item_id="ITEM_1", issue_number=71, is_draft=False,
                     iteration_slug=iteration, priority=priority, status=status)
    control = resolve_live_control_labels(labels, CONFIG)
    desired = resolve_desired(IssueAuthority(71, "OPEN", labels), control)
    plan = plan_sync(
        item=item, desired_status=desired.status_option,
        desired_priority=desired.priority_option,
        desired_priority_clear=desired.priority_clear,
        desired_iteration_key=desired.iteration_key,
        desired_iteration_clear=desired.iteration_clear,
        config=CONFIG,
    )
    return plan, desired, control


def iteration_mutations(plan):
    return [m for m in plan.mutations if m.kind in ("set_iteration", "clear_iteration")]


def test_red1_schedule_current_preserves_existing_v163():
    plan, _, _ = plan_for(["schedule:current"], iteration="v1.6.3")
    assert iteration_mutations(plan) == []


def test_red2_schedule_current_preserves_existing_v164_not_hardcoded():
    plan, _, _ = plan_for(["schedule:current"], iteration="v1.6.4")
    assert iteration_mutations(plan) == []


def test_red3_schedule_next_preserves_existing_iteration():
    plan, _, _ = plan_for(["schedule:next"], iteration="v1.6.4")
    assert iteration_mutations(plan) == []


def test_red4_schedule_backlog_preserves_existing_iteration():
    plan, _, _ = plan_for(["schedule:backlog"], iteration="v1.6.3")
    assert iteration_mutations(plan) == []


def test_red5_no_authority_fails_closed_without_guessing():
    # No existing Iteration + schedule:current: automation must not assign the
    # calendar-current iteration — leave the product Iteration unset.
    plan, _, _ = plan_for(["schedule:current"], iteration=None)
    assert iteration_mutations(plan) == []


def test_red6_repeated_runs_are_idempotent():
    first, _, _ = plan_for(["schedule:current"], iteration="v1.6.3")
    second, _, _ = plan_for(["schedule:current"], iteration="v1.6.3")
    assert iteration_mutations(first) == []
    assert first.mutations == second.mutations


def test_red7_converged_schedule_issue_plans_zero_mutations():
    # Status/Priority already at their converged values: a schedule-only issue
    # must produce no mutation at all (guard does not disturb unrelated fields).
    plan, _, _ = plan_for(["schedule:current"], iteration="v1.6.3", priority=None, status="open")
    assert plan.mutations == []
    assert plan.findings == []


def test_explicit_iteration_authority_still_wins_over_schedule():
    # iteration:<key> remains the product Iteration authority; schedule:current
    # neither overrides it nor raises a conflict.
    labels = ["iteration:v1.6.3", "schedule:current"]
    plan, desired, control = plan_for(labels, iteration="i-001")
    assert desired.iteration_key == "v1.6.3"
    assert [m for m in plan.mutations if m.kind == "set_iteration"] != []
    assert not any(c.field == "iteration" for c in control.conflicts)


def test_bare_exact_title_authority_still_wins_over_schedule():
    labels = ["v1.6.3", "schedule:current"]
    plan, desired, control = plan_for(labels, iteration="i-001")
    assert desired.iteration_key == "v1.6.3"
    assert [m for m in plan.mutations if m.kind == "set_iteration"] != []
    assert not any(c.field == "iteration" for c in control.conflicts)


# ---------------------------------------------------------------------------
# R2 (Role A review): PRODUCT ITERATION IS PERSISTENT PROJECT TRUTH.
# Absence of Iteration control metadata means UNMANAGED/PRESERVE — never clear,
# regardless of schedule state. Only explicit Iteration authority may mutate.
# ---------------------------------------------------------------------------

def test_r2a_no_iteration_authority_preserves_existing_v163():
    plan, desired, _ = plan_for(["priority:p1"], iteration="v1.6.3", priority="P1")
    assert iteration_mutations(plan) == []
    assert desired.iteration_clear is False


def test_r2b_no_iteration_authority_preserves_existing_v164():
    plan, desired, _ = plan_for(["status:backlog"], iteration="v1.6.4", status="open")
    assert iteration_mutations(plan) == []
    assert desired.iteration_clear is False


def test_r2c_no_authority_and_no_existing_iteration_stays_unset():
    plan, desired, _ = plan_for(["priority:p1"], iteration=None, priority="P1")
    assert iteration_mutations(plan) == []
    assert desired.iteration_key is None
    assert desired.iteration_clear is False


def test_r2d_removing_schedule_label_preserves_iteration():
    # An issue was at v1.6.3 carrying schedule:current; the schedule label was
    # removed. The remaining labels carry no Iteration authority → preserve.
    plan, desired, _ = plan_for(["priority:p1"], iteration="v1.6.3", priority="P1")
    assert iteration_mutations(plan) == []
    assert desired.iteration_clear is False


def test_r2e_closed_issue_preserves_iteration():
    item = ItemState(item_id="ITEM_1", issue_number=61, is_draft=False,
                     iteration_slug="v1.6.3", priority="P1", status="open")
    labels = ["priority:p1"]
    control = resolve_live_control_labels(labels, CONFIG)
    desired = resolve_desired(IssueAuthority(61, "CLOSED", labels), control)
    plan = plan_sync(item=item, desired_status=desired.status_option,
                     desired_priority=desired.priority_option,
                     desired_priority_clear=desired.priority_clear,
                     desired_iteration_key=desired.iteration_key,
                     desired_iteration_clear=desired.iteration_clear,
                     config=CONFIG)
    assert desired.status_option == "Done"  # closure semantics intact
    assert iteration_mutations(plan) == []


def test_r2f_weekly_reconcile_yields_zero_iteration_drift_without_authority():
    from project_automation.reconcile import detect_drift

    item = ItemState(item_id="ITEM_1", issue_number=71, is_draft=False,
                     iteration_slug="v1.6.3", priority="P1", status="open")
    issue = IssueAuthority(71, "OPEN", ["priority:p1"])
    control = resolve_live_control_labels(issue.labels, CONFIG)
    drifts, _ = detect_drift([(issue, control)], {71: item}, CONFIG)
    assert drifts == []
