"""Release Integrity Guard 契约测试(#10 生命周期守卫)。

覆盖:
- 判定层(evaluate):全部 PASS 场景 + 任务契约要求的每个 FAIL 场景
  (tag SHA 背离 / Release 缺失 / Release tag 背离 / notes 空 / 生产 SHA 背离 /
  生产 status 非 success / 验收 SHA 背离 / report_path 来源不可信),以及
  fail-closed 语义(缺参不放行、draft 不算发布、坏 manifest ≠ 缺 manifest、
  状态源不可用 ≠ 无状态、证据源不可用 ≠ 证据缺失);
- 采集层(collect):tag 解析、audit 模式自动锚定、publish 模式不查生产记录、
  closure 对权威记录拉取 status 史(404/非列表/网络失败一律 fail-closed);
- CLI(--facts-json 离线路径):退出码 + JSON 产物;
- workflow 契约:仅 workflow_call + workflow_dispatch(❌ 无 push 触发,
  普通 main push 不受影响);inputs 经 env 数据边界传入(❌ 不内插进 shell
  源码);permissions 保持 contents:read;build-image.yml 未被守卫改写;
- record_production_deployment.py:POST 体正确、缺 token 拒绝、API 失败非零、
  运行簿顺序契约(update.sh 成功 → /health 身份核验 → 之后才记录)显式在案。

全部离线确定性(不访问网络):GitHub 交互经注入/monkeypatch;report_path
入库核验用真实临时 git 仓库(TestRecorder 已有同类先例)。
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


def status_obj(state: str = "success", sid: int = 1001, **kw):
    base = {
        "id": sid,
        "state": state,
        "environment": "production",
        "created_at": "2026-09-10T00:01:00Z",
        "description": f"deployed {TAG}",
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


# ---- report_path 入库核验的真实边界(临时 git 仓库) ----

REPORT_REL = "docs/engineering/tasks/acceptance-report-example.md"


def real_runner(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def init_evidence_repo(tmp_path: Path) -> Path:
    """最小 git 仓库,内含一个被跟踪的报告文件;report_path 核验用它。"""
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
    report = repo / REPORT_REL
    report.parent.mkdir(parents=True)
    report.write_text("# runtime acceptance report\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "add", REPORT_REL], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "evidence"], check=True, env=env)
    return repo


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
        production_statuses=[status_obj()],
        production_statuses_error=None,
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
        "production_statuses": f.production_statuses,
        "production_statuses_error": f.production_statuses_error,
        "acceptance_manifest": f.acceptance_manifest,
        "acceptance_manifest_error": f.acceptance_manifest_error,
    }
    return json.dumps(payload)


# ---------------------------------------------------------------- 判定层:PASS


class TestPassScenarios:
    def test_publish_mode_all_agree(self):
        results = guard.evaluate(facts(), guard.MODE_PUBLISH)
        assert all(r.status == guard.PASS for r in results), [r.line() for r in results]

    def test_closure_mode_all_agree(self, tmp_path: Path):
        repo = init_evidence_repo(tmp_path)
        f = facts(acceptance_manifest=acceptance_obj(report_path=REPORT_REL))
        results = guard.evaluate(f, guard.MODE_CLOSURE, repo_root=str(repo), runner=real_runner)
        assert all(r.status == guard.PASS for r in results), [r.line() for r in results]

    def test_audit_mode_anchors_release_sha_to_tag_without_expected(self, tmp_path: Path):
        repo = init_evidence_repo(tmp_path)
        f = facts(
            expected_sha=None, acceptance_manifest=acceptance_obj(report_path=REPORT_REL)
        )
        results = guard.evaluate(f, guard.MODE_AUDIT, repo_root=str(repo), runner=real_runner)
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


# ---------------------------------------------------------------- 判定层:生产状态权威(跟进 ①)


class TestProductionStatusAuthority:
    """记录存在 + SHA 一致 ≠ 闭环:权威记录必须持有 effective/latest status=success。"""

    INV = "PRODUCTION DEPLOYMENT STATUS == success"

    def _closure(self, **kw):
        return results_by_invariant(guard.evaluate(facts(**kw), guard.MODE_CLOSURE))

    def test_success_status_passes(self):
        r = self._closure()[self.INV]
        assert r.status == guard.PASS
        assert "state=success" in r.observed

    @pytest.mark.parametrize(
        "state", ["queued", "in_progress", "pending", "failure", "error", "inactive"]
    )
    def test_every_non_success_state_fails(self, state):
        r = self._closure(production_statuses=[status_obj(state=state)])[self.INV]
        assert r.status == guard.FAIL
        assert f"state={state}" in r.observed

    def test_status_absent_fails(self):
        """部署存在但从未被确认(无任何 status)→ FAIL。"""
        r = self._closure(production_statuses=[])[self.INV]
        assert r.status == guard.FAIL
        assert "无任何 Deployment Status" in r.observed

    def test_status_source_unavailable_is_not_missing_nor_success(self):
        """状态源不可用(鉴权/限流/5xx)按失败处理,不得解释为无状态/成功。"""
        f = facts(
            production_statuses=[],
            production_statuses_error="GitHub API /deployments/7/statuses HTTP 502(证据源不可用)",
        )
        r = results_by_invariant(guard.evaluate(f, guard.MODE_CLOSURE))[self.INV]
        assert r.status == guard.FAIL
        assert "502" in r.observed
        assert "不可用" in r.detail

    @pytest.mark.parametrize(
        "bad", [[{"foo": "bar"}], ["not-a-dict"], [{}], [{"state": ""}]]
    )
    def test_status_payload_malformed_fails(self, bad):
        r = self._closure(production_statuses=bad)[self.INV]
        assert r.status == guard.FAIL, bad
        assert "畸形" in r.observed

    def test_latest_status_wins_over_older_success(self):
        """id 更大的 failure 覆盖更早的 success(effective = 最新状态)。"""
        r = self._closure(
            production_statuses=[
                status_obj(state="success", sid=1),
                status_obj(state="failure", sid=2),
            ]
        )[self.INV]
        assert r.status == guard.FAIL
        assert "state=failure" in r.observed

    def test_status_selection_is_order_independent(self):
        """官方文档不保证 statuses 列表排序:按 id 取最大,前后顺序不影响结论。"""
        newer = status_obj(state="success", sid=2)
        older = status_obj(state="failure", sid=1)
        for order in ([newer, older], [older, newer]):
            r = self._closure(production_statuses=order)[self.INV]
            assert r.status == guard.PASS, order

    def test_inactive_after_success_never_passes(self):
        """环境被去活的 inactive 也不能代表在位生产。"""
        r = self._closure(
            production_statuses=[
                status_obj(state="success", sid=1),
                status_obj(state="inactive", sid=2),
            ]
        )[self.INV]
        assert r.status == guard.FAIL


# ---------------------------------------------------------------- 判定层:验收报告来源(跟进 ②)


class TestReportProvenance:
    """report_path 必须解析为仓库内被 git 跟踪的真实文件;否则 FAIL。"""

    INV = "RUNTIME_ACCEPTANCE_REPORT_PROVENANCE"

    def _eval(self, manifest, repo_root, runner=None):
        f = facts(acceptance_manifest=manifest)
        return results_by_invariant(
            guard.evaluate(
                f, guard.MODE_CLOSURE, repo_root=str(repo_root), runner=runner or real_runner
            )
        )[self.INV]

    def test_tracked_report_passes(self, tmp_path: Path):
        repo = init_evidence_repo(tmp_path)
        r = self._eval(acceptance_obj(report_path=REPORT_REL), repo)
        assert r.status == guard.PASS
        assert "入库" in r.detail or "跟踪" in r.detail

    def test_manifest_missing_fails_provenance(self):
        r = self._eval(None, Path("."))
        assert r.status == guard.FAIL
        assert "不存在" in r.observed

    def test_manifest_invalid_fails_provenance(self):
        f = facts(
            acceptance_manifest=None,
            acceptance_manifest_error="manifest 缺少必填字段:executor",
        )
        r = results_by_invariant(guard.evaluate(f, guard.MODE_CLOSURE))[self.INV]
        assert r.status == guard.FAIL

    def test_nonexistent_report_fails(self, tmp_path: Path):
        repo = init_evidence_repo(tmp_path)
        r = self._eval(acceptance_obj(report_path="docs/engineering/tasks/ghost.md"), repo)
        assert r.status == guard.FAIL
        assert "不存在" in r.detail

    def test_absolute_path_rejected(self, tmp_path: Path):
        repo = init_evidence_repo(tmp_path)
        r = self._eval(acceptance_obj(report_path="/etc/passwd"), repo)
        assert r.status == guard.FAIL
        assert "绝对路径" in r.detail

    def test_traversal_rejected(self, tmp_path: Path):
        repo = init_evidence_repo(tmp_path)
        r = self._eval(acceptance_obj(report_path="../outside.md"), repo)
        assert r.status == guard.FAIL
        assert "穿越" in r.detail

    def test_deeper_traversal_rejected(self, tmp_path: Path):
        repo = init_evidence_repo(tmp_path)
        r = self._eval(acceptance_obj(report_path="docs/../../outside.md"), repo)
        assert r.status == guard.FAIL
        assert "穿越" in r.detail

    def test_symlink_escape_rejected(self, tmp_path: Path):
        repo = init_evidence_repo(tmp_path)
        outside = tmp_path / "outside.md"
        outside.write_text("outside evidence", encoding="utf-8")
        link = repo / "docs" / "engineering" / "linked.md"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(outside)
        r = self._eval(acceptance_obj(report_path="docs/engineering/linked.md"), repo)
        assert r.status == guard.FAIL
        assert "边界之外" in r.detail

    def test_untracked_file_rejected(self, tmp_path: Path):
        repo = init_evidence_repo(tmp_path)
        target = repo / "docs" / "engineering" / "tasks" / "untracked.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("not committed", encoding="utf-8")
        r = self._eval(acceptance_obj(report_path="docs/engineering/tasks/untracked.md"), repo)
        assert r.status == guard.FAIL
        assert "跟踪" in r.detail

    def test_directory_rejected(self, tmp_path: Path):
        repo = init_evidence_repo(tmp_path)
        r = self._eval(acceptance_obj(report_path="docs"), repo)
        assert r.status == guard.FAIL

    def test_git_unavailable_fails_closed(self, tmp_path: Path):
        repo = init_evidence_repo(tmp_path)

        def dead_runner(cmd):
            return subprocess.CompletedProcess(cmd, 128, "", "fatal: not a git repository")

        r = self._eval(acceptance_obj(report_path=REPORT_REL), repo, runner=dead_runner)
        assert r.status == guard.FAIL
        assert "不可用" in r.detail or "fail-closed" in r.detail


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

    # ---- 权威记录的 status 史采集(closure/audit) ----

    def _collect(self, mode: str, github_get):
        runner = lambda cmd: subprocess.CompletedProcess(cmd, 0, SHA + "\n", "")
        return guard.collect_facts(
            mode, TAG, SHA, "harryhua-ai/ask-ai", runner, github_get
        )

    def test_closure_fetches_statuses_of_authoritative_record(self):
        paths = []

        def github_get(repo, path):
            paths.append(path)
            if path.startswith("/deployments?"):
                return [deployment_obj()]
            if "/statuses" in path:
                return [status_obj()]
            return release_obj()

        f = self._collect(guard.MODE_CLOSURE, github_get)
        assert any("/deployments/7/statuses" in p for p in paths)
        assert f.production_statuses == [status_obj()]
        assert f.production_statuses_error is None

    def test_status_endpoint_404_is_source_inconsistency_not_missing(self):
        """部署在册而状态源 404 = 证据源不一致,fail-closed,不当作"无状态"。"""

        def github_get(repo, path):
            if path.startswith("/deployments?"):
                return [deployment_obj()]
            if "/statuses" in path:
                return None  # fetch_github_json 对 404 的语义
            return release_obj()

        f = self._collect(guard.MODE_CLOSURE, github_get)
        assert f.production_statuses_error is not None
        assert "404" in f.production_statuses_error

    def test_status_endpoint_5xx_is_fail_closed_collection_error(self):
        def github_get(repo, path):
            if path.startswith("/deployments?"):
                return [deployment_obj()]
            if "/statuses" in path:
                raise guard.CollectionError("GitHub API /deployments/7/statuses HTTP 502")
            return release_obj()

        f = self._collect(guard.MODE_CLOSURE, github_get)
        assert f.production_statuses_error is not None
        assert "502" in f.production_statuses_error

    def test_non_list_status_payload_is_malformed(self):
        def github_get(repo, path):
            if path.startswith("/deployments?"):
                return [deployment_obj()]
            if "/statuses" in path:
                return {"unexpected": "shape"}
            return release_obj()

        f = self._collect(guard.MODE_CLOSURE, github_get)
        assert f.production_statuses_error is not None
        assert "畸形" in f.production_statuses_error

    def test_malformed_authoritative_record_reports_status_unverifiable(self):
        def github_get(repo, path):
            if path.startswith("/deployments?"):
                return ["not-a-dict"]
            return release_obj()

        f = self._collect(guard.MODE_CLOSURE, github_get)
        assert f.production_statuses_error is not None
        assert "畸形" in f.production_statuses_error


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

    def test_closure_pass_end_to_end_with_status_and_evidence(self, tmp_path):
        """闭环全绿:status=success + manifest + 入库报告(真实 git 仓库核验)。"""
        repo = init_evidence_repo(tmp_path)
        f = facts(acceptance_manifest=acceptance_obj(report_path=REPORT_REL))
        proc, out = self._run(
            f, guard.MODE_CLOSURE, tmp_path, extra=("--repo-root", str(repo))
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["verdict"] == "PASS"

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

    def test_permissions_remain_contents_read(self, workflow):
        """收紧边界回归:权限不因硬化而扩大。"""
        assert workflow.get("permissions") == {"contents": "read"}

    # ---- 跟进 ④:inputs 经 env 数据边界,不内插进 shell 源码 ----

    def _guard_step(self, workflow):
        steps = workflow["jobs"]["guard"]["steps"]
        return next(
            s for s in steps if "release_integrity_check.py" in str(s.get("run", ""))
        )

    def test_inputs_not_interpolated_into_run_script(self, workflow):
        """${{ inputs.* }} 在 run: 里是文本替换 = 把外部输入拼进代码,禁止。"""
        for step in workflow["jobs"]["guard"]["steps"]:
            run = step.get("run")
            if run:
                assert "${{ inputs." not in run, step.get("name")
                assert "${{ github." not in run, step.get("name")

    def test_inputs_transport_through_env_boundary(self, workflow):
        env = self._guard_step(workflow)["env"]
        assert env["GUARD_INPUT_MODE"] == "${{ inputs.mode }}"
        assert env["GUARD_INPUT_TAG"] == "${{ inputs.tag }}"
        assert env["GUARD_INPUT_EXPECTED_SHA"] == "${{ inputs.expected_sha }}"

    def test_run_consumes_env_vars_as_data(self, workflow):
        run = self._guard_step(workflow)["run"]
        assert '"$GUARD_INPUT_MODE"' in run
        assert '"$GUARD_INPUT_TAG"' in run
        assert '"$GUARD_INPUT_EXPECTED_SHA"' in run
        assert "set -euo pipefail" in run

    def test_build_workflow_not_wired_to_guard(self):
        """边界证明:build-image.yml(含普通 push main 触发)未被守卫改写,
        也没有 push main 时运行守卫的路径。"""
        text = BUILD_WORKFLOW.read_text(encoding="utf-8")
        assert "release_integrity_check" not in text
        assert "release-integrity" not in text


# ---------------------------------------------------------------- 运行簿契约(跟进 ③)


class TestRunbookContract:
    """记录顺序契约必须显式在案:update.sh 成功 → /health 身份核验 →
    之后才记录。recorder 保持低层记录原语,顺序责任在运行簿文档。"""

    def test_recorder_docstring_states_required_ordering(self):
        doc = recorder.__doc__ or ""
        assert "deploy/prod/update.sh" in doc
        assert "/health" in doc
        assert "DEPLOY" in doc and "VERIFY" in doc and "RECORD" in doc
        assert "不可颠倒" in doc

    def test_recorder_stays_low_level_no_runtime_probe_no_deploy(self):
        """低层原语边界:代码本体不得探测 /health、不得执行部署
        (subprocess 仅允许 resolve_sha 的 git rev-parse 一处)。"""
        src = RECORDER.read_text(encoding="utf-8")
        body = src.split('"""', 2)[2]
        assert "/health" not in body
        assert "localhost" not in body
        assert body.count("subprocess.run") == 1
        assert '"git",' in body

    def test_update_sh_header_documents_evidence_recording_order(self):
        """权威部署契约文档 = update.sh 头部;必须绑定记录顺序。"""
        update_sh = REPO / "deploy" / "prod" / "update.sh"
        src = update_sh.read_text(encoding="utf-8")
        assert "record_production_deployment.py" in src
        assert "/health" in src
        assert "RECORD EVIDENCE" in src
        assert "伪证" in src


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
