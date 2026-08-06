"""DB data_sources 迁移:local_git → github(clone 型) + 删除废弃旧 github REST 源。

背景:
- 决策 2A:github 统一为唯一 git 源类型,local_git 移除 @register。
- 生产 DB 现有 10 个 local_git 源(repo_path + branches + file_types,真增量生产源)
  与 10 个旧 github REST 源(owner/repo/branch/include_dirs,早期 REST API 源,已被
  local_git 取代但 enabled=true)。
- 新 GitHubConnector 读 ``config['repo_url']`` —— 旧 REST 源(owner/repo 无 repo_url)
  实例化会 KeyError,必须清理。

迁移动作:
1. local_git 源 → github:
   - ``repo_url`` = ``https://github.com/camthink-ai/<repo_path basename>.git``
     (repo_path basename 精确对应仓库名,核对自 DB:全部 camthink-ai org)
   - ``clone_path`` = 原 repo_path(复用现有 clone 副本,_ensure_cloned 见存在跳过)
   - ``branches`` / ``file_types`` / 可选 exclude_* 保留
   - id / product / enabled / sync_interval 不变(文档 source_id 不变,无需 reindex)
2. 删除废弃旧 github REST 源(config 含 owner/repo 且无 repo_url)。

幂等:重复运行无副作用(local_git 已无,旧 REST 已删)。

用法:
    DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai \\
    python scripts/migrate_github_source_schema.py [--dry-run]

    注:未设 DATABASE_URL 时回退到开发库默认串。dry-run 只 SELECT,不写。
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# 所有 local_git 源 repo_path 都在 camthink-ai org 下(核对自 DB 现有 github 源 owner)
GITHUB_ORG = "camthink-ai"
DEFAULT_DSN = "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai"


def _resolve_dsn() -> str:
    """从 DATABASE_URL 取连接串,回退开发库默认;强制 asyncpg 驱动。"""
    dsn = os.environ.get("DATABASE_URL", DEFAULT_DSN)
    if dsn.startswith("postgresql://"):
        dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    return dsn


def build_github_config(local_git_config: dict) -> dict:
    """local_git config → 新 github config。

    Args:
        local_git_config: 迁移前的 local_git config(repo_path / branches / file_types)。

    Returns:
        新 github config(repo_url / clone_path / branches / file_types + 可选 exclude)。
    """
    repo_path = local_git_config.get("repo_path", "")
    repo_name = Path(repo_path).name
    new_config: dict = {
        "repo_url": f"https://github.com/{GITHUB_ORG}/{repo_name}.git",
        "clone_path": repo_path,  # 复用现有 clone 副本
        "branches": list(local_git_config.get("branches", ["main"])),
        "file_types": list(local_git_config.get("file_types", [".py"])),
    }
    # 保留可选过滤字段(若有)
    if local_git_config.get("exclude_dirs"):
        new_config["exclude_dirs"] = list(local_git_config["exclude_dirs"])
    if local_git_config.get("exclude_regex"):
        new_config["exclude_regex"] = local_git_config["exclude_regex"]
    if local_git_config.get("max_file_size") is not None:
        new_config["max_file_size"] = local_git_config["max_file_size"]
    if local_git_config.get("channel_visibility"):
        new_config["channel_visibility"] = list(local_git_config["channel_visibility"])
    return new_config


def is_legacy_rest_github(config: dict) -> bool:
    """旧 github REST 源:config 含 owner/repo 但无 repo_url(已被 local_git 取代)。

    新 github(clone 型)源 config 以 repo_url 为必填,不含 owner/repo。
    """
    return "owner" in config and "repo" in config and "repo_url" not in config


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="只打印,不写 DB")
    args = ap.parse_args()

    dsn = _resolve_dsn()
    print(f"DB: {_mask(dsn)}  mode: {'dry-run' if args.dry_run else 'APPLY'}")
    engine = create_async_engine(dsn)
    migrated = legacy_deleted = 0

    async with engine.begin() as conn:
        # 1. local_git → github + 新 schema
        result = await conn.execute(
            text(
                "SELECT id, product, config "
                "FROM data_sources WHERE type = 'local_git' ORDER BY id"
            )
        )
        rows = result.fetchall()
        print(f"\nlocal_git 源: {len(rows)} 个 → 迁移为 github(clone 型)")
        for ds_id, product, config in rows:
            new_config = build_github_config(config)
            repo_url = new_config["repo_url"]
            if args.dry_run:
                print(f"  [dry-run] {ds_id} (product={product})")
                print(f"            repo_url   = {repo_url}")
                print(f"            clone_path = {new_config['clone_path']}")
                print(f"            branches   = {new_config['branches']}")
                print(f"            file_types = {new_config['file_types']}")
            else:
                await conn.execute(
                    text("UPDATE data_sources SET type='github', config=CAST(:c AS jsonb) WHERE id=:id"),
                    {"c": json.dumps(new_config), "id": ds_id},
                )
                print(f"  migrated {ds_id}: {repo_url} branches={new_config['branches']}")
            migrated += 1

        # 2. 删除废弃旧 github REST 源(owner/repo 无 repo_url)
        #    注:步骤 1 APPLY 后,新迁移的 github 源有 repo_url,不会被识别为 legacy。
        result = await conn.execute(
            text("SELECT id, config FROM data_sources WHERE type = 'github' ORDER BY id")
        )
        legacy_ids = [r[0] for r in result.fetchall() if is_legacy_rest_github(r[1])]
        print(f"\n废弃旧 github REST 源: {len(legacy_ids)} 个 → {'待删' if args.dry_run else '删除'}")
        for ds_id in legacy_ids:
            print(f"  {'[dry-run] 待删' if args.dry_run else 'deleted'} {ds_id}")
        if legacy_ids and not args.dry_run:
            await conn.execute(
                text("DELETE FROM data_sources WHERE id = ANY(:ids)"),
                {"ids": legacy_ids},
            )
        legacy_deleted = len(legacy_ids)

    await engine.dispose()
    print(
        f"\n汇总: 迁移 {migrated} local_git→github, 删除 {legacy_deleted} 废弃旧 github REST。"
        f"{'(dry-run,未写)' if args.dry_run else ''}"
    )
    return 0


def _mask(dsn: str) -> str:
    """dsn 密码打码,便于日志输出。"""
    if "@" in dsn and "://" in dsn:
        head, tail = dsn.rsplit("@", 1)
        if ":" in head:
            head = head.rsplit(":", 1)[0] + ":***"
        return f"{head}@{tail}"
    return dsn


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
