"""DraftIssue restoration regression (PROJECT-ITERATION-DRAFT-RESTORE-FIX).

updateProjectV2Field(iterationConfiguration) full-replaces the set and regenerates
every iteration id, orphaning item values — INCLUDING DraftIssue items. The
transaction snapshot/restore/verify must therefore cover Issue AND DraftIssue
items; content type must never exclude an assigned item.
"""
import json
import re

from project_automation.iteration_txn import create_iteration_transaction
from project_automation.model import FieldConfig, IterationDef, OptionDef
from project_automation.service import Context, LiveIterationOps, Settings

EXISTING = [
    ("it-old-1", "I-001 — Answer Intelligence Foundation", "2026-09-07", 14),
    ("it-old-2", "I-UX-001 — Widget Experience Corrective", "2026-09-21", 14),
    ("it-old-3", "v1.6.0 — Knowledge Integrity & Source Truth", "2026-10-05", 14),
]
NEW = ("it-new-x", "v1.7.0 — Next Development Timebox", "2026-10-19", 14)


def _settings():
    return Settings(owner="harryhua-ai", repo="ask-ai", project_number=2, token="test-token")


def _context():
    return Context(
        project_id="PROJ",
        config=FieldConfig(
            status_options=[OptionDef("s1", "Backlog"), OptionDef("s2", "Done")],
            priority_options=[OptionDef("p1", "P0"), OptionDef("p2", "P1"), OptionDef("p3", "P2")],
            iterations=[IterationDef(id=i, title=t, start_date=s, duration=d) for i, t, s, d in EXISTING],
        ),
        field_ids={"status": "fS", "priority": "fP", "iteration": "fI"},
        config_anchor="2026-09-07",
        config_duration=14,
    )


def _draft_items(count=14):
    """14 DraftIssue items assigned to I-001 — mirrors the live Project."""
    return [
        {"id": f"PVTI_draft_{n}", "content": {"__typename": "DraftIssue", "title": f"I-001 work item {n}"},
         "iteration": {"iterationId": "it-old-1", "title": EXISTING[0][1]}}
        for n in range(count)
    ]


def _issue_items():
    return [
        {"id": "PVTI_32", "content": {"__typename": "Issue", "number": 32, "state": "CLOSED"},
         "iteration": {"iterationId": "it-old-1", "title": EXISTING[0][1]}},
        {"id": "PVTI_6", "content": {"__typename": "Issue", "number": 6, "state": "CLOSED"},
         "iteration": {"iterationId": "it-old-2", "title": EXISTING[1][1]}},
        {"id": "PVTI_25", "content": {"__typename": "Issue", "number": 25, "state": "OPEN"},
         "iteration": {"iterationId": "it-old-3", "title": EXISTING[2][1]}},
    ]


class FakeProjectTransport:
    """Models GitHub truth independently of the adapter under test.

    - updateProjectV2Field(iterationConfiguration) mutates exactly once, regenerates
      every iteration id, and ORPHANS item values whose iteration id vanished.
    - updateProjectV2ItemFieldValue re-attaches an item to an iteration id.
    - items/context reads always reflect current internal state.
    """

    def __init__(self, fail_item_ids=()):
        self.iterations = [list(i) for i in EXISTING]  # [id, title, start, duration]
        self.items = _issue_items() + _draft_items(14)
        self.update_calls = 0
        self.fail_item_ids = set(fail_item_ids)

    # -- transport surface -------------------------------------------------
    def graphql(self, query: str) -> dict:
        if "iterationConfiguration" in query and "updateProjectV2Field" in query:
            return self._update_config(query)
        if "updateProjectV2ItemFieldValue" in query:
            return self._set_item(query)
        if "fieldValueByName" in query:
            return self._items_page()
        if 'field(name: "Iteration")' in query:
            return self._context_response()
        raise AssertionError(f"unexpected query in fake: {query[:80]}")

    # -- internals ----------------------------------------------------------
    def _slug_map(self):
        from project_automation.model import iteration_slug
        return {iteration_slug(i[1]): i[0] for i in self.iterations}

    def _update_config(self, query: str):
        self.update_calls += 1
        assert self.update_calls == 1, "configuration must be mutated exactly once"
        payload = self._extract_iterations_array(query)
        self.iterations = [[f"regen-{n}", p["title"], p["startDate"], p["duration"]]
                           for n, p in enumerate(payload)]
        live = {i[0] for i in self.iterations}
        for item in self.items:  # orphan values whose iteration id vanished
            if item["iteration"] and item["iteration"]["iterationId"] not in live:
                item["iteration"] = None
        return {"updateProjectV2Field": {"projectV2Field": {"configuration": {
            "duration": 14, "startDay": 1,
            "iterations": [{"id": i[0], "title": i[1], "startDate": i[2], "duration": i[3]} for i in self.iterations],
        }}}}

    @staticmethod
    def _extract_iterations_array(query: str):
        # build_query inlines GraphQL object literals (bare keys); convert to JSON
        key = "iterations: "
        start = query.index(key) + len(key)
        assert query[start] == "["
        depth = 0
        for j, ch in enumerate(query[start:], start=start):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    raw = query[start:j + 1]
                    return json.loads(re.sub(r"([,{]\s*)([A-Za-z_][A-Za-z0-9_]*):", r'\1"\2":', raw))
        raise AssertionError("unterminated iterations array in fake query")

    def _set_item(self, query: str):
        item_id = re.search(r'itemId: "([^"]+)"', query).group(1)
        iteration_id = re.search(r'iterationId: "([^"]+)"', query).group(1)
        if item_id in self.fail_item_ids:
            raise RuntimeError("simulated restore write failure")
        item = next(i for i in self.items if i["id"] == item_id)
        title = next(i[1] for i in self.iterations if i[0] == iteration_id)
        item["iteration"] = {"iterationId": iteration_id, "title": title}
        return {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": item_id}}}

    def _items_page(self):
        nodes = []
        for item in self.items:
            node = {"id": item["id"], "content": dict(item["content"])}
            node["iteration"] = (
                {"iterationId": item["iteration"]["iterationId"], "title": item["iteration"]["title"]}
                if item["iteration"] else None)
            node["priority"] = None
            node["status"] = None
            nodes.append(node)
        return {"user": {"projectV2": {"items": {
            "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}}}}

    def _context_response(self):
        return {"user": {"projectV2": {"id": "PROJ", "status": {"id": "fS", "options": []},
                "priority": {"id": "fP", "options": []}, "iteration": {"id": "fI", "configuration": {
                    "duration": 14, "startDay": 1,
                    "iterations": [{"id": i[0], "title": i[1], "startDate": i[2], "duration": i[3]}
                                   for i in self.iterations]}}},
                "repository": {"id": "REPO"}}}

    # -- truth inspection (independent of the adapter under test) ------------
    def truth_dangling(self):
        """Items whose stored iteration value does not resolve in the live set."""
        live = {i[0]: i for i in self.iterations}
        return [i["id"] for i in self.items if i["iteration"] and i["iteration"]["iterationId"] not in live]


class TestAdapterCoversDrafts:
    def test_get_item_assignments_includes_draft_items(self):
        t = FakeProjectTransport()
        ops = LiveIterationOps(t, _context(), _settings())
        assignments = ops.get_item_assignments()
        draft_ids = [i["id"] for i in _draft_items(14)]
        for did in draft_ids:
            assert assignments.get(did) == "i-001", f"draft {did} missing from snapshot"


class TestEndToEndDraftRestoration:
    def _run(self, fail_item_ids=()):
        t = FakeProjectTransport(fail_item_ids=fail_item_ids)
        pre_slugs = {i["id"]: "i-001" for i in _draft_items(14)}
        pre_slugs.update({"PVTI_32": "i-001", "PVTI_6": "i-ux-001", "PVTI_25": "v1.6.0"})
        ops = LiveIterationOps(t, _context(), _settings())
        all_ids = [i["id"] for i in t.items]
        result = create_iteration_transaction(ops, existing=EXISTING, new=NEW, item_ids=all_ids)
        return t, result, pre_slugs

    def test_all_14_drafts_and_issues_survive_regeneration(self):
        t, result, pre_slugs = self._run()
        assert t.update_calls == 1
        # no orphaned assignments anywhere — issue or draft
        assert t.truth_dangling() == [], f"orphaned items: {t.truth_dangling()}"
        # every previous assignment resolves to its same semantic iteration
        slug_by_id = {i[0]: (i[1].split(" — ")[0].strip().lower().replace(" ", "-")) for i in t.iterations}
        for item in t.items:
            if item["id"] not in pre_slugs:
                continue
            assert item["iteration"] is not None, f"{item['id']} lost its iteration"
            got = slug_by_id[item["iteration"]["iterationId"]]
            assert got == pre_slugs[item["id"]], f"{item['id']}: {got} != {pre_slugs[item['id']]}"
        # new iteration exists
        assert any("v1.7.0" in i[1] for i in t.iterations)
        assert result.restored == len(pre_slugs)  # 17 = 3 issues + 14 drafts

    def test_draft_restore_failure_fails_closed(self):
        from project_automation.errors import RestorationFailure
        import pytest
        draft_id = _draft_items(1)[0]["id"]
        t = FakeProjectTransport(fail_item_ids=[draft_id])
        ops = LiveIterationOps(t, _context(), _settings())
        with pytest.raises(RestorationFailure) as exc:
            create_iteration_transaction(ops, existing=EXISTING, new=NEW,
                                         item_ids=[i["id"] for i in t.items])
        assert draft_id in str(exc.value)

    def test_verify_catches_dangling_draft_when_reads_are_truthful(self):
        t, result, pre_slugs = self._run()
        # after a green run, a truthful re-read must agree with the transaction result
        post = ops_assignments = LiveIterationOps(t, _context(), _settings()).get_item_assignments()
        for item_id, slug in pre_slugs.items():
            assert post.get(item_id) == slug, f"post-verify mismatch for {item_id}"
