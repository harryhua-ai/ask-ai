"""GitHub transport: `gh api graphql` subprocess with a caller-provided token.

User-owned Projects v2 are NOT accessible to the repository GITHUB_TOKEN; a PAT
with project access is required (contract §10). Absent token → clean
AUTHENTICATION ERROR instead of a cryptic 401 deep inside a run.
"""
from __future__ import annotations

import json
import os
import subprocess

from .errors import AuthenticationError, ProjectMutationFailure


class GhCliTransport:
    def __init__(self, token: str | None, runner=None, timeout: float = 60.0):
        if not token:
            raise AuthenticationError(
                "no GitHub token with Projects access; set PROJECT_SYNC_TOKEN (classic PAT with "
                "'repo' + 'project' scopes, or fine-grained PAT with Projects read/write). "
                "The repository GITHUB_TOKEN cannot read or mutate user-owned Projects v2.")
        self.token = token
        self.timeout = timeout
        self._runner = runner or subprocess.run

    def graphql(self, query: str) -> dict:
        cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
        env = dict(os.environ)
        env["GH_TOKEN"] = self.token
        try:
            proc = self._runner(cmd, capture_output=True, text=True, timeout=self.timeout, env=env)
        except subprocess.TimeoutExpired as exc:
            raise ProjectMutationFailure(f"GitHub API timeout after {self.timeout}s") from exc
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            if "Bad credentials" in stderr or "401" in stderr or "HTTP 40" in stderr:
                raise AuthenticationError(f"GitHub rejected the token: {stderr[:300]}")
            raise ProjectMutationFailure(f"gh api graphql failed: {stderr[:500]}")
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise ProjectMutationFailure(f"unparseable GitHub response: {proc.stdout[:300]}") from exc
        if payload.get("errors"):
            first = payload["errors"][0].get("message", str(payload["errors"][0]))
            raise ProjectMutationFailure(f"GitHub GraphQL error: {first[:400]}")
        return payload.get("data", {})
