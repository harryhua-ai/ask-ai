"""生产部署编排契约测试(#10 · deploy-production.yml + recorder 分阶段)。

覆盖(任务测试契约逐项):
- workflow 契约:仅 workflow_dispatch;environment=production;permissions
  最小(contents:read + deployments:write,无 packages);concurrency 组
  production-deployment 且 cancel-in-progress=false;inputs 经 env 数据边界
  (❌ 不内插进 run 源码);严格 SSH 主机键(❌ 不出现 no/accept-new);
  flock + 仅调既有 update.sh(❌ 不重实现 docker 逻辑);Guard 在任何远端
  变更之前;成功收尾在身份双断言之后;失败收尾存在;无 main HEAD 身份;
- 身份冻结行为(bash 级实证):合法 vX.Y.Z → 解析 40 位 SHA;latest/main/
  分支名/SHA/缺 v 全拒;
- recorder 分阶段:create=in_progress 在途记录;success/failure/error 追加
  到既有记录(按 sha 解析最新);无记录可追加 → 拒绝;历史原子模式
  (break-glass)载荷与 create 阶段同一证据模型;
- verify_runtime_identity:version/git_sha 双断言(任一不匹配 → 拒绝,
  success 无代码路径)。

全部离线确定性;GitHub 交互经 monkeypatch;身份冻结步用真实临时 git 仓库。
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent.parent
RECORDER = REPO / "scripts" / "record_production_deployment.py"
VERIFIER = REPO / "scripts" / "verify_runtime_identity.py"
DEPLOY_WORKFLOW = REPO / ".github" / "workflows" / "deploy-production.yml"
GUARD_WORKFLOW = REPO / ".github" / "workflows" / "release-integrity.yml"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


recorder = _load_module(RECORDER, "record_production_deployment_orchestration")

SHA = "a" * 40
OTHER_SHA = "b" * 40
TAG = "v1.4.0"


# ---------------------------------------------------------------- workflow 契约


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(DEPLOY_WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def steps(workflow):
    return {s.get("id"): s for s in workflow["jobs"]["deploy"]["steps"]}


def _run_texts(workflow):
    return [s.get("run", "") for s in workflow["jobs"]["deploy"]["steps"] if "run" in s]


class TestWorkflowContract:
    def test_dispatch_only(self, workflow):
        triggers = workflow.get(True, workflow.get("on"))
        assert set(triggers.keys()) == {"workflow_dispatch"}
        assert set(triggers["workflow_dispatch"]["inputs"].keys()) == {"tag"}
        assert triggers["workflow_dispatch"]["inputs"]["tag"]["required"] is True

    def test_production_environment(self, workflow):
        assert workflow["jobs"]["deploy"]["environment"] == "production"

    def test_minimum_permissions(self, workflow):
        assert workflow["permissions"] == {"contents": "read", "deployments": "write"}

    def test_concurrency_serializes_never_cancels(self, workflow):
        cc = workflow["concurrency"]
        assert cc["group"] == "production-deployment"
        assert cc["cancel-in-progress"] is False

    def test_inputs_cross_env_boundary_only(self, workflow):
        for run in _run_texts(workflow):
            assert "${{ inputs." not in run
            assert "${{ github." not in run
            assert "${{ secrets." not in run
            assert "${{ vars." not in run
            assert "set -euo pipefail" in run

    def test_input_tag_mapped_via_env(self, workflow):
        identity = [s for s in workflow["jobs"]["deploy"]["steps"] if s.get("id") == "identity"][0]
        assert identity["env"]["INPUT_TAG"] == "${{ inputs.tag }}"

    def test_strict_ssh_host_key_policy(self, workflow):
        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        assert "StrictHostKeyChecking=yes" in text
        assert "StrictHostKeyChecking=no" not in text
        assert "accept-new" not in text
        assert "BatchMode=yes" in text
        assert "UserKnownHostsFile=" in text
        # known_hosts 缺失/与主机不匹配 → fail-closed(绝不置空继续)
        assert 'grep -q "$SSH_HOST" "$KH_FILE"' in text

    def test_only_existing_primitive_no_docker_reimplementation(self, workflow):
        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        assert "deploy/prod/update.sh" in text
        for forbidden in ("docker compose", "docker pull", "docker build", "ghcr.io/harryhua-ai/ask-ai:"):
            assert forbidden not in text, forbidden
        assert "flock -w 0 /tmp/askai-deploy.lock" in text

    def test_tag_validation_before_ssh(self, workflow):
        identity = [s for s in workflow["jobs"]["deploy"]["steps"] if s.get("id") == "identity"][0]
        run = identity["run"]
        assert "^v(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$" in run
        assert '"$TAG" = "latest"' in run
        # 部署步(SSH)使用身份步输出,而非原始输入
        deploy = [s for s in workflow["jobs"]["deploy"]["steps"] if s.get("id") == "deploy"][0]
        assert deploy["env"]["DEPLOY_TAG"] == "${{ steps.identity.outputs.tag }}"

    def test_guard_before_any_mutation(self, workflow):
        ids = [s.get("id") for s in workflow["jobs"]["deploy"]["steps"]]
        guard, record_create, deploy = ids.index("guard"), ids.index("record_create"), ids.index("deploy")
        assert guard < record_create < deploy
        guard_step = [s for s in workflow["jobs"]["deploy"]["steps"] if s.get("id") == "guard"][0]
        assert "--mode release-publish" in guard_step["run"]
        assert "--expected-sha" in guard_step["run"]

    def test_success_only_after_identity_verification(self, workflow):
        ids = [s.get("id") for s in workflow["jobs"]["deploy"]["steps"]]
        assert ids.index("verify_identity") < ids.index("record_success")
        record_success = [s for s in workflow["jobs"]["deploy"]["steps"] if s.get("id") == "record_success"][0]
        assert record_success["if"] == "success()"
        verify = [s for s in workflow["jobs"]["deploy"]["steps"] if s.get("id") == "verify_identity"][0]
        assert "verify_runtime_identity.py" in verify["run"]
        # 双断言输入(期望 version + 期望 SHA)来自冻结身份,经 env 数据边界
        assert verify["env"]["EXPECT_SHA"] == "${{ steps.identity.outputs.sha }}"
        assert verify["env"]["EXPECT_VERSION"] == "${{ steps.identity.outputs.version }}"

    def test_failure_never_leaves_success(self, workflow):
        finalize = [s for s in workflow["jobs"]["deploy"]["steps"] if s.get("id") == "record_failure"][0]
        cond = finalize["if"].replace(" ", "").replace("\n", "")
        assert "failure()" in cond
        assert "steps.record_create.outputs.created=='true'" in cond
        assert "steps.record_success.outcome!='failure'" in cond
        assert "--phase failure" in finalize["run"]
        assert "PRODUCTION STATE RECONCILIATION REQUIRED" in finalize["run"]

    def test_no_main_head_identity_and_no_autorollback(self):
        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        assert "github.sha" not in text  # 身份只来自输入 tag 的 git 解析
        assert "rollback" not in text.lower()  # 无自动回滚代码路径

    def test_guard_workflow_not_modified_by_orchestration(self):
        """release-integrity.yml 保持原样(编排经 workflow_call 语义复用,不改文件)。"""
        text = GUARD_WORKFLOW.read_text(encoding="utf-8")
        assert "deploy-production" not in text
        assert "PROD_DEPLOY" not in text


# ---------------------------------------------------------------- 身份冻结(bash 级实证)


def _init_tagged_repo(tmp_path: Path, tag: str = "v1.2.3") -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
    }
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "init"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "tag", tag], check=True, env=env)
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"{tag}^{{commit}}"],
        capture_output=True, text=True, check=True, env=env,
    ).stdout.strip()
    return repo, sha


def _run_identity_step(tmp_path: Path, repo: Path, tag: str):
    workflow = yaml.safe_load(DEPLOY_WORKFLOW.read_text(encoding="utf-8"))
    identity = [s for s in workflow["jobs"]["deploy"]["steps"] if s.get("id") == "identity"][0]
    out_file = tmp_path / "github_output"
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "INPUT_TAG": tag,
        "GITHUB_OUTPUT": str(out_file),
    }
    proc = subprocess.run(
        ["bash", "-c", identity["run"]], cwd=str(repo), env=env,
        capture_output=True, text=True, check=False,
    )
    outputs = {}
    if out_file.exists():
        for line in out_file.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                outputs[k] = v
    return proc, outputs


class TestIdentityFreezing:
    def test_valid_tag_resolves_and_freezes(self, tmp_path: Path):
        repo, sha = _init_tagged_repo(tmp_path)
        proc, outputs = _run_identity_step(tmp_path, repo, "v1.2.3")
        assert proc.returncode == 0, proc.stderr
        assert outputs == {"tag": "v1.2.3", "sha": sha, "version": "1.2.3"}

    @pytest.mark.parametrize("bad", ["latest", "main", "v1", "v1.2", "1.2.3", "v1.2.3-rc.1", "abc123", "v01.2.3"])
    def test_invalid_inputs_rejected_before_anything(self, tmp_path: Path, bad: str):
        repo, _ = _init_tagged_repo(tmp_path)
        proc, outputs = _run_identity_step(tmp_path, repo, bad)
        assert proc.returncode != 0
        assert outputs == {}

    def test_unknown_tag_rejected_even_if_format_valid(self, tmp_path: Path):
        repo, _ = _init_tagged_repo(tmp_path)
        proc, outputs = _run_identity_step(tmp_path, repo, "v9.9.9")
        assert proc.returncode != 0
        assert outputs == {}


# ---------------------------------------------------------------- recorder 分阶段


class TestRecorderPhases:
    def _token(self, monkeypatch):
        monkeypatch.setenv("GH_TOKEN", "t0k3n")

    def test_create_phase_posts_in_progress(self, monkeypatch):
        self._token(monkeypatch)
        calls = []

        def fake_request(repo, path, token, body):
            calls.append((repo, path, json.loads(json.dumps(body))))
            return {"id": 42, "html_url": "https://github.com/x"}

        monkeypatch.setattr(recorder, "_request", fake_request)
        rc = recorder.main(["--tag", TAG, "--sha", SHA, "--phase", "create"])
        assert rc == 0
        assert len(calls) == 2
        assert calls[0][1] == "/deployments"
        assert calls[0][2]["ref"] == SHA
        assert calls[0][2]["payload"]["git_sha"] == SHA
        assert calls[1][1] == "/deployments/42/statuses"
        assert calls[1][2]["state"] == "in_progress"  # 守卫侧 ≠ success

    def _patch_resolve(self, monkeypatch, deployment_id=42):
        monkeypatch.setattr(
            recorder, "_get_request",
            lambda repo, path, token: [{"id": deployment_id, "sha": SHA}],
        )

    @pytest.mark.parametrize("phase,state", [("success", "success"), ("failure", "failure"), ("error", "error")])
    def test_finalize_phases_append_status_to_existing_record(self, monkeypatch, phase, state):
        self._token(monkeypatch)
        self._patch_resolve(monkeypatch)
        calls = []

        def fake_request(repo, path, token, body):
            calls.append((path, json.loads(json.dumps(body))))
            return {"state": state}

        monkeypatch.setattr(recorder, "_request", fake_request)
        assert recorder.main(["--tag", TAG, "--sha", SHA, "--phase", phase]) == 0
        assert calls == [("/deployments/42/statuses", {"state": state, "environment": "production", "description": f"{state} {TAG} @ {SHA[:12]}"})]

    def test_finalize_without_existing_record_rejected(self, monkeypatch):
        """找不到待收尾记录 → 拒绝(不得凭空新建成功)。"""
        self._token(monkeypatch)
        monkeypatch.setattr(recorder, "_get_request", lambda repo, path, token: [])
        assert recorder.main(["--tag", TAG, "--sha", SHA, "--phase", "success"]) == 2

    def test_break_glass_atomic_mode_unchanged(self, monkeypatch):
        """省略 --phase = 历史 break-glass 原子模式:create + success 一次完成。"""
        self._token(monkeypatch)
        calls = []

        def fake_request(repo, path, token, body):
            calls.append((path, json.loads(json.dumps(body))))
            return {"id": 7, "html_url": ""}

        monkeypatch.setattr(recorder, "_request", fake_request)
        assert recorder.main(["--tag", TAG, "--sha", SHA]) == 0
        assert [c[0] for c in calls] == ["/deployments", "/deployments/7/statuses"]
        assert calls[0][1]["payload"]["tag"] == TAG
        assert calls[1][1]["state"] == "success"

    def test_create_phase_same_evidence_model_as_break_glass(self, monkeypatch):
        """编排 create 与 break-glass 原子 create 写同一 Deployment 证据模型。"""
        self._token(monkeypatch)
        bodies = []

        def fake_request(repo, path, token, body):
            bodies.append(json.loads(json.dumps(body)))
            return {"id": 1, "html_url": ""}

        monkeypatch.setattr(recorder, "_request", fake_request)
        recorder.main(["--tag", TAG, "--sha", SHA, "--phase", "create"])
        create_phase = bodies[0]
        bodies.clear()
        recorder.main(["--tag", TAG, "--sha", SHA])
        legacy = bodies[0]
        for key in ("ref", "environment", "auto_merge", "required_contexts"):
            assert create_phase[key] == legacy[key]
        assert create_phase["payload"]["tag"] == legacy["payload"]["tag"] == TAG
        assert create_phase["payload"]["git_sha"] == legacy["payload"]["git_sha"] == SHA


# ---------------------------------------------------------------- 运行时身份双断言


def _run_verifier(args, health_json: str | None, tmp_path: Path):
    cmd = [sys.executable, str(VERIFIER), *args]
    proc = subprocess.run(
        cmd, input=health_json, capture_output=True, text=True, check=False,
        env={"PATH": "/usr/bin:/bin"},
    )
    return proc


class TestRuntimeIdentityVerification:
    ARGS = ["--expect-version", "1.4.0", "--expect-sha", SHA]

    def test_match_passes(self, tmp_path: Path):
        health = json.dumps({"status": "ok", "version": "1.4.0", "git_sha": SHA, "app_mode": "prod"})
        assert _run_verifier(self.ARGS, health, tmp_path).returncode == 0

    def test_version_mismatch_never_passes(self, tmp_path: Path):
        health = json.dumps({"version": "1.3.0", "git_sha": SHA})
        proc = _run_verifier(self.ARGS, health, tmp_path)
        assert proc.returncode == 1

    def test_sha_mismatch_never_passes(self, tmp_path: Path):
        health = json.dumps({"version": "1.4.0", "git_sha": OTHER_SHA})
        proc = _run_verifier(self.ARGS, health, tmp_path)
        assert proc.returncode == 1

    def test_missing_fields_fail_closed(self, tmp_path: Path):
        assert _run_verifier(self.ARGS, json.dumps({"version": "1.4.0"}), tmp_path).returncode == 1
        assert _run_verifier(self.ARGS, json.dumps({}), tmp_path).returncode == 1

    def test_malformed_health_never_passes(self, tmp_path: Path):
        assert _run_verifier(self.ARGS, "not-json", tmp_path).returncode == 1

    def test_bad_expect_sha_is_usage_error(self, tmp_path: Path):
        proc = _run_verifier(["--expect-version", "1.4.0", "--expect-sha", "abc"], "{}", tmp_path)
        assert proc.returncode == 2
