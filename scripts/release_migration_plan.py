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

   条目按序执行、幂等(存量库可重复执行)。清单与代码同树同 tag —— 迁移需求
   与发布身份天然绑定,不存在 mutable-main 歧义。

2. **历史桥(窄,仅清单机制诞生前的已冻结发布)**:桥是封闭集合,只允许引用
   「该冻结发布镜像内确实存在」的脚本(workflow 在执行任何镜像代码前先断言
   镜像内 RELEASE.json == 冻结身份,update.sh [3/6] 同款)—— 即迁移代码来自
   冻结工件而非 mutable main。桥只减不增。

**契约边界(确定性、可测试、不依赖 mutable main)**:一个冻结发布是否受清单
契约约束,由**其自身谱系**决定 —— 谱系中存在「新增 deploy/prod/migrations.json」
的提交(`git log <sha> --diff-filter=A`)即属契约时代。由此:

- A. 契约前历史发布(谱系从未引入清单机制):只允许历史桥;桥无条目 →
  NONE(MIGRATION NOT REQUIRED,唯一允许缺清单的路径);
- B. 契约时代发布:树内**必须**存在 migrations.json —— 缺失 = 退出码 1
  fail-closed,部署绝不得进行(例如清单曾入谱系后被从树中删除/遗忘,一律
  拒绝),**绝不从「文件缺失」推断「无迁移」**;
- C. 空清单 ``{"migrations":[]}`` = 权威的 MIGRATION NOT REQUIRED。

解析优先级:树内有清单 → 只用清单(桥不参与);树内无清单且属契约时代 →
FAIL;历史时代 → 查桥;桥无条目 → NONE。

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


def _manifest_contract_era(repo_root: str, sha: str) -> bool:
    """判定冻结发布是否受迁移清单契约约束(§2 契约边界,确定性且不依赖 mutable main)。

    边界 = **该发布自身谱系**中是否存在「新增 MANIFEST_PATH」的提交
    (`git log <sha> --diff-filter=A -- <path>`;只读冻结 SHA 的祖先历史,与
    main/工作区当前状态无关)::

        True  = 契约时代发布:树内必须携带 migrations.json,缺失即 fail-closed;
        False = 契约前历史发布:仅允许历史桥,桥无条目 → NONE。

    前置:完整谱系(编排 checkout 为 fetch-depth: 0)。浅检出无法判定边界
    (git log 空手而归 ≠ 历史发布)→ 证据源不足,fail-closed。git 其余错误
    → 退出码 1(拒绝猜测)。
    """
    shallow = _git(repo_root, "rev-parse", "--is-shallow-repository")
    if shallow.returncode != 0:
        print(
            "❌ 判定迁移清单契约边界失败(无法探测检出深度;证据源不可用,拒绝猜测):"
            + shallow.stderr.strip()[:200],
            file=sys.stderr,
        )
        raise SystemExit(1)
    if shallow.stdout.strip() == "true":
        print(
            "❌ 浅检出(shallow clone)无法判定迁移清单契约边界:谱系历史不完整,"
            "缺失清单既可能是契约违例也可能是历史发布 —— 拒绝猜测(fail-closed;"
            "编排 checkout 为 fetch-depth: 0,不受影响)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    proc = _git(
        repo_root, "log", "--format=%H", "-n", "1", sha,
        "--diff-filter=A", "--", MANIFEST_PATH,
    )
    if proc.returncode != 0:
        print(
            f"❌ 判定迁移清单契约边界失败(git 退出码 {proc.returncode};证据源不可用,"
            "拒绝猜测):\n" + proc.stderr.strip()[:300],
            file=sys.stderr,
        )
        raise SystemExit(1)
    return bool(proc.stdout.strip())


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

    # 树内无清单:先判契约时代 —— 谱系已引入清单机制的发布缺清单 = fail-closed,
    # 绝不从「文件缺失」推断「无迁移」(v1.4.0 事故类别的最后防线)。
    if _manifest_contract_era(repo_root, sha):
        print(
            f"❌ 冻结发布 {tag}@{sha[:12]} 属迁移清单契约(谱系已引入 {MANIFEST_PATH})"
            "但树内缺失该文件 —— 缺失即失败(fail-closed),部署绝不得进行",
            file=sys.stderr,
        )
        raise SystemExit(1)

    bridge = BRIDGE_MIGRATIONS.get(tag)
    if bridge is not None:
        print(
            f"PLAN SOURCE: bridge(历史发布 {tag},谱系未引入清单机制;执行前镜像身份"
            "先断言)",
            file=sys.stderr,
        )
        return _validate_entries(repo_root, sha, list(bridge), f"bridge[{tag}]")

    print(
        f"⚠️ 冻结树 {sha[:12]} 无 {MANIFEST_PATH} 且谱系未引入清单机制(契约前历史发布)、"
        f"历史桥无 {tag} 条目 → MIGRATION NOT REQUIRED(仅历史发布允许此路径)",
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
