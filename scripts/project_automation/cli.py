#!/usr/bin/env python3
"""ASK-AI Project automation CLI (contract §7/§8/§9/§10/§19).

Subcommands:
    sync             Workflow A — synchronize one Issue's Project projection from its control labels
    reconcile        Workflow C — detect and (optionally) repair authority/projection drift
    iteration-create Workflow B — privileged iteration creation with fail-closed restoration
    bootstrap        one-time migration: accepted Project state → canonical control labels
    ensure-labels    create the canonical control label set (idempotent)

Token: PROJECT_SYNC_TOKEN or GH_TOKEN env (classic PAT with 'repo' + 'project' scopes).
The repository GITHUB_TOKEN cannot access user-owned Projects v2.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from project_automation.errors import ProjectAutoError  # noqa: E402
from project_automation.service import (bootstrap, create_iteration, ensure_labels,  # noqa: E402
                                        reconcile, settings_from, sync_issue)
from project_automation.transport import GhCliTransport  # noqa: E402

DEFAULT_OWNER = os.environ.get("ASKAI_PROJECT_OWNER", "harryhua-ai")
DEFAULT_NUMBER = int(os.environ.get("ASKAI_PROJECT_NUMBER", "2"))
DEFAULT_REPO = os.environ.get("ASKAI_REPO", "harryhua-ai/ask-ai")


def _emit(report: dict) -> None:
    text = json.dumps(report, indent=1, ensure_ascii=False)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        lines = [f"## Project automation — {report.get('result', '?')}", ""]
        if report.get("issue"):
            lines.append(f"Issue: #{report['issue']}")
        for f in report.get("findings", []):
            lines.append(f"- `{f.get('code', 'NOTE')}` {f.get('message', '')}")
        for d in report.get("drifts", []):
            lines.append(f"- `{d.get('code')}` #{d.get('issue', '')} {d.get('message', '')}")
        for sk in report.get("skipped", []):
            lines.append(f"- skipped `{sk['code']}` #{sk.get('issue', '')} {sk['message']}")
        for d in report.get("needs_attention", []):
            lines.append(f"- NEEDS ATTENTION `{d['code']}` #{d.get('issue', '')} {d['message']}")
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="project-automation")
    parser.add_argument("--owner", default=DEFAULT_OWNER)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--project-number", type=int, default=DEFAULT_NUMBER)
    parser.add_argument("--token", default=None, help="GitHub token; defaults to PROJECT_SYNC_TOKEN/GH_TOKEN")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="synchronize one Issue from its control labels")
    p_sync.add_argument("--issue", type=int, required=True)
    g = p_sync.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dry-run", action="store_true")

    p_rec = sub.add_parser("reconcile", help="detect and repair drift")
    g = p_rec.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dry-run", action="store_true")

    p_iter = sub.add_parser("iteration-create", help="create an iteration (privileged, fail-closed)")
    p_iter.add_argument("--key", required=True, help="iteration key, e.g. v1.7.0 or i-002")
    p_iter.add_argument("--theme", required=True, help="theme text after the ' — ' separator")
    p_iter.add_argument("--start-date", required=True, help="YYYY-MM-DD (a Monday matches field startDay=1)")
    p_iter.add_argument("--duration", type=int, default=14)
    g = p_iter.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dry-run", action="store_true")

    p_boot = sub.add_parser("bootstrap", help="accepted Project state → canonical control labels")
    g = p_boot.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dry-run", action="store_true")

    sub.add_parser("ensure-labels", help="create canonical control labels (idempotent)")

    args = parser.parse_args(argv)

    try:
        token = args.token or os.environ.get("PROJECT_SYNC_TOKEN") or os.environ.get("GH_TOKEN")
        settings = settings_from(owner=args.owner, repo_full=args.repo,
                                 number=args.project_number, token=token)
        transport = GhCliTransport(settings.token)
        if args.command == "sync":
            report = sync_issue(transport, settings, args.issue, dry_run=not args.apply)
        elif args.command == "reconcile":
            report = reconcile(transport, settings, dry_run=not args.apply)
        elif args.command == "iteration-create":
            title = f"{args.key} — {args.theme}" if args.theme else args.key
            report = create_iteration(transport, settings, args.key, title,
                                      args.start_date, args.duration, dry_run=not args.apply)
        elif args.command == "bootstrap":
            report = bootstrap(transport, settings, dry_run=not args.apply)
        elif args.command == "ensure-labels":
            report = ensure_labels(transport, settings)
        else:  # pragma: no cover
            parser.error(f"unknown command {args.command}")
    except ProjectAutoError as exc:
        _emit({"result": "ERROR", "code": exc.code, "message": exc.message})
        return 1

    _emit(report)
    if report.get("findings") or report.get("needs_attention"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
