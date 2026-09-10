#!/usr/bin/env python3
"""把一次生产部署记录为 GitHub Deployment(#10 生命周期守卫的证据接口)。

背景:生产 SHA 今天只活在 tesla-t4 主机上(镜像内 RELEASE.json + /health),
GitHub 侧没有任何机器可读记录 → PRODUCTION_SHA == RELEASE_SHA 无法自动核验。
本脚本是**最小补充接口**:update.sh 完成部署后运行一次,把
(ref=<发布 SHA>, environment=production, payload={tag, git_sha}) 写进
GitHub Deployments API,守卫(scripts/release_integrity_check.py)即可核验。

只记录,不部署:本脚本不 touch 任何容器/服务;部署仍由
deploy/prod/update.sh <tag> 完成(其 fail-closed 契约不变)。

运行簿契约(强制顺序,不可颠倒 —— adoption 跟进 ③):

    1. DEPLOY    deploy/prod/update.sh <tag> 完整成功(退出码 0);
    2. VERIFY    update.sh 的 fail-closed 核验全部通过:镜像内 RELEASE.json
                 version/git_sha 断言([3/6])+ /health 运行时 version 与
                 请求 tag 一致([5/6])+ 三服务同 tag([6/6]);
    3. RECORD    此后才允许运行本脚本,回写 deployment + status=success。

绝不允许:未部署先记录 / update.sh 失败仍记录 / 部署命令刚启动就记录成功。
status=success 只是「已通过运行时身份核验的部署」的机器可读**镜像**,
不是部署事实本身;本脚本无法远程核验上述顺序(低层记录原语),顺序责任
在运行簿 —— 见 deploy/prod/update.sh 头部「部署后证据记录」。违反顺序
写入的记录是伪证;守卫侧仍会独立核验 PRODUCTION_SHA == RELEASE_SHA 与
Runtime Acceptance,单条记录不足以闭环。

分阶段生命周期(--phase,生产部署编排专用 —— 单一证据写者):

    create        新建 Deployment + status=in_progress(编排层在 update.sh
                  **启动前**建立在途记录;in_progress 在守卫侧 ≠ success,
                  不构成任何"已部署"声明);
    success       给既有记录追加 status=success(仅在运行时身份双断言
                  /health.version==version 且 /health.git_sha==发布 SHA
                  通过后,由编排层调用);
    failure|error 给既有记录追加对应状态(SSH/锁/update.sh/身份核验/证据
                  落盘任一失败后调用;中途取消/传输不确定时**不得**写
                  success —— 状态非 success 在守卫侧一律 fail-closed)。

    success/failure/error 按 (sha + environment) 解析最新记录,或用
    --deployment-id 显式钉死;找不到记录 → 退出码 2(不得凭空新建成功)。
    省略 --phase = 历史原子模式:create + success 一次完成(break-glass
    手动路径沿用,契约不变:仅在部署成功且身份核验通过后运行)。

用法(tesla-t4 或任意有网络处):

    GH_TOKEN=<token> python3 scripts/record_production_deployment.py --tag v1.3.0
    GH_TOKEN=<token> python3 scripts/record_production_deployment.py --tag v1.3.0 --sha <40位>
    GH_TOKEN=<token> python3 scripts/record_production_deployment.py \
        --tag v1.4.0 --sha <40位> --phase create          # 编排:在途记录
    GH_TOKEN=<token> python3 scripts/record_production_deployment.py \
        --tag v1.4.0 --sha <40位> --phase success         # 编排:身份核验通过后
    # 可选 --note "部署说明";--repo 缺省 GITHUB_REPOSITORY 或 harryhua-ai/ask-ai
    # --deployment-id <id> 显式钉死要追加状态的记录(缺省按 sha 解析最新)

token 需要 repo 级 deployments 写权限(classic: repo;fine-grained:
Contents/Deployments write)。重复运行会新建 Deployment 记录(审计留痕,
守卫永远读最新一条)。

退出码:0 = 记录成功;1 = API 失败(记录未落,守卫侧将保持 fail-closed);
2 = 用法错误(缺 token/缺 tag)或待追加状态的记录不存在。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

DEFAULT_REPO = "harryhua-ai/ask-ai"
ENVIRONMENT = "production"
API = "https://api.github.com"

# 分阶段生命周期状态(GitHub Deployment status 合法子集;create 阶段固定
# 追加 in_progress —— 守卫侧非 success 一律 fail-closed,不构成部署声明)
PHASES = ("create", "success", "failure", "error")
PHASE_STATE = {"create": "in_progress", "success": "success", "failure": "failure", "error": "error"}


def _request(repo: str, path: str, token: str, body: dict) -> dict:
    request = urllib.request.Request(
        f"{API}/repos/{repo}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_request(repo: str, path: str, token: str):
    """GET;404 → None;非 404/网络/解析错误 → SystemExit(1)(证据源不可用)。"""
    request = urllib.request.Request(
        f"{API}/repos/{repo}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        print(f"❌ GitHub API GET {path} HTTP {exc.code}(证据源不可用)", file=sys.stderr)
        raise SystemExit(1) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"❌ GitHub API GET {path} 不可达:{exc}(证据源不可用)", file=sys.stderr)
        raise SystemExit(1) from exc


def resolve_sha(repo_dir: str, tag: str) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", f"{tag}^{{commit}}"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise SystemExit(f"❌ 无法把 {tag} 解析为 commit(检查 tag 是否存在)")
    return proc.stdout.strip()


def create_deployment(repo: str, token: str, tag: str, sha: str, note: str, phase: str | None) -> dict:
    """新建 Deployment 记录(证据创建唯一入口;成功状态由调用方按契约回写)。"""
    recorded_by = "scripts/record_production_deployment.py"
    if phase == "create":
        recorded_by += " (--phase create)"
    return _request(
        repo,
        "/deployments",
        token,
        {
            "ref": sha,
            "environment": ENVIRONMENT,
            "description": f"ask-ai {tag} 生产部署(update.sh 完成后记录)"
            if phase is None
            else f"ask-ai {tag} 生产部署(编排在途记录)",
            "auto_merge": False,
            "required_contexts": [],
            "payload": {
                "tag": tag,
                "git_sha": sha,
                "recorded_by": recorded_by,
                **({"note": note} if note else {}),
            },
        },
    )


def append_status(repo: str, token: str, deployment_id: int, state: str, tag: str, sha: str) -> dict:
    return _request(
        repo,
        f"/deployments/{deployment_id}/statuses",
        token,
        {
            "state": state,
            "environment": ENVIRONMENT,
            "description": f"{state} {tag} @ {sha[:12]}",
        },
    )


def resolve_latest_deployment(repo: str, token: str, sha: str) -> int | None:
    """按精确 sha + environment 解析最新记录;API 顺序无文档保证 → 按 id 最大。"""
    data = _get_request(
        repo,
        f"/deployments?sha={sha}&environment={ENVIRONMENT}&per_page=100",
        token,
    )
    if not isinstance(data, list) or not data:
        return None
    entries = [d for d in data if isinstance(d, dict) and str(d.get("id") or "").strip().isdigit()]
    if not entries:
        return None
    return max(int(str(d["id"])) for d in entries)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="记录一次生产部署到 GitHub Deployments")
    parser.add_argument("--tag", required=True, help="本次部署的 release tag(如 v1.3.0)")
    parser.add_argument("--sha", help="发布 commit;缺省用 git 解析 --tag")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO)
    parser.add_argument("--note", default="")
    parser.add_argument("--repo-dir", default=".", help="git 仓库根(解析 tag 用)")
    parser.add_argument(
        "--phase",
        choices=PHASES,
        help=(
            "分阶段生命周期: create=in_progress 在途记录;success/failure/error=给既有"
            "记录追加状态。缺省 = 历史原子模式(create+success 一次完成,break-glass 沿用)"
        ),
    )
    parser.add_argument(
        "--deployment-id",
        type=int,
        help="追加状态时显式钉死记录 id(缺省按 sha+environment 解析最新)",
    )
    args = parser.parse_args(argv)

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print('❌ 缺少 GH_TOKEN/GITHUB_TOKEN:没有凭证就不能伪造"已记录",直接拒绝', file=sys.stderr)
        return 2

    sha = (args.sha or resolve_sha(args.repo_dir, args.tag)).lower()
    if len(sha) != 40:
        print(f"❌ 需要 40 位完整 SHA 记录生产身份,得到 {sha!r}", file=sys.stderr)
        return 2

    try:
        if args.phase in ("success", "failure", "error"):
            deployment_id = args.deployment_id or resolve_latest_deployment(args.repo, token, sha)
            if deployment_id is None:
                print(
                    f"❌ 找不到 sha={sha[:12]} 的 production 部署记录,无从追加"
                    f" {PHASE_STATE[args.phase]} 状态(不得凭空新建成功)",
                    file=sys.stderr,
                )
                return 2
            status = append_status(
                args.repo, token, deployment_id, PHASE_STATE[args.phase], args.tag, sha
            )
            print(
                f"✅ 已记录部署状态:deployment={deployment_id} state={status.get('state', PHASE_STATE[args.phase])}"
                f" tag={args.tag} sha={sha[:12]}"
            )
            return 0

        deployment = create_deployment(args.repo, token, args.tag, sha, args.note, args.phase)
        deployment_id = deployment["id"]
        # 原子模式(break-glass)契约 = create + success 一次完成(仅在部署成功
        # 且身份核验通过后运行,见运行簿);create 阶段才是 in_progress 在途记录。
        legacy_state = "success" if args.phase is None else PHASE_STATE[args.phase]
        append_status(args.repo, token, deployment_id, legacy_state, args.tag, sha)
    except urllib.error.HTTPError as exc:
        print(
            f"❌ GitHub API 拒绝记录(HTTP {exc.code}):{exc.read().decode('utf-8', 'replace')[:300]}",
            file=sys.stderr,
        )
        return 1
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
        print(f"❌ 记录失败(网络/响应异常):{exc}", file=sys.stderr)
        return 1

    if args.phase == "create":
        print(f"✅ 已建立在途部署记录:environment={ENVIRONMENT} tag={args.tag} sha={sha[:12]}")
        print(f"   deployment id={deployment_id} url={deployment.get('html_url', '')}")
        print("   守卫侧 in_progress ≠ success;运行时身份双断言通过后以 --phase success 收尾")
    else:
        print(f"✅ 已记录生产部署:environment={ENVIRONMENT} tag={args.tag} sha={sha[:12]}")
        print(f"   deployment id={deployment_id} url={deployment.get('html_url', '')}")
        print(
            "   守卫核验:python3 scripts/release_integrity_check.py --mode production-closure --tag "
            f"{args.tag}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
