"""Authoritative sprint:* semantics — absent label clears Sprint (hardening).

The transitional additive rule (absence → preserve Sprint) existed only to
protect pre-bootstrap manual Sprint values. Bootstrap has since run and
bidirectional equivalence was proven (11=11, drift=0), so Sprint now behaves
as a normal authoritative dimension mirroring Iteration:

    one valid sprint label   → Sprint = mapped value
    no sprint label          → Sprint cleared
    multiple/unknown labels  → FAIL CLOSED (no Sprint mutation)
    already equivalent       → zero mutation
"""
from project_automation.labels import parse_control_labels
from project_automation.mapping import resolve_desired
from project_automation.model import FieldConfig, IssueAuthority, ItemState, IterationDef, OptionDef
from project_automation.planner import plan_sync
from project_automation.reconcile import detect_drift

CONFIG = FieldConfig(
    status_options=[OptionDef("s1", "Backlog"), OptionDef("s2", "In progress"),
                    OptionDef("s4", "In review"), OptionDef("s3", "Done")],
    priority_options=[OptionDef("p1", "P0"), OptionDef("p2", "P1"), OptionDef("p3", "P2")],
    iterations=[IterationDef("i1", "I-001 — Answer Intelligence Foundation", "2026-09-07", 14),
                IterationDef("i2", "v1.6.0 — Knowledge Integrity & Source Truth", "2026-10-05", 14)],
    sprints=[IterationDef("sp1", "Bug Fix Sprint — 2026-09", "2026-09-14", 14)],
)

# fully-converged member except where a case varies sprint
def member(sprint_slug="bug-fix-2026-09"):
    return ItemState(item_id="it1", issue_number=28, is_draft=False, iteration_slug="v1.6.0",
                     priority="P1", status="Backlog", sprint_slug=sprint_slug)

CONVERGED_LABELS = ["status:backlog", "priority:p1", "iteration:v1.6.0", "sprint:bug-fix-2026-09"]


def plan(item, labels):
    d = resolve_desired(IssueAuthority(number=28, state="OPEN", labels=labels))
    return plan_sync(item=item, desired_status=d.status_option,
                     desired_priority=d.priority_option, desired_priority_clear=d.priority_clear,
                     desired_iteration_key=d.iteration_key, desired_iteration_clear=d.iteration_clear,
                     desired_sprint_key=d.sprint_key, desired_sprint_clear=d.sprint_clear,
                     config=CONFIG)


class TestAuthoritativeAbsentClear:
    # case 1: no sprint label + Sprint populated → plan clear_sprint
    def test_absent_label_populated_sprint_plans_clear(self):
        p = plan(member(sprint_slug="bug-fix-2026-09"), CONVERGED_LABELS[:3])
        sprint_kinds = [m.kind for m in p.mutations if "sprint" in m.kind]
        assert sprint_kinds == ["clear_sprint"]

    # case 2: no sprint label + Sprint already empty → zero mutation
    def test_absent_label_empty_sprint_zero_mutation(self):
        p = plan(member(sprint_slug=None), CONVERGED_LABELS[:3])
        assert p.mutations == [] and p.findings == []

    # case 3: one valid sprint label + Sprint empty → set Sprint
    def test_valid_label_empty_sprint_plans_set(self):
        p = plan(member(sprint_slug=None), CONVERGED_LABELS)
        kinds = [m.kind for m in p.mutations if "sprint" in m.kind]
        assert kinds == ["set_sprint"]
        m = next(m for m in p.mutations if m.kind == "set_sprint")
        assert m.payload["sprint_title"] == "Bug Fix Sprint — 2026-09"

    # case 4: one valid sprint label + wrong Sprint → correct Sprint
    def test_valid_label_wrong_sprint_plans_correction(self):
        p = plan(member(sprint_slug="some-other-sprint"), CONVERGED_LABELS)
        kinds = [m.kind for m in p.mutations if "sprint" in m.kind]
        assert kinds == ["set_sprint"]

    # case 5: valid label + correct Sprint → zero mutation
    def test_valid_label_correct_sprint_zero_mutation(self):
        p = plan(member(sprint_slug="bug-fix-2026-09"), CONVERGED_LABELS)
        assert p.mutations == [] and p.findings == []

    # case 6: multiple sprint labels → FAIL CLOSED, no Sprint mutation (no clear either)
    def test_multiple_sprint_labels_fail_closed_no_clear_no_set(self):
        p = plan(member(sprint_slug="bug-fix-2026-09"),
                 CONVERGED_LABELS[:3] + ["sprint:bug-fix-2026-09", "sprint:other-sprint"])
        assert [m.kind for m in p.mutations if "sprint" in m.kind] == []
        d = resolve_desired(IssueAuthority(28, "OPEN",
                          CONVERGED_LABELS[:3] + ["sprint:bug-fix-2026-09", "sprint:other-sprint"]))
        assert d.sprint_key is None and d.sprint_clear is False
        assert d.errors()

    # case 7: unknown sprint label → FAIL CLOSED, no Sprint mutation (existing value preserved)
    def test_unknown_sprint_label_fail_closed_preserves_value(self):
        p = plan(member(sprint_slug="bug-fix-2026-09"),
                 CONVERGED_LABELS[:3] + ["sprint:future-sprint"])
        assert [m.kind for m in p.mutations if "sprint" in m.kind] == []
        assert p.findings and any(f.code == "UNKNOWN_SPRINT" and f.field == "sprint" for f in p.findings)

    # case 8: Sprint clear must not modify Iteration/Priority/Status
    def test_clear_isolates_other_dimensions(self):
        p = plan(member(sprint_slug="bug-fix-2026-09"), CONVERGED_LABELS[:3])
        assert [m.kind for m in p.mutations] == ["clear_sprint"]
        assert all("iteration" not in m.kind and "priority" not in m.kind and "status" not in m.kind
                   for m in p.mutations)

    # case 9: Sprint mutation failure must not corrupt other dimensions
    def test_sprint_failure_isolation_keeps_other_fields(self):
        item = member(sprint_slug=None)
        labels = ["sprint:future-sprint", "status:in-review", "priority:p0", "iteration:i-001"]
        p = plan(item, labels)
        kinds = [m.kind for m in p.mutations]
        assert "set_status" in kinds and "set_priority" in kinds and "set_iteration" in kinds
        assert all("sprint" not in k for k in kinds)
        assert any(f.code == "UNKNOWN_SPRINT" for f in p.findings)


class TestAuthoritativeReconcile:
    # case 10: Sprint populated + no sprint label = deterministic drift planning the clear
    def test_reconcile_detects_populated_sprint_without_label(self):
        authority = [(IssueAuthority(28, "OPEN", CONVERGED_LABELS[:3]),
                      parse_control_labels(CONVERGED_LABELS[:3]))]
        items = {28: member(sprint_slug="bug-fix-2026-09")}
        drifts, _ = detect_drift(authority, items, CONFIG)
        wrong = [d for d in drifts if d.code == "WRONG_SPRINT"]
        assert wrong and wrong[0].fixable
        assert any(m.kind == "clear_sprint" for m in wrong[0].fix.mutations)

    def test_reconcile_equivalent_state_reports_no_sprint_drift(self):
        authority = [(IssueAuthority(28, "OPEN", CONVERGED_LABELS),
                      parse_control_labels(CONVERGED_LABELS))]
        items = {28: member(sprint_slug="bug-fix-2026-09")}
        drifts, _ = detect_drift(authority, items, CONFIG)
        assert [d for d in drifts if "SPRINT" in d.code] == []

    def test_reconcile_empty_sprint_no_label_no_drift(self):
        authority = [(IssueAuthority(28, "OPEN", CONVERGED_LABELS[:3]),
                      parse_control_labels(CONVERGED_LABELS[:3]))]
        items = {28: member(sprint_slug=None)}
        drifts, _ = detect_drift(authority, items, CONFIG)
        assert [d for d in drifts if "SPRINT" in d.code] == []


class TestAuthoritativeTransitionStability:
    # case 11: bootstrap derivation remains semantically stable post-transition
    def test_bootstrap_derivation_unchanged(self):
        from project_automation.service import derive_labels_for_item
        labels, review = derive_labels_for_item(member(sprint_slug="bug-fix-2026-09"), "CLOSED")
        assert "sprint:bug-fix-2026-09" in labels and review == []
        labels2, _ = derive_labels_for_item(member(sprint_slug=None), "OPEN")
        assert not any(l.startswith("sprint:") for l in labels2)

    # case 12: DraftIssue remains untouched by sprint authority
    def test_draft_item_sprint_untouched(self):
        draft = ItemState(item_id="d1", issue_number=None, is_draft=True, iteration_slug="i-001",
                          priority=None, status=None, sprint_slug="bug-fix-2026-09")
        p = plan(draft, CONVERGED_LABELS)
        assert p.mutations == []
        assert any(f.code == "DRAFT_SKIPPED" for f in p.findings)
