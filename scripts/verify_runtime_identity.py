#!/usr/bin/env python3
"""生产运行时身份双断言(#10 · 生产部署编排的 VERIFY 步骤)。

对运行中生产实例的 ``/health`` 上报身份做**独立**核验:

    version == 请求的发布版本(无 v 前缀 SemVer)
    且
    git_sha == 冻结的发布 commit(40 位,仓库侧权威解析)

两者同时通过才允许把 Deployment 状态收尾为 success;任一不满足 → 退出码 1,
**绝不允许 success**。编排路径(deploy-production.yml)与 break-glass 手动
路径共用本实现,保证两条路径核验语义逐位一致。

/health 身份来自进程启动时一次性加载的镜像内 RELEASE.json(不可变,
backend/main.py),非环境可变值 —— 比对它即比对"正在运行的那个实例"。

用法:

    curl -sf http://localhost:18000/health | \\
        python3 scripts/verify_runtime_identity.py --expect-version 1.4.0 \\
            --expect-sha <40位>
    python3 scripts/verify_runtime_identity.py --expect-version 1.4.0 \\
        --expect-sha <40位> --health-file /tmp/health.json

退出码:0 = 双断言通过;1 = 身份不匹配/数据缺失(fail-closed);
2 = 用法错误。
"""

from __future__ import annotations

import argparse
import json
import re
import sys

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def verify(health: dict, expect_version: str, expect_sha: str) -> tuple[bool, str]:
    """返回 (通过, 诊断)。缺字段/不匹配一律不通过(绝不放行)。"""
    actual_version = str(health.get("version") or "")
    actual_sha = str(health.get("git_sha") or "").strip().lower()
    version_ok = actual_version == expect_version
    sha_ok = bool(_SHA_RE.match(actual_sha)) and actual_sha == expect_sha.strip().lower()
    if version_ok and sha_ok:
        return True, f"version={actual_version} git_sha={actual_sha} 双断言通过"
    detail = (
        f"version 期望 {expect_version} 实得 {actual_version or '(缺失)'};"
        f"git_sha 期望 {expect_sha[:12]} 实得 {actual_sha[:12] or '(缺失)'}"
    )
    if not _SHA_RE.match(actual_sha):
        detail += "(git_sha 非法/缺失,fail-closed)"
    return False, detail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生产 /health 运行时身份双断言(version + git_sha)")
    parser.add_argument("--expect-version", required=True, help="期望版本(无 v 前缀,如 1.4.0)")
    parser.add_argument("--expect-sha", required=True, help="冻结的发布 commit(40 位)")
    parser.add_argument(
        "--health-file", help="/health JSON 文件;缺省从 stdin 读(如 curl 管道)"
    )
    args = parser.parse_args(argv)

    if not _SHA_RE.match(args.expect_sha.strip().lower()):
        print(f"❌ --expect-sha 须为 40 位 commit,得到 {args.expect_sha!r}", file=sys.stderr)
        return 2

    raw = open(args.health_file, encoding="utf-8").read() if args.health_file else sys.stdin.read()
    try:
        health = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"❌ /health 响应不可解析(坏证据 ≠ 通过证据):{exc}", file=sys.stderr)
        return 1
    if not isinstance(health, dict):
        print("❌ /health 响应非对象,fail-closed", file=sys.stderr)
        return 1

    ok, detail = verify(health, args.expect_version, args.expect_sha)
    if not ok:
        print(f"❌ 运行时身份不匹配,绝不允许 success:{detail}", file=sys.stderr)
        return 1
    print(f"✅ 运行时身份核验通过:{detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
