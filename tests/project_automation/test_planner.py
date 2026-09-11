"""Sync planning: diffs, idempotency, membership, option availability."""
from project_automation.model import FieldConfig, ItemState, OptionDef
from project_automation.planner import plan_sync

STATUS = FieldConfig(
    status_options=[OptionDef("s1", "Backlog"), OptionDef("s2", "In progress"), OptionDef("s3", "Done")],
    priority_options=[OptionDef("p1", "P0"), OptionDef("p2", "P1"), OptionDef("p3", "P2")],
    iterations=[],
)

MEMBER = ItemState(item_id="item-1", issue_number=30, is_draft=False, iteration_slug=None, priority="P2", status="Backlog")


class TestIdempotentSync:
    def test_already_correct_produces_zero_mutations(self):
        d = plan_sync(item=MEMBER, desired_priority="P2", desired_priority_clear=False,
                      desired_status="Backlog", desired_iteration_key=None, desired_iteration_clear=True, config=STATUS)
        assert d.mutations == []
        assert d.findings == []

    def test_rerun_after_apply_is_noop(self):
        first = plan_sync(item=MEMBER, desired_priority="P1", desired_priority_clear=False,
                          desired_status="In progress", desired_iteration_key=None, desired_iteration_clear=True, config=STATUS)
        assert len(first.mutations) == 2
        after = ItemState(item_id="item-1", issue_number=30, is_draft=False, iteration_slug=None, priority="P1", status="In progress")
        second = plan_sync(item=after, desired_priority="P1", desired_priority_clear=False,
                           desired_status="In progress", desired_iteration_key=None, desired_iteration_clear=True, config=STATUS)
        assert second.mutations == []


class TestMembership:
    def test_non_member_gets_membership_plus_all_fields(self):
        d = plan_sync(item=None, desired_priority="P0", desired_priority_clear=False,
                      desired_status="Backlog", desired_iteration_key=None, desired_iteration_clear=True, config=STATUS)
        kinds = [m.kind for m in d.mutations]
        assert kinds[0] == "add_membership"
        assert "set_priority" in kinds
        assert "set_status" in kinds


class TestClearSemantics:
    def test_absent_priority_label_clears_existing_value(self):
        d = plan_sync(item=MEMBER, desired_priority=None, desired_priority_clear=True,
                      desired_status="Backlog", desired_iteration_key=None, desired_iteration_clear=True, config=STATUS)
        kinds = [m.kind for m in d.mutations]
        assert kinds == ["clear_priority"]

    def test_absent_iteration_label_clears_existing_iteration(self):
        member = ItemState(item_id="item-1", issue_number=30, is_draft=False, iteration_slug="i-002", priority=None, status="Backlog")
        d = plan_sync(item=member, desired_priority=None, desired_priority_clear=True,
                      desired_status="Backlog", desired_iteration_key=None, desired_iteration_clear=True, config=STATUS)
        assert [m.kind for m in d.mutations] == ["clear_iteration"]


class TestOptionAvailability:
    def test_status_option_missing_surfaces_unknown_option(self):
        d = plan_sync(item=MEMBER, desired_priority="P1", desired_priority_clear=False,
                      desired_status="Ready", desired_iteration_key=None, desired_iteration_clear=True, config=STATUS)
        assert [m.kind for m in d.mutations] == ["set_priority"]
        assert d.findings and d.findings[0].code == "UNKNOWN_OPTION"
        assert "Ready" in d.findings[0].message

    def test_priority_option_missing_surfaces_unknown_option(self):
        d = plan_sync(item=MEMBER, desired_priority="P3", desired_priority_clear=False,
                      desired_status="Backlog", desired_iteration_key=None, desired_iteration_clear=True, config=STATUS)
        assert d.findings and d.findings[0].code == "UNKNOWN_OPTION"


class TestDraftSafety:
    def test_draft_items_are_never_mutated(self):
        draft = ItemState(item_id="d1", issue_number=None, is_draft=True, iteration_slug=None, priority=None, status="Done")
        d = plan_sync(item=draft, desired_priority="P0", desired_priority_clear=False,
                      desired_status="Backlog", desired_iteration_key=None, desired_iteration_clear=True, config=STATUS)
        assert d.mutations == []
        assert any(f.code == "DRAFT_SKIPPED" for f in d.findings)
