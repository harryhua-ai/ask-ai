"""Issue #91 REVIEW_3:GitHubConnector 权威内容指纹能力(窄面)契约。

``membership_content_fingerprints(source_ids)`` 必须与灌入哈希**同变换**
(read_text utf-8/replace + 通用换行平移 + utf-8 sha256),自 git 对象库
(``git show origin/<branch>:<rel>``)读取 —— 多分支共用 clone、按分支
reset 的瞬态状态下恒正确;仅对存在排除登记的身份被调用(零全量成本)。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.connectors.github import GitHubConnector
from backend.connectors.registry import SourceConfig

pytestmark = pytest.mark.unit


def _git(*args: str, cwd: Path) -> None:
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(cwd.parent),
    }
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, env=env
    )


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
            "file_types": [".md", ".txt"],
            "exclude_dirs": ["tests"],
        },
        sync_interval="24h",
    )
    return GitHubConnector(cfg)


def _fetch_hash(path: Path) -> str:
    """与 github.py fetch 完全相同的哈希变换(_make_document 同源)。"""
    content = path.read_text(encoding="utf-8", errors="replace")
    return hashlib.sha256(content.encode()).hexdigest()


def _build_clone(tmp_path: Path) -> tuple[GitHubConnector, Path]:
    clone = tmp_path / "clone"
    clone.mkdir(parents=True)
    _git("init", "-b", "main", cwd=clone)
    (clone / "docs").mkdir()
    (clone / "docs" / "overview.md").write_text("# overview\n\ntext.\n", encoding="utf-8")
    (clone / "docs" / "crlf.md").write_bytes(b"# crlf\r\n\r\nwindows line endings\r\n")
    (clone / "docs" / "unicode.md").write_text("# 中文\n\n换行与中文混排。\n", encoding="utf-8")
    _git("add", "-A", cwd=clone)
    _git("commit", "-m", "init", cwd=clone)
    # 模拟已 fetch 的远端 ref(membership 自身会 fetch;指纹读取基于对象库)
    _git("update-ref", "refs/remotes/origin/main", "HEAD", cwd=clone)
    return _connector(tmp_path, ["main"]), clone


def test_fingerprint_matches_ingestion_hash_byte_for_byte(tmp_path):
    """哈希同源性:指纹 == RawDocument.content_hash(含 CRLF/中文变换面)。"""
    conn, clone = _build_clone(tmp_path)
    fp = conn.membership_content_fingerprints(
        [
            "wiki-documents-local/main/docs/overview.md",
            "wiki-documents-local/main/docs/crlf.md",
            "wiki-documents-local/main/docs/unicode.md",
        ]
    )
    for rel in ("overview.md", "crlf.md", "unicode.md"):
        sid = f"wiki-documents-local/main/docs/{rel}"
        expected = _fetch_hash(clone / "docs" / rel)
        assert fp[sid] == expected, f"{rel} 指纹必须与灌入哈希逐字节一致"

    # 与 _make_document 产出的 RawDocument.content_hash 直接对齐
    doc = conn._make_document("docs/overview.md", (clone / "docs" / "overview.md").read_text(encoding="utf-8"), "main")
    assert fp["wiki-documents-local/main/docs/overview.md"] == doc.content_hash


def test_fingerprint_detects_authoritative_change(tmp_path):
    """远端 ref 推进(内容变更)后指纹漂移;工作树状态无关(对象库读取)。"""
    conn, clone = _build_clone(tmp_path)
    sid = "wiki-documents-local/main/docs/overview.md"
    before = conn.membership_content_fingerprints([sid])[sid]

    # 上游变更 + 远端 ref 前进(工作树可以仍停留在旧树 —— 对象库读取不受影响)
    (clone / "docs" / "overview.md").write_text("# overview v2\n\nchanged.\n", encoding="utf-8")
    _git("add", "-A", cwd=clone)
    _git("commit", "-m", "v2", cwd=clone)
    _git("update-ref", "refs/remotes/origin/main", "HEAD", cwd=clone)

    after = conn.membership_content_fingerprints([sid])[sid]
    assert after != before, "权威内容变更必须反映为指纹漂移(立即失效压制的依据)"


def test_fingerprint_absent_for_unknown_or_out_of_scope_identities(tmp_path):
    conn, _clone = _build_clone(tmp_path)
    fp = conn.membership_content_fingerprints(
        [
            "wiki-documents-local/main/docs/does-not-exist.md",  # 远端无此文件
            "other-source/main/docs/overview.md",  # 非本法源
            "wiki-documents-local/dev/docs/overview.md",  # 分支不在 scope
            "malformed",
        ]
    )
    assert fp == {}, "不可判定身份不得出现在返回值(调用方窗口兜底)"
