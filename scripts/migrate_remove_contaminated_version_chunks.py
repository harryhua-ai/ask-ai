"""INC-WEB-EMBED-413 矫正:清除误挂进现行版本的越界持久 chunk 行。

生产事实(2026-09-14,website-camthink):``migrate_p1_lifecycle_foundation.py``
内容回填旧实现把每个 Weaviate 对象的 chunk 行无条件挂到该文档**现行版本**
(仅按 (version_id, chunk_index) 去重)。文档演进(新版本激活)后重跑回填,
legacy 对象的超限行(3005/2452 字符)被误挂进新现行版本 → sync gap-heal
修复重放把这些行原样送嵌入 → HTTP 413 ``text exceeds max_length=1024``
→ 修复代零激活,小时级 cron 连续复现(gens 11–15)。

本迁移删除**结构上可证明为误挂**的行,幂等、范围精确:

    document_version_chunks 行,其所属版本满足
        generation_ordinal > 0            (构建激活写入的世界)
        AND chunk_index >= version.chunk_count

依据:ordinal > 0 的版本由构建原子激活写入,激活不变量 = 持久行恰为
0..chunk_count-1;任何 idx ≥ chunk_count 的行都违背该不变量,即回填误挂
(回填 1:1 拷贝 legacy 对象全量 index,无现行版本范围意识)。ordinal = 0
的 legacy 初始版本**不在范围内** —— 其 1:1 全量拷贝是迁移冻结契约
(FIX-1 NUL 矫正同批),保持原样。

幂等:重跑命中 0 行即 no-op。不触碰 Weaviate、不重嵌、不改未命中行。
回填归属矫正(同事故根因 1 的代码修复)见 migrate_p1_lifecycle_foundation
的 ``_version_id_map``;本脚本只清除**已写入**的误挂行。

应用侧鲁棒性(迁移执行前的过渡窗):修复重放已按版本权威范围
(chunk_index < chunk_count)限界并路由超契约文档源重建(generation_builder);
一致性校验按现行版本代在服口径计数(vector_consistency)。本迁移进一步
恢复 U-9 chunk serving 投影的行数口径真值(total = 行数 = chunk_count)。
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from backend.config import load_settings
from backend.db.session import get_engine

_CONTAMINATED_SQL = """
SELECT c.id, v.source_id, v.generation_ordinal, v.chunk_count, c.chunk_index, length(c.text)
FROM document_version_chunks c
JOIN document_versions v ON v.id = c.version_id
WHERE v.generation_ordinal > 0
  AND c.chunk_index >= v.chunk_count
"""

_DELETE_SQL = """
DELETE FROM document_version_chunks c
USING document_versions v
WHERE v.id = c.version_id
  AND v.generation_ordinal > 0
  AND c.chunk_index >= v.chunk_count
"""


async def migrate(engine) -> dict:
    """清除误挂行;返回审计计数(幂等:重跑 removed=0)。"""
    async with engine.begin() as conn:
        rows = (await conn.execute(text(_CONTAMINATED_SQL))).all()
        for row in rows:
            print(
                f"contaminated: version={row[1]} gen_ord={row[2]} "
                f"chunk_count={row[3]} row.chunk_index={row[4]} text_len={row[5]}"
            )
        result = await conn.execute(text(_DELETE_SQL))
        removed = int(result.rowcount or 0)
    async with engine.connect() as conn:
        residual = len((await conn.execute(text(_CONTAMINATED_SQL))).all())
    if removed != len(rows) or residual != 0:
        raise RuntimeError(
            f"矫正不完整:计划 {len(rows)} 行,删除 {removed},残留 {residual}(fail-closed)"
        )
    print(f"OK: 清除误挂 chunk 行 {removed} 条(幂等矫正完成)")
    return {"planned": len(rows), "removed": removed}


async def _main() -> None:
    settings = load_settings()
    engine = get_engine(settings.postgres_dsn)
    try:
        await migrate(engine)
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
