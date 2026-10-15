"""CLOSED-issue sync behavior — live-defect regression tests.

Root causes proven from real Actions evidence (runs 34599644360/34599655896/
34599672245/34599689927):

D — sync_issue passes the plan containing `add_membership` straight to
    apply_plan, which raises "unknown mutation kind 'add_membership'" AFTER the
    item was already added: first sync of any not-yet-member issue partially
    applies (membership yes, Iteration/Priority/Status never) and fails.
B — the single global concurrency group `project-automation` lets GitHub
    replace every PENDING per-issue run in a label burst; all but the last
    event's run are cancelled (runs for #20/#21/#34/#45 at 23:26Z), so those
    issues never converge. Per-issue concurrency keys and dispatch input
    sanitization addressed those findings. Workflow-level assertions were
    removed when the Project Actions entrypoints were retired.
"""
import sys
sys.path.insert(0, "scripts")
from project_automation.service import Settings, sync_issue

class _NonMemberFakeTransport:
    """Live-shape transport where the issue is NOT yet a Project member.

    Mirrors the real GraphQL shapes closely enough to drive sync_issue through
    ADD_ITEM; records every mutation so the test can assert convergence.
    """

    def __init__(self, labels):
        self.labels = list(labels)
        self.item_added = False
        self.item = {"priority": None, "iteration": None, "status": None}

    def graphql(self, query, **variables):
        if "clearProjectV2ItemFieldValue" in query:
            raise AssertionError("clear not expected in this scenario")
        if "addProjectV2ItemById" in query:
            self.item_added = True
            return {"addProjectV2ItemById": {"item": {"id": "ITEM_NEW"}}}
        if 'status: field(name: "Status")' in query:
            return {"user": {"projectV2": {
                "id": "PVT_1",
                "status": {"id": "F_S", "options": [{"id": "s1", "name": "Backlog"},
                                                    {"id": "s3", "name": "Done"}]},
                "priority": {"id": "F_P", "options": [{"id": "p3", "name": "P2"}]},
                "iteration": {"id": "F_I", "configuration": {"duration": 14, "iterations": [
                    {"id": "i2", "title": "v1.6.0 — Knowledge Integrity & Source Truth",
                     "startDate": "2026-10-05", "duration": 14}],
                    "completedIterations": [
                        {"id": "fbbcc5e7", "title": "I-000 — Pre-Iteration Foundation",
                         "startDate": "2026-08-24", "duration": 14}]}}
            }, "repository": {"id": "R_1"}}}
        if "issue(number:" in query:
            return {"repository": {"issue": {
                "id": "I_11", "number": 11, "state": "CLOSED",
                "labels": {"nodes": [{"name": l} for l in self.labels]},
                "projectItems": {"nodes": []},
            }}}
        if "items(first: 100" in query:
            nodes = []
            if self.item_added:
                nodes.append({
                    "id": "ITEM_NEW",
                    "content": {"__typename": "Issue", "number": 11, "state": "CLOSED"},
                    "iteration": ({"iterationId": "fbbcc5e7",
                                   "title": "I-000 — Pre-Iteration Foundation"}
                                  if self.item["iteration"] == "i-000" else None),
                    "priority": ({"name": "P2"} if self.item["priority"] else None),
                    "status": ({"name": "Done"} if self.item["status"] else None),
                })
            return {"user": {"projectV2": {"items": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": nodes,
            }}}}
        if "updateProjectV2ItemFieldValue" in query:
            if "iterationId" in query:
                self.item["iteration"] = "i-000"
            elif "singleSelectOptionId" in query:
                if '"s3"' in query:
                    self.item["status"] = "s3"  # Done option id
                elif '"p3"' in query:
                    self.item["priority"] = "p3"  # P2 option id
            return {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "ITEM_NEW"}}}
        raise AssertionError(f"unexpected query: {query[:80]}")


class TestSyncNonMemberConvergence:
    def test_first_sync_of_non_member_converges_instead_of_crashing(self):
        # live defect: run 34599644360 crashed here with
        # "unknown mutation kind 'add_membership'" after ADD_ITEM succeeded
        s = Settings(owner="harryhua-ai", repo="ask-ai", project_number=2, token="x")
        ft = _NonMemberFakeTransport(labels=["iteration:i-000"])
        report = sync_issue(ft, s, 11, dry_run=False)
        assert report["result"] == "APPLIED"
        assert ft.item_added is True
        assert report["after"]["iteration"] == "i-000"

    def test_first_sync_applies_exactly_the_requested_fields(self):
        s = Settings(owner="harryhua-ai", repo="ask-ai", project_number=2, token="x")
        ft = _NonMemberFakeTransport(labels=["iteration:i-000"])
        report = sync_issue(ft, s, 11, dry_run=False)
        kinds = report["applied"]
        assert "add_membership" not in kinds  # handled before apply_plan, not via it
        assert "set_iteration" in kinds
        assert all(k in ("set_iteration", "set_status", "set_priority", "clear_priority")
                   for k in kinds)

    def test_dry_run_of_non_member_plans_membership_and_fields(self):
        s = Settings(owner="harryhua-ai", repo="ask-ai", project_number=2, token="x")
        ft = _NonMemberFakeTransport(labels=["iteration:i-000"])
        report = sync_issue(ft, s, 11, dry_run=True)
        kinds = [m["kind"] for m in report["mutations"]]
        assert "add_membership" in kinds and "set_iteration" in kinds


class TestClosedIssueSemanticsUnchanged:
    def test_closed_issue_resolves_completed_iteration(self):
        from project_automation.mapping import resolve_desired
        from project_automation.model import FieldConfig, IssueAuthority, IterationDef
        cfg = FieldConfig(iterations=[IterationDef("fbbcc5e7", "I-000 — Pre-Iteration Foundation",
                                                   "2026-08-24", 14)])
        d = resolve_desired(IssueAuthority(20, "CLOSED", ["priority:p2", "iteration:i-000"]))
        assert d.status_option == "Done"  # closure owns Done
        assert d.iteration_key == "i-000"
        from project_automation.mapping import resolve_iteration
        it = resolve_iteration(cfg.iterations, d.iteration_key)
        assert it is not None and it.id == "fbbcc5e7"
