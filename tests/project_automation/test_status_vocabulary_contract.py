"""#85 / Actions run #321: Issue control-label → Project Status vocabulary contract.

Root cause (PROVEN): ``project_automation.mapping`` mapped ``status:backlog`` to
the Status option ``Backlog`` (and kept ``in-review`` → ``In review``) while the
live Project had renamed/removed those options, so every issue labeled
``status:backlog`` (#81-#85) died in ``FAILED_VALIDATION`` / ``UNKNOWN_OPTION
Project has no Status option 'Backlog'`` before any mutation (run 321 log
2026-09-15T10:08:24Z; issue #83 had no Project item — zero partial mutation).

Canonical vocabulary frozen from a read-only probe (2026-09-15,
``gh api graphql`` → ``user(harryhua-ai).projectV2(number: 2)`` field ``Status``,
"@harryhua-ai's ask-ai project"):

    open (f75ad846) / In progress (47fc9ee4) / Done (98236657)

Contract: the mapping may only name options that exist in this live set. A
recognized control value without a live option (``status:in-review``,
``status:ready``) is RESERVED — visible finding, NO Status mutation, never a
guessed "closest" option. Unknown options keep failing closed in the planner.
"""
from project_automation.labels import parse_control_labels
from project_automation.mapping import (
    DEFAULT_OPEN_STATUS,
    DONE,
    STATUS_MAP,
    resolve_desired,
)
from project_automation.model import FieldConfig, IssueAuthority, ItemState, IterationDef, OptionDef
from project_automation.planner import plan_sync

LIVE_STATUS_OPTIONS = ("open", "In progress", "Done")

# Live-shaped Project 2 schema (option/iteration ids probed 2026-09-15).
LIVE_CONFIG = FieldConfig(
    status_options=[OptionDef("f75ad846", "open"), OptionDef("47fc9ee4", "In progress"),
                    OptionDef("98236657", "Done")],
    priority_options=[OptionDef("p0", "P0"), OptionDef("p1", "P1"), OptionDef("p2", "P2")],
    iterations=[IterationDef("4ce642b8", "v1.6.3", "2026-09-15", 7),
                IterationDef("935f5c79", "v1.6.4", "2026-09-21", 7)],
)

ISSUE83_LABELS = ["bug", "priority:p0", "status:backlog", "iteration:v1.6.3", "schedule:current"]


def issue83_desired():
    control = parse_control_labels(ISSUE83_LABELS)
    return resolve_desired(IssueAuthority(83, "OPEN", ISSUE83_LABELS), control)


class TestVocabularyFreeze:
    def test_every_mapped_option_exists_in_live_status_field(self):
        # acceptance: read-only probe confirms mapped options exist in the live field
        mapped = set(STATUS_MAP.values()) | {DEFAULT_OPEN_STATUS, DONE}
        assert mapped <= set(LIVE_STATUS_OPTIONS)

    def test_status_backlog_maps_to_live_open_option(self):
        assert STATUS_MAP["backlog"] == "open"

    def test_open_default_is_live_open_option(self):
        assert DEFAULT_OPEN_STATUS == "open"

    def test_in_review_has_no_live_option_and_is_not_mapped(self):
        # no live "In review" option exists: the value must not stay in the mapped
        # vocabulary (that stale mapping is exactly the #321 drift class)
        assert "in-review" not in STATUS_MAP
        assert "In review" not in set(STATUS_MAP.values())


class TestIssue83Reproduction:
    def test_status_backlog_desires_live_open_option(self):
        d = issue83_desired()
        assert d.status_option == "open"

    def test_full_projection_plans_converging_mutations_zero_findings(self):
        d = issue83_desired()
        assert d.priority_option == "P0"
        assert d.iteration_key == "v1.6.3"
        plan = plan_sync(item=None, desired_status=d.status_option,
                         desired_priority=d.priority_option, desired_priority_clear=d.priority_clear,
                         desired_iteration_key=d.iteration_key, desired_iteration_clear=d.iteration_clear,
                         config=LIVE_CONFIG)
        assert plan.findings == []
        kinds = {m.kind: m for m in plan.mutations}
        assert kinds["add_membership"]
        assert kinds["set_status"].payload["option_name"] == "open"
        assert kinds["set_priority"].payload["option_name"] == "P0"
        assert kinds["set_iteration"].payload["iteration_title"] == "v1.6.3"

    def test_converged_issue83_is_idempotent_zero_mutations(self):
        # acceptance: repeated execution yields ALREADY_CONVERGED / zero mutation
        item = ItemState(item_id="ITEM_83", issue_number=83, is_draft=False,
                         iteration_slug="v1.6.3", priority="P0", status="open")
        d = issue83_desired()
        plan = plan_sync(item=item, desired_status=d.status_option,
                         desired_priority=d.priority_option, desired_priority_clear=d.priority_clear,
                         desired_iteration_key=d.iteration_key, desired_iteration_clear=d.iteration_clear,
                         config=LIVE_CONFIG)
        assert plan.mutations == [] and plan.findings == []


class TestFailClosedPreserved:
    def test_status_label_without_live_option_is_reserved_never_guessed(self):
        # 'In review' has no live option: recognized intent → visible RESERVED
        # finding + NO Status mutation; never mapped to a "closest" live option
        d = resolve_desired(IssueAuthority(84, "OPEN", ["status:in-review"]))
        assert d.status_option is None
        assert any("RESERVED" in e for e in d.errors())

    def test_unknown_status_option_still_rejected_by_planner(self):
        # fail-closed non-goal guard: a desired status absent from the live field
        # must still surface UNKNOWN_OPTION with zero status mutations
        plan = plan_sync(item=None, desired_status="In Review",
                         desired_priority=None, desired_priority_clear=True,
                         desired_iteration_key=None, desired_iteration_clear=False,
                         config=LIVE_CONFIG)
        assert any(f.code == "UNKNOWN_OPTION" and f.field == "status" for f in plan.findings)
        assert not any(m.kind == "set_status" for m in plan.mutations)
