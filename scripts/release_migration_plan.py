#!/usr/bin/env python3
"""解析一个冻结发布身份需要执行哪些数据库迁移(v1.4.0 存量库事件矫正)。

事件背景(2026-09-10,run 34454739497):v1.4.0 依赖 site_experiences.launcher_presentation,
但既有生产库没有该列,部署生命周期也没有任何「迁移先于依赖它的新应用」环节 ——
backend 启动即崩、update.sh 健康轮询超时、部署失败、生产中断。本脚本是矫正的
**迁移所有权模型**:部署编排(workflow)在 rollout 之前调用它,得到该发布
**必须执行**的迁移清单,然后逐条在冻结发布镜像内执行(执行载体 = 既有
compose 一次性服务 `sync`,与 README 的 `run --rm sync python scripts/…` 同款)。

所有权模型(持久机制,杜绝 `if version == vX` 永久硬编码):

1. **发布自有清单(权威,面向未来)**:冻结发布树内的
   ``deploy/prod/migrations.json``::

       {"migrations": ["scripts/migrate_xxx.py", ...]}   # 有序;空列表 = 无迁移

   契约:**清单机制存在后的每个发布树都必须携带该文件**(无迁移也要带空列表),
   条目按序执行、幂等(存量库可重复执行)。清单与代码同树同 tag —— 迁移需求
   与发布身份天然绑定,不存在 mutable-main 歧义。

2. **历史桥(窄,仅清单机制诞生前的已冻结发布)**:这些树的清单永久缺失,
   桥是唯一补救口径。桥**只允许**引用「该冻结发布镜像内确实存在」的脚本
   (workflow 在执行任何镜像代码前先断言镜像内 RELEASE.json == 冻结身份,
   update.sh [3/6] 同款)—— 即迁移代码来自冻结工件而非 mutable main。
   桥是封闭集合,只减不增;新发布一律走清单。

解析优先级:冻结树有清单 → 只用清单(桥不再参与);无清单 → 查桥;都没有 →
NONE(MIGRATION NOT REQUIRED)。清单缺失且无桥条目时 stderr 打印显式警告,
提醒「清单契约发布必须携带清单」。

fail-closed:清单非法 JSON / 非对象 / 缺 migrations / 条目非法(绝对路径、
路径穿越、越出 scripts/、非法字符、冻结树内不存在)→ 退出码 1,编排层随之中止,
绝不「带病继续 rollout」。

用法(部署编排 migrate 步;--sha 必须是 identity 步冻结的 40 位发布 SHA):

    python3 scripts/release_migration_plan.py --tag v1.5.0 --sha <40位> --repo-root .
    # stdout:每行一个 scripts/… 路径;无迁移时输出 NONE
    # stderr:PLAN SOURCE 说明(manifest@<sha12> / bridge / none)

退出码:0 = 有计划或 NONE;1 = 证据源不可用/清单非法(fail-closed);
2 = 用法错误(参数缺失/格式非法)。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

MANIFEST_PATH = "deploy/prod/migrations.json"

TAG_RE = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
# 迁移条目白名单:仅 scripts/ 下的 .py 相对路径;单字符集防注入(进 SSH env 前缀
# 与远端命令前还有 workflow 侧身份校验,这里保证解析器输出本身即安全数据)。
ENTRY_RE = re.compile(r"^scripts/[A-Za-z0-9_][A-Za-z0-9_./-]*\.py$")

# 历史桥(封闭集合):清单机制(deploy/prod/migrations.json)诞生**前**已冻结的
# 发布。键 = 精确 tag;值 = 该冻结镜像内存在的迁移脚本(镜像内 RELEASE.json
# 会在执行前与冻结 SHA 断言一致 —— 迁移代码来源 = 冻结工件,非 mutable main)。
# v1.4.0:site_experiences.launcher_presentation(I-UX-001 矫正列;镜像内含
# scripts/migrate_add_site_launcher_presentation.py,与 tag 41278f0 同 blob)。
BRIDGE_MIGRATIONS: dict[str, tuple[str, ...]] = {
    "v1.4.0": ("scripts/migrate_add_site_launcher_presentation.py",),
}


def _git(repo_root: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", repo_root, *args], capture_output=True, text=True, check=False
    )


def _read_frozen_file(repo_root: str, sha: str, path: str) -> str | None:
    """读冻结树内文件;文件不在该树内 → None;其他 git 错误 → fail-closed。"""
    proc = _git(repo_root, "show", f"{sha}:{path}")
    if proc.returncode == 0:
        return proc.stdout
    # 「does not exist」= 树内从未有;「exists on disk, but not in」= 磁盘有但
    # 冻结树无(未随 tag 提交)。两者都是确定性的「该冻结树无此文件」。
    if (
        "does not exist" in proc.stderr
        or "pathspec" in proc.stderr
        or "exists on disk, but not in" in proc.stderr
    ):
        return None
    print(
        f"❌ 读取冻结树 {path} 失败(git 退出码 {proc.returncode};证据源不可用,"
        "拒绝猜测):\n" + proc.stderr.strip()[:300],
        file=sys.stderr,
    )
    raise SystemExit(1)


def _entry_exists_in_tree(repo_root: str, sha: str, path: str) -> bool:
    proc = _git(repo_root, "cat-file", "-e", f"{sha}:{path}")
    if proc.returncode == 0:
        return True
    if "does not exist" in proc.stderr or "pathspec" in proc.stderr:
        return False
    print(
        f"❌ 校验冻结树条目 {path} 失败(证据源不可用,拒绝猜测):\n"
        + proc.stderr.strip()[:300],
        file=sys.stderr,
    )
    raise SystemExit(1)


def _validate_entries(repo_root: str, sha: str, entries: object, source: str) -> list[str]:
    if not isinstance(entries, list) or not all(isinstance(e, str) for e in entries):
        print(
            f"❌ {source} 的 migrations 必须是字符串列表(fail-closed,拒绝猜测)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    plan: list[str] = []
    for entry in entries:
        if not ENTRY_RE.match(entry) or ".." in entry:
            print(
                f"❌ {source} 迁移条目非法:{entry!r}(仅允许 scripts/ 下 .py 相对路径,"
                "禁止绝对路径/穿越/特殊字符)",
                file=sys.stderr,
            )
            raise SystemExit(1)
        if not _entry_exists_in_tree(repo_root, sha, entry):
            print(
                f"❌ {source} 迁移条目在冻结树 {sha[:12]} 内不存在:{entry}(清单与"
                "代码必须同树同 tag;fail-closed)",
                file=sys.stderr,
            )
            raise SystemExit(1)
        plan.append(entry)
    return plan


def resolve_plan(tag: str, sha: str, repo_root: str) -> list[str]:
    """返回该冻结发布需执行的迁移脚本(有序);空列表 = MIGRATION NOT REQUIRED。"""
    manifest_raw = _read_frozen_file(repo_root, sha, MANIFEST_PATH)
    if manifest_raw is not None:
        try:
            manifest = json.loads(manifest_raw)
        except json.JSONDecodeError as exc:
            print(f"❌ {MANIFEST_PATH} 不是合法 JSON(fail-closed):{exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        if not isinstance(manifest, dict) or "migrations" not in manifest:
            print(
                f"❌ {MANIFEST_PATH} 必须是含 migrations 键的对象(fail-closed)",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print(f"PLAN SOURCE: manifest@{sha[:12]}", file=sys.stderr)
        return _validate_entries(repo_root, sha, manifest["migrations"], MANIFEST_PATH)

    bridge = BRIDGE_MIGRATIONS.get(tag)
    if bridge is not None:
        print(
            f"PLAN SOURCE: bridge(清单机制诞生前的历史发布 {tag};执行前镜像身份"
            "先断言)",
            file=sys.stderr,
        )
        return _validate_entries(repo_root, sha, list(bridge), f"bridge[{tag}]")

    print(
        f"⚠️ 冻结树 {sha[:12]} 无 {MANIFEST_PATH} 且历史桥无 {tag} 条目 → 视为无迁移。"
        f"契约:清单机制存在后的发布树必须携带 {MANIFEST_PATH}(无迁移也要空列表)",
        file=sys.stderr,
    )
    print("PLAN SOURCE: none", file=sys.stderr)
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="解析冻结发布身份的数据库迁移计划(部署编排 migrate 步专用)"
    )
    parser.add_argument("--tag", required=True, help="冻结发布 tag(如 v1.4.0)")
    parser.add_argument("--sha", required=True, help="identity 步冻结的 40 位发布 SHA")
    parser.add_argument("--repo-root", default=".", help="git 仓库根(读冻结树用)")
    args = parser.parse_args(argv)

    if not TAG_RE.match(args.tag):
        print(f"❌ --tag 必须是精确 vX.Y.Z,得到 {args.tag!r}", file=sys.stderr)
        return 2
    if not SHA_RE.match(args.sha):
        print(f"❌ --sha 必须是 40 位 commit SHA,得到 {args.sha!r}", file=sys.stderr)
        return 2

    plan = resolve_plan(args.tag, args.sha.lower(), args.repo_root)
    if not plan:
        print("NONE")
        return 0
    for entry in plan:
        print(entry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
