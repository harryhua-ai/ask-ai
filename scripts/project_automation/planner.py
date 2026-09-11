"""Sync planning: diff desired projection vs actual Project item into mutations.

Idempotent by construction — an already-correct item plans zero mutations.
Per-field isolation: one field's unknown/conflict never blocks the others.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .mapping import resolve_iteration
from .model import FieldConfig, ItemState, sprint_title_slug


@dataclass
class Mutation:
    kind: str  # add_membership | set_status | set_priority | clear_priority | set_iteration | clear_iteration | set_sprint | clear_sprint
    payload: dict = field(default_factory=dict)


@dataclass
class Finding:
    code: str  # UNKNOWN_OPTION | UNKNOWN_ITERATION | METADATA_CONFLICT | DRAFT_SKIPPED
    message: str
    field: str | None = None  # projection field the finding blocks ("status"|"priority"|"iteration"|None)


@dataclass
class SyncPlan:
    mutations: list[Mutation] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings


def plan_sync(
    *,
    item: ItemState | None,
    desired_status: str | None,
    desired_priority: str | None,
    desired_priority_clear: bool,
    desired_iteration_key: str | None,
    desired_iteration_clear: bool,
    config: FieldConfig,
    desired_sprint_key: str | None = None,
    desired_sprint_clear: bool = False,
) -> SyncPlan:
    plan = SyncPlan()

    if item is not None and item.is_draft:
        plan.findings.append(Finding("DRAFT_SKIPPED", "draft project items have no Issue authority"))
        return plan

    if item is None:
        plan.mutations.append(Mutation("add_membership"))

    if desired_status is not None:
        opt = config.status_option(desired_status)
        if opt is None:
            plan.findings.append(
                Finding("UNKNOWN_OPTION", f"Project has no Status option '{desired_status}'; "
                                          f"add the option or use the vocabulary mapping in project_automation.mapping",
                        field="status")
            )
        elif item is None or item.status != opt.name:
            plan.mutations.append(Mutation("set_status", {"option_id": opt.id, "option_name": opt.name}))

    if desired_priority_clear:
        if item is not None and item.priority is not None:
            plan.mutations.append(Mutation("clear_priority"))
    elif desired_priority is not None:
        opt = config.priority_option(desired_priority)
        if opt is None:
            plan.findings.append(Finding("UNKNOWN_OPTION", f"Project has no Priority option '{desired_priority}'",
                                         field="priority"))
        elif item is None or item.priority != opt.name:
            plan.mutations.append(Mutation("set_priority", {"option_id": opt.id, "option_name": opt.name}))

    if desired_iteration_clear:
        if item is not None and item.iteration_slug is not None:
            plan.mutations.append(Mutation("clear_iteration"))
    elif desired_iteration_key is not None:
        it = resolve_iteration(config.iterations, desired_iteration_key)
        if it is None:
            plan.findings.append(
                Finding("UNKNOWN_ITERATION",
                        f"iteration '{desired_iteration_key}' does not exist in the Project; "
                        f"iteration creation is a separate privileged workflow "
                        f"(project-iteration-create.yml) — refusing to guess",
                        field="iteration")
            )
        elif item is None or item.iteration_slug != it.slug:
            plan.mutations.append(Mutation("set_iteration", {"iteration_id": it.id, "iteration_title": it.title}))

    # Sprint: independent authoritative dimension; never touches Iteration.
    # absent label → clear; unknown key → fail closed (existing value preserved).
    if desired_sprint_clear:
        if item is not None and item.sprint_slug is not None:
            plan.mutations.append(Mutation("clear_sprint"))
    elif desired_sprint_key is not None:
        sp = config.sprint_by_slug(sprint_title_slug(desired_sprint_key))
        if sp is None:
            plan.findings.append(
                Finding("UNKNOWN_SPRINT",
                        f"sprint '{desired_sprint_key}' does not exist in the Project Sprint field; "
                        f"no Sprint mutation — create the Sprint value first",
                        field="sprint")
            )
        elif item is None or item.sprint_slug != sprint_title_slug(sp.title):
            plan.mutations.append(Mutation("set_sprint", {"sprint_id": sp.id, "sprint_title": sp.title}))

    return plan
