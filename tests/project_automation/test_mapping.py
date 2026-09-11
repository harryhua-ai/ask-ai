"""Authority→projection mapping: priority/status semantics, closure override, reopen."""
from project_automation.labels import parse_control_labels
from project_automation.mapping import resolve_desired
from project_automation.model import IssueAuthority

OPEN = "OPEN"
CLOSED = "CLOSED"


def desired_for(number, state, labels):
    return resolve_desired(IssueAuthority(number=number, state=state, labels=labels))


class TestPriorityMapping:
    def test_p0_label_maps_to_P0_option(self):
        d = desired_for(1, OPEN, ["priority:p0"])
        assert d.priority_option == "P0"

    def test_all_priorities(self):
        for label, option in [("p0", "P0"), ("p1", "P1"), ("p2", "P2")]:
            assert desired_for(1, OPEN, [f"priority:{label}"]).priority_option == option

    def test_absent_priority_label_means_clear(self):
        d = desired_for(1, OPEN, ["status:backlog"])
        assert d.priority_option is None
        assert d.priority_clear is True

    def test_conflicting_priority_yields_no_value_and_error(self):
        d = desired_for(1, OPEN, ["priority:p0", "priority:p1"])
        assert d.priority_option is None
        assert d.priority_clear is False  # never clear on conflict; leave untouched
        assert d.errors()


class TestStatusMapping:
    def test_backlog(self):
        assert desired_for(1, OPEN, ["status:backlog"]).status_option == "Backlog"

    def test_ready_is_reserved_and_produces_no_status_mutation(self):
        # Project has no 'Ready' option: status:ready is reserved/unsupported —
        # it must surface as a visible finding and never cause a Status change.
        d = desired_for(1, OPEN, ["status:ready"])
        assert d.status_option is None
        assert any("RESERVED" in e for e in d.errors())

    def test_ready_is_not_defaulted_to_backlog(self):
        # explicit reserved intent must not silently fall back to the open default
        d = desired_for(1, OPEN, ["status:ready", "priority:p1"])
        assert d.status_option is None

    def test_in_progress(self):
        assert desired_for(1, OPEN, ["status:in-progress"]).status_option == "In progress"

    def test_in_review(self):
        assert desired_for(1, OPEN, ["status:in-review"]).status_option == "In review"

    def test_open_without_status_label_defaults_backlog(self):
        d = desired_for(1, OPEN, ["priority:p1"])
        assert d.status_option == "Backlog"

    def test_closed_overrides_status_label_to_done(self):
        d = desired_for(1, CLOSED, ["status:in-progress"])
        assert d.status_option == "Done"

    def test_closed_overrides_status_conflict_to_done(self):
        d = desired_for(1, CLOSED, ["status:backlog", "status:in-progress"])
        assert d.status_option == "Done"
        assert d.errors()  # conflict still surfaced

    def test_reopen_without_status_label_not_done(self):
        # issue reopened (state OPEN) while project says Done: desired must move off Done
        d = desired_for(1, OPEN, [])
        assert d.status_option == "Backlog"
        assert d.status_option != "Done"

    def test_reopen_with_status_label_uses_label(self):
        d = desired_for(1, OPEN, ["status:in-review"])
        assert d.status_option == "In review"


class TestIterationDesired:
    def test_iteration_label_carries_semantic_key(self):
        d = desired_for(1, OPEN, ["iteration:v1.6.0"])
        assert d.iteration_key == "v1.6.0"

    def test_absent_iteration_label_means_clear(self):
        d = desired_for(1, OPEN, ["status:backlog"])
        assert d.iteration_key is None
        assert d.iteration_clear is True

    def test_conflicting_iteration_labels(self):
        d = desired_for(1, OPEN, ["iteration:i-002", "iteration:v1.6.0"])
        assert d.iteration_key is None
        assert d.iteration_clear is False
        assert d.errors()

    def test_malformed_iteration_label_surfaces_error(self):
        d = desired_for(1, OPEN, ["iteration:not valid!"])
        assert d.iteration_key is None
        assert d.errors()
