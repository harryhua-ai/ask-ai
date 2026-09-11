"""sprint:* label authority — Sprint field convergence (narrow increment).

Frozen semantics preserved: iteration:*→Iteration, priority:*→Priority,
status:*→Status mappings are untouched; Sprint is an independent dimension and
a Sprint label never mutates Iteration (nor vice versa).

Additive authority (v1): an ABSENT sprint label leaves the Sprint field
untouched — bootstrap cannot run inside the increment that introduces sprint
labels, so absent→clear would erase existing manual Sprint values before
labels could be derived. Clearing Sprint is not expressible in v1.
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

MEMBER = ItemState(item_id="it1", issue_number=28, is_draft=False, iteration_slug="v1.6.0",
                   priority="P1", status="Backlog", sprint_slug="bug-fix-2026-09")


def desired(labels, state="OPEN"):
    return resolve_desired(IssueAuthority(number=28, state=state, labels=labels))


def plan(item, labels):
    d = resolve_desired(IssueAuthority(number=28, state="OPEN", labels=labels))
    return plan_sync(item=item, desired_status=d.status_option,
                     desired_priority=d.priority_option, desired_priority_clear=d.priority_clear,
                     desired_iteration_key=d.iteration_key, desired_iteration_clear=d.iteration_clear,
                     desired_sprint_key=d.sprint_key, desired_sprint_touch=d.sprint_touch,
                     config=CONFIG)


class TestSprintVocabulary:
    def test_canonical_sprint_label_parsed(self):
        cl = parse_control_labels(["sprint:bug-fix-2026-09"])
        assert cl.sprint_key == "bug-fix-2026-09"
        assert cl.has_sprint_label is True

    def test_conflicting_sprint_labels_detected(self):
        cl = parse_control_labels(["sprint:bug-fix-2026-09", "sprint:other-sprint"])
        assert cl.sprint_key is None
        assert cl.conflicts and cl.conflicts[0].field == "sprint"

    def test_sprint_label_opts_issue_into_projection(self):
        assert parse_control_labels(["sprint:bug-fix-2026-09"]).has_any is True


class TestSprintMapping:
    def test_canonical_label_resolves_desired_sprint(self):
        d = desired(["sprint:bug-fix-2026-09"])
        assert d.sprint_key == "bug-fix-2026-09"
        assert d.sprint_touch is True

    def test_absent_sprint_label_is_additive_no_touch(self):
        # bootstrap cannot run inside this increment: absent label must NOT clear
        # existing manual Sprint values (11 issues carry them today)
        d = desired(["status:backlog", "priority:p1", "iteration:i-001"])
        assert d.sprint_touch is False
        assert d.sprint_key is None

    def test_conflicting_sprint_labels_fail_closed(self):
        d = desired(["sprint:bug-fix-2026-09", "sprint:other-sprint"])
        assert d.sprint_touch is False
        assert d.errors()

    def test_sprint_and_iteration_are_independent_dimensions(self):
        d = desired(["sprint:bug-fix-2026-09", "iteration:i-001"])
        assert d.sprint_key == "bug-fix-2026-09"
        assert d.iteration_key == "i-001"


class TestSprintPlanning:
    def test_canonical_label_plans_set_sprint(self):
        item = ItemState(item_id="it1", issue_number=28, is_draft=False, iteration_slug="v1.6.0",
                         priority="P1", status="Backlog", sprint_slug=None)
        p = plan(item, ["sprint:bug-fix-2026-09", "status:backlog", "priority:p1", "iteration:v1.6.0"])
        kinds = [m.kind for m in p.mutations]
        assert "set_sprint" in kinds
        m = next(m for m in p.mutations if m.kind == "set_sprint")
        assert m.payload["sprint_title"].startswith("Bug Fix Sprint")

    def test_already_correct_plans_zero_sprint_mutation(self):
        p = plan(MEMBER, ["sprint:bug-fix-2026-09", "status:backlog", "priority:p1", "iteration:v1.6.0"])
        assert [m.kind for m in p.mutations if "sprint" in m.kind] == []
        assert p.mutations == [] and p.findings == []

    def test_unknown_sprint_key_fails_closed_without_mutation(self):
        p = plan(MEMBER, ["sprint:future-sprint", "status:backlog"])
        assert [m.kind for m in p.mutations if "sprint" in m.kind] == []
        assert p.findings and p.findings[0].code == "UNKNOWN_SPRINT"
        assert p.findings[0].field == "sprint"

    def test_sprint_failure_isolation_keeps_other_fields_planned(self):
        # unknown sprint must not corrupt/block Iteration, Priority or Status
        item = ItemState(item_id="it1", issue_number=28, is_draft=False, iteration_slug="v1.6.0",
                         priority="P1", status="Backlog", sprint_slug="bug-fix-2026-09")
        p = plan(item, ["sprint:future-sprint", "status:in-review", "priority:p0", "iteration:i-001"])
        kinds = [m.kind for m in p.mutations]
        assert "set_status" in kinds and "set_priority" in kinds and "set_iteration" in kinds
        assert all("sprint" not in k for k in kinds)

    def test_sprint_label_never_mutates_iteration(self):
        item = ItemState(item_id="it1", issue_number=28, is_draft=False, iteration_slug="v1.6.0",
                         priority="P1", status="Backlog", sprint_slug=None)
        p = plan(item, ["sprint:bug-fix-2026-09", "status:backlog", "priority:p1", "iteration:v1.6.0"])
        assert [m.kind for m in p.mutations] == ["set_sprint"]

    def test_iteration_label_never_mutates_sprint(self):
        item = ItemState(item_id="it1", issue_number=28, is_draft=False, iteration_slug=None,
                         priority="P1", status="Backlog", sprint_slug="bug-fix-2026-09")
        p = plan(item, ["iteration:i-001"])
        assert [m.kind for m in p.mutations if "sprint" in m.kind] == []


class TestSprintReconcile:
    def test_reconcile_detects_wrong_sprint_drift(self):
        authority = [(IssueAuthority(28, "OPEN", ["sprint:bug-fix-2026-09", "status:backlog"]),
                      parse_control_labels(["sprint:bug-fix-2026-09", "status:backlog"]))]
        items = {28: ItemState(item_id="i", issue_number=28, is_draft=False, iteration_slug=None,
                               priority="P1", status="Backlog", sprint_slug=None)}
        drifts, _ = detect_drift(authority, items, CONFIG)
        wrong = [d for d in drifts if d.code == "WRONG_SPRINT"]
        assert wrong and wrong[0].fixable

    def test_reconcile_repairs_deterministic_sprint_drift(self):
        authority = [(IssueAuthority(28, "OPEN", ["sprint:bug-fix-2026-09", "status:backlog"]),
                      parse_control_labels(["sprint:bug-fix-2026-09", "status:backlog"]))]
        items = {28: ItemState(item_id="i", issue_number=28, is_draft=False, iteration_slug=None,
                               priority="P1", status="Backlog", sprint_slug=None)}
        drifts, _ = detect_drift(authority, items, CONFIG)
        fix = next(d for d in drifts if d.code == "WRONG_SPRINT").fix
        assert any(m.kind == "set_sprint" for m in fix.mutations)

    def test_reconcile_additive_sprint_no_false_drift(self):
        # project has a Sprint value, issue has no sprint label yet → untouched, no drift
        authority = [(IssueAuthority(28, "OPEN", ["status:backlog", "priority:p1"]),
                      parse_control_labels(["status:backlog", "priority:p1"]))]
        items = {28: MEMBER}
        drifts, _ = detect_drift(authority, items, CONFIG)
        assert [d for d in drifts if "sprint" in d.code] == []

    def test_reconcile_unknown_sprint_label_reported_not_fixed(self):
        authority = [(IssueAuthority(28, "OPEN", ["sprint:future-sprint"]),
                      parse_control_labels(["sprint:future-sprint"]))]
        items = {28: MEMBER}
        drifts, _ = detect_drift(authority, items, CONFIG)
        bad = [d for d in drifts if d.code == "UNKNOWN_SPRINT_LABEL"]
        assert bad and not bad[0].fixable
        assert all("sprint" not in (d.fix.mutations[0].kind if d.fix and d.fix.mutations else "")
                   for d in drifts if d.fixable)


class TestSprintBootstrapDerivation:
    def test_derive_labels_include_sprint(self):
        from project_automation.service import derive_labels_for_item
        labels, review = derive_labels_for_item(MEMBER, "CLOSED")
        assert "sprint:bug-fix-2026-09" in labels
        assert review == []

    def test_derive_without_sprint_value_adds_no_sprint_label(self):
        from project_automation.service import derive_labels_for_item
        bare = ItemState(item_id="it2", issue_number=30, is_draft=False, iteration_slug="v1.6.0",
                         priority="P0", status="Backlog", sprint_slug=None)
        labels, review = derive_labels_for_item(bare, "OPEN")
        assert not any(l.startswith("sprint:") for l in labels)
