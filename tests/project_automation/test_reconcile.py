"""Reconciliation drift detection over a real Project snapshot fixture."""
import json
from pathlib import Path

from project_automation.labels import parse_control_labels
from project_automation.model import FieldConfig, IterationDef, IssueAuthority, ItemState, OptionDef
from project_automation.reconcile import detect_drift

FIXTURE = Path(__file__).parent / "fixtures" / "project_snapshot_20260911.json"

CONFIG = FieldConfig(
    status_options=[OptionDef("s1", "Backlog"), OptionDef("s2", "In progress"), OptionDef("s3", "In review"), OptionDef("s4", "Done")],
    priority_options=[OptionDef("p1", "P0"), OptionDef("p2", "P1"), OptionDef("p3", "P2")],
    iterations=[],
)


def load_fixture():
    return json.loads(FIXTURE.read_text())


class TestDriftDetection:
    def test_fixture_loads_real_snapshot_shape(self):
        snap = load_fixture()
        assert snap["iterations"]["v1.6.0"]["title"].startswith("v1.6.0")
        assert "items" in snap and len(snap["items"]) > 40

    def test_missing_membership_is_fixable(self):
        authority = [(IssueAuthority(99, "OPEN", ["priority:p1", "status:backlog"]), parse("priority:p1", "status:backlog"))]
        items = {}
        drifts, skipped = detect_drift(authority, items, config_from_fixture())
        assert any(d.code == "MISSING_FROM_PROJECT" and d.fixable for d in drifts)

    def test_wrong_priority_repaired(self):
        authority = [(IssueAuthority(30, "OPEN", ["priority:p0", "status:backlog"]), parse("priority:p0", "status:backlog"))]
        items = {30: ItemState(item_id="i", issue_number=30, is_draft=False, iteration_slug=None, priority="P2", status="Backlog")}
        drifts, _ = detect_drift(authority, items, config_from_fixture())
        wrong = [d for d in drifts if d.code == "WRONG_PRIORITY"]
        assert wrong and wrong[0].fixable

    def test_closed_issue_not_done_is_fixable(self):
        authority = [(IssueAuthority(4, "CLOSED", ["status:backlog"]), parse("status:backlog"))]
        items = {4: ItemState(item_id="i", issue_number=4, is_draft=False, iteration_slug=None, priority=None, status="In progress")}
        drifts, _ = detect_drift(authority, items, config_from_fixture())
        assert any(d.code == "CLOSED_NOT_DONE" and d.fixable for d in drifts)

    def test_reopened_issue_stuck_done_is_fixable(self):
        authority = [(IssueAuthority(7, "OPEN", ["status:backlog"]), parse("status:backlog"))]
        items = {7: ItemState(item_id="i", issue_number=7, is_draft=False, iteration_slug=None, priority=None, status="Done")}
        drifts, _ = detect_drift(authority, items, config_from_fixture())
        assert any(d.code == "OPEN_BUT_DONE" and d.fixable for d in drifts)

    def test_unknown_iteration_label_reported_not_fixed(self):
        authority = [(IssueAuthority(7, "OPEN", ["iteration:v1.7.0", "status:backlog"]), parse("iteration:v1.7.0", "status:backlog"))]
        items = {7: ItemState(item_id="i", issue_number=7, is_draft=False, iteration_slug=None, priority=None, status="Backlog")}
        drifts, _ = detect_drift(authority, items, config_from_fixture())
        bad = [d for d in drifts if d.code == "UNKNOWN_ITERATION_LABEL"]
        assert bad and not bad[0].fixable

    def test_conflicting_labels_reported_not_fixed(self):
        authority = [(IssueAuthority(7, "OPEN", ["priority:p0", "priority:p1"]), parse("priority:p0", "priority:p1"))]
        items = {7: ItemState(item_id="i", issue_number=7, is_draft=False, iteration_slug=None, priority=None, status="Backlog")}
        drifts, _ = detect_drift(authority, items, config_from_fixture())
        bad = [d for d in drifts if d.code == "CONFLICTING_LABELS"]
        assert bad and not bad[0].fixable

    def test_unopted_member_issue_is_skipped_not_drift(self):
        authority = [(IssueAuthority(7, "OPEN", ["bug"]), parse("bug"))]
        items = {7: ItemState(item_id="i", issue_number=7, is_draft=False, iteration_slug=None, priority="P2", status="Backlog")}
        drifts, skipped = detect_drift(authority, items, config_from_fixture())
        assert drifts == []
        assert skipped and skipped[0].code == "NO_CONTROL_METADATA"

    def test_draft_items_skipped(self):
        drifts, skipped = detect_drift([], {}, config_from_fixture(), draft_items=2)
        assert drifts == []
        assert skipped and skipped[0].code == "DRAFT_NO_AUTHORITY"


def parse(*labels):
    return parse_control_labels(list(labels))


def config_from_fixture():
    snap = load_fixture()
    iterations = [
        IterationDef(id=v.get("id", "x"), title=v["title"], start_date=v["start_date"], duration=v["duration"])
        for v in snap["iterations"].values()
    ]
    return FieldConfig(
        status_options=CONFIG.status_options,
        priority_options=CONFIG.priority_options,
        iterations=iterations,
    )
