"""Authority → projection mapping (contract §5/§6).

Deterministic, closed-vocabulary translation from Issue state + control labels
to desired Project field values. Closure always wins over status labels;
reopening recomputes from labels and can never silently stay Done.
"""
from __future__ import annotations

from dataclasses import dataclass

from .labels import ControlLabels, parse_control_labels
from .model import IssueAuthority, iteration_slug

PRIORITY_MAP = {"p0": "P0", "p1": "P1", "p2": "P2"}
STATUS_MAP = {
    "backlog": "Backlog",
    "in-progress": "In progress",
    "in-review": "In review",
}
DONE = "Done"
DEFAULT_OPEN_STATUS = "Backlog"
RESERVED_STATUS_NOTE = ("status:ready is RESERVED/UNSUPPORTED: the Project has no 'Ready' Status option; "
                        "no Status mutation until the option is authorized")


def resolve_iteration(config_iterations, key: str | None):
    """Resolve a label iteration key against the LIVE iteration list by semantic slug."""
    if key is None:
        return None
    slug = iteration_slug(key)
    for it in config_iterations:
        if it.slug == slug:
            return it
    return None


@dataclass
class DesiredProjection:
    status_option: str | None  # None = do not touch Status
    priority_option: str | None  # None = do not set a value
    priority_clear: bool  # True = absence of authority clears the field
    iteration_key: str | None
    iteration_clear: bool
    # Sprint authority (hardened): absent sprint label = clear, mirroring Iteration.
    # Safe only because bootstrap derived the historical labels and bidirectional
    # equivalence was proven before this rule replaced the transitional additive one.
    sprint_key: str | None = None
    sprint_clear: bool = False
    control: ControlLabels = None

    def errors(self) -> list[str]:
        out: list[str] = []
        for c in self.control.conflicts:
            out.append(f"conflicting {'/'.join(c.values)} for control field '{c.field}'")
        out.extend(f"unrecognized control label '{u}'" for u in self.control.unknown)
        if self.control.status_reserved:
            out.append(RESERVED_STATUS_NOTE)
        return out


def resolve_desired(issue: IssueAuthority, control: ControlLabels | None = None) -> DesiredProjection:
    control = control or parse_control_labels(issue.labels)
    closed = issue.state == "CLOSED"

    # Status: closure overrides everything; labels next; open default Backlog.
    if closed:
        status_option: str | None = DONE
    elif control.status is not None:
        status_option = STATUS_MAP[control.status]
    elif control.has_status_label:
        status_option = None  # status labels present but unmappable/conflicting → fail safe
    else:
        status_option = DEFAULT_OPEN_STATUS

    # Priority: absent label = clear authority; unmappable/conflicting = fail safe.
    if not control.has_priority_label:
        priority_option, priority_clear = None, True
    elif control.priority is not None:
        priority_option, priority_clear = PRIORITY_MAP[control.priority], False
    else:
        priority_option, priority_clear = None, False

    # Iteration: absent label = clear authority; unmappable/conflicting = fail safe.
    if not control.has_iteration_label:
        iteration_key, iteration_clear = None, True
    elif control.iteration_key is not None:
        iteration_key, iteration_clear = control.iteration_key, False
    else:
        iteration_key, iteration_clear = None, False

    # Sprint (authoritative): absent label = clear; unmappable/conflicting = fail safe.
    if control.sprint_key is not None:
        sprint_key, sprint_clear = control.sprint_key, False
    elif control.has_sprint_label:
        sprint_key, sprint_clear = None, False  # conflicting/unknown sprint labels → fail safe
    else:
        sprint_key, sprint_clear = None, True

    return DesiredProjection(
        status_option=status_option,
        priority_option=priority_option,
        priority_clear=priority_clear,
        iteration_key=iteration_key,
        iteration_clear=iteration_clear,
        sprint_key=sprint_key,
        sprint_clear=sprint_clear,
        control=control,
    )
