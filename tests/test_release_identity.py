"""Release identity 单元测试(Issue #10 版本与发布治理)。

冻结契约:
- 权威链 = git tag → CI 生成 RELEASE.json → 镜像内 COPY → 进程启动一次性加载;
- fail-closed:APP_MODE=prod 下 manifest 缺失/非法 → 启动失败(镜像不得假冒正式版本);
- 任何模式下,**存在但非法**的 manifest 一律 raise(坏文件 ≠ 缺失);
- 非 prod 且缺失 → 显式 dev 兜底(0.0.0-dev,source=fallback),绝不假冒正式版本;
- 无 DB 版本权威、无可变 env 版本权威。
"""

import json
import os
from pathlib import Path

import pytest

from backend.release import (
    ReleaseIdentityError,
    get_release_identity,
    load_release_identity,
    reset_release_identity_cache,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    reset_release_identity_cache()
    yield
    reset_release_identity_cache()


def _write_manifest(path: Path, **overrides) -> Path:
    manifest = {
        "version": "1.0.0",
        "git_sha": "a" * 40,
        "built_at": "2026-09-03T12:00:00Z",
        "image": "ghcr.io/harryhua-ai/ask-ai:v1.0.0",
        "ci_run_id": "12345",
    }
    manifest.update(overrides)
    for key in [k for k, v in manifest.items() if v is None]:
        del manifest[key]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


class TestManifestParsing:
    def test_valid_manifest_roundtrip(self, tmp_path: Path):
        p = _write_manifest(tmp_path / "RELEASE.json")
        rid = load_release_identity(p, app_mode="production")
        assert rid.version == "1.0.0"
        assert rid.git_sha == "a" * 40
        assert rid.built_at == "2026-09-03T12:00:00Z"
        assert rid.image == "ghcr.io/harryhua-ai/ask-ai:v1.0.0"
        assert rid.ci_run_id == "12345"
        assert rid.app_mode == "production"
        assert rid.source == "manifest"

    def test_tag_prefixed_version_normalized_to_semver(self, tmp_path: Path):
        """build tag 带 v 前缀时归一为无前缀 SemVer(1.0.0,不是 v1.0.0)。"""
        p = _write_manifest(tmp_path / "RELEASE.json", version="v1.2.3")
        assert load_release_identity(p, app_mode="production").version == "1.2.3"

    def test_semver_build_metadata_accepted(self, tmp_path: Path):
        p = _write_manifest(tmp_path / "RELEASE.json", version="0.0.0+main.04c75e0")
        assert load_release_identity(p, app_mode="development").version == "0.0.0+main.04c75e0"

    def test_missing_required_field_raises_even_in_dev(self, tmp_path: Path):
        """存在但非法 → 任何模式都 fail-closed(坏文件 ≠ 缺失)。"""
        p = _write_manifest(tmp_path / "RELEASE.json")
        p.write_text(json.dumps({"version": "1.0.0", "git_sha": "a" * 40}))
        with pytest.raises(ReleaseIdentityError, match="built_at"):
            load_release_identity(p, app_mode="development")

    def test_malformed_version_raises(self, tmp_path: Path):
        p = _write_manifest(tmp_path / "RELEASE.json", version="1.0")
        with pytest.raises(ReleaseIdentityError, match="version"):
            load_release_identity(p, app_mode="production")

    def test_malformed_version_word_raises(self, tmp_path: Path):
        p = _write_manifest(tmp_path / "RELEASE.json", version="latest")
        with pytest.raises(ReleaseIdentityError):
            load_release_identity(p, app_mode="production")

    def test_malformed_sha_raises(self, tmp_path: Path):
        p = _write_manifest(tmp_path / "RELEASE.json", git_sha="not-a-sha")
        with pytest.raises(ReleaseIdentityError, match="git_sha"):
            load_release_identity(p, app_mode="production")

    def test_empty_field_raises(self, tmp_path: Path):
        p = _write_manifest(tmp_path / "RELEASE.json", image="")
        with pytest.raises(ReleaseIdentityError, match="image"):
            load_release_identity(p, app_mode="production")

    def test_corrupt_json_raises_even_in_dev(self, tmp_path: Path):
        p = tmp_path / "RELEASE.json"
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(ReleaseIdentityError):
            load_release_identity(p, app_mode="development")


class TestFailClosed:
    def test_prod_missing_manifest_raises(self, tmp_path: Path):
        with pytest.raises(ReleaseIdentityError, match="fail-closed"):
            load_release_identity(tmp_path / "RELEASE.json", app_mode="production")

    def test_dev_missing_manifest_falls_back(self, tmp_path: Path):
        rid = load_release_identity(tmp_path / "RELEASE.json", app_mode="development")
        assert rid.version == "0.0.0-dev"
        assert rid.source == "fallback"
        assert rid.app_mode == "development"
        # 兜底 sha 允许 unknown,但绝不伪造正式版本号
        assert len(rid.git_sha) >= 7
        assert rid.version != "1.0.0"


class TestProcessSingleton:
    def test_identity_loaded_once_and_immutable(self, tmp_path: Path, monkeypatch):
        p = _write_manifest(tmp_path / "RELEASE.json")
        monkeypatch.setenv("APP_MODE", "prod")
        monkeypatch.setattr("backend.release._RELEASE_FILE", p)
        first = get_release_identity()
        # 文件被删/改不影响本进程已加载的不可变身份
        p.unlink()
        assert get_release_identity() is first
        assert get_release_identity().version == "1.0.0"

    def test_env_app_mode_prod_is_strict(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("APP_MODE", "prod")
        monkeypatch.setattr("backend.release._RELEASE_FILE", tmp_path / "RELEASE.json")
        with pytest.raises(ReleaseIdentityError):
            get_release_identity()

    def test_env_app_mode_dev_falls_back(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("APP_MODE", raising=False)
        monkeypatch.setattr("backend.release._RELEASE_FILE", tmp_path / "RELEASE.json")
        rid = get_release_identity()
        assert rid.source == "fallback"

    def test_real_repo_dev_fallback_usable(self):
        """本仓开发态:无 RELEASE.json 时健康兜底可加载(不抛错)。"""
        monkey_env = os.environ.copy()
        assert monkey_env.get("APP_MODE") != "prod" or Path("RELEASE.json").exists()
        rid = get_release_identity()
        assert rid.version
        assert rid.git_sha
