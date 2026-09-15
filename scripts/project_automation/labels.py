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
SCHEDULE_PREFIX = "schedule:"

PRIORITY_VALUES = ("p0", "p1", "p2")
# Mappable status values: exactly those with a live Project Status option
# (open / In progress / Done, probed 2026-09-15 — #85 vocabulary realignment).
STATUS_VALUES = ("backlog", "in-progress")
# RESERVED/UNSUPPORTED: recognized as explicit control intent, but the Project has
# no matching Status option ('Ready' never existed; 'In review' was removed when
# the live Status field became open/In progress/Done). Using one yields a visible
# finding and NO Status mutation until the option is authorized (never add it via
# singleSelectOptions full-replace), and it is never mapped to a guessed nearest
# option.
STATUS_RESERVED = ("ready", "in-review")
SCHEDULE_VALUES = ("current", "next", "backlog")

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
    priority_value: str | None = None
    status: str | None = None
    status_value: str | None = None
    schedule: str | None = None
    has_iteration_label: bool = False
    has_priority_label: bool = False
    has_status_label: bool = False
    has_schedule_label: bool = False
    # SCHEDULE ≠ PRODUCT ITERATION: a valid schedule:* label suspends Iteration
    # convergence entirely — the automation must neither write nor clear the
    # product Iteration on its behalf (2026-09-15 drift fix).
    iteration_suspended: bool = False
    status_reserved: bool = False
    conflicts: list[MetadataConflict] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)

    @property
    def has_any(self) -> bool:
        return self.has_iteration_label or self.has_priority_label or self.has_status_label \
            or self.has_schedule_label


def normalize_control_value(raw: str) -> str:
    return raw.strip().lower().replace(" ", "-")


def parse_control_labels(labels: list[str]) -> ControlLabels:
    cl = ControlLabels()
    found: dict[str, set[str]] = {
        "iteration": set(), "priority": set(), "status": set(), "schedule": set(),
    }
    for label in labels:
        for prefix, key in ((ITERATION_PREFIX, "iteration"), (PRIORITY_PREFIX, "priority"),
                            (STATUS_PREFIX, "status"),
                            (SCHEDULE_PREFIX, "schedule")):
            if label.lower().startswith(prefix):
                cl.has_iteration_label |= key == "iteration"
                cl.has_priority_label |= key == "priority"
                cl.has_status_label |= key == "status"
                cl.has_schedule_label |= key == "schedule"
                value = normalize_control_value(label[len(prefix):])
                found[key].add(value)
                if key == "iteration" and not ITERATION_KEY_RE.match(value) or key == "priority" and value not in PRIORITY_VALUES:
                    cl.unknown.append(label)
                elif key == "status" and value not in STATUS_VALUES:
                    if value in STATUS_RESERVED:
                        cl.status_reserved = True
                    else:
                        cl.unknown.append(label)
                elif key == "schedule" and value not in SCHEDULE_VALUES:
                    cl.unknown.append(label)

    single = {k: next(iter(v)) if len(v) == 1 else None for k, v in found.items()}
    if len(found["iteration"]) == 1 and ITERATION_KEY_RE.match(single["iteration"]):
        cl.iteration_key = single["iteration"]
    if len(found["priority"]) == 1 and single["priority"] in PRIORITY_VALUES:
        cl.priority = single["priority"]
    if len(found["priority"]) == 1:
        cl.priority_value = single["priority"]
    if len(found["status"]) == 1 and single["status"] in STATUS_VALUES:
        cl.status = single["status"]
    if len(found["status"]) == 1:
        cl.status_value = single["status"]
    if len(found["schedule"]) == 1 and single["schedule"] in SCHEDULE_VALUES:
        cl.schedule = single["schedule"]
        # Scheduling intent never claims Iteration authority; suspension applies
        # unless an explicit iteration:* label is also present.
        cl.iteration_suspended = not cl.has_iteration_label

    for key, values in found.items():
        if len(values) > 1:
            cl.conflicts.append(MetadataConflict(field=key, values=sorted(values)))
    return cl


def has_any_control_label(labels: list[str]) -> bool:
    return parse_control_labels(labels).has_any
