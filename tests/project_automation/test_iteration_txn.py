"""Iteration creation transaction: full-replace hazard protocol (snapshot→mutate→restore→verify)."""
import pytest

from project_automation.errors import ConfigError, RestorationFailure, VerificationFailure
from project_automation.iteration_txn import create_iteration_transaction

EXISTING = [
    ("it-old-1", "I-001 — Answer Intelligence Foundation", "2026-09-07", 14),
    ("it-old-2", "v1.5.0 — Answer Intelligence Release 1", "2026-09-10", 14),
    ("it-old-3", "I-UX-001 — Widget Experience Corrective", "2026-09-21", 14),
    ("it-old-4", "v1.6.0 — Knowledge Integrity & Source Truth", "2026-10-05", 14),
]
NEW = ("it-new-x", "v1.7.0 — New Theme", "2026-10-19", 14)
# pre-mutation state: item_id → RAW iteration id (GitHub stores ids, not slugs)
ASSIGNMENTS = {
    "PVTI_30": "it-old-4",  # v1.6.0
    "PVTI_25": "it-old-4",  # v1.6.0
    "PVTI_4": "it-old-2",   # v1.5.0
    "PVTI_32": "it-old-1",  # i-001
}
# semantic expectation: same slugs must hold after id regeneration
EXPECTED_SLUGS = {"PVTI_30": "v1.6.0", "PVTI_25": "v1.6.0", "PVTI_4": "v1.5.0", "PVTI_32": "i-001"}


class FakeGitHub:
    """Simulates GitHub's full-replace + id-regeneration behavior."""

    def __init__(self, fail_restore_for=None, lie_about_restore=False, drop_iteration=None):
        self.existing = list(EXISTING)
        self.assignments = dict(ASSIGNMENTS)
        self.fail_restore_for = fail_restore_for or []
        self.lie_about_restore = lie_about_restore
        self.drop_iteration = drop_iteration
        self.update_calls = 0
        self.restored = {}

    def get_iterations(self):
        return list(self.existing)

    def get_item_assignments(self):
        if self.lie_about_restore and self.update_calls:
            return {}  # simulate readback/writes not landing — verification must catch it
        slugs = {}
        by_id = {i[0]: i for i in self.existing}
        for item_id, iter_id in self.assignments.items():
            it = by_id.get(iter_id)
            if it:
                from project_automation.iteration_txn import iteration_slug
                slugs[item_id] = iteration_slug(it[1])
        return slugs

    def update_iterations(self, all_iterations):
        self.update_calls += 1
        assert self.update_calls == 1, "config must be mutated exactly once"
        # full replace: regenerate ALL ids
        self.existing = [(f"regen-{n}", t, s, d) for n, (old, t, s, d) in enumerate(all_iterations)]
        if self.drop_iteration is not None:
            self.existing = [e for e in self.existing if iteration_slug_of(e[1]) != self.drop_iteration]

    def set_item_iteration(self, item_id, iteration_id):
        if item_id in self.fail_restore_for:
            raise RuntimeError("simulated write failure")
        self.assignments[item_id] = iteration_id


def iteration_slug_of(title):
    from project_automation.iteration_txn import iteration_slug
    return iteration_slug(title)


class TestHappyPath:
    def test_new_iteration_created_and_all_assignments_semantically_restored(self):
        gh = FakeGitHub()
        result = create_iteration_transaction(gh, existing=EXISTING, new=NEW, item_ids=list(ASSIGNMENTS))
        assert result.created.slug.startswith("v1.7.0")
        assert gh.update_calls == 1
        # every item points at the REGENERATED id for the same semantic iteration
        title_by_id = {i: t for i, t, s, d in gh.existing}
        for item_id, expected_slug in EXPECTED_SLUGS.items():
            assert iteration_slug_of(title_by_id[gh.assignments[item_id]]) == expected_slug
        assert result.restored == len(EXPECTED_SLUGS)

    def test_all_existing_iterations_preserved_verbatim(self):
        gh = FakeGitHub()
        create_iteration_transaction(gh, existing=EXISTING, new=NEW, item_ids=list(ASSIGNMENTS))
        titles_after = [t for i, t, s, d in gh.existing]
        for old in EXISTING:
            assert old[1] in titles_after
        assert len(gh.existing) == len(EXISTING) + 1


class TestFailClosed:
    def test_duplicate_iteration_key_refused_before_mutation(self):
        gh = FakeGitHub()
        dup = ("x", "v1.6.0 — Duplicate Attempt", "2026-11-02", 14)
        with pytest.raises(ConfigError):
            create_iteration_transaction(gh, existing=EXISTING, new=dup, item_ids=[])
        assert gh.update_calls == 0  # refused BEFORE any mutation

    def test_partial_restoration_failure_fails_closed(self):
        gh = FakeGitHub(fail_restore_for=["PVTI_25"])
        with pytest.raises(RestorationFailure) as exc:
            create_iteration_transaction(gh, existing=EXISTING, new=NEW, item_ids=list(ASSIGNMENTS))
        assert "PVTI_25" in str(exc.value)

    def test_verification_failure_when_restore_lies(self):
        gh = FakeGitHub(lie_about_restore=True)
        with pytest.raises(VerificationFailure):
            create_iteration_transaction(gh, existing=EXISTING, new=NEW, item_ids=list(ASSIGNMENTS))

    def test_dropped_iteration_detected_as_verification_failure(self):
        gh = FakeGitHub(drop_iteration="v1.5.0")
        with pytest.raises((RestorationFailure, VerificationFailure)):
            create_iteration_transaction(gh, existing=EXISTING, new=NEW, item_ids=list(ASSIGNMENTS))
