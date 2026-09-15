"""High-level Project operations used by the CLI: fetch, plan, apply, verify.

All Project identity (field ids, option ids, iteration ids, item ids) is resolved
per run from live state and never persisted as durable truth (contract §3).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
from dataclasses import dataclass

from . import queries as q
from .errors import AuthenticationError, ConfigError, ProjectMutationFailure, VerificationFailure
from .iteration_txn import IterationTuple, create_iteration_transaction
from .mapping import (
    RESERVED_STATUS_NOTE,
    STATUS_MAP,
    resolve_desired,
    resolve_iteration,
    resolve_live_control_labels,
)
from .model import (
    FieldConfig,
    IssueAuthority,
    ItemState,
    IterationDef,
    OptionDef,
    iteration_slug,
)
from .planner import Finding, Mutation, SyncPlan, plan_sync
from .reconcile import detect_drift
from .transport import GhCliTransport

STATUS_FIELD = "Status"
PRIORITY_FIELD = "Priority"
ITERATION_FIELD = "Iteration"


@dataclass
class Settings:
    owner: str
    repo: str
    project_number: int
    token: str


def settings_from(*, owner: str, repo_full: str, number: int, token: str | None) -> Settings:
    repo_name = repo_full.split("/")[-1]
    return Settings(owner=owner, repo=repo_name, project_number=number, token=token or "")


@dataclass
class Context:
    project_id: str
    config: FieldConfig
    field_ids: dict  # {"status": id, "priority": id, "iteration": id}
    config_anchor: str  # configuration-level startDate anchor
    config_duration: int


def gh_cli_json(args: list[str], token: str, timeout: float = 60.0):
    """Run a gh command and parse its JSON output. Commands with human-readable
    success output (e.g. `gh issue edit`) are tolerated: the exit code decides success."""
    env = dict(os.environ)
    env["GH_TOKEN"] = token
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout, env=env,
                           check=False)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        if "Bad credentials" in stderr or "401" in stderr:
            raise AuthenticationError(f"GitHub rejected the token: {stderr[:300]}")
        raise ProjectMutationFailure(f"gh {' '.join(args[:3])} failed: {stderr[:400]}")
    out = proc.stdout.strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return out[:200]


def fetch_context(t: GhCliTransport, s: Settings) -> Context:
    data = t.graphql(q.build_query(q.PROJECT_CONTEXT, owner=s.owner, repo=s.repo, number=s.project_number))
    pv = (data.get("user") or {}).get("projectV2")
    if not pv:
        raise ConfigError(f"project #{s.project_number} not found for user '{s.owner}'")
    status_f, prio_f, iter_f = pv.get("status"), pv.get("priority"), pv.get("iteration")
    if not (status_f and prio_f and iter_f):
        raise ConfigError("Project is missing required fields Status/Priority/Iteration")
    cfg = (iter_f or {}).get("configuration") or {}
    if not isinstance(status_f.get("options"), list) or not isinstance(prio_f.get("options"), list):
        raise ConfigError("Project Status/Priority schema is not a single-select field with options")
    if not isinstance(cfg.get("iterations", []), list) or not isinstance(
            cfg.get("completedIterations", []), list):
        raise ConfigError("Project Iteration schema has no readable iteration configuration")
    # Completed iterations are first-class: this project assigns to historical
    # timeboxes, and once an iteration's end date passes, GitHub moves it out of
    # `iterations` into `completedIterations`. Resolution/restore must see both.
    iterations = [
        IterationDef(id=i["id"], title=i["title"], start_date=i["startDate"], duration=i["duration"])
        for i in [*cfg.get("iterations", []), *cfg.get("completedIterations", [])]
    ]
    anchors = sorted(i["startDate"] for i in cfg.get("iterations", []))
    return Context(
        project_id=pv["id"],
        config=FieldConfig(
            status_options=[OptionDef(o["id"], o["name"]) for o in status_f["options"]],
            priority_options=[OptionDef(o["id"], o["name"]) for o in prio_f["options"]],
            iterations=iterations,
        ),
        field_ids={"status": status_f["id"], "priority": prio_f["id"], "iteration": iter_f["id"]},
        config_anchor=anchors[0] if anchors else "2026-09-07",
        config_duration=cfg.get("duration", 14),
    )


def _iter_item_pages(t: GhCliTransport, s: Settings):
    after = None
    while True:
        data = t.graphql(q.build_query(q.PROJECT_ITEMS, owner=s.owner, number=s.project_number, after=after))
        conn = data["user"]["projectV2"]["items"]
        yield from conn["nodes"]
        if not conn["pageInfo"]["hasNextPage"]:
            return
        after = conn["pageInfo"]["endCursor"]


def fetch_items(t: GhCliTransport, s: Settings) -> list[ItemState]:
    items: list[ItemState] = []
    for n in _iter_item_pages(t, s):
        content = n.get("content") or {}
        is_draft = content.get("__typename") == "DraftIssue"
        it = n.get("iteration")
        items.append(ItemState(
            item_id=n["id"],
            issue_number=content.get("number") if not is_draft else None,
            is_draft=is_draft,
            iteration_slug=iteration_slug(it["title"]) if it else None,
            priority=(n.get("priority") or {}).get("name"),
            status=(n.get("status") or {}).get("name"),
            iteration_id=it.get("iterationId") if it else None,
            iteration_title=it.get("title") if it else None,
        ))
    return items


def fetch_issue(t: GhCliTransport, s: Settings, number: int) -> tuple[IssueAuthority, str, list[dict]]:
    data = t.graphql(q.build_query(q.ISSUE, owner=s.owner, repo=s.repo, number=number))
    issue = (data.get("repository") or {}).get("issue")
    if not issue:
        raise ConfigError(f"issue #{number} not found in {s.owner}/{s.repo}")
    authority = IssueAuthority(
        number=issue["number"],
        state=issue["state"],
        labels=[l["name"] for l in issue["labels"]["nodes"]],
    )
    return authority, issue["id"], issue["projectItems"]["nodes"]


def apply_plan(t: GhCliTransport, ctx: Context, item_id: str, plan: SyncPlan) -> list[str]:
    applied: list[str] = []
    for m in plan.mutations:
        if m.kind == "set_status":
            t.graphql(q.build_query(q.SET_STATUS, projectId=ctx.project_id, itemId=item_id,
                                    fieldId=ctx.field_ids["status"], optionId=m.payload["option_id"]))
        elif m.kind == "set_priority":
            t.graphql(q.build_query(q.SET_STATUS, projectId=ctx.project_id, itemId=item_id,
                                    fieldId=ctx.field_ids["priority"], optionId=m.payload["option_id"]))
        elif m.kind == "clear_priority":
            t.graphql(q.build_query(q.CLEAR_FIELD, projectId=ctx.project_id, itemId=item_id,
                                    fieldId=ctx.field_ids["priority"]))
        elif m.kind == "set_iteration":
            t.graphql(q.build_query(q.SET_ITERATION, projectId=ctx.project_id, itemId=item_id,
                                    fieldId=ctx.field_ids["iteration"], iterationId=m.payload["iteration_id"]))
        elif m.kind == "clear_iteration":
            t.graphql(q.build_query(q.CLEAR_FIELD, projectId=ctx.project_id, itemId=item_id,
                                    fieldId=ctx.field_ids["iteration"]))
        else:
            raise ProjectMutationFailure(f"unknown mutation kind '{m.kind}'")
        applied.append(m.kind)
    return applied


def _append_control_findings(plan: SyncPlan, control, desired, config: FieldConfig) -> None:
    """Turn malformed recognized labels into visible, field-scoped failures.

    The parser keeps legacy ``unknown`` visibility, while live options decide
    whether a future Priority/Status value is actually valid.
    """
    existing = {(f.code, f.field) for f in plan.findings}
    for label in control.unknown:
        lowered = label.lower()
        if lowered.startswith("priority:"):
            if desired.priority_option and config.priority_option(desired.priority_option):
                continue
            code, field = "UNKNOWN_OPTION", "priority"
            message = f"Project has no Priority option for control label '{label}'"
        elif lowered.startswith("status:"):
            if desired.status_option and config.status_option(desired.status_option):
                continue
            code, field = "UNKNOWN_OPTION", "status"
            message = f"Project has no Status option for control label '{label}'"
        elif lowered.startswith("iteration:"):
            code, field = "UNKNOWN_ITERATION", "iteration"
            message = f"malformed or unresolved Iteration control label '{label}'"
        elif lowered.startswith("schedule:"):
            code, field = "UNKNOWN_SCHEDULE", "iteration"
            message = f"unsupported schedule control label '{label}'"
        else:
            code, field = "UNKNOWN_CONTROL_LABEL", None
            message = f"unrecognized control label '{label}'"
        if (code, field) not in existing:
            plan.findings.append(Finding(code, message, field=field))
            existing.add((code, field))


def sync_issue(t: GhCliTransport, s: Settings, number: int, dry_run: bool) -> dict:
    ctx = fetch_context(t, s)
    authority, content_id, memberships = fetch_issue(t, s, number)
    project_memberships = [m for m in memberships if m.get("project", {}).get("id") == ctx.project_id]
    if len(project_memberships) > 1:
        raise VerificationFailure(f"issue #{number} has multiple Project items for project {ctx.project_id}")
    member_item_id = project_memberships[0]["id"] if project_memberships else None

    control = resolve_live_control_labels(authority.labels, ctx.config)
    if not control.has_any:
        return {"issue": number, "result": "NO_CONTROL_INTENT", "mutations": [], "findings": []}

    items = fetch_items(t, s)
    matching_items = [i for i in items if i.issue_number == number]
    if len(matching_items) > 1:
        raise VerificationFailure(f"issue #{number} has multiple resolved Project items")
    item = matching_items[0] if matching_items else None
    if member_item_id and item is None:
        raise VerificationFailure(f"issue #{number} is a Project member but its item could not be resolved")

    desired = resolve_desired(authority, control)
    # The current live Project uses the built-in ``open`` Status option while
    # older automation fixtures call the same default ``Backlog``.  Preserve
    # the legacy mapping, but let the live schema supply its equivalent when
    # no explicit status label is present.
    if (authority.state == "OPEN" and not control.has_status_label
            and ctx.config.status_option(desired.status_option or "") is None):
        live_open = ctx.config.status_option("open")
        if live_open is not None:
            desired.status_option = live_open.name
    plan = plan_sync(item=item, desired_status=desired.status_option,
                     desired_priority=desired.priority_option, desired_priority_clear=desired.priority_clear,
                     desired_iteration_key=desired.iteration_key, desired_iteration_clear=desired.iteration_clear,
                     config=ctx.config)
    for c in control.conflicts:
        plan.findings.append(Finding(
            "METADATA_CONFLICT",
            f"conflicting {'/'.join(c.values)} for control field '{c.field}'; that field left unchanged",
            field=c.field))
    if control.status_reserved:
        plan.findings.append(Finding(
            "UNSUPPORTED_STATUS_RESERVED", RESERVED_STATUS_NOTE, field="status"))
    _append_control_findings(plan, control, desired, ctx.config)

    report = {
        "issue": number,
        "requested": {"status": desired.status_option, "priority": desired.priority_option,
                      "priority_clear": desired.priority_clear, "iteration": desired.iteration_key,
                      "iteration_clear": desired.iteration_clear},
        "before": {"status": item.status if item else None, "priority": item.priority if item else None,
                   "iteration": item.iteration_slug if item else None},
        "mutations": [{"kind": m.kind, **m.payload} for m in plan.mutations],
        "findings": [{"code": f.code, "message": f.message} for f in plan.findings],
        "dry_run": dry_run,
    }
    if dry_run:
        report["result"] = "DRY_RUN"
        return report

    if plan.findings:
        report["result"] = "FAILED_VALIDATION"
        return report

    if item is None:
        data = t.graphql(q.build_query(q.ADD_ITEM, projectId=ctx.project_id, contentId=content_id))
        item_id = data["addProjectV2ItemById"]["item"]["id"]
    else:
        item_id = item.item_id

    # Membership is applied above via ADD_ITEM; the planning-level add_membership
    # marker is not an executable mutation (live incident 34599644360: passing it
    # to apply_plan crashed AFTER the item was added, leaving fields unset).
    field_plan = SyncPlan(mutations=[m for m in plan.mutations if m.kind != "add_membership"],
                          findings=plan.findings)
    applied = apply_plan(t, ctx, item_id, field_plan)

    # VERIFY: re-read and compare against the requested semantic state,
    # excluding fields whose resolution already produced a visible finding
    blocked = {f.field for f in plan.findings if f.field}
    after_items = [i for i in fetch_items(t, s) if i.issue_number == number]
    if len(after_items) > 1:
        raise VerificationFailure(f"issue #{number} has multiple Project items after synchronization")
    after = after_items[0] if after_items else None
    if after is None:
        raise VerificationFailure(f"issue #{number} still absent from Project after sync")
    problems = []
    if desired.status_option is not None and "status" not in blocked and after.status != desired.status_option:
        problems.append(f"status: expected {desired.status_option!r}, got {after.status!r}")
    if desired.priority_clear and "priority" not in blocked and after.priority is not None:
        problems.append(f"priority: expected cleared, got {after.priority!r}")
    if desired.priority_option is not None and "priority" not in blocked and after.priority != desired.priority_option:
        problems.append(f"priority: expected {desired.priority_option!r}, got {after.priority!r}")
    if desired.iteration_clear and "iteration" not in blocked and after.iteration_slug is not None:
        problems.append(f"iteration: expected cleared, got {after.iteration_slug!r}")
    if desired.iteration_key is not None and "iteration" not in blocked:
        expected = resolve_iteration(ctx.config.iterations, desired.iteration_key)
        expected_slug = expected.slug if expected else iteration_slug(desired.iteration_key)
        if expected and after.iteration_id and after.iteration_id != expected.id:
            problems.append(f"iteration: expected id {expected.id!r}, got {after.iteration_id!r}")
        elif after.iteration_slug != expected_slug:
            problems.append(f"iteration: expected {expected_slug!r}, got {after.iteration_slug!r}")
    if problems:
        raise VerificationFailure(f"issue #{number} did not converge: " + "; ".join(problems))

    report["after"] = {"status": after.status, "priority": after.priority,
                         "iteration": after.iteration_slug,
                         "iteration_title": after.iteration_title,
                         "iteration_id": after.iteration_id}
    report["read_back"] = {"verified": True, "requested": report["requested"],
                            "actual": report["after"]}
    report["applied"] = applied
    report["result"] = "APPLIED" if applied else "ALREADY_CONVERGED"
    return report


def list_repo_issues(s: Settings) -> list[IssueAuthority]:
    raw = gh_cli_json(["issue", "list", "--repo", f"{s.owner}/{s.repo}", "--state", "all",
                       "--limit", "1000", "--json", "number,state,labels"], s.token)
    return [IssueAuthority(number=r["number"], state=r["state"], labels=[l["name"] for l in r["labels"]])
            for r in raw]


def detect_project_drift(t: GhCliTransport, s: Settings):
    ctx = fetch_context(t, s)
    items = fetch_items(t, s)
    authority = [(a, resolve_live_control_labels(a.labels, ctx.config)) for a in list_repo_issues(s)]
    item_states = {i.issue_number: i for i in items if not i.is_draft}
    draft_count = sum(1 for i in items if i.is_draft)
    drifts, skipped = detect_drift(authority, item_states, ctx.config, draft_items=draft_count)
    return ctx, items, drifts, skipped


def reconcile(t: GhCliTransport, s: Settings, dry_run: bool) -> dict:
    ctx, items, drifts, skipped = detect_project_drift(t, s)
    report = {
        "drifts": [{"issue": d.issue_number, "code": d.code, "message": d.message, "fixable": d.fixable}
                   for d in drifts],
        "skipped": [{"issue": sk.issue_number, "code": sk.code, "message": sk.message} for sk in skipped],
        "dry_run": dry_run,
    }
    if dry_run:
        report["result"] = "DRY_RUN"
        return report

    item_by_number = {i.issue_number: i for i in items if not i.is_draft}
    applied: list[str] = []
    plans_by_issue: dict[int, list[Mutation]] = {}
    for d in drifts:
        if not (d.fixable and d.fix):
            continue
        number = d.issue_number
        assert number is not None
        if any(m.kind == "add_membership" for m in d.fix.mutations):
            _, content_id, memberships = fetch_issue(t, s, number)
            if not any(m["project"]["id"] == ctx.project_id for m in memberships):
                t.graphql(q.build_query(q.ADD_ITEM, projectId=ctx.project_id, contentId=content_id))
            plans_by_issue.setdefault(number, []).append(
                next(m for m in d.fix.mutations if m.kind == "add_membership"))
        field_plan = SyncPlan(mutations=[m for m in d.fix.mutations if m.kind != "add_membership"])
        if field_plan.mutations:
            target = (item_by_number.get(number) or next(
                (i for i in fetch_items(t, s) if i.issue_number == number), None))
            if target is None:
                raise VerificationFailure(f"reconcile: item for issue #{number} unresolved after add")
            applied += apply_plan(t, ctx, target.item_id, field_plan)
            plans_by_issue.setdefault(number, []).extend(field_plan.mutations)

    if plans_by_issue:
        refreshed = {i.issue_number: i for i in fetch_items(t, s) if not i.is_draft}
        for number, mutations in plans_by_issue.items():
            item = refreshed.get(number)
            if item is None:
                raise VerificationFailure(f"reconcile: issue #{number} missing after mutation")
            problems = []
            for mutation in mutations:
                if mutation.kind == "add_membership":
                    continue
                if mutation.kind == "set_status" and item.status != mutation.payload["option_name"]:
                    problems.append(f"status expected {mutation.payload['option_name']!r}, got {item.status!r}")
                elif mutation.kind == "set_priority" and item.priority != mutation.payload["option_name"]:
                    problems.append(f"priority expected {mutation.payload['option_name']!r}, got {item.priority!r}")
                elif mutation.kind == "clear_priority" and item.priority is not None:
                    problems.append(f"priority expected cleared, got {item.priority!r}")
                elif mutation.kind == "set_iteration":
                    expected = iteration_slug(mutation.payload["iteration_title"])
                    if item.iteration_id and item.iteration_id != mutation.payload["iteration_id"]:
                        problems.append(f"iteration expected id {mutation.payload['iteration_id']!r}, got {item.iteration_id!r}")
                    elif item.iteration_slug != expected:
                        problems.append(f"iteration expected {expected!r}, got {item.iteration_slug!r}")
                elif mutation.kind == "clear_iteration" and item.iteration_slug is not None:
                    problems.append(f"iteration expected cleared, got {item.iteration_slug!r}")
            if problems:
                raise VerificationFailure(f"reconcile issue #{number} did not converge: " + "; ".join(problems))

    report["applied"] = applied
    report["read_back"] = {"verified": True, "issues": sorted(plans_by_issue)} if plans_by_issue else None
    report["result"] = "REPAIRED" if applied else "NO_DRIFT"
    report["needs_attention"] = [{"issue": d.issue_number, "code": d.code, "message": d.message}
                                 for d in drifts if not d.fixable]
    return report


def derive_labels_for_item(item: ItemState, state: str) -> tuple[list[str], list[str]]:
    """Accepted Project state → canonical control labels. Returns (labels, needs_review)."""
    labels: list[str] = []
    review: list[str] = []
    if item.iteration_slug:
        labels.append(f"iteration:{item.iteration_slug}")
    if item.priority:
        labels.append(f"priority:{item.priority.strip().lower().replace(' ', '-')}")
    if state != "CLOSED":  # closure owns Done; no status label required
        inv = {v: k for k, v in STATUS_MAP.items()}
        if item.status in inv:
            labels.append(f"status:{inv[item.status]}")
        elif item.status:
            review.append(f"no canonical status label for option '{item.status}'")
    return labels, review


def bootstrap(t: GhCliTransport, s: Settings, dry_run: bool) -> dict:
    """One-time migration: accepted Project state → canonical control labels (contract §19)."""
    fetch_context(t, s)
    items = fetch_items(t, s)
    issues = list_repo_issues(s)
    existing_labels = {a.number: set(a.labels) for a in issues}
    states = {a.number: a.state for a in issues}
    planned, review, conflicts = [], [], []
    for item in items:
        if item.is_draft or item.issue_number is None or item.issue_number not in existing_labels:
            continue
        number = item.issue_number
        labels, needs_review = derive_labels_for_item(item, states.get(number, "OPEN"))
        current = existing_labels[number]
        additions = [l for l in labels if l not in current]
        contradicting = sorted(
            l for l in current
            if l.split(":")[0] in ("iteration", "priority", "status") and l not in labels
        )
        if contradicting:
            conflicts.append({"issue": number, "labels": contradicting})
        for r in needs_review:
            review.append({"issue": number, "note": r})
        if additions:
            planned.append({"issue": number, "add": additions})

    report = {"planned": planned, "needs_review": review, "contradicting_existing_labels": conflicts,
              "dry_run": dry_run}
    if dry_run:
        report["result"] = "DRY_RUN"
        return report

    applied = []
    for entry in planned:
        for label in entry["add"]:
            gh_cli_json(["issue", "edit", str(entry["issue"]), "--repo", f"{s.owner}/{s.repo}",
                         "--add-label", label], s.token)
            applied.append({"issue": entry["issue"], "label": label})
    report["applied"] = applied
    report["result"] = "BOOTSTRAPPED"
    return report


def canonical_labels(config: FieldConfig) -> list[str]:
    priority_labels = [f"priority:{o.name.strip().lower().replace(' ', '-')}"
                       for o in config.priority_options]
    return priority_labels + \
           [f"status:{v}" for v in sorted(STATUS_MAP)] + \
           [f"iteration:{i.slug}" for i in config.iterations]


def ensure_labels(t: GhCliTransport, s: Settings) -> dict:
    ctx = fetch_context(t, s)
    canonical = canonical_labels(ctx.config)
    existing = {l["name"] for l in gh_cli_json(
        ["label", "list", "--repo", f"{s.owner}/{s.repo}", "--json", "name"], s.token)}
    created = []
    for name in canonical:
        if name in existing:
            continue
        color = "D4C5F9" if name.startswith("iteration:") else ("D93F0B" if name.startswith("priority:") else "0E8A16")
        gh_cli_json(["label", "create", name, "--repo", f"{s.owner}/{s.repo}", "--color", color,
                     "--description", f"ASK-AI canonical project control: {name}"], s.token)
        created.append(name)
    return {"result": "ENSURED", "created": created, "canonical": canonical}


class LiveIterationOps:
    """Adapter presenting the iteration transaction interface over the live transport."""

    def __init__(self, t: GhCliTransport, ctx: Context, settings: Settings):
        self.t, self.ctx, self.s = t, ctx, settings

    def get_iterations(self) -> list[IterationTuple]:
        fresh = fetch_context(self.t, self.s)
        return [IterationTuple(i.id, i.title, i.start_date, i.duration) for i in fresh.config.iterations]

    def get_item_assignments(self) -> dict[str, str]:
        # Cover EVERY Project item with an Iteration value - Issue AND DraftIssue.
        # The full-replace id regeneration orphans both; skipping drafts here would
        # silently orphan them (14 I-001 draft items exist on the live Project).
        out: dict[str, str] = {}
        for n in _iter_item_pages(self.t, self.s):
            it = n.get("iteration")
            if it:
                out[n["id"]] = iteration_slug(it["title"])
        return out

    def set_item_iteration(self, item_id: str, iteration_id: str):
        self.t.graphql(q.build_query(q.SET_ITERATION, projectId=self.ctx.project_id, itemId=item_id,
                                     fieldId=self.ctx.field_ids["iteration"], iterationId=iteration_id))

    def update_iterations(self, tuples: list[tuple]):
        durations = {t[3] for t in tuples}
        if len(durations) != 1:
            raise ConfigError(f"mixed iteration durations {sorted(durations)}; field requires a single duration")
        anchor = min(t[2] for t in tuples)
        payload = [{"title": t[1], "startDate": t[2], "duration": t[3]} for t in tuples]
        self.t.graphql(q.build_query(q.UPDATE_ITERATION_CONFIG, fieldId=self.ctx.field_ids["iteration"],
                                     iterations=payload, startDate=anchor, duration=tuples[0][3]))


def create_iteration(t: GhCliTransport, s: Settings, key: str, title: str, start_date: str,
                     duration: int, dry_run: bool) -> dict:
    try:
        _dt.date.fromisoformat(start_date)
    except ValueError as exc:
        raise ConfigError(f"invalid --start-date '{start_date}' (expected YYYY-MM-DD)") from exc
    if not 1 <= duration <= 200:
        raise ConfigError(f"invalid --duration {duration} (expected 1..200)")
    ctx = fetch_context(t, s)
    existing = [IterationTuple(i.id, i.title, i.start_date, i.duration) for i in ctx.config.iterations]
    new = IterationTuple(id="pending", title=title, start_date=start_date, duration=duration)
    if iteration_slug(title) in {i.slug for i in ctx.config.iterations}:
        raise ConfigError(f"iteration '{iteration_slug(title)}' already exists; refusing duplicate creation")
    items = fetch_items(t, s)
    if dry_run:
        return {"result": "DRY_RUN", "title": title, "start_date": start_date, "duration": duration,
                "existing_iterations": [i.slug for i in ctx.config.iterations],
                "would_restore_assignments": sum(1 for i in items if i.iteration_slug)}
    ops = LiveIterationOps(t, ctx, s)
    result = create_iteration_transaction(ops, existing=existing, new=new,
                                          item_ids=[i.item_id for i in items])
    label = f"iteration:{result.created.slug}"
    gh_cli_json(["label", "create", label, "--repo", f"{s.owner}/{s.repo}", "--color", "D4C5F9",
                 "--description", f"ASK-AI canonical project control: {label}", "--force"], s.token)
    return {
        "result": "CREATED",
        "iteration": {"id": result.created.id, "title": result.created.title, "slug": result.created.slug,
                      "start_date": result.created.start_date, "duration": result.created.duration},
        "restored": result.restored,
        "verified_items": len(result.pre_assignments),
        "control_label": label,
    }
