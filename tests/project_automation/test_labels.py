"""Canonical control-label vocabulary: parsing, validation, conflict detection."""
import pytest

from project_automation.labels import (
    ControlLabels,
    has_any_control_label,
    parse_control_labels,
)


class TestParseControlLabels:
    def test_single_valid_priority(self):
        cl = parse_control_labels(["bug", "priority:p0"])
        assert cl.priority == "p0"
        assert cl.iteration_key is None
        assert cl.status is None
        assert cl.conflicts == []
        assert cl.unknown == []

    def test_all_three_prefixes(self):
        cl = parse_control_labels(["iteration:v1.6.0", "priority:p1", "status:in-review"])
        assert cl.iteration_key == "v1.6.0"
        assert cl.priority == "p1"
        assert cl.status == "in-review"

    def test_casing_normalized(self):
        cl = parse_control_labels(["Priority:P0", "STATUS:Backlog"])
        assert cl.priority == "p0"
        assert cl.status == "backlog"

    def test_duplicate_identical_labels_not_conflict(self):
        cl = parse_control_labels(["priority:p0", "priority:p0"])
        assert cl.priority == "p0"
        assert cl.conflicts == []

    def test_conflicting_priority_labels(self):
        cl = parse_control_labels(["priority:p0", "priority:p1"])
        assert cl.priority is None
        assert len(cl.conflicts) == 1
        assert cl.conflicts[0].field == "priority"
        assert set(cl.conflicts[0].values) == {"p0", "p1"}

    def test_conflicting_status_labels(self):
        cl = parse_control_labels(["status:backlog", "status:in-progress"])
        assert cl.status is None
        assert cl.conflicts[0].field == "status"

    def test_unknown_priority_value_reported(self):
        cl = parse_control_labels(["priority:p9"])
        assert cl.priority is None
        assert any("priority:p9" in u for u in cl.unknown)

    def test_unknown_status_value_reported(self):
        cl = parse_control_labels(["status:discovery"])
        assert cl.status is None
        assert cl.unknown

    def test_iteration_key_slug_normalization(self):
        cl = parse_control_labels(["iteration:I-UX-001"])
        assert cl.iteration_key == "i-ux-001"

    def test_iteration_key_malformed_rejected(self):
        cl = parse_control_labels(["iteration:foo bar;rm -rf /"])
        assert cl.iteration_key is None
        assert cl.unknown

    def test_iteration_key_too_long_rejected(self):
        cl = parse_control_labels(["iteration:" + "a" * 80])
        assert cl.iteration_key is None
        assert cl.unknown

    def test_non_control_labels_ignored(self):
        cl = parse_control_labels(["bug", "documentation", "priority: p0 "])
        assert cl.priority == "p0"  # whitespace tolerated, normalized

    def test_empty_labels(self):
        cl = parse_control_labels([])
        assert cl == ControlLabels()


class TestOptIn:
    def test_any_control_label_opts_in(self):
        assert has_any_control_label(["bug", "status:backlog"]) is True

    def test_malformed_control_label_still_opts_in(self):
        # an attempted control label signals intent; it must surface as unknown, not be ignored
        assert has_any_control_label(["priority:banana"]) is True

    def test_no_control_label_no_optin(self):
        assert has_any_control_label(["bug", "enhancement"]) is False
