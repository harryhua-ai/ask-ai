"""#124 AC4: qualification provenance migration belongs to each frozen release plan."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = "scripts/migrate_add_sales_lead_qualification_provenance.py"
CONTACT_VOID = "scripts/migrate_add_sales_lead_contact_void.py"


def test_qualification_provenance_is_appended_after_contact_void_in_release_plan(tmp_path):
    manifest_path = ROOT / "deploy/prod/migrations.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest["migrations"]

    assert entries.count(MIGRATION) == 1
    assert entries.count(CONTACT_VOID) == 1
    assert entries[-2:] == [CONTACT_VOID, MIGRATION]
    assert all((ROOT / entry).is_file() for entry in entries)

    # Resolve the committed frozen tree shape through the production planner.
    repo = tmp_path / "frozen"
    repo.mkdir()
    _git(repo, "init", "-q")
    frozen_paths = ["scripts/release_migration_plan.py", "deploy/prod/migrations.json", *entries]
    for relative in frozen_paths:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-qm",
        "frozen",
    )
    sha = _git(repo, "rev-parse", "HEAD", capture=True).strip()
    result = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts/release_migration_plan.py"),
            "--tag",
            "v9.9.9",
            "--sha",
            sha,
            "--repo-root",
            str(repo),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    planned = result.stdout.splitlines()
    assert planned[-2:] == [CONTACT_VOID, MIGRATION]


def _git(repo: Path, *args: str, capture: bool = False) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        capture_output=capture,
    )
    return result.stdout if capture else ""
