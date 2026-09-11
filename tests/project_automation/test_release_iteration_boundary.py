"""Release ≠ Iteration governance regression boundary (Role A review fix).

Frozen governance: Iteration = development timebox; Release = shipped version.
Routine sync must never infer a GitHub Release/tag as a Project Iteration, and
no release-shaped data path may enter the automation.
"""
from pathlib import Path

from project_automation.labels import parse_control_labels
from project_automation.mapping import resolve_desired, resolve_iteration
from project_automation.model import IssueAuthority, IterationDef

LIVE_CORRECTED_SET = [
    IterationDef(id="659fde78", title="I-001 — Answer Intelligence Foundation", start_date="2026-09-07", duration=14),
    IterationDef(id="ccecdb22", title="I-UX-001 — Widget Experience Corrective", start_date="2026-09-21", duration=14),
    IterationDef(id="89b82cdb", title="v1.6.0 — Knowledge Integrity & Source Truth", start_date="2026-10-05", duration=14),
]


class TestReleaseIsNeverAnIteration:
    def test_release_version_does_not_resolve_as_iteration(self):
        # v1.5.0 exists as a GitHub Release/tag in this repository; the corrected
        # iteration set does not contain it — resolution must yield None.
        assert resolve_iteration(LIVE_CORRECTED_SET, "v1.5.0") is None

    def test_release_shaped_label_maps_to_unknown_iteration_finding(self):
        d = resolve_desired(IssueAuthority(number=1, state="OPEN", labels=["iteration:v1.5.0", "status:backlog"]))
        assert d.iteration_key == "v1.5.0"
        assert resolve_iteration(LIVE_CORRECTED_SET, d.iteration_key) is None  # planner will report UNKNOWN_ITERATION

    def test_release_prefix_is_not_a_control_label(self):
        cl = parse_control_labels(["release:v1.5.0", "tag:v1.5.0"])
        assert cl.has_any is False
        assert cl.iteration_key is None

    def test_release_value_in_body_is_irrelevant(self):
        # only labels are authority; release mentions in titles/bodies are never parsed
        d = resolve_desired(IssueAuthority(number=1, state="OPEN",
                                           labels=["status:backlog"],
                                           ))
        assert d.iteration_key is None and d.iteration_clear is True

    def test_dev_timebox_keys_still_resolve(self):
        assert resolve_iteration(LIVE_CORRECTED_SET, "i-001") is not None
        assert resolve_iteration(LIVE_CORRECTED_SET, "v1.6.0") is not None


class TestNoReleaseDataPathInAutomation:
    def test_automation_source_never_touches_release_or_tag_apis(self):
        # boundary scan: no automation module may consult GitHub Release/tag data,
        # preventing any release→iteration inference from being reintroduced
        banned = ("releases", "refs/tags", "git/tags", "list_releases", "release:")
        root = Path(__file__).resolve().parents[2] / "scripts" / "project_automation"
        offenders = []
        for py in root.glob("*.py"):
            text = py.read_text(encoding="utf-8").lower()
            for token in banned:
                if token in text:
                    offenders.append(f"{py.name}:{token}")
        assert offenders == [], f"release/tag data path reintroduced: {offenders}"

    def test_status_ready_is_reserved_vocabulary(self):
        from project_automation.labels import STATUS_RESERVED, STATUS_VALUES
        assert "ready" not in STATUS_VALUES
        assert STATUS_RESERVED == ("ready",)
