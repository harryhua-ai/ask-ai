"""Canonical Issue control-label vocabulary (contract §4/§11).

One canonical mapping, explicit and machine-readable. Issue prose is never parsed.
Values are validated against closed sets; anything else surfaces as visible metadata.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

PRIORITY_PREFIX = "priority:"
STATUS_PREFIX = "status:"
ITERATION_PREFIX = "iteration:"
SPRINT_PREFIX = "sprint:"

PRIORITY_VALUES = ("p0", "p1", "p2")
STATUS_VALUES = ("backlog", "in-progress", "in-review")
# RESERVED/UNSUPPORTED: recognized as explicit control intent, but the Project has no
# 'Ready' Status option. Using it yields a visible finding and NO Status mutation
# until the option is authorized (never add it via singleSelectOptions full-replace).
STATUS_RESERVED = ("ready",)

# iteration keys are slugs: short, lowercase, no shell metacharacters, no whitespace
ITERATION_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


@dataclass
class MetadataConflict:
    field: str
    values: list[str]


@dataclass
class ControlLabels:
    iteration_key: str | None = None
    priority: str | None = None
    status: str | None = None
    sprint_key: str | None = None
    has_iteration_label: bool = False
    has_priority_label: bool = False
    has_status_label: bool = False
    has_sprint_label: bool = False
    status_reserved: bool = False
    conflicts: list[MetadataConflict] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)

    @property
    def has_any(self) -> bool:
        return self.has_iteration_label or self.has_priority_label or self.has_status_label \
            or self.has_sprint_label


def normalize_control_value(raw: str) -> str:
    return raw.strip().lower().replace(" ", "-")


def parse_control_labels(labels: list[str]) -> ControlLabels:
    cl = ControlLabels()
    found: dict[str, set[str]] = {"iteration": set(), "priority": set(), "status": set(), "sprint": set()}
    for label in labels:
        for prefix, key in ((ITERATION_PREFIX, "iteration"), (PRIORITY_PREFIX, "priority"),
                            (STATUS_PREFIX, "status"), (SPRINT_PREFIX, "sprint")):
            if label.lower().startswith(prefix):
                cl.has_iteration_label |= key == "iteration"
                cl.has_priority_label |= key == "priority"
                cl.has_status_label |= key == "status"
                cl.has_sprint_label |= key == "sprint"
                value = normalize_control_value(label[len(prefix):])
                found[key].add(value)
                if key == "iteration" and not ITERATION_KEY_RE.match(value):
                    cl.unknown.append(label)
                elif key == "priority" and value not in PRIORITY_VALUES:
                    cl.unknown.append(label)
                elif key == "status" and value not in STATUS_VALUES:
                    if value in STATUS_RESERVED:
                        cl.status_reserved = True
                    else:
                        cl.unknown.append(label)
                elif key == "sprint" and not ITERATION_KEY_RE.match(value):
                    cl.unknown.append(label)

    single = {k: next(iter(v)) if len(v) == 1 else None for k, v in found.items()}
    if len(found["iteration"]) == 1 and ITERATION_KEY_RE.match(single["iteration"]):
        cl.iteration_key = single["iteration"]
    if len(found["priority"]) == 1 and single["priority"] in PRIORITY_VALUES:
        cl.priority = single["priority"]
    if len(found["status"]) == 1 and single["status"] in STATUS_VALUES:
        cl.status = single["status"]
    if len(found["sprint"]) == 1 and ITERATION_KEY_RE.match(single["sprint"]):
        cl.sprint_key = single["sprint"]

    for key, values in found.items():
        if len(values) > 1:
            cl.conflicts.append(MetadataConflict(field=key, values=sorted(values)))
    return cl


def has_any_control_label(labels: list[str]) -> bool:
    return parse_control_labels(labels).has_any
