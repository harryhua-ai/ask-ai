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

用法(tesla-t4 或任意有网络处):

    GH_TOKEN=<token> python3 scripts/record_production_deployment.py --tag v1.3.0
    GH_TOKEN=<token> python3 scripts/record_production_deployment.py --tag v1.3.0 --sha <40位>
    # 可选 --note "部署说明";--repo 缺省 GITHUB_REPOSITORY 或 harryhua-ai/ask-ai

token 需要 repo 级 deployments 写权限(classic: repo;fine-grained:
Contents/Deployments write)。重复运行会新建 Deployment 记录(审计留痕,
守卫永远读最新一条)。

退出码:0 = 记录成功;1 = API 失败(记录未落,守卫侧将保持 fail-closed);
2 = 用法错误(缺 token/缺 tag)。
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="记录一次生产部署到 GitHub Deployments")
    parser.add_argument("--tag", required=True, help="本次部署的 release tag(如 v1.3.0)")
    parser.add_argument("--sha", help="发布 commit;缺省用 git 解析 --tag")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO)
    parser.add_argument("--note", default="")
    parser.add_argument("--repo-dir", default=".", help="git 仓库根(解析 tag 用)")
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
        deployment = _request(
            args.repo,
            "/deployments",
            token,
            {
                "ref": sha,
                "environment": ENVIRONMENT,
                "description": f"ask-ai {args.tag} 生产部署(update.sh 完成后记录)",
                "auto_merge": False,
                "required_contexts": [],
                "payload": {
                    "tag": args.tag,
                    "git_sha": sha,
                    "recorded_by": "scripts/record_production_deployment.py",
                    **({"note": args.note} if args.note else {}),
                },
            },
        )
        _request(
            args.repo,
            f"/deployments/{deployment['id']}/statuses",
            token,
            {
                "state": "success",
                "environment": ENVIRONMENT,
                "description": f"deployed {args.tag} @ {sha[:12]}",
            },
        )
    except urllib.error.HTTPError as exc:
        print(
            f"❌ GitHub API 拒绝记录(HTTP {exc.code}):{exc.read().decode('utf-8', 'replace')[:300]}",
            file=sys.stderr,
        )
        return 1
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
        print(f"❌ 记录失败(网络/响应异常):{exc}", file=sys.stderr)
        return 1

    print(f"✅ 已记录生产部署:environment={ENVIRONMENT} tag={args.tag} sha={sha[:12]}")
    print(f"   deployment id={deployment['id']} url={deployment.get('html_url', '')}")
    print(
        "   守卫核验:python3 scripts/release_integrity_check.py --mode production-closure --tag "
        f"{args.tag}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
