"""Sprint is no longer part of the ASK-AI Project governance schema (product decision, frozen).

The Project's Sprint field was intentionally deleted by the Product Owner. The
automation still resolves ``field(name: "Sprint")`` in PROJECT_CONTEXT, which
GitHub hard-errors when the field is absent (live evidence: Actions run
34927298633 — "Could not resolve to a Unions::ProjectV2FieldConfiguration with
the name Sprint") — so project-sync / project-reconcile / iteration-create all
fail at schema load before any legitimate work.

Target contract proven here: the control plane operates correctly with
Iteration + Priority + Status only, on a schema with NO Sprint field, without
regressing the Iteration R2 semantics (schedule never owns Iteration; absence
of Iteration authority = PRESERVE).
"""
import re

import pytest

from project_automation import service as service_module
from project_automation.errors import ProjectMutationFailure
from project_automation.model import IssueAuthority
from project_automation.queries import PROJECT_CONTEXT, PROJECT_ITEMS
from project_automation.service import Settings, fetch_context, reconcile, sync_issue

LIVE_SPRINT_ERROR = ("gh api graphql failed: gh: Could not resolve to a "
                     "Unions::ProjectV2FieldConfiguration with the name Sprint")

ITERATION_TITLES = {"i-001": "I-001 — Answer Intelligence Foundation", "v163": "v1.6.3"}
STATUS_NAMES = {"s-open": "open", "s-progress": "In progress", "s-done": "Done"}
PRIORITY_NAMES = {"p1": "P1"}


class SprintLessProjectTransport:
    """Live-shaped transport for a Project whose Sprint field has been deleted.

    GitHub rejects the entire PROJECT_CONTEXT document while it still contains
    ``field(name: "Sprint")``; this transport reproduces that exactly.
    """

    def __init__(self, *, labels=(), issue_state="OPEN", item_iteration_id=None,
                 item_priority=None, item_status="open"):
        self.labels = list(labels)
        self.issue_state = issue_state
        self.item_iteration_id = item_iteration_id
        self.item_priority = item_priority
        self.item_status = item_status
        self.mutations = []

    def graphql(self, query, **variables):
        if 'field(name: "Sprint")' in query:
            raise ProjectMutationFailure(LIVE_SPRINT_ERROR)
        if 'status: field(name: "Status")' in query:
            return {"user": {"projectV2": {
                "id": "PVT_1",
                "status": {"id": "F_S", "options": [{"id": i, "name": n} for i, n in STATUS_NAMES.items()]},
                "priority": {"id": "F_P", "options": [{"id": i, "name": n} for i, n in PRIORITY_NAMES.items()]},
                "iteration": {"id": "F_I", "configuration": {"duration": 14, "iterations": [
                    {"id": "i-001", "title": ITERATION_TITLES["i-001"], "startDate": "2026-09-07", "duration": 14},
                    {"id": "v163", "title": ITERATION_TITLES["v163"], "startDate": "2026-11-02", "duration": 14}],
                    "completedIterations": []}},
            }, "repository": {"id": "R_1"}}}
        if "issue(number:" in query:
            return {"repository": {"issue": {
                "id": "ISSUE_71", "number": 71, "state": self.issue_state,
                "labels": {"nodes": [{"name": label} for label in self.labels]},
                "projectItems": {"nodes": [{"id": "ITEM_1", "project": {"id": "PVT_1", "number": 2}}]},
            }}}
        if "items(first: 100" in query:
            return {"user": {"projectV2": {"items": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [{"id": "ITEM_1",
                           "content": {"__typename": "Issue", "number": 71, "state": self.issue_state},
                           "iteration": ({"iterationId": self.item_iteration_id,
                                          "title": ITERATION_TITLES[self.item_iteration_id]}
                                         if self.item_iteration_id else None),
                           "priority": ({"name": PRIORITY_NAMES[self.item_priority]}
                                        if self.item_priority else None),
                           "status": {"name": self.item_status}}]
            }}}}
        if "updateProjectV2ItemFieldValue" in query:
            self.mutations.append(query)
            iteration_id = re.search(r'iterationId: "([^"]+)"', query)
            if iteration_id:
                self.item_iteration_id = iteration_id.group(1)
            option_id = re.search(r'singleSelectOptionId: "([^"]+)"', query)
            if option_id:
                if 'fieldId: "F_P"' in query:
                    self.item_priority = option_id.group(1)
                else:
                    self.item_status = STATUS_NAMES.get(option_id.group(1), self.item_status)
            if "clearProjectV2ItemFieldValue" not in query and "fieldId: \"F_P\"" in query and not option_id:
                self.item_priority = None
            return {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "ITEM_1"}}}
        if "clearProjectV2ItemFieldValue" in query:
            self.mutations.append(query)
            return {"clearProjectV2ItemFieldValue": {"projectV2Item": {"id": "ITEM_1"}}}
        raise AssertionError(f"unexpected query: {query[:120]}")


def _settings():
    return Settings(owner="harryhua-ai", repo="ask-ai", project_number=2, token="x")


def test_red1_context_discovery_succeeds_without_sprint_field():
    ctx = fetch_context(SprintLessProjectTransport(), _settings())
    assert ctx.project_id == "PVT_1"
    assert ctx.field_ids["iteration"] == "F_I"
    assert [i.slug for i in ctx.config.iterations] == ["i-001", "v1.6.3"]


def test_red2_sync_issue_completes_without_sprint_field():
    transport = SprintLessProjectTransport(labels=["schedule:current"], item_iteration_id="v163")
    report = sync_issue(transport, _settings(), 71, dry_run=False)
    assert report["result"] == "ALREADY_CONVERGED"
    assert transport.mutations == []


def test_red3_reconcile_completes_without_sprint_field(monkeypatch):
    monkeypatch.setattr(service_module, "list_repo_issues",
                        lambda s: [IssueAuthority(71, "OPEN", ["priority:p1"])])
    transport = SprintLessProjectTransport(labels=["priority:p1"], item_iteration_id="v163",
                                           item_priority="p1", item_status="Backlog")
    report = reconcile(transport, _settings(), dry_run=False)
    assert report["result"] == "NO_DRIFT"
    assert transport.mutations == []


def test_red4_no_query_document_references_sprint_field():
    assert "Sprint" not in PROJECT_CONTEXT
    assert "Sprint" not in PROJECT_ITEMS


def test_control4_iteration_field_still_resolves_without_sprint():
    ctx = fetch_context(SprintLessProjectTransport(), _settings())
    assert ctx.field_ids["status"] == "F_S"
    assert ctx.field_ids["priority"] == "F_P"
    assert ctx.field_ids["iteration"] == "F_I"


def test_control5_priority_mutation_still_works_without_sprint():
    transport = SprintLessProjectTransport(labels=["priority:p1"], item_iteration_id="v163",
                                           item_priority=None)
    report = sync_issue(transport, _settings(), 71, dry_run=False)
    assert report["result"] == "APPLIED"
    assert transport.item_priority == "p1"
    assert transport.item_iteration_id == "v163"  # untouched by the Priority convergence


def test_control6_status_mutation_still_works_without_sprint():
    transport = SprintLessProjectTransport(labels=["priority:p1"], issue_state="CLOSED",
                                           item_iteration_id="v163", item_status="open")
    report = sync_issue(transport, _settings(), 71, dry_run=False)
    assert report["result"] == "APPLIED"
    assert transport.item_status == "Done"  # closure semantics intact
    assert transport.item_iteration_id == "v163"


def test_control7_iteration_r2_preserve_semantics_without_sprint():
    # schedule:current on a sprint-less schema: existing Iteration preserved,
    # nothing guessed, zero mutations.
    transport = SprintLessProjectTransport(labels=["schedule:current"], item_iteration_id="v163")
    report = sync_issue(transport, _settings(), 71, dry_run=False)
    assert report["result"] == "ALREADY_CONVERGED"
    assert report["requested"]["iteration_clear"] is False
    assert transport.item_iteration_id == "v163"
    assert transport.mutations == []


def test_control8_explicit_iteration_authority_works_without_sprint():
    transport = SprintLessProjectTransport(labels=["iteration:v1.6.3"], item_iteration_id="i-001")
    report = sync_issue(transport, _settings(), 71, dry_run=False)
    assert report["result"] == "APPLIED"
    assert transport.item_iteration_id == "v163"
    assert any("iterationId: \"v163\"" in m for m in transport.mutations)
