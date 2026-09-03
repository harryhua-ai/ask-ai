"""documents 身份迁移(Issue #13 Stage A,D1/D2 冻结契约)。

语义变更:
    旧:PK = (content_hash, branch) —— 内容寻址;同内容同分支只允许一行,
        行归属被"最后灌入者"抢占(Issue #13 根因 RC-1)。
    新:PK = (source_id) —— 路径(source document)身份;source_id 为
        复合路径串 `<source_id>/<branch>/<rel_path>`,每个真实文档一行;
        content_hash 降级为普通索引(内容指纹,保留同内容检测能力)。

要点:
- 零回填:source_id 列本就承载完整路径串(与向量库 uuid5(source_id#i)
  同一寻址),无需新增列/搬数据;Weaviate 零迁移。
- 幂等:已迁移(PK=source_id)时重复执行为 no-op;索引用 IF NOT EXISTS。
- 守卫:旧 PK 不阻止同 source_id 多行(同路径内容变更历史遗留),
  迁移前检测并合并(保留 updated_at 最新一行,删除其余),逐行报告。
- 可回滚:`--rollback` 恢复 (content_hash, branch) PK;若存在同
  (content_hash, branch) 多行则拒绝回滚(明确报错,不静默丢数据)。

用法:
    python scripts/migrate_documents_path_identity.py             # 正向
    python scripts/migrate_documents_path_identity.py --rollback  # 回滚
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text

from backend.config import load_settings
from backend.db.session import get_engine


def _pk_columns(sync_conn) -> list[str]:
    """返回 documents 表当前 PK 列序(run_sync 内同步执行)。"""
    insp = inspect(sync_conn)
    pk = insp.get_pk_constraint("documents")
    return list(pk.get("constrained_columns") or []) if pk else []


async def migrate(engine, *, rollback: bool = False) -> dict:
    """执行身份迁移(正向或回滚),返回动作报告(可审计)。

    全部 DDL 幂等;动作以报告形式逐条列出,便于 Production Repair Gate
    的 dry-run/apply 双阶段消费(本函数本身即"apply",调用方负责授权)。
    """
    actions: list[str] = []
    async with engine.begin() as conn:
        pk = await conn.run_sync(_pk_columns)

        if not rollback:
            if pk == ["source_id"]:
                # 幂等 no-op:仅确保指纹索引存在(幂等)
                await conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_documents_content_hash "
                        "ON documents (content_hash)"
                    )
                )
                actions.append("noop: already migrated (PK=source_id)")
                return {"actions": actions}

            if pk != ["content_hash", "branch"]:
                raise RuntimeError(
                    f"documents PK 为 {pk},既非旧契约 (content_hash, branch) 也非新契约 "
                    "(source_id),拒绝迁移(请人工核查 schema 演化)"
                )

            # 守卫:同 source_id 多行(旧 PK 下同路径内容变更的历史遗留)。
            # 合并策略 = 保留 updated_at 最新一行(权威最新状态),删除其余。
            dup_rows = (
                await conn.execute(
                    text(
                        "SELECT source_id, count(*) AS n FROM documents "
                        "GROUP BY source_id HAVING count(*) > 1 ORDER BY source_id"
                    )
                )
            ).all()
            for sid, n in dup_rows:
                await conn.execute(
                    text(
                        "DELETE FROM documents WHERE source_id = :sid "
                        "AND updated_at < (SELECT max(updated_at) FROM documents "
                        "WHERE source_id = :sid)"
                    ).bindparams(sid=sid)
                )
                actions.append(f"merge duplicate source_id rows: {sid} ({n} -> 1)")

            await conn.execute(text("ALTER TABLE documents DROP CONSTRAINT documents_pkey"))
            actions.append("drop PK (content_hash, branch)")
            await conn.execute(
                text("ALTER TABLE documents ADD CONSTRAINT documents_pkey PRIMARY KEY (source_id)")
            )
            actions.append("add PK (source_id)")
            # 旧模型 source_id 上的普通索引在 PK 下冗余,删除
            await conn.execute(text("DROP INDEX IF EXISTS ix_documents_source_id"))
            actions.append("drop redundant index ix_documents_source_id")
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_documents_content_hash ON documents (content_hash)"
                )
            )
            actions.append("ensure index ix_documents_content_hash")
        else:
            if pk != ["source_id"]:
                raise RuntimeError(f"documents PK 为 {pk},仅在 PK=source_id(已迁移)状态下支持回滚")
            dup = (
                await conn.execute(
                    text(
                        "SELECT content_hash, branch, count(*) FROM documents "
                        "GROUP BY content_hash, branch HAVING count(*) > 1 LIMIT 1"
                    )
                )
            ).first()
            if dup:
                raise RuntimeError(
                    f"存在同 (content_hash, branch) 多行(如 {dup[0][:12]}…/{dup[1]}),"
                    "回滚将违反旧 PK,拒绝(新契约下的合法共存行不可回滚)"
                )
            await conn.execute(text("ALTER TABLE documents DROP CONSTRAINT documents_pkey"))
            actions.append("drop PK (source_id)")
            await conn.execute(
                text(
                    "ALTER TABLE documents ADD CONSTRAINT documents_pkey "
                    "PRIMARY KEY (content_hash, branch)"
                )
            )
            actions.append("restore PK (content_hash, branch)")
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_documents_source_id ON documents (source_id)")
            )
            actions.append("restore index ix_documents_source_id")
            await conn.execute(text("DROP INDEX IF EXISTS ix_documents_content_hash"))
            actions.append("drop index ix_documents_content_hash")
    return {"actions": actions}


async def main() -> None:
    rollback = "--rollback" in sys.argv
    settings = load_settings(
        config_dir=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config"
        )
    )
    engine = get_engine(settings.postgres_dsn)
    try:
        report = await migrate(engine, rollback=rollback)
        for a in report["actions"]:
            print(f"[migrate-documents-identity] {a}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
