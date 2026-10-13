#!/usr/bin/env python3
"""Route supported GitHub review events to the attempt-bound verifier."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _pull_request_number(event_name: str, event: dict[str, Any]) -> int | None:
    action = event.get("action")
    if event_name == "pull_request_review":
        if action not in {"submitted", "edited", "dismissed"}:
            return None
        pull_request = event.get("pull_request")
        return _positive_int(pull_request.get("number")) \
            if isinstance(pull_request, dict) else None
    if event_name == "issue_comment":
        if action not in {"created", "edited", "deleted"}:
            return None
        issue = event.get("issue")
        if not isinstance(issue, dict) or not isinstance(issue.get("pull_request"), dict):
            return None
        return _positive_int(issue.get("number"))
    return None


def main() -> int:
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_path:
        print("review trigger: GITHUB_EVENT_PATH is unavailable", file=sys.stderr)
        return 2
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"review trigger: GitHub event is unreadable: {exc}", file=sys.stderr)
        return 2
    if not isinstance(event, dict):
        print("review trigger: GitHub event is not an object", file=sys.stderr)
        return 2

    pr_number = _pull_request_number(event_name, event)
    if pr_number is None:
        print(json.dumps({"routed": False, "event": event_name}))
        return 0

    verifier = Path(__file__).with_name("ght-gha-review-verdict.py")
    if not verifier.is_file():
        print(f"review trigger: trusted verifier is missing beside {__file__}",
              file=sys.stderr)
        return 2
    # Event payloads select the PR only; the verifier reads current review state.
    return subprocess.run([sys.executable, str(verifier), str(pr_number)],
                          check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
