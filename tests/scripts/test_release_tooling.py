"""#10 发布工具链契约测试(构建脚本 / CI workflow / 部署脚本)。

覆盖验收 E(构建契约)与 F(部署脚本)的仓库内可测部分:
- generate_release_manifest.sh:合法输入产出含 tag/SHA 的 manifest;非法输入退出非零;
- update.sh:显式 tag 接受、缺参拒绝、latest 拒绝、三应用服务一致更新、
  回滚走同一命令契约(静态契约锁 + bash 语法校验);
- build-image.yml:构建期生成 RELEASE.json + 镜像内断言步骤存在;
  semver tag 触发;无自动 GitHub Release 发布步骤;
- prod compose:镜像 tag 必填(拒绝回退 latest)。

docker/网络相关行为不在单测内执行(见任务边界;运行时验证在 CI/部署门)。
"""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent.parent
GENERATOR = REPO / "scripts" / "generate_release_manifest.sh"
UPDATE_SH = REPO / "deploy" / "prod" / "update.sh"
WORKFLOW = REPO / ".github" / "workflows" / "build-image.yml"
PROD_COMPOSE = REPO / "deploy" / "prod" / "docker-compose.yml"


def _run_gen(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(GENERATOR), *args], capture_output=True, text=True, check=False
    )


class TestGenerateManifest:
    def test_valid_input_writes_expected_manifest(self, tmp_path: Path):
        out = tmp_path / "RELEASE.json"
        proc = _run_gen("v1.2.3", "A" * 40, "ghcr.io/harryhua-ai/ask-ai:v1.2.3", "42", str(out))
        assert proc.returncode == 0, proc.stderr
        data = json.loads(out.read_text(encoding="utf-8"))
        # tag 归一为无前缀 SemVer;sha 归一为小写
        assert data["version"] == "1.2.3"
        assert data["git_sha"] == "a" * 40
        assert data["image"] == "ghcr.io/harryhua-ai/ask-ai:v1.2.3"
        assert data["ci_run_id"] == "42"
        # built_at = 权威构建钟生成(非空、UTC 秒级格式)
        assert "T" in data["built_at"] and data["built_at"].endswith("Z")

    def test_default_output_and_image(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        proc = _run_gen("0.0.0+main.04c75e0", "04c75e0" + "b" * 33)
        assert proc.returncode == 0, proc.stderr
        data = json.loads((tmp_path / "RELEASE.json").read_text(encoding="utf-8"))
        assert data["image"] == "ghcr.io/harryhua-ai/ask-ai:dev"
        assert data["version"] == "0.0.0+main.04c75e0"

    @pytest.mark.parametrize("bad_args", [
        ("1.0", "a" * 40),                # 非 SemVer
        ("latest", "a" * 40),             # latest 不是版本
        ("v1.0.0", "nothex"),             # 非法 sha
        ("v1.0.0", ""),                   # 空 sha
    ])
    def test_invalid_input_rejected(self, tmp_path: Path, bad_args):
        out = tmp_path / "RELEASE.json"
        proc = _run_gen(*bad_args, str(out))
        assert proc.returncode != 0
        assert not out.exists()

    def test_missing_args_rejected(self):
        proc = subprocess.run(["bash", str(GENERATOR)], capture_output=True, text=True)
        assert proc.returncode != 0


class TestUpdateShContract:
    def test_bash_syntax_valid(self):
        proc = subprocess.run(["bash", "-n", str(UPDATE_SH)], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr

    def test_missing_tag_fails(self):
        proc = subprocess.run(["bash", str(UPDATE_SH)], capture_output=True, text=True)
        assert proc.returncode != 0
        assert "tag" in (proc.stderr + proc.stdout).lower()

    def test_latest_rejected(self):
        proc = subprocess.run(["bash", str(UPDATE_SH), "latest"], capture_output=True, text=True)
        assert proc.returncode != 0
        assert "latest" in (proc.stderr + proc.stdout).lower()

    def test_all_three_app_services_updated(self):
        """三应用服务(backend/sync-cron/sync-executor)必须同批更新。"""
        text = UPDATE_SH.read_text(encoding="utf-8")
        for svc in ("backend", "sync-cron", "sync-executor"):
            assert svc in text, f"update.sh 未更新 {svc}"
        assert "up -d" in text

    def test_in_image_manifest_asserted_before_switch(self):
        """切换服务前必须校验镜像内 RELEASE.json 与请求 tag 一致。"""
        text = UPDATE_SH.read_text(encoding="utf-8")
        assert "RELEASE.json" in text
        assert "docker create" in text or "docker pull" in text
        # 版本比对顺序:先校验后 up -d
        assert text.index("RELEASE.json") < text.index("up -d")

    def test_health_version_cross_check(self):
        """部署后必须用 /health 核验运行版本与请求 tag 一致(回滚同契约)。"""
        text = UPDATE_SH.read_text(encoding="utf-8")
        assert "/health" in text
        assert "version" in text

    def test_rollback_same_command_documented(self):
        text = UPDATE_SH.read_text(encoding="utf-8")
        assert "回滚" in text  # 旧 tag 同命令回滚须文档化


class TestWorkflowContract:
    @pytest.fixture(scope="class")
    def workflow(self):
        data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        return data

    def test_semver_tag_trigger_present(self, workflow):
        # PyYAML(YAML 1.1)把 `on:` 解析成布尔 True 键,两种形态都要兼容
        push = workflow.get("on", workflow.get(True))["push"]
        assert push["tags"] == ["v*.*.*"]

    def test_release_manifest_generated_in_build(self, workflow):
        """构建期必须生成 RELEASE.json 并传入镜像上下文。"""
        steps_text = str(workflow["jobs"]["build-and-push"]["steps"])
        assert "RELEASE.json" in steps_text
        assert "generate_release_manifest.sh" in steps_text

    def test_in_image_manifest_asserted(self, workflow):
        """push 后必须对镜像内 RELEASE.json 做版本/SHA 断言。"""
        steps_text = str(workflow["jobs"]["build-and-push"]["steps"])
        assert "assert" in steps_text.lower()
        assert "git_sha" in steps_text

    def test_no_auto_github_release_publication(self, workflow):
        """CI 不得自动创建 GitHub Release(显式发布操作,用 release-notes/vX.Y.Z.md)。"""
        text = WORKFLOW.read_text(encoding="utf-8")
        assert "softprops/action-gh-release" not in text
        assert "gh release create" not in text
        assert "release-notes/" not in text  # 发布素材不进 CI 自动化

    def test_oci_labels_retained(self, workflow):
        """OCI labels(metadata-action)保留作交叉核对证据。"""
        steps = workflow["jobs"]["build-and-push"]["steps"]
        meta = [s for s in steps if s.get("name") == "Extract metadata (tags, labels)"]
        assert meta and "labels" in str(meta)


class TestProdComposeContract:
    def test_image_tag_required_not_latest(self):
        """生产 compose 镜像 tag 必填——缺 ASKAI_IMAGE_TAG 时 compose 报错,禁止回退 latest。"""
        text = PROD_COMPOSE.read_text(encoding="utf-8")
        assert "ASKAI_IMAGE_TAG:-latest" not in text
        assert "ASKAI_IMAGE_TAG:?" in text

    def test_three_app_services_share_anchor_image(self):
        data = yaml.safe_load(PROD_COMPOSE.read_text(encoding="utf-8"))
        base = data["x-backend-base"]["image"]
        for svc in ("backend", "sync", "sync-executor", "sync-cron"):
            assert data["services"][svc]["image"] == base, svc
