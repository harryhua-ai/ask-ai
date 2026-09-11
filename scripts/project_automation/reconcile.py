"""Drift detection between Issue authority and Project projection (contract §9).

Deterministic drift is repaired; ambiguous/conflicting authority is reported
and left untouched — never guessed.
"""
from __future__ import annotations

from dataclasses import dataclass

from .labels import ControlLabels
from .mapping import DONE, resolve_desired
from .model import FieldConfig, IssueAuthority, ItemState
from .planner import Finding, SyncPlan, plan_sync


@dataclass
class Drift:
    issue_number: int | None
    code: str
    message: str
    fixable: bool
    fix: SyncPlan | None = None


@dataclass
class Skipped:
    issue_number: int | None
    code: str
    message: str


_FINDING_TO_DRIFT = {
    "UNKNOWN_ITERATION": "UNKNOWN_ITERATION_LABEL",
    "UNKNOWN_OPTION": "UNKNOWN_PROJECT_OPTION",
    "METADATA_CONFLICT": "CONFLICTING_LABELS",
    "UNSUPPORTED_STATUS_RESERVED": "RESERVED_STATUS_LABEL",
}

_MUTATION_TO_DRIFT = {
    "set_priority": "WRONG_PRIORITY",
    "clear_priority": "WRONG_PRIORITY",
    "set_iteration": "WRONG_ITERATION",
    "clear_iteration": "WRONG_ITERATION",
}


def _classify_status_mutation(mutation_kind: str, payload: dict, issue: IssueAuthority, item: ItemState) -> str:
    if mutation_kind != "set_status":
        return "WRONG_STATUS"
    if issue.state == "CLOSED":
        return "CLOSED_NOT_DONE"
    if item.status == DONE:
        return "OPEN_BUT_DONE"
    return "WRONG_STATUS"


def detect_drift(
    authority: list[tuple[IssueAuthority, ControlLabels]],
    items: dict[int, ItemState],
    config: FieldConfig,
    draft_items: int = 0,
) -> tuple[list[Drift], list[Skipped]]:
    drifts: list[Drift] = []
    skipped: list[Skipped] = []

    if draft_items:
        skipped.append(Skipped(None, "DRAFT_NO_AUTHORITY", f"{draft_items} draft item(s) have no Issue authority"))

    for issue, control in authority:
        item = items.get(issue.number)

        if not control.has_any:
            if item is not None:
                skipped.append(Skipped(issue.number, "NO_CONTROL_METADATA",
                                       "Project member without control labels — not opted into projection"))
            continue

        if item is None:
            plan = plan_sync(
                item=None,
                desired_status=None,  # filled by plan below after membership exists
                desired_priority=None, desired_priority_clear=True,
                desired_iteration_key=None, desired_iteration_clear=True, config=config,
            )
            desired = resolve_desired(issue, control)
            full = plan_sync(item=None, desired_status=desired.status_option,
                             desired_priority=desired.priority_option, desired_priority_clear=desired.priority_clear,
                             desired_iteration_key=desired.iteration_key, desired_iteration_clear=desired.iteration_clear,
                             config=config)
            drifts.append(Drift(issue.number, "MISSING_FROM_PROJECT",
                                "issue carries control labels but is not a Project member",
                                fixable=True, fix=full))
            _append_findings(drifts, issue.number, full)
            continue

        for entry in control.conflicts:
            drifts.append(Drift(issue.number, "CONFLICTING_LABELS",
                                f"conflicting labels for '{entry.field}': {sorted(entry.values)}", fixable=False))
        for label in control.unknown:
            drifts.append(Drift(issue.number, "UNKNOWN_CONTROL_LABEL",
                                f"unrecognized control label '{label}'", fixable=False))
        if control.status_reserved:
            drifts.append(Drift(issue.number, "RESERVED_STATUS_LABEL",
                                "status:ready is reserved/unsupported (Project has no 'Ready' option)",
                                fixable=False))

        desired = resolve_desired(issue, control)
        plan = plan_sync(item=item, desired_status=desired.status_option,
                         desired_priority=desired.priority_option, desired_priority_clear=desired.priority_clear,
                         desired_iteration_key=desired.iteration_key, desired_iteration_clear=desired.iteration_clear,
                         config=config)
        for m in plan.mutations:
            if m.kind == "add_membership":
                continue
            code = (_MUTATION_TO_DRIFT.get(m.kind) or _classify_status_mutation(m.kind, m.payload, issue, item))
            drifts.append(Drift(issue.number, code, f"{m.kind} → {m.payload}", fixable=True,
                                fix=SyncPlan(mutations=[m])))
        _append_findings(drifts, issue.number, plan)

        if item.status is not None and config.status_option(item.status) is None:
            drifts.append(Drift(issue.number, "ACTUAL_OPTION_UNKNOWN",
                                f"Project item carries Status value '{item.status}' unknown to the field",
                                fixable=False))

    return drifts, skipped


def _append_findings(drifts: list[Drift], issue_number: int, plan: SyncPlan) -> None:
    for f in plan.findings:
        code = _FINDING_TO_DRIFT.get(f.code)
        if code:
            drifts.append(Drift(issue_number, code, f.message, fixable=False))
