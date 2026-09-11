"""Iteration creation transaction (contract §8 Critical Iteration Safety).

GitHub's updateProjectV2Field(iterationConfiguration) full-replaces the set and
regenerates EVERY iteration id. The transaction therefore runs:

    PRE-SNAPSHOT → MUTATION (exactly once) → RE-RESOLVE → RESTORE → VERIFY

with fail-closed semantics: any restoration or verification gap raises and the
caller must treat Project iteration state as unproven.
"""
from __future__ import annotations

from dataclasses import dataclass

from .errors import ConfigError, RestorationFailure, VerificationFailure
from .model import IterationDef, iteration_slug  # noqa: F401  (iteration_slug re-exported)

IterationLike = tuple  # (id, title, start_date, duration)


@dataclass
class IterationTuple:
    id: str
    title: str
    start_date: str
    duration: int

    @property
    def slug(self) -> str:
        return iteration_slug(self.title)

    def as_def(self) -> IterationDef:
        return IterationDef(id=self.id, title=self.title, start_date=self.start_date, duration=self.duration)

    def as_raw(self) -> tuple:
        return (self.id, self.title, self.start_date, self.duration)


def _coerce(it) -> IterationTuple:
    return it if isinstance(it, IterationTuple) else IterationTuple(*it)


@dataclass
class TxResult:
    created: IterationDef
    pre_assignments: dict[str, str]  # item_id → iteration slug (semantic)
    post_assignments: dict[str, str]
    restored: int


def create_iteration_transaction(gh, *, existing: list, new, item_ids: list[str]) -> TxResult:
    """`gh` implements the transport operations:

        get_iterations() -> list[IterationTuple | tuple]
        get_item_assignments() -> dict[item_id, iteration_slug]   (semantic snapshot)
        set_item_iteration(item_id, iteration_id)
        update_iterations(list[tuple])                            (must mutate exactly once)
    """
    existing = [_coerce(t) for t in existing]
    new = _coerce(new)

    existing_slugs = [t.slug for t in existing]
    new_slug = new.slug
    if new_slug in existing_slugs:
        raise ConfigError(f"iteration '{new_slug}' already exists; refusing duplicate creation")
    if len(set(existing_slugs)) != len(existing_slugs):
        raise ConfigError("existing iteration set contains duplicate semantic keys; refusing to mutate")

    # PRE-SNAPSHOT: semantic assignment of every item
    assignments = gh.get_item_assignments()
    pre = {i: assignments[i] for i in item_ids if i in assignments}

    # MUTATION: exactly one configuration update, every existing iteration verbatim
    gh.update_iterations([t.as_raw() for t in [*existing, new]])

    # RE-RESOLVE: semantic identity against regenerated ids
    post_iterations = [_coerce(t) for t in gh.get_iterations()]
    slug_to_id: dict[str, str] = {}
    for t in post_iterations:
        if t.slug in slug_to_id:
            raise VerificationFailure(f"semantic duplicate iteration '{t.slug}' after update")
        slug_to_id[t.slug] = t.id

    expected = {t.slug: (t.start_date, t.duration) for t in [*existing, new]}
    for slug, (start, duration) in expected.items():
        t = next((t for t in post_iterations if t.slug == slug), None)
        if t is None:
            raise VerificationFailure(f"iteration '{slug}' missing after update (full-replace dropped it)")
        if (t.start_date, t.duration) != (start, duration):
            raise VerificationFailure(
                f"iteration '{slug}' drifted: expected {start}+{duration}d, got {t.start_date}+{t.duration}d")
    if new_slug not in slug_to_id:
        raise VerificationFailure(f"new iteration '{new_slug}' was not created")

    # RESTORE: remap every previously-assigned item to the regenerated id
    post_assignments = gh.get_item_assignments()
    restored = 0
    for item_id, slug in pre.items():
        if post_assignments.get(item_id) == slug:
            continue  # already semantically correct
        target_id = slug_to_id.get(slug)
        if target_id is None:
            raise RestorationFailure(f"item {item_id}: iteration '{slug}' vanished; refusing partial restore")
        try:
            gh.set_item_iteration(item_id, target_id)
            restored += 1
        except Exception as exc:  # noqa: BLE001 - fail closed on any write error
            raise RestorationFailure(f"item {item_id}: restore to '{slug}' failed: {exc}") from exc

    # VERIFY: 100% semantic equivalence + new iteration exists
    final = gh.get_item_assignments()
    for item_id, slug in pre.items():
        if final.get(item_id) != slug:
            raise VerificationFailure(
                f"item {item_id}: expected iteration '{slug}', observed '{final.get(item_id)}'")

    created = next(t.as_def() for t in post_iterations if t.slug == new_slug)
    return TxResult(created=created, pre_assignments=pre, post_assignments=final, restored=restored)
