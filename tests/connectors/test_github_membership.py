"""#71 GitHub connector — authoritative membership enumeration contract.

`membership_source_ids()` must return the CURRENT in-scope path set of the
just-fetched working tree (same file_types / exclusion / safety filters as
ingestion), per branch, without reading file contents. This is the
authoritative side of `stale_set = ledger − authoritative` (#71).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.connectors.github import GitHubConnector
from backend.connectors.registry import SourceConfig

pytestmark = pytest.mark.unit


def _connector(tmp_path: Path, branches: list[str]) -> GitHubConnector:
    cfg = SourceConfig(
        id="wiki-documents-local",
        type="github",
        product="wiki",
        enabled=True,
        config={
            "repo_url": "https://github.com/example/wiki.git",
            "clone_path": str(tmp_path / "clone"),
            "branches": branches,
            "file_types": [".md"],
            "exclude_dirs": ["tests"],
        },
        sync_interval="24h",
    )
    return GitHubConnector(cfg)


def _write(clone: Path, rel: str, content: str = "# t\n") -> None:
    p = clone / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_m1_membership_walks_current_tree_with_ingestion_filters(tmp_path, monkeypatch):
    conn = _connector(tmp_path, ["main"])
    clone = tmp_path / "clone"
    _write(clone, "docs/0-overview.md")
    _write(clone, "docs/deep/2-sdk-reference.md")
    _write(clone, "docs/skipped-binary.bin")  # not in file_types
    _write(clone, "tests/zz-excluded.md")  # excluded dir
    _write(clone, ".git/HEAD", "ref: refs/heads/main\n")  # clone internals

    # No network / no git: the contract under test is tree-walk + filters.
    monkeypatch.setattr(conn, "_ensure_cloned", lambda branch: None)
    monkeypatch.setattr(conn, "_git_sync_branch", lambda branch: None)

    members = conn.membership_source_ids()

    assert members == {
        "wiki-documents-local/main/docs/0-overview.md",
        "wiki-documents-local/main/docs/deep/2-sdk-reference.md",
    }


def test_m2_membership_is_branch_scoped(tmp_path, monkeypatch):
    conn = _connector(tmp_path, ["main", "hw-v1.2"])
    clone = tmp_path / "clone"
    # Single working copy — connector resets per branch; both rounds see files.
    _write(clone, "docs/a.md")

    seen_branches: list[str] = []

    def _fake_sync(branch: str) -> None:
        seen_branches.append(branch)

    monkeypatch.setattr(conn, "_ensure_cloned", lambda branch: None)
    monkeypatch.setattr(conn, "_git_sync_branch", _fake_sync)

    members = conn.membership_source_ids()
    assert seen_branches == ["main", "hw-v1.2"]  # authoritative per-branch fetch+reset
    assert members == {
        "wiki-documents-local/main/docs/a.md",
        "wiki-documents-local/hw-v1.2/docs/a.md",
    }


def test_m3_membership_enum_sentinel_is_documented_capability():
    """The capability is optional protocol-wide (filesystem/woo untouched)."""
    import inspect

    from backend.connectors import filesystem as fs_mod

    src = inspect.getsource(fs_mod)
    assert "membership_source_ids" not in src  # no forced implementation
