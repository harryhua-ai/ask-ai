"""release_migration_plan.py 契约测试(v1.4.0 存量库迁移矫正 · 迁移所有权模型)。

覆盖:
- 冻结树清单优先:树内 deploy/prod/migrations.json 存在 → 只用清单(桥不参与);
  空列表 = 无迁移;
- 历史桥:仅精确 tag 命中;封闭集合;条目必须存在于冻结树;
- fail-closed:清单非法 JSON / 缺 migrations / 条目非列表 / 绝对路径 / 路径穿越 /
  越出 scripts/ / 冻结树内不存在 / git 证据源不可用 → 一律拒绝(退出码 1),
  绝不「缺证据就当无迁移」;
- 用法错误(非法 tag/SHA)→ 退出码 2;
- 真实仓库冒烟:v1.4.0 冻结树(无清单)→ 桥命中 launcher_presentation 迁移;
  候选树(有清单)→ 清单命中。

全部离线确定性;冻结树经真实临时 git 仓库构造。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
PLAN_SCRIPT = REPO / "scripts" / "release_migration_plan.py"

LAUNCHER_MIGRATION = "scripts/migrate_add_site_launcher_presentation.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


plan_mod = _load_module(PLAN_SCRIPT, "release_migration_plan")

SHA = "a" * 40
MANIFEST = plan_mod.MANIFEST_PATH


# ---------------------------------------------------------------- 临时冻结树


def _init_repo_with_tree(tmp_path: Path, files: dict[str, str], tag: str = "v9.9.9"):
    """构造一个打了 tag 的最小 git 仓库;files 会提交进该 tag。返回 (repo, sha)。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@m",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@m",
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
    }
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    for path, content in files.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "tree"],
        check=True,
        env=env,
    )
    subprocess.run(["git", "-C", str(repo), "tag", tag], check=True, env=env)
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"{tag}^{{commit}}"],
        capture_output=True, text=True, check=True, env=env,
    ).stdout.strip()
    return repo, sha


def _resolve(repo: Path, sha: str, tag: str = "v9.9.9"):
    return plan_mod.resolve_plan(tag, sha, str(repo))


# ---------------------------------------------------------------- 清单(权威)


class TestManifestWins:
    def test_manifest_entries_returned_in_order(self, tmp_path):
        repo, sha = _init_repo_with_tree(
            tmp_path,
            {
                MANIFEST: json.dumps(
                    {"migrations": ["scripts/migrate_b.py", "scripts/migrate_a.py"]}
                ),
                "scripts/migrate_a.py": "",
                "scripts/migrate_b.py": "",
            },
        )
        assert _resolve(repo, sha) == ["scripts/migrate_b.py", "scripts/migrate_a.py"]

    def test_manifest_with_empty_list_means_no_migration(self, tmp_path, capsys):
        repo, sha = _init_repo_with_tree(tmp_path, {MANIFEST: json.dumps({"migrations": []})})
        assert _resolve(repo, sha) == []
        assert "PLAN SOURCE: manifest" in capsys.readouterr().err

    def test_manifest_presence_disables_bridge(self, tmp_path):
        """树内有清单时桥绝不参与(清单是唯一权威;桥只属于无清单的历史发布)。"""
        repo, sha = _init_repo_with_tree(
            tmp_path,
            {MANIFEST: json.dumps({"migrations": []})},
            tag="v1.4.0",
        )
        assert _resolve(repo, sha, tag="v1.4.0") == []


# ---------------------------------------------------------------- 历史桥


class TestHistoricalBridge:
    def test_bridge_hits_exact_tag_when_manifest_absent(self, tmp_path):
        """桥条目必须同时在冻结树内(执行前提 = 镜像内含该脚本,树/镜像同源)。"""
        repo, sha = _init_repo_with_tree(
            tmp_path, {LAUNCHER_MIGRATION: ""}, tag="v1.4.0"
        )
        assert _resolve(repo, sha, tag="v1.4.0") == [LAUNCHER_MIGRATION]

    def test_bridge_is_closed_set_no_entry_means_none(self, tmp_path, capsys):
        repo, sha = _init_repo_with_tree(tmp_path, {})
        assert _resolve(repo, sha, tag="v1.5.0") == []
        out = capsys.readouterr()
        assert "PLAN SOURCE: none" in out.err
        assert "契约" in out.err  # 显式提醒清单契约

    def test_bridge_requires_fuzzy_tag_miss(self, tmp_path):
        """桥按精确 tag 匹配:v1.4 / v1.4.0-rc1 等变体不命中。"""
        repo, sha = _init_repo_with_tree(tmp_path, {})
        assert plan_mod.BRIDGE_MIGRATIONS.get("v1.4") is None
        assert plan_mod.BRIDGE_MIGRATIONS.get("v1.4.0-rc1") is None
        assert list(plan_mod.BRIDGE_MIGRATIONS) == ["v1.4.0"]


# ---------------------------------------------------------------- fail-closed


class TestFailClosed:
    def _repo_with_manifest(self, tmp_path, raw):
        return _init_repo_with_tree(tmp_path, {MANIFEST: raw})

    def test_invalid_json_rejected(self, tmp_path):
        repo, sha = self._repo_with_manifest(tmp_path, "{not json")
        with pytest.raises(SystemExit) as ei:
            _resolve(repo, sha)
        assert ei.value.code == 1

    def test_manifest_without_migrations_key_rejected(self, tmp_path):
        repo, sha = self._repo_with_manifest(tmp_path, json.dumps({"steps": []}))
        with pytest.raises(SystemExit) as ei:
            _resolve(repo, sha)
        assert ei.value.code == 1

    def test_non_list_migrations_rejected(self, tmp_path):
        repo, sha = self._repo_with_manifest(
            tmp_path, json.dumps({"migrations": "scripts/migrate_a.py"})
        )
        with pytest.raises(SystemExit) as ei:
            _resolve(repo, sha)
        assert ei.value.code == 1

    @pytest.mark.parametrize(
        "entry",
        [
            "/etc/passwd.py",                  # 绝对路径
            "scripts/../evil.py",              # 路径穿越
            "scripts/migrate_x.sh",            # 非 .py
            "backend/migrate_x.py",            # 越出 scripts/
            "scripts/sub dir/mig.py",          # 非法字符(注入面)
            "scripts/$MIG.py",                 # 非法字符(注入面)
        ],
    )
    def test_illegal_entries_rejected(self, tmp_path, entry):
        repo, sha = self._repo_with_manifest(
            tmp_path, json.dumps({"migrations": [entry]})
        )
        with pytest.raises(SystemExit) as ei:
            _resolve(repo, sha)
        assert ei.value.code == 1

    def test_entry_missing_from_frozen_tree_rejected(self, tmp_path):
        """清单与代码必须同树同 tag:引用树内不存在的脚本 → 拒绝。"""
        repo, sha = self._repo_with_manifest(
            tmp_path, json.dumps({"migrations": ["scripts/migrate_ghost.py"]})
        )
        with pytest.raises(SystemExit) as ei:
            _resolve(repo, sha)
        assert ei.value.code == 1

    def test_bridge_entry_missing_from_tree_rejected(self, tmp_path):
        """桥条目也必须在冻结树内(镜像内含该脚本是执行前提)。"""
        repo, sha = _init_repo_with_tree(tmp_path, {}, tag="v1.4.0")
        with pytest.raises(SystemExit) as ei:
            _resolve(repo, sha, tag="v1.4.0")
        assert ei.value.code == 1

    def test_git_unavailable_fails_closed_not_treated_as_absent(self, tmp_path):
        """git 证据源不可用(非 git 目录)→ 拒绝,绝不当作「无清单」。"""
        bogus = tmp_path / "not-a-repo"
        bogus.mkdir()
        with pytest.raises(SystemExit) as ei:
            _resolve(bogus, SHA, tag="v1.4.0")
        assert ei.value.code == 1


# ---------------------------------------------------------------- CLI 用法


class TestCli:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(PLAN_SCRIPT), *args],
            capture_output=True, text=True, check=False, cwd=str(REPO),
        )

    def test_bad_tag_is_usage_error(self):
        assert self._run("--tag", "latest", "--sha", SHA, "--repo-root", str(REPO)).returncode == 2

    def test_bad_sha_is_usage_error(self):
        assert self._run("--tag", "v1.4.0", "--sha", "abc", "--repo-root", str(REPO)).returncode == 2

    def test_none_printed_on_stdout(self, tmp_path):
        repo, sha = _init_repo_with_tree(tmp_path, {})
        proc = self._run("--tag", "v1.5.0", "--sha", sha, "--repo-root", str(repo))
        assert proc.returncode == 0
        assert proc.stdout.strip() == "NONE"


# ---------------------------------------------------------------- 真实冻结树冒烟


class TestRealRepoSmoke:
    def test_v140_frozen_tree_resolves_via_bridge(self):
        """v1.4.0 冻结树(清单机制诞生前)→ 桥命中 launcher_presentation 迁移。"""
        sha = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "--verify", "--quiet", "v1.4.0^{commit}"],
            capture_output=True, text=True, check=False,
        ).stdout.strip()
        if not sha:
            pytest.skip("本检出无 v1.4.0 tag(CI 浅检出);冻结树桥路径由临时仓库测试覆盖")
        assert plan_mod.resolve_plan("v1.4.0", sha, str(REPO)) == [LAUNCHER_MIGRATION]

    def test_candidate_tree_resolves_via_manifest(self):
        """候选树(含清单)→ 清单命中,且条目在树内存在。"""
        probe = subprocess.run(
            ["git", "-C", str(REPO), "cat-file", "-e", f"HEAD:{MANIFEST}"],
            capture_output=True, text=True, check=False,
        )
        if probe.returncode != 0:
            pytest.skip("HEAD 树尚无清单(候选未提交);清单路径由临时仓库测试覆盖")
        sha = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        plan = plan_mod.resolve_plan("v1.5.0", sha, str(REPO))
        assert LAUNCHER_MIGRATION in plan
