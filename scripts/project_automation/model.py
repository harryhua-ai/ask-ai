"""Data model for Project state. IDs are per-run observations, never durable identity."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


def iteration_slug(title: str) -> str:
    """Semantic iteration identity: the code token before the em-dash theme separator.

    "I-UX-001 — Widget Experience Corrective" -> "i-ux-001"
    "v1.6.0 — Knowledge Integrity & Source Truth" -> "v1.6.0"

    Tolerant of ID regeneration and theme renames; the code prefix is the stable key.
    """
    head = title.split("—")[0]
    slug = head.strip().lower().replace(" ", "-")
    return re.sub(r"[^a-z0-9._-]", "", slug)


def sprint_title_slug(title: str) -> str:
    """Semantic Sprint identity: the full title normalized, with the redundant word
    "sprint" dropped ("Bug Fix Sprint — 2026-09" -> "bug-fix-2026-09") — the label
    prefix already names the dimension. Unlike iterations, Sprint's distinguishing
    date sits AFTER the em-dash, so the code-prefix token is not unique enough."""
    s = title.strip().lower().replace(" — ", "-").replace("—", "-").replace(" ", "-")
    s = re.sub(r"[^a-z0-9._-]", "", s)
    tokens = [tk for tk in s.split("-") if tk and tk != "sprint"]
    return "-".join(tokens)


@dataclass
class OptionDef:
    id: str
    name: str


@dataclass
class IterationDef:
    id: str
    title: str
    start_date: str
    duration: int

    @property
    def slug(self) -> str:
        return iteration_slug(self.title)


@dataclass
class FieldConfig:
    status_options: list[OptionDef] = field(default_factory=list)
    priority_options: list[OptionDef] = field(default_factory=list)
    iterations: list[IterationDef] = field(default_factory=list)
    sprints: list[IterationDef] = field(default_factory=list)

    def sprint_by_slug(self, slug: str) -> IterationDef | None:
        for sp in self.sprints:
            if sprint_title_slug(sp.title) == slug:
                return sp
        return None

    def status_option(self, name: str) -> OptionDef | None:
        return self._opt(self.status_options, name)

    def priority_option(self, name: str) -> OptionDef | None:
        return self._opt(self.priority_options, name)

    def iteration_by_slug(self, slug: str) -> IterationDef | None:
        for it in self.iterations:
            if it.slug == slug:
                return it
        return None

    @staticmethod
    def _opt(options: list[OptionDef], name: str) -> OptionDef | None:
        for o in options:
            if o.name == name:
                return o
        return None


@dataclass
class IssueAuthority:
    number: int
    state: str  # "OPEN" | "CLOSED"
    labels: list[str]


@dataclass
class ItemState:
    item_id: str
    issue_number: int | None
    is_draft: bool
    iteration_slug: str | None
    priority: str | None
    status: str | None
    sprint_slug: str | None = None
