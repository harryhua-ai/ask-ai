"""Issue #69 control-plane contract tests.

These tests intentionally describe the live-schema behavior before the
implementation is changed.  They are the RED gate for the remediation.
"""
import pytest
from project_automation.errors import ProjectMutationFailure, VerificationFailure
from project_automation.mapping import resolve_desired, resolve_live_control_labels
from project_automation.model import FieldConfig, IssueAuthority, ItemState, IterationDef, OptionDef
from project_automation.service import Settings, sync_issue

CONFIG = FieldConfig(
    status_options=[OptionDef("s-open", "open"), OptionDef("s-progress", "In progress"),
                    OptionDef("s-done", "Done")],
    priority_options=[OptionDef("p0", "P0"), OptionDef("p1", "P1"), OptionDef("p2", "P2"),
                      OptionDef("p3", "P3")],
    iterations=[
        IterationDef("i-current", "I-001 — Current", "2026-09-07", 14),
        IterationDef("i-next", "v9.99.99-test", "2026-09-21", 14),
    ],
)


def test_bare_label_exactly_matching_live_iteration_is_authoritative():
    control = resolve_live_control_labels(["v9.99.99-test"], CONFIG)
    desired = resolve_desired(IssueAuthority(1, "OPEN", ["v9.99.99-test"]), control)

    assert control.has_any is True
    assert desired.iteration_key == "v9.99.99-test"
    assert desired.iteration_clear is False


def test_future_iteration_name_needs_no_source_whitelist():
    future = IterationDef("i-future", "never-before-seen", "2027-01-04", 14)
    config = FieldConfig(iterations=[future])
    control = resolve_live_control_labels(["never-before-seen"], config)

    assert control.iteration_key == "never-before-seen"
    assert control.unknown == []


def test_nonexistent_bare_label_is_ordinary_metadata():
    control = resolve_live_control_labels(["v9.99.98-test", "frontend"], CONFIG)

    assert control.has_any is False


def test_multiple_exact_iteration_labels_fail_closed():
    control = resolve_live_control_labels(["I-001 — Current", "v9.99.99-test"], CONFIG)

    assert control.has_any is True
    assert any(conflict.field == "iteration" for conflict in control.conflicts)


def test_schedule_current_never_claims_iteration_authority():
    # SCHEDULE ≠ PRODUCT ITERATION (2026-09-15 drift fix): schedule:current is
    # scheduling intent only; the explicit iteration label alone decides.
    labels = ["iteration:i-001", "schedule:current"]
    control = resolve_live_control_labels(labels, CONFIG)
    desired = resolve_desired(IssueAuthority(1, "OPEN", labels), control)

    assert control.iteration_key == "i-001"
    assert desired.iteration_key == "i-001"
    assert not any(conflict.field == "iteration" for conflict in control.conflicts)


def test_schedule_current_does_not_override_explicit_iteration():
    labels = ["iteration:v9.99.99-test", "schedule:current"]
    control = resolve_live_control_labels(labels, CONFIG)
    desired = resolve_desired(IssueAuthority(1, "OPEN", labels), control)

    assert desired.iteration_key == "v9.99.99-test"
    assert not any(conflict.field == "iteration" for conflict in control.conflicts)


def test_priority_is_validated_against_live_options_not_source_whitelist():
    control = resolve_live_control_labels(["priority:p3"], CONFIG)
    desired = resolve_desired(IssueAuthority(1, "OPEN", ["priority:p3"]), control)

    assert desired.priority_option == "P3"


def test_missing_priority_option_is_a_planning_failure():
    config = FieldConfig(priority_options=[OptionDef("p0", "P0")])
    control = resolve_live_control_labels(["priority:p3"], config)
    desired = resolve_desired(IssueAuthority(1, "OPEN", ["priority:p3"]), control)

    from project_automation.planner import plan_sync

    plan = plan_sync(item=ItemState("item", 1, False, None, None, "open"),
                     desired_status=None, desired_priority=desired.priority_option,
                     desired_priority_clear=False, desired_iteration_key=None,
                     desired_iteration_clear=True, config=config)
    assert any(f.code == "UNKNOWN_OPTION" and f.field == "priority" for f in plan.findings)


class _SyncTransport:
    """Minimal live-shaped GraphQL transport with controllable verification."""

    def __init__(self, labels, *, iteration=None, mismatch=False, fail_read=False, fail_mutation=False,
                 item_status="open"):
        self.labels = labels
        self.iteration = iteration
        self.mismatch = mismatch
        self.fail_read = fail_read
        self.fail_mutation = fail_mutation
        self.item_status = item_status
        self.mutations = []

    def graphql(self, query, **variables):
        if "status: field(name: \"Status\")" in query:
            if self.fail_read:
                raise ProjectMutationFailure("simulated Project schema read failure")
            return {"user": {"projectV2": {
                "id": "PVT_1",
                "status": {"id": "F_S", "options": [
                    {"id": "s-open", "name": "open"},
                    {"id": "s-progress", "name": "In progress"},
                    {"id": "s-done", "name": "Done"},
                ]},
                "priority": {"id": "F_P", "options": [
                    {"id": "p0", "name": "P0"}, {"id": "p1", "name": "P1"},
                    {"id": "p2", "name": "P2"}, {"id": "p3", "name": "P3"},
                ]},
                "iteration": {"id": "F_I", "configuration": {
                    "duration": 14, "iterations": [
                        {"id": "i-current", "title": "I-001 — Current",
                         "startDate": "2026-09-07", "duration": 14},
                        {"id": "i-next", "title": "v9.99.99-test",
                         "startDate": "2026-09-21", "duration": 14},
                    ], "completedIterations": []}},
            }, "repository": {"id": "R_1"}}}
        if "issue(number:" in query:
            return {"repository": {"issue": {
                "id": "ISSUE_1", "number": 68, "state": "OPEN",
                "labels": {"nodes": [{"name": label} for label in self.labels]},
                "projectItems": {"nodes": [{"id": "ITEM_1", "project": {"id": "PVT_1", "number": 2}}]},
            }}}
        if "items(first: 100" in query:
            actual = None if self.mismatch else self.iteration
            return {"user": {"projectV2": {"items": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [{"id": "ITEM_1", "content": {"__typename": "Issue", "number": 68,
                                                                  "state": "OPEN"},
                           "iteration": ({"iterationId": "i-next", "title": actual}
                                         if actual else None),
                           "priority": None, "status": {"name": self.item_status}}]
            }}}}
        if "updateProjectV2ItemFieldValue" in query:
            if self.fail_mutation:
                raise ProjectMutationFailure("simulated Project mutation failure")
            self.mutations.append(query)
            if "iterationId" in query:
                self.iteration = "v9.99.99-test"
            return {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "ITEM_1"}}}
        raise AssertionError(f"unexpected query: {query[:100]}")


def _settings():
    return Settings(owner="harryhua-ai", repo="ask-ai", project_number=2, token="x")


def test_sync_exact_iteration_mutates_and_reads_back():
    transport = _SyncTransport(["v9.99.99-test"], iteration=None)

    report = sync_issue(transport, _settings(), 68, dry_run=False)

    assert report["result"] == "APPLIED"
    assert report["read_back"]["verified"] is True
    assert report["after"]["iteration"] == "v9.99.99-test"


def test_already_converged_is_verified_noop():
    transport = _SyncTransport(["v9.99.99-test"], iteration="v9.99.99-test")

    report = sync_issue(transport, _settings(), 68, dry_run=False)

    assert report["result"] == "ALREADY_CONVERGED"
    assert report["mutations"] == []
    assert report["read_back"]["verified"] is True


def test_sync_schedule_label_never_rewrites_iteration():
    # The live-incident regression: an issue carrying only schedule:current whose
    # Project item already holds an Iteration must converge with ZERO mutations —
    # the calendar-current iteration is never written (Actions run 34926050556
    # rewrote v1.6.3 → I-001 exactly here before the fix).
    transport = _SyncTransport(["schedule:current"], iteration="I-001 — Current")

    report = sync_issue(transport, _settings(), 68, dry_run=False)

    assert report["result"] == "ALREADY_CONVERGED"
    assert report["mutations"] == []
    assert transport.mutations == []


def test_sync_without_iteration_authority_preserves_existing_iteration():
    # R2 (Role A): the reviewer's exact scenario end-to-end — no iteration:*
    # AND no schedule:* label. Absence of Iteration authority is
    # UNMANAGED/PRESERVE: the item's existing Iteration is never cleared.
    transport = _SyncTransport(["status:in-progress"], iteration="I-001 — Current",
                               item_status="In progress")

    report = sync_issue(transport, _settings(), 68, dry_run=False)

    assert report["result"] == "ALREADY_CONVERGED"
    assert report["mutations"] == []
    assert report["requested"]["iteration_clear"] is False
    assert transport.mutations == []


def test_read_back_mismatch_is_failure():
    transport = _SyncTransport(["v9.99.99-test"], iteration=None, mismatch=True)

    with pytest.raises(VerificationFailure, match="did not converge"):
        sync_issue(transport, _settings(), 68, dry_run=False)


def test_mutation_failure_is_failure():
    transport = _SyncTransport(["v9.99.99-test"], iteration=None, fail_mutation=True)

    with pytest.raises(ProjectMutationFailure, match="simulated Project mutation failure"):
        sync_issue(transport, _settings(), 68, dry_run=False)


def test_ordinary_labels_are_a_legitimate_noop():
    transport = _SyncTransport(["frontend"], iteration="v9.99.99-test")

    report = sync_issue(transport, _settings(), 68, dry_run=False)

    assert report["result"] == "NO_CONTROL_INTENT"
    assert transport.mutations == []


def test_recognized_missing_iteration_fails_without_mutation():
    transport = _SyncTransport(["iteration:does-not-exist"], iteration=None)

    report = sync_issue(transport, _settings(), 68, dry_run=False)

    assert report["result"] == "FAILED_VALIDATION"
    assert any(f["code"] == "UNKNOWN_ITERATION" for f in report["findings"])
    assert transport.mutations == []


def test_project_api_read_failure_is_not_a_success():
    transport = _SyncTransport(["v9.99.99-test"], fail_read=True)

    with pytest.raises(ProjectMutationFailure, match="schema read failure"):
        sync_issue(transport, _settings(), 68, dry_run=False)
