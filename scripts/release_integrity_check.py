#!/usr/bin/env python3
"""Release lifecycle integrity guard(#10 版本与发布治理 · 生命周期一致性守卫)。

对**一个明确的 release 身份**(tag + 权威 SHA)做确定性核验,防止发布生命周期
半途而废却被静默当成已完成(如:tag 已打但 GitHub Release 缺失、生产跑的
不是发布 SHA、验收记录与发布 SHA 背离)。

不变量与权威证据源:

    不变量                          权威证据(本仓现状)                     状态
    TAG_EXISTS                     git rev-parse <tag>^{commit}            AUTOMATED
    TAG_SHA == RELEASE_SHA         调用方冻结的 --expected-sha vs tag 解析   AUTOMATED
    GITHUB_RELEASE_EXISTS          GitHub Releases API(须已发布非 draft)  AUTOMATED
    GITHUB_RELEASE_TAG == TAG      Release 对象 tag_name                    AUTOMATED
    RELEASE_NOTES_NONEMPTY         Release body 非空白                      AUTOMATED
    PRODUCTION_SHA == RELEASE_SHA  GitHub Deployments API environment=
                                   production 最新记录的 sha(与
                                   payload.git_sha 互证)                  AUTOMATED
                                   (记录接口 scripts/record_production_
                                   deployment.py;运行簿契约:仅在
                                   update.sh 成功 + /health 运行时身份
                                   核验之后记录 —— 见 deploy/prod/
                                   update.sh 头部「部署后证据记录」)
    PRODUCTION DEPLOYMENT
        STATUS == success          同一权威记录的 GET /deployments/{id}/
                                   statuses 最新状态(官方未定义列表排序,
                                   按 status id 最大选取,免排序假设);
                                   仅 success 放行 —— 无状态 / queued /
                                   in_progress / pending / failure /
                                   error / inactive / 状态源不可用 /
                                   载荷畸形一律 fail-closed               AUTOMATED
    RUNTIME_ACCEPTANCE_SHA ==
        RELEASE_SHA                deployments/acceptance/<version>.json
                                   (人工验收证据的可审阅 manifest,经 PR
                                   入库;缺失/非法均 fail-closed)          AUTOMATED
                                   (约定已定义,首个 manifest 待正式验收产生)
    RUNTIME_ACCEPTANCE_REPORT
        _PROVENANCE                manifest.report_path 须解析为仓库内被
                                   git 跟踪的真实文件(仓库相对;绝对/
                                   穿越/符号链接逃逸/未跟踪/缺失一律
                                   FAIL)                                 AUTOMATED

证据源**不可用 ≠ 证据不存在**:GitHub API 非 404 错误(鉴权/限流/5xx)按
COLLECTION ERROR 处理,绝不当作"Release 缺失"放行 —— 与 backend/release.py
的"坏文件 ≠ 缺失"同一哲学。

模式(fail 边界不同):

    release-publish     tag + GitHub Release 五项不变量;--expected-sha 必填
                        (没有冻结 SHA 就无从谈"核验",缺参 = FAIL,不是 SKIP)
    production-closure  上述 + 生产记录 + 验收 manifest(正式闭环判定)
    audit               同 closure 不变量;--tag 缺省取最新 vX.Y.Z;
                        --expected-sha 缺省时锚定 release_sha = tag 解析 SHA
                        (只核验链内一致性,不假冒"已验收"语义)

设计边界:本守卫**不创建/修改** tag、Release、部署记录;只读核验 + 显式诊断。
main 上存在"已接受未发版"的代码是合法状态 —— 守卫不挂在普通 push 触发上
(见 .github/workflows/release-integrity.yml:仅 workflow_call / dispatch)。

验收 manifest schema(deployments/acceptance/<version>.json,version 无 v 前缀):

    {
      "version": "1.3.0",                  # 必填,无前缀 SemVer
      "tag": "v1.3.0",                     # 必填
      "git_sha": "<40 位发布 commit>",      # 必填,== release_sha 才算 PASS
      "verified_at": "2026-09-10T...Z",    # 必填(权威验收钟)
      "executor": "...",                   # 必填(执行人/会话标识)
      "report_path": "docs/...",           # 必填,仓库相对路径;须解析为被 git
                                           # 跟踪的真实文件(绝对/穿越/缺失/
                                           # 未跟踪 → REPORT_PROVENANCE FAIL)
      "checks": [...]                      # 可选(逐项冒烟结果)
    }

用法:

    python3 scripts/release_integrity_check.py --mode release-publish \
        --tag v1.3.0 --expected-sha <sha>
    python3 scripts/release_integrity_check.py --mode production-closure --tag v1.3.0
    python3 scripts/release_integrity_check.py --mode audit            # 最新 tag
    # 离线/测试:--facts-json 直接喂采集结果,跳过 git/GitHub 采集

退出码:0 = 本模式全部不变量 PASS;1 = 任一不变量 FAIL(含采集失败,
fail-closed);2 = 用法错误。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

DEFAULT_REPO = "harryhua-ai/ask-ai"
PRODUCTION_ENVIRONMENT = "production"
ACCEPTANCE_DIR = os.path.join("deployments", "acceptance")

# 与 backend/release.py 同一词法:v/V 前缀仅在余下为合法 SemVer 时剥除
_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)" r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")

MODE_PUBLISH = "release-publish"
MODE_CLOSURE = "production-closure"
MODE_AUDIT = "audit"
MODES = (MODE_PUBLISH, MODE_CLOSURE, MODE_AUDIT)

PASS = "PASS"
FAIL = "FAIL"


class CollectionError(RuntimeError):
    """证据源不可用(非"证据缺失")—— fail-closed,不得解释为某不变量通过。"""


def normalize_version(raw: str) -> str:
    value = (raw or "").strip()
    if value[:1] in ("v", "V") and _SEMVER_RE.match(value[1:]):
        value = value[1:]
    return value


def normalize_sha(raw: str) -> str:
    return (raw or "").strip().lower()


# ---------------------------------------------------------------- 采集层


@dataclass
class ReleaseFacts:
    """一次性采集的生命周期事实;--facts-json 可直接构造(离线/测试)。"""

    tag: str
    expected_sha: str | None
    tag_exists: bool = False
    tag_commit: str | None = None
    release: dict | None = None
    release_fetch_error: str | None = None
    production_deployments: list = field(default_factory=list)
    production_fetch_error: str | None = None
    production_statuses: list = field(default_factory=list)
    production_statuses_error: str | None = None
    acceptance_manifest: dict | None = None
    acceptance_manifest_error: str | None = None


def collect_git_tag(tag: str, runner: Callable) -> tuple[bool, str | None]:
    proc = runner(["git", "rev-parse", "--verify", "--quiet", f"{tag}^{{commit}}"])
    if proc.returncode == 0 and proc.stdout.strip():
        return True, normalize_sha(proc.stdout)
    # 区分"tag 不存在"与"git 本身不可用":后者不是生命周期事实
    probe = runner(["git", "rev-parse", "--verify", "HEAD"])
    if probe.returncode != 0:
        raise CollectionError("git 不可用,无法解析 tag(rev-parse HEAD 失败)")
    return False, None


def discover_latest_tag(runner: Callable) -> str:
    proc = runner(["git", "tag", "--list", "v*", "--sort=-v:refname"])
    if proc.returncode != 0:
        raise CollectionError("git tag 列举失败")
    for line in proc.stdout.splitlines():
        name = line.strip()
        if name:
            return name
    raise CollectionError("仓库内没有任何 vX.Y.Z tag,无从锚定 audit")


def fetch_github_json(repo: str, path: str, token: str | None) -> object:
    """GET https://api.github.com{path};404 → None;其余错误 → CollectionError。"""
    url = f"https://api.github.com/repos/{repo}{path}"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise CollectionError(
            f"GitHub API {path} HTTP {exc.code}(证据源不可用,非证据缺失)"
        ) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise CollectionError(f"GitHub API {path} 不可达:{exc}(证据源不可用,非证据缺失)") from exc


def load_acceptance_manifest(version: str, base_dir: str) -> tuple[dict | None, str | None]:
    """读验收 manifest;返回 (manifest, error)。缺失与非法分别报告,不互相冒充。"""
    path = os.path.join(base_dir, f"{version}.json")
    if not os.path.exists(path):
        return None, None  # 缺失是显式不变量失败,不是采集错误
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"manifest 存在但不可解析(坏证据 ≠ 缺证据):{exc}"
    required = ("version", "tag", "git_sha", "verified_at", "executor", "report_path")
    missing = [k for k in required if not str(data.get(k) or "").strip()]
    if missing:
        return None, f"manifest 缺少必填字段:{','.join(missing)}"
    if not _SHA_RE.match(normalize_sha(data["git_sha"])):
        return None, f"manifest git_sha 非法:{data['git_sha']!r}"
    if normalize_version(data["version"]) != version:
        return None, f"manifest version={data['version']!r} 与文件锚定版本 {version} 不一致"
    return data, None


def collect_facts(
    mode: str,
    tag: str | None,
    expected_sha: str | None,
    repo: str,
    runner: Callable,
    github_get: Callable[[str, str], object],
    acceptance_dir: str = ACCEPTANCE_DIR,
) -> ReleaseFacts:
    resolved_tag = tag or discover_latest_tag(runner)
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    tag_exists, tag_commit = collect_git_tag(resolved_tag, runner)

    release = None
    release_err = None
    try:
        release = github_get(repo, f"/releases/tags/{resolved_tag}")
    except CollectionError as exc:
        release_err = str(exc)

    deployments: list = []
    prod_err = None
    statuses: list = []
    statuses_err = None
    if mode in (MODE_CLOSURE, MODE_AUDIT):
        try:
            data = github_get(
                repo, f"/deployments?environment={PRODUCTION_ENVIRONMENT}&per_page=100"
            )
            deployments = data if isinstance(data, list) else []
        except CollectionError as exc:
            prod_err = str(exc)
        # 权威记录的状态史:仅对最新一条记录采集(它才是 closure 的 SHA 权威)。
        # 404/非列表/网络失败都不当作"无状态" —— 状态证据源一律 fail-closed。
        if deployments and not isinstance(deployments[0], dict):
            statuses_err = "最新生产记录畸形(非对象),状态史无从核验"
        elif deployments and isinstance(deployments[0], dict):
            dep_id = deployments[0].get("id")
            if dep_id is None or str(dep_id).strip() == "":
                statuses_err = "最新生产记录缺 id,状态史无从核验(记录畸形)"
            else:
                try:
                    payload = github_get(
                        repo, f"/deployments/{dep_id}/statuses?per_page=100"
                    )
                    if payload is None:
                        statuses_err = (
                            f"GET /deployments/{dep_id}/statuses → 404"
                            "(部署记录在册而状态源缺失,证据源不一致)"
                        )
                    elif isinstance(payload, list):
                        statuses = payload
                    else:
                        statuses_err = "statuses 响应非列表(状态载荷畸形)"
                except CollectionError as exc:
                    statuses_err = str(exc)

    version = normalize_version(resolved_tag)
    manifest, manifest_err = load_acceptance_manifest(version, acceptance_dir)

    return ReleaseFacts(
        tag=resolved_tag,
        expected_sha=normalize_sha(expected_sha) if expected_sha else None,
        tag_exists=tag_exists,
        tag_commit=tag_commit,
        release=release if isinstance(release, dict) else None,
        release_fetch_error=release_err,
        production_deployments=deployments,
        production_fetch_error=prod_err,
        production_statuses=statuses,
        production_statuses_error=statuses_err,
        acceptance_manifest=manifest,
        acceptance_manifest_error=manifest_err,
    )


# ---------------------------------------------------------------- 判定层


@dataclass
class CheckResult:
    invariant: str
    status: str
    expected: str = ""
    observed: str = ""
    detail: str = ""

    def line(self) -> str:
        head = f"[{self.status}] {self.invariant}"
        parts = [
            p
            for p in (
                f"expected={self.expected}" if self.expected else "",
                f"observed={self.observed}" if self.observed else "",
            )
            if p
        ]
        text = "  ".join([head, *parts])
        if self.detail:
            text += f"  # {self.detail}"
        return text


def _release_sha(facts: ReleaseFacts) -> str | None:
    """权威 release SHA:优先调用方冻结值;audit 未冻结时锚定 tag 解析结果。"""
    return facts.expected_sha or facts.tag_commit


SUCCESS_STATE = "success"


def effective_production_status(
    statuses: list,
) -> tuple[dict | None, str | None]:
    """权威记录的 effective/latest 状态。返回 (latest_status, error)。

    官方文档不保证 statuses 列表排序 → 按 status id 最大选取(id 单调递增),
    免受 API 排序假设影响;id 缺失时退化为 created_at 字典序,再不行保持稳定。
    空列表 → (None, None)(调用方按"无状态"FAIL);条目非 dict 或无可解析
    state → (None, 畸形说明)。只有 state 字符串精确等于 success 才算通过。
    """
    if not statuses:
        return None, None
    entries = [s for s in statuses if isinstance(s, dict) and str(s.get("state") or "").strip()]
    if not entries:
        return None, "状态载荷畸形(无任何可解析的 state 字段)"

    def rank(s: dict) -> tuple[int, str]:
        raw = str(s.get("id") or "").strip()
        return (int(raw) if raw.isdigit() else 0, str(s.get("created_at") or ""))

    return max(entries, key=rank), None


def resolve_report_artifact(
    report_path: str,
    repo_root: str,
    runner: Callable,
) -> tuple[str, str | None]:
    """验收报告来源验证:report_path 必须解析为仓库内被 git 跟踪的真实文件。

    fail-closed 矩阵:空值 / 绝对路径 / 词汇穿越(../)/ 符号链接真实路径逃逸
    仓库边界 / 文件不存在 / 指向目录 / git 不可用(无法核验入库状态)/
    未被 git 跟踪 —— 全部 FAIL,绝不静默放行。返回 (归一化路径, error)。
    """
    raw = (report_path or "").strip()
    if not raw:
        return "", "report_path 为空"
    if raw.startswith("/") or os.path.isabs(raw):
        return raw, "绝对路径拒绝(须为仓库相对路径)"
    import posixpath

    norm = posixpath.normpath(raw)
    if norm in ("", ".", "..") or norm.startswith("../") or norm.startswith("/"):
        return raw, "路径穿越仓库边界"
    real_repo = os.path.realpath(repo_root)
    real_candidate = os.path.realpath(os.path.join(repo_root, norm))
    if real_candidate != real_repo and not real_candidate.startswith(real_repo + os.sep):
        return norm, "真实路径解析到仓库边界之外(符号链接逃逸)"
    if not os.path.isfile(real_candidate):
        return norm, "指向的仓库证据文件不存在(或不是普通文件)"
    proc = runner(["git", "-C", repo_root, "ls-files", "--", norm])
    if proc is None or proc.returncode != 0:
        return norm, "git 不可用,无法核验证据是否入库(fail-closed)"
    tracked = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    if norm not in tracked:
        return norm, "证据文件未被 git 跟踪(非入库证据,不构成可审阅记录)"
    return norm, None


def _default_runner() -> Callable:
    return lambda cmd: subprocess.run(cmd, capture_output=True, text=True, check=False)


def evaluate(
    facts: ReleaseFacts,
    mode: str,
    repo_root: str = ".",
    runner: Callable | None = None,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    tag = facts.tag

    # ---- TAG_EXISTS / TAG_SHA == RELEASE_SHA ----
    if not facts.tag_exists:
        results.append(CheckResult("TAG_EXISTS", FAIL, observed=f"{tag}: git 中不存在"))
        results.append(
            CheckResult("TAG_SHA == RELEASE_SHA", FAIL, detail="tag 不存在,TAG_SHA 无从核验")
        )
    else:
        results.append(CheckResult("TAG_EXISTS", PASS, observed=f"{tag} → {facts.tag_commit[:12]}"))
        release_sha = _release_sha(facts)
        if mode == MODE_PUBLISH and not facts.expected_sha:
            results.append(
                CheckResult(
                    "TAG_SHA == RELEASE_SHA",
                    FAIL,
                    detail="release-publish 模式必须显式提供 --expected-sha(冻结的接受 SHA);"
                    "缺参 = 不可核验 = FAIL,绝不静默降级为通过",
                )
            )
        elif not release_sha:
            results.append(
                CheckResult(
                    "TAG_SHA == RELEASE_SHA", FAIL, detail="既无 --expected-sha 也无 tag 解析结果"
                )
            )
        else:
            results.append(
                CheckResult(
                    "TAG_SHA == RELEASE_SHA",
                    PASS if facts.tag_commit == release_sha else FAIL,
                    expected=release_sha,
                    observed=facts.tag_commit,
                )
            )

    # ---- GitHub Release 三项 ----
    if facts.release_fetch_error:
        detail = facts.release_fetch_error
        results.append(
            CheckResult(
                "GITHUB_RELEASE_EXISTS",
                FAIL,
                observed=detail,
                detail="证据源不可用按失败处理,不当作 Release 缺失",
            )
        )
    elif facts.release is None:
        results.append(
            CheckResult(
                "GITHUB_RELEASE_EXISTS",
                FAIL,
                observed=f"GET /releases/tags/{tag} → 404(无 Release)",
            )
        )
    else:
        is_draft = bool(facts.release.get("draft"))
        results.append(
            CheckResult(
                "GITHUB_RELEASE_EXISTS",
                FAIL if is_draft else PASS,
                observed=(
                    f"draft=true(存在但未发布,url={facts.release.get('html_url', '')})"
                    if is_draft
                    else f"published,id={facts.release.get('id')}"
                ),
                detail="draft ≠ 已发布:正式发布不得以 draft 冒充完成" if is_draft else "",
            )
        )
        observed_tag = str(facts.release.get("tag_name") or "")
        results.append(
            CheckResult(
                "GITHUB_RELEASE_TAG == TAG",
                PASS if observed_tag == tag else FAIL,
                expected=tag,
                observed=observed_tag or "(空)",
            )
        )
        body = str(facts.release.get("body") or "")
        results.append(
            CheckResult(
                "RELEASE_NOTES_NONEMPTY",
                PASS if body.strip() else FAIL,
                observed=f"body {len(body.strip())} 字符" if body.strip() else "body 为空/纯空白",
            )
        )
        target = str(facts.release.get("target_commitish") or "")
        if (
            _SHA_RE.match(target.lower())
            and facts.tag_commit
            and target.lower() != facts.tag_commit
        ):
            results.append(
                CheckResult(
                    "RELEASE_TARGET_COMMITISH == TAG_SHA",
                    FAIL,
                    expected=facts.tag_commit[:12],
                    observed=target[:12],
                    detail="Release 对象钉住的 commit 与 tag 解析结果背离",
                )
            )
        elif target:
            results.append(
                CheckResult(
                    "RELEASE_TARGET_COMMITISH == TAG_SHA",
                    PASS,
                    observed=target,
                    detail="target_commitish 为分支名/引用(非 SHA),按创建约定视为一致",
                )
            )

    # ---- 生产与验收(仅 closure/audit)----
    if mode in (MODE_CLOSURE, MODE_AUDIT):
        release_sha = _release_sha(facts)
        if facts.production_fetch_error:
            results.append(
                CheckResult(
                    "PRODUCTION_SHA == RELEASE_SHA",
                    FAIL,
                    observed=facts.production_fetch_error,
                    detail="证据源不可用按失败处理",
                )
            )
        elif not facts.production_deployments:
            results.append(
                CheckResult(
                    "PRODUCTION_SHA == RELEASE_SHA",
                    FAIL,
                    observed="GitHub Deployments API environment=production 无任何记录",
                    detail="生产 SHA 今日无机器可读记录源即视为未闭环;"
                    "接口:scripts/record_production_deployment.py(部署后运行一次)",
                )
            )
        elif not release_sha:
            results.append(
                CheckResult("PRODUCTION_SHA == RELEASE_SHA", FAIL, detail="release SHA 无从锚定")
            )
        else:
            latest = (
                facts.production_deployments[0]
                if isinstance(facts.production_deployments[0], dict)
                else {}
            )
            prod_sha = normalize_sha(str(latest.get("sha") or ""))
            payload = latest.get("payload") if isinstance(latest.get("payload"), dict) else {}
            payload_sha = normalize_sha(str((payload or {}).get("git_sha") or ""))
            observed = prod_sha or "(空)"
            detail = f"生产记录 created_at={latest.get('created_at', '')}"
            if payload_sha and payload_sha != prod_sha:
                # 记录自相矛盾:sha 字段与 payload.git_sha 不一致 → 证据不可信,不放行
                results.append(
                    CheckResult(
                        "PRODUCTION_SHA == RELEASE_SHA",
                        FAIL,
                        expected=release_sha,
                        observed=observed,
                        detail=detail + f";payload.git_sha={payload_sha}(记录内部自相矛盾)",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        "PRODUCTION_SHA == RELEASE_SHA",
                        PASS if prod_sha == release_sha else FAIL,
                        expected=release_sha,
                        observed=observed,
                        detail=detail,
                    )
                )

        # ---- PRODUCTION DEPLOYMENT STATUS == success(adoption 跟进 ①)----
        # 记录存在 + SHA 一致 ≠ 生产在位:权威记录还必须持有 effective/latest
        # status=success。无状态/queued/in_progress/pending/failure/error/
        # inactive/状态源不可用/载荷畸形一律 FAIL,绝不降级为 warning,也绝不
        # 把"状态源不可用"当作"无状态"或"成功"。status=success 是**已通过
        # 运行时身份核验的部署**的机器可读镜像 —— 写记录本身不制造生产事实。
        if facts.production_fetch_error:
            results.append(
                CheckResult(
                    "PRODUCTION DEPLOYMENT STATUS == success",
                    FAIL,
                    observed=facts.production_fetch_error,
                    detail="生产证据源不可用按失败处理,状态无从核验",
                )
            )
        elif not facts.production_deployments:
            results.append(
                CheckResult(
                    "PRODUCTION DEPLOYMENT STATUS == success",
                    FAIL,
                    observed="无权威生产记录",
                    detail="记录缺失时状态无从核验(见 PRODUCTION_SHA 检查)",
                )
            )
        elif facts.production_statuses_error:
            results.append(
                CheckResult(
                    "PRODUCTION DEPLOYMENT STATUS == success",
                    FAIL,
                    observed=facts.production_statuses_error,
                    detail="状态证据源不可用按失败处理,不得当作「无状态」或「成功」",
                )
            )
        else:
            latest_status, status_err = effective_production_status(facts.production_statuses)
            if status_err:
                results.append(
                    CheckResult(
                        "PRODUCTION DEPLOYMENT STATUS == success",
                        FAIL,
                        observed=status_err,
                        detail="状态载荷畸形不放行",
                    )
                )
            elif latest_status is None:
                results.append(
                    CheckResult(
                        "PRODUCTION DEPLOYMENT STATUS == success",
                        FAIL,
                        observed="权威记录无任何 Deployment Status",
                        detail="部署存在但从未被确认:记录方须在 update.sh 成功 +"
                        " /health 身份核验后回写 success 状态",
                    )
                )
            else:
                state = str(latest_status.get("state") or "").strip()
                observed = f"state={state} created_at={latest_status.get('created_at', '')}"
                if state.lower() == SUCCESS_STATE:
                    results.append(
                        CheckResult(
                            "PRODUCTION DEPLOYMENT STATUS == success",
                            PASS,
                            observed=observed,
                            detail="仅 effective/latest status=success 证明部署已被确认",
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            "PRODUCTION DEPLOYMENT STATUS == success",
                            FAIL,
                            expected="success",
                            observed=observed,
                            detail="非 success 状态(queued/in_progress/pending/"
                            "failure/error/inactive)不证明生产在位",
                        )
                    )

        if facts.acceptance_manifest_error:
            results.append(
                CheckResult(
                    "RUNTIME_ACCEPTANCE_SHA == RELEASE_SHA",
                    FAIL,
                    observed=facts.acceptance_manifest_error,
                    detail="坏证据 ≠ 缺证据,同样不放行",
                )
            )
        elif facts.acceptance_manifest is None:
            results.append(
                CheckResult(
                    "RUNTIME_ACCEPTANCE_SHA == RELEASE_SHA",
                    FAIL,
                    observed=f"{ACCEPTANCE_DIR}/{normalize_version(tag)}.json 不存在",
                    detail="约定:人工验收证据经可审阅 manifest 入库" "(schema 见本脚本 docstring)",
                )
            )
        elif not release_sha:
            results.append(
                CheckResult(
                    "RUNTIME_ACCEPTANCE_SHA == RELEASE_SHA", FAIL, detail="release SHA 无从锚定"
                )
            )
        else:
            acc_sha = normalize_sha(facts.acceptance_manifest["git_sha"])
            results.append(
                CheckResult(
                    "RUNTIME_ACCEPTANCE_SHA == RELEASE_SHA",
                    PASS if acc_sha == release_sha else FAIL,
                    expected=release_sha,
                    observed=acc_sha,
                    detail=(
                        f"verified_at={facts.acceptance_manifest['verified_at']} "
                        f"report={facts.acceptance_manifest['report_path']}"
                    ),
                )
            )

        # ---- RUNTIME_ACCEPTANCE_REPORT_PROVENANCE(adoption 跟进 ②)----
        # report_path 仅非空不够:必须解析为仓库内被 git 跟踪的真实文件,
        # 否则验收报告可指向任意外部路径而无法审阅。
        if facts.acceptance_manifest_error:
            results.append(
                CheckResult(
                    "RUNTIME_ACCEPTANCE_REPORT_PROVENANCE",
                    FAIL,
                    observed=facts.acceptance_manifest_error,
                    detail="manifest 非法,报告来源无从验证",
                )
            )
        elif facts.acceptance_manifest is None:
            results.append(
                CheckResult(
                    "RUNTIME_ACCEPTANCE_REPORT_PROVENANCE",
                    FAIL,
                    observed=f"{ACCEPTANCE_DIR}/{normalize_version(tag)}.json 不存在",
                    detail="无 manifest 即无验收报告来源",
                )
            )
        else:
            resolved, report_err = resolve_report_artifact(
                str(facts.acceptance_manifest.get("report_path") or ""),
                repo_root,
                runner or _default_runner(),
            )
            results.append(
                CheckResult(
                    "RUNTIME_ACCEPTANCE_REPORT_PROVENANCE",
                    FAIL if report_err else PASS,
                    observed=resolved or "(空)",
                    detail=report_err or "report_path 解析为仓库内被 git 跟踪的真实文件",
                )
            )

    return results


# ---------------------------------------------------------------- 入口


def facts_from_json(path: str) -> ReleaseFacts:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return ReleaseFacts(
        tag=data["tag"],
        expected_sha=data.get("expected_sha"),
        tag_exists=bool(data.get("tag_exists")),
        tag_commit=data.get("tag_commit"),
        release=data.get("release"),
        release_fetch_error=data.get("release_fetch_error"),
        production_deployments=data.get("production_deployments") or [],
        production_fetch_error=data.get("production_fetch_error"),
        production_statuses=data.get("production_statuses") or [],
        production_statuses_error=data.get("production_statuses_error"),
        acceptance_manifest=data.get("acceptance_manifest"),
        acceptance_manifest_error=data.get("acceptance_manifest_error"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Release lifecycle integrity guard(#10)")
    parser.add_argument("--mode", choices=MODES, default=MODE_AUDIT)
    parser.add_argument("--tag", help="release tag;audit 缺省取最新 vX.Y.Z")
    parser.add_argument("--expected-sha", help="冻结的接受 release SHA(release-publish 必填)")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO)
    parser.add_argument("--acceptance-dir", default=ACCEPTANCE_DIR)
    parser.add_argument(
        "--repo-root",
        default=".",
        help="仓库根(report_path 入库核验的 git 边界;缺省当前目录)",
    )
    parser.add_argument("--facts-json", help="离线喂采集结果(测试/诊断),跳过 git+GitHub 采集")
    parser.add_argument("--output-json", help="把逐项判定写入该 JSON 文件")
    args = parser.parse_args(argv)

    runner = _default_runner()

    if args.facts_json:
        try:
            facts = facts_from_json(args.facts_json)
            if args.tag:
                facts.tag = args.tag
            if args.expected_sha:
                facts.expected_sha = normalize_sha(args.expected_sha)
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            print(f"❌ --facts-json 不可用:{exc}", file=sys.stderr)
            return 2
    else:
        try:
            facts = collect_facts(
                args.mode,
                args.tag,
                args.expected_sha,
                args.repo,
                runner,
                lambda r, p: fetch_github_json(r, p, _token()),
            )
        except CollectionError as exc:
            print(f"❌ 采集失败(fail-closed):{exc}", file=sys.stderr)
            return 1

    results = evaluate(facts, args.mode, repo_root=args.repo_root, runner=runner)
    failures = [r for r in results if r.status == FAIL]

    print("== Release Integrity Guard ==")
    print(f"mode={args.mode} tag={facts.tag} repo={args.repo}")
    for r in results:
        print(r.line())
    verdict = "PASS" if not failures else "FAIL"
    print(f"RELEASE INTEGRITY: {verdict} ({len(results)} invariants, {len(failures)} failures)")

    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "mode": args.mode,
                    "tag": facts.tag,
                    "verdict": verdict,
                    "results": [vars(r) for r in results],
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )
            fh.write("\n")
    return 0 if not failures else 1


def _token() -> str | None:
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")


if __name__ == "__main__":
    sys.exit(main())
