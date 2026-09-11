"""Iteration semantic resolution: label key → live iteration, tolerant of ID regeneration."""
import pytest

from project_automation.mapping import resolve_iteration
from project_automation.model import IterationDef


def iteration(id_, title, start="2026-01-05", duration=14):
    return IterationDef(id=id_, title=title, start_date=start, duration=duration)


CONFIG = [
    iteration("id-a", "I-001 — Answer Intelligence Foundation"),
    iteration("id-b", "v1.5.0 — Answer Intelligence Release 1"),
    iteration("id-c", "I-UX-001 — Widget Experience Corrective"),
    iteration("id-d", "v1.6.0 — Knowledge Integrity & Source Truth"),
]


class TestSemanticResolution:
    def test_release_key_resolves(self):
        assert resolve_iteration(CONFIG, "v1.6.0").id == "id-d"

    def test_initiative_keys_resolve(self):
        assert resolve_iteration(CONFIG, "i-001").id == "id-a"
        assert resolve_iteration(CONFIG, "i-ux-001").id == "id-c"

    def test_resolution_ignores_regenerated_ids(self):
        # GitHub regenerated every id; semantic identity (title prefix) must still resolve
        regenerated = [
            iteration("brand-new-1", "I-001 — Answer Intelligence Foundation"),
            iteration("brand-new-2", "v1.6.0 — Knowledge Integrity & Source Truth"),
        ]
        assert resolve_iteration(regenerated, "v1.6.0").id == "brand-new-2"
        assert resolve_iteration(regenerated, "i-001").id == "brand-new-1"

    def test_unknown_iteration_returns_none(self):
        assert resolve_iteration(CONFIG, "v1.7.0") is None

    def test_title_theme_edits_do_not_break_resolution(self):
        renamed = [iteration("id-x", "v1.6.0 — Renamed Theme Not Part Of Key")]
        assert resolve_iteration(renamed, "v1.6.0").id == "id-x"

    def test_key_is_slug_normalized_both_sides(self):
        weird = [iteration("id-y", "  v1.6.0  — spaces")]
        assert resolve_iteration(weird, "V1.6.0").id == "id-y"

    def test_ambiguous_prefix_does_not_match(self):
        # "v1.6" must not match "v1.6.0" — slug equality, not prefix
        assert resolve_iteration(CONFIG, "v1.6") is None
