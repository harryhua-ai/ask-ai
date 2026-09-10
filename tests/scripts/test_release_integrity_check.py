"""Release Integrity Guard 契约测试(#10 生命周期守卫)。

覆盖:
- 判定层(evaluate):全部 PASS 场景 + 任务契约要求的每个 FAIL 场景
  (tag SHA 背离 / Release 缺失 / Release tag 背离 / notes 空 / 生产 SHA 背离 /
  验收 SHA 背离),以及 fail-closed 语义(缺参不放行、draft 不算发布、
  坏 manifest ≠ 缺 manifest、证据源不可用 ≠ 证据缺失);
- 采集层(collect):tag 解析、audit 模式自动锚定、publish 模式不查生产记录;
- CLI(--facts-json 离线路径):退出码 + JSON 产物;
- workflow 契约:仅 workflow_call + workflow_dispatch(❌ 无 push 触发,
  普通 main push 不受影响);build-image.yml 未被守卫改写;
- record_production_deployment.py:POST 体正确、缺 token 拒绝、API 失败非零。

全部离线确定性(不访问网络):GitHub 交互经注入/monkeypatch。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent.parent
GUARD = REPO / "scripts" / "release_integrity_check.py"
RECORDER = REPO / "scripts" / "record_production_deployment.py"
GUARD_WORKFLOW = REPO / ".github" / "workflows" / "release-integrity.yml"
BUILD_WORKFLOW = REPO / ".github" / "workflows" / "build-image.yml"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclass 解析注解时按 __module__ 回查 sys.modules
    spec.loader.exec_module(module)
    return module


guard = _load_module(GUARD, "release_integrity_check")
recorder = _load_module(RECORDER, "record_production_deployment")

SHA = "a" * 40
OTHER_SHA = "b" * 40
TAG = "v1.3.0"


# ---------------------------------------------------------------- fixtures


def release_obj(**kw):
    base = {
        "id": 1,
        "tag_name": TAG,
        "draft": False,
        "body": "## What's changed\n\n- release notes body",
        "target_commitish": "",
        "html_url": "https://github.com/harryhua-ai/ask-ai/releases/tag/" + TAG,
    }
    base.update(kw)
    return base


def deployment_obj(sha: str = SHA, **kw):
    base = {
        "id": 7,
        "sha": sha,
        "environment": "production",
        "created_at": "2026-09-10T00:00:00Z",
        "payload": {"tag": TAG, "git_sha": sha},
    }
    base.update(kw)
    return base


def acceptance_obj(sha: str = SHA, **kw):
    base = {
        "version": "1.3.0",
        "tag": TAG,
        "git_sha": sha,
        "verified_at": "2026-09-10T08:00:00Z",
        "executor": "smoke-session",
        "report_path": "docs/engineering/tasks/example-execution.md",
    }
    base.update(kw)
    return base


def facts(**kw):
    """全绿基线 facts;按测试需要覆盖单点制造矛盾。"""
    base = dict(
        tag=TAG,
        expected_sha=SHA,
        tag_exists=True,
        tag_commit=SHA,
        release=release_obj(),
        release_fetch_error=None,
        production_deployments=[deployment_obj()],
        production_fetch_error=None,
        acceptance_manifest=acceptance_obj(),
        acceptance_manifest_error=None,
    )
    base.update(kw)
    return guard.ReleaseFacts(**base)


def results_by_invariant(results):
    return {r.invariant: r for r in results}


def to_facts_json(f: guard.ReleaseFacts) -> str:
    payload = {
        "tag": f.tag,
        "expected_sha": f.expected_sha,
        "tag_exists": f.tag_exists,
        "tag_commit": f.tag_commit,
        "release": f.release,
        "release_fetch_error": f.release_fetch_error,
        "production_deployments": f.production_deployments,
        "production_fetch_error": f.production_fetch_error,
        "acceptance_manifest": f.acceptance_manifest,
        "acceptance_manifest_error": f.acceptance_manifest_error,
    }
    return json.dumps(payload)


# ---------------------------------------------------------------- 判定层:PASS


class TestPassScenarios:
    def test_publish_mode_all_agree(self):
        results = guard.evaluate(facts(), guard.MODE_PUBLISH)
        assert all(r.status == guard.PASS for r in results), [r.line() for r in results]

    def test_closure_mode_all_agree(self):
        results = guard.evaluate(facts(), guard.MODE_CLOSURE)
        assert all(r.status == guard.PASS for r in results), [r.line() for r in results]

    def test_audit_mode_anchors_release_sha_to_tag_without_expected(self):
        f = facts(expected_sha=None)
        results = guard.evaluate(f, guard.MODE_AUDIT)
        assert all(r.status == guard.PASS for r in results), [r.line() for r in results]

    def test_annotated_tag_peel_is_transparent_to_evaluator(self):
        """annotated tag 的 tag_commit 已是剥壳 commit,判定层无需特判。"""
        f = facts(tag_commit=SHA)
        assert (
            results_by_invariant(guard.evaluate(f, guard.MODE_PUBLISH))[
                "TAG_SHA == RELEASE_SHA"
            ].status
            == guard.PASS
        )


# ---------------------------------------------------------------- 判定层:FAIL


class TestFailScenarios:
    def test_tag_sha_differs_from_expected(self):
        f = facts(tag_commit=OTHER_SHA)
        r = results_by_invariant(guard.evaluate(f, guard.MODE_PUBLISH))["TAG_SHA == RELEASE_SHA"]
        assert r.status == guard.FAIL
        assert SHA in r.expected and OTHER_SHA in r.observed

    def test_missing_expected_sha_in_publish_mode_fails_closed(self):
        """release-publish 没有冻结 SHA = 不可核验 = FAIL,绝不静默降级。"""
        f = facts(expected_sha=None)
        r = results_by_invariant(guard.evaluate(f, guard.MODE_PUBLISH))["TAG_SHA == RELEASE_SHA"]
        assert r.status == guard.FAIL
        assert "expected-sha" in r.detail

    def test_github_release_missing(self):
        f = facts(release=None)
        r = results_by_invariant(guard.evaluate(f, guard.MODE_PUBLISH))["GITHUB_RELEASE_EXISTS"]
        assert r.status == guard.FAIL
        assert "404" in r.observed

    def test_release_fetch_error_is_not_treated_as_missing(self):
        """鉴权/限流/5xx = 证据源不可用,必须 FAIL,不得解释为"无 Release"放行。"""
        f = facts(release=None, release_fetch_error="GitHub API /releases/tags/v1.3.0 HTTP 502")
        r = results_by_invariant(guard.evaluate(f, guard.MODE_PUBLISH))["GITHUB_RELEASE_EXISTS"]
        assert r.status == guard.FAIL
        assert "502" in r.observed

    def test_release_tag_differs(self):
        f = facts(release=release_obj(tag_name="v1.2.9"))
        r = results_by_invariant(guard.evaluate(f, guard.MODE_PUBLISH))["GITHUB_RELEASE_TAG == TAG"]
        assert r.status == guard.FAIL
        assert TAG in r.expected and "v1.2.9" in r.observed

    def test_release_notes_empty(self):
        f = facts(release=release_obj(body="   \n  "))
        r = results_by_invariant(guard.evaluate(f, guard.MODE_PUBLISH))["RELEASE_NOTES_NONEMPTY"]
        assert r.status == guard.FAIL

    def test_draft_release_is_not_published(self):
        f = facts(release=release_obj(draft=True))
        r = results_by_invariant(guard.evaluate(f, guard.MODE_PUBLISH))["GITHUB_RELEASE_EXISTS"]
        assert r.status == guard.FAIL
        assert "draft" in r.observed

    def test_release_target_commitish_sha_mismatch(self):
        f = facts(release=release_obj(target_commitish=OTHER_SHA))
        results = results_by_invariant(guard.evaluate(f, guard.MODE_PUBLISH))
        assert results["RELEASE_TARGET_COMMITISH == TAG_SHA"].status == guard.FAIL

    def test_release_target_commitish_branch_name_not_fabricated_as_contradiction(self):
        f = facts(release=release_obj(target_commitish="main"))
        results = results_by_invariant(guard.evaluate(f, guard.MODE_PUBLISH))
        assert results["RELEASE_TARGET_COMMITISH == TAG_SHA"].status == guard.PASS

    def test_production_sha_differs(self):
        f = facts(production_deployments=[deployment_obj(sha=OTHER_SHA)])
        r = results_by_invariant(guard.evaluate(f, guard.MODE_CLOSURE))[
            "PRODUCTION_SHA == RELEASE_SHA"
        ]
        assert r.status == guard.FAIL
        assert SHA in r.expected and OTHER_SHA in r.observed

    def test_production_record_missing_fails_closed(self):
        """正式生产发布不得在无生产记录时被静默当成生命周期完成。"""
        f = facts(production_deployments=[])
        r = results_by_invariant(guard.evaluate(f, guard.MODE_CLOSURE))[
            "PRODUCTION_SHA == RELEASE_SHA"
        ]
        assert r.status == guard.FAIL
        assert "无任何记录" in r.observed

    def test_production_payload_internal_contradiction_surfaced(self):
        f = facts(production_deployments=[deployment_obj(payload={"git_sha": OTHER_SHA})])
        r = results_by_invariant(guard.evaluate(f, guard.MODE_CLOSURE))[
            "PRODUCTION_SHA == RELEASE_SHA"
        ]
        assert r.status == guard.FAIL
        assert "自相矛盾" in r.detail or OTHER_SHA[:12] in r.observed

    def test_acceptance_sha_differs(self):
        f = facts(acceptance_manifest=acceptance_obj(sha=OTHER_SHA))
        r = results_by_invariant(guard.evaluate(f, guard.MODE_CLOSURE))[
            "RUNTIME_ACCEPTANCE_SHA == RELEASE_SHA"
        ]
        assert r.status == guard.FAIL

    def test_acceptance_manifest_missing_fails_closed(self):
        f = facts(acceptance_manifest=None)
        r = results_by_invariant(guard.evaluate(f, guard.MODE_CLOSURE))[
            "RUNTIME_ACCEPTANCE_SHA == RELEASE_SHA"
        ]
        assert r.status == guard.FAIL
        assert "acceptance" in r.observed

    def test_acceptance_manifest_invalid_is_fail_not_missing(self):
        """坏证据 ≠ 缺证据:解析失败/字段缺失同样不放行。"""
        f = facts(
            acceptance_manifest=None, acceptance_manifest_error="manifest 缺少必填字段:executor"
        )
        r = results_by_invariant(guard.evaluate(f, guard.MODE_CLOSURE))[
            "RUNTIME_ACCEPTANCE_SHA == RELEASE_SHA"
        ]
        assert r.status == guard.FAIL
        assert "坏证据" in r.detail

    def test_tag_missing_cascades_explicitly(self):
        f = facts(tag_exists=False, tag_commit=None, release=None)
        results = results_by_invariant(guard.evaluate(f, guard.MODE_PUBLISH))
        assert results["TAG_EXISTS"].status == guard.FAIL
        assert results["TAG_SHA == RELEASE_SHA"].status == guard.FAIL


# ---------------------------------------------------------------- 采集层


class TestCollection:
    def test_git_tag_resolution(self):
        calls = []

        def runner_ok(cmd):
            calls.append(cmd)
            if "HEAD" in cmd:
                return subprocess.CompletedProcess(cmd, 0, SHA, "")
            return subprocess.CompletedProcess(cmd, 0, SHA + "\n", "")

        exists, sha = guard.collect_git_tag(TAG, runner_ok)
        assert exists and sha == SHA
        assert any(f"{TAG}^{{commit}}" in c for c in calls if c and "rev-parse" in c)

    def test_git_unavailable_is_collection_error_not_missing_tag(self):
        def runner_dead(cmd):
            return subprocess.CompletedProcess(cmd, 128, "", "fatal: not a git repository")

        with pytest.raises(guard.CollectionError):
            guard.collect_git_tag(TAG, runner_dead)

    def test_publish_mode_does_not_query_production_or_deployments(self):
        """publish 阶段尚无生产/验收语义,不发起相关采集(也不因其缺失而误报)。"""
        queried = []

        def github_get(repo, path):
            queried.append(path)
            return release_obj()

        runner = lambda cmd: subprocess.CompletedProcess(cmd, 0, SHA + "\n", "")
        f = guard.collect_facts(
            guard.MODE_PUBLISH, TAG, SHA, "harryhua-ai/ask-ai", runner, github_get
        )
        assert not any("/deployments" in p for p in queried)
        assert f.release is not None

    def test_audit_mode_discovers_latest_tag(self):
        def runner(cmd):
            if "tag" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "v1.3.0\nv1.2.1\n", "")
            return subprocess.CompletedProcess(cmd, 0, SHA + "\n", "")

        tag = guard.discover_latest_tag(runner)
        assert tag == "v1.3.0"

    def test_audit_mode_without_any_tag_is_collection_error(self):
        runner = lambda cmd: subprocess.CompletedProcess(cmd, 0, "", "")
        with pytest.raises(guard.CollectionError):
            guard.discover_latest_tag(runner)

    def test_acceptance_manifest_roundtrip(self, tmp_path: Path):
        d = tmp_path / "acceptance"
        d.mkdir()
        (d / "1.3.0.json").write_text(json.dumps(acceptance_obj()), encoding="utf-8")
        manifest, err = guard.load_acceptance_manifest("1.3.0", str(d))
        assert err is None and manifest["git_sha"] == SHA

    def test_acceptance_manifest_version_file_mismatch_rejected(self, tmp_path: Path):
        d = tmp_path / "acceptance"
        d.mkdir()
        (d / "1.3.0.json").write_text(json.dumps(acceptance_obj(version="1.2.9")), encoding="utf-8")
        _, err = guard.load_acceptance_manifest("1.3.0", str(d))
        assert err and "不一致" in err

    def test_acceptance_manifest_missing_field_rejected(self, tmp_path: Path):
        d = tmp_path / "acceptance"
        d.mkdir()
        bad = acceptance_obj()
        del bad["executor"]
        (d / "1.3.0.json").write_text(json.dumps(bad), encoding="utf-8")
        _, err = guard.load_acceptance_manifest("1.3.0", str(d))
        assert err and "executor" in err

    def test_github_404_is_missing_not_error(self, monkeypatch):
        class Fake404(guard.urllib.error.HTTPError):
            def __init__(self):
                super().__init__("url", 404, "Not Found", None, None)  # type: ignore[arg-type]

        def fake_urlopen(request, timeout):
            raise Fake404()

        monkeypatch.setattr(guard.urllib.request, "urlopen", fake_urlopen)
        assert guard.fetch_github_json("harryhua-ai/ask-ai", "/releases/tags/v9.9.9", None) is None

    def test_github_5xx_is_collection_error(self, monkeypatch):
        class Fake500(guard.urllib.error.HTTPError):
            def __init__(self):
                super().__init__("url", 500, "Server Error", None, None)  # type: ignore[arg-type]

        def fake_urlopen(request, timeout):
            raise Fake500()

        monkeypatch.setattr(guard.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(guard.CollectionError):
            guard.fetch_github_json("harryhua-ai/ask-ai", "/releases/tags/v9.9.9", None)


# ---------------------------------------------------------------- CLI(离线路径)


class TestCliOffline:
    def _run(self, facts_obj: guard.ReleaseFacts, mode: str, tmp_path: Path, extra=()):
        facts_path = tmp_path / "facts.json"
        out_path = tmp_path / "results.json"
        facts_path.write_text(to_facts_json(facts_obj), encoding="utf-8")
        proc = subprocess.run(
            [
                sys.executable,
                str(GUARD),
                "--mode",
                mode,
                "--facts-json",
                str(facts_path),
                "--output-json",
                str(out_path),
                *extra,
            ],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": "/usr/bin:/bin", "GH_TOKEN": ""},
        )
        return proc, out_path

    def test_publish_pass_exit_zero(self, tmp_path):
        proc, out = self._run(facts(), guard.MODE_PUBLISH, tmp_path)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["verdict"] == "PASS"

    def test_publish_sha_contradiction_exit_one_with_diagnostics(self, tmp_path):
        proc, _ = self._run(facts(tag_commit=OTHER_SHA), guard.MODE_PUBLISH, tmp_path)
        assert proc.returncode == 1
        assert "FAIL" in proc.stdout and "TAG_SHA" in proc.stdout

    def test_closure_requires_production_record(self, tmp_path):
        proc, _ = self._run(facts(production_deployments=[]), guard.MODE_CLOSURE, tmp_path)
        assert proc.returncode == 1
        assert "PRODUCTION_SHA == RELEASE_SHA" in proc.stdout

    def test_usage_error_exit_two(self, tmp_path):
        proc = subprocess.run(
            [sys.executable, str(GUARD), "--mode", "bogus-mode"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 2


# ---------------------------------------------------------------- 记录脚本


class TestRecorder:
    def test_missing_token_rejected(self, monkeypatch):
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert recorder.main(["--tag", TAG, "--sha", SHA]) == 2

    def test_posts_deployment_then_success_status(self, monkeypatch):
        monkeypatch.setenv("GH_TOKEN", "t0k3n")
        calls = []

        def fake_request(repo, path, token, body):
            calls.append((repo, path, token, json.loads(json.dumps(body))))
            return {"id": 42, "html_url": "https://github.com/x"}

        monkeypatch.setattr(recorder, "_request", fake_request)
        rc = recorder.main(["--tag", TAG, "--sha", SHA, "--note", "smoke ok"])
        assert rc == 0
        assert len(calls) == 2
        repo, dep_path, token, dep_body = calls[0]
        assert dep_path == "/deployments"
        assert dep_body["ref"] == SHA and dep_body["environment"] == "production"
        assert dep_body["payload"]["tag"] == TAG and dep_body["payload"]["git_sha"] == SHA
        assert dep_body["required_contexts"] == []
        _, status_path, _, status_body = calls[1]
        assert status_path == "/deployments/42/statuses"
        assert status_body["state"] == "success"

    def test_api_failure_returns_one(self, monkeypatch):
        monkeypatch.setenv("GH_TOKEN", "t0k3n")

        def fake_request(repo, path, token, body):
            raise recorder.urllib.error.HTTPError(
                "url", 403, "Forbidden", None, None
            )  # type: ignore[arg-type]

        monkeypatch.setattr(recorder, "_request", fake_request)
        assert recorder.main(["--tag", TAG, "--sha", SHA]) == 1

    def test_resolves_sha_from_git_when_absent(self, tmp_path: Path):
        """--sha 缺省时从真实 git 仓库解析 tag(临时仓库,确定性)。"""
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-q", "--allow-empty", "-m", "init"],
            check=True,
            env={
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t",
                "PATH": "/usr/bin:/bin",
                "HOME": str(tmp_path),
            },
        )
        subprocess.run(["git", "-C", str(tmp_path), "tag", TAG], check=True)
        sha = subprocess.run(
            ["git", "-C", str(tmp_path), "rev-parse", TAG],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        resolved = recorder.resolve_sha(str(tmp_path), TAG)
        assert resolved == sha


# ---------------------------------------------------------------- workflow / 边界契约


class TestWorkflowContract:
    @pytest.fixture(scope="class")
    def workflow(self):
        return yaml.safe_load(GUARD_WORKFLOW.read_text(encoding="utf-8"))

    def _triggers(self, workflow):
        return workflow.get("on", workflow.get(True))

    def test_no_push_trigger(self, workflow):
        """守卫绝不挂 push 触发:main 上"已接受未发版"是合法状态,
        不得让普通 main push 因无 Release 而失败。"""
        assert "push" not in self._triggers(workflow)

    def test_call_and_dispatch_only(self, workflow):
        triggers = self._triggers(workflow)
        assert set(triggers.keys()) == {"workflow_call", "workflow_dispatch"}

    def test_workflow_call_inputs(self, workflow):
        inputs = self._triggers(workflow)["workflow_call"]["inputs"]
        assert set(inputs.keys()) == {"tag", "expected_sha", "mode"}
        assert inputs["mode"]["default"] in guard.MODES

    def test_dispatch_defaults_to_audit(self, workflow):
        inputs = self._triggers(workflow)["workflow_dispatch"]["inputs"]
        assert inputs["mode"]["default"] == guard.MODE_AUDIT

    def test_checkout_full_history_for_tags(self, workflow):
        steps = workflow["jobs"]["guard"]["steps"]
        checkout = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout")]
        assert checkout and checkout[0]["with"]["fetch-depth"] == 0

    def test_guard_invoked_with_token(self, workflow):
        text = GUARD_WORKFLOW.read_text(encoding="utf-8")
        assert "release_integrity_check.py" in text
        assert "GH_TOKEN" in text

    def test_build_workflow_not_wired_to_guard(self):
        """边界证明:build-image.yml(含普通 push main 触发)未被守卫改写,
        也没有 push main 时运行守卫的路径。"""
        text = BUILD_WORKFLOW.read_text(encoding="utf-8")
        assert "release_integrity_check" not in text
        assert "release-integrity" not in text


# ---------------------------------------------------------------- 词法对齐


class TestLexicalAlignment:
    """与 backend/release.py 同一词法:v 前缀剥除、sha 小写归一。"""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("v1.3.0", "1.3.0"),
            ("V1.3.0", "1.3.0"),
            ("1.3.0", "1.3.0"),
            ("v1.3.0-rc.1", "1.3.0-rc.1"),
            ("v1.3.0+build.7", "1.3.0+build.7"),
        ],
    )
    def test_version_normalization(self, raw, expected):
        assert guard.normalize_version(raw) == expected

    def test_sha_normalization(self):
        assert guard.normalize_sha("A" * 40) == SHA

    def test_semver_rejects_non_semver(self):
        assert not guard._SEMVER_RE.match(guard.normalize_version("latest"))
