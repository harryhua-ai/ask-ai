"""r3 发布安全门 G3:注册期孤儿身份碰撞 fail-closed guard。

已定事实(#178/#179,勿重新调查):r2 侧注册 API 允许客户端指定旧 id 重注册;
孤儿账本(683 docs / 2,685 chunks / 4 ready 代 + uploads 孤儿文件 181/530)
与现役零引用并存时,跨版本重注册会把历史内容重新挂到新活跃源身份下 →
跨版本重暴露。现存 PG 备份恢复还会复活注册行,程序性"不要重注册"不可依赖。

本模块为数据源注册路径(``create_data_source``)提供**只读、有界**的存在性
探测:待注册 source_id(含其确定性派生:generation 裸 id、DocumentVersion/
Chunk 的复合路径身份、uploads 子树目录名)命中任何「无活跃来源持有的历史
孤儿内容」表面即判碰撞,由调用方拒绝注册(409),要求先走显式对账,绝不
静默通过。

设计约束(修复 1):
- 复用 #174 ``source_deletion`` 的身份谓词:复合路径列(documents /
  document_versions)用 ``startswith(f"{source_id}/", autoescape=True)``
  精确前缀(防 %/_ LIKE 通配符越界);裸 id 列(index_generations.source_id)
  用精确相等 —— 杜绝前缀/空白歧义;
- 只读且有界:全部为 ``limit(1)`` 存在性探测,不全表扫客户内容、不读取
  chunk 原文(chunk 经 version_id 关联探测,同样 limit(1));
- 正常全新 id 注册零影响:无孤儿行/目录时五个探测全部未命中(误伤防护
  见 T1/T12);
- 管理员确需复用 id 的显式出口 = 错误信息点名碰撞表面并指引显式对账;
  本模块不实现任何绕过。

边界(如实):探测与插入同处注册单事务(#174 单事务模式)。READ COMMITTED
下纯 check→insert 的并发同 id 竞态窗已由 R2-3 最小修复封闭:注册事务入口
``pg_advisory_xact_lock(hashtextextended(:id,0))`` 串行化同 id 注册(后到者
等待前者 commit 后被 existing-check 以 409 拒绝;R1 现码曾在并发双注册给出
[201, 500],见 tests/api/admin/test_r3gate_registration_concurrency.py 的 RED
实证)。「探测期间出现孤儿」的确定性复现离线不可构造:PG 侧孤儿只能由删除
final 事务原子产生(账本行+配置行同事务移除,source_deletion),删除在途期
配置行始终存在 → 注册被 existing-check 拦截;缓解纵深 = 注册后 PK + 咨询锁
保护 id,后续删除/重注册再过 guard。Weaviate source_id-only 孤儿索引碰撞
不在本 guard 探测面内(离线无 Weaviate)→ 如实 BLOCKED,见交接 closure。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    Document,
    DocumentVersion,
    DocumentVersionChunk,
    IndexGeneration,
)
from backend.services.upload_storage import (
    UPLOADS_CORPUS_ROOT,
    _validate_source_component,
)

# 可发现错误锚点(调用方必须原样包含在拒绝 detail 中)
COLLISION_ANCHOR = "source identity collides with orphaned historical content"


def upload_orphan_subtree(
    source_id: str, uploads_root: str | Path | None = None
) -> Path | None:
    """uploads 孤儿子树只读存在性探测;命中返回该目录路径,否则 None。

    非 SafePath 组件的 source_id 不可能有本应用拥有的 uploads 子树
    (upload_storage._validate_source_component 同一谓词),返回 None;
    身份越界由 DB 探测兜底。
    """
    root = Path(uploads_root) if uploads_root is not None else UPLOADS_CORPUS_ROOT
    try:
        _validate_source_component(source_id)
    except RuntimeError:
        return None
    candidate = root / source_id
    return candidate if candidate.exists() else None


async def find_orphan_identity_surfaces(
    session: AsyncSession,
    source_id: str,
    *,
    uploads_root: str | Path | None = None,
) -> list[str]:
    """探测全部孤儿身份表面;返回命中表面名列表(空列表 = 无碰撞)。

    调用时序契约:调用方必须先确认 ``data_sources`` 无该 id 行(活跃来源
    不存在,孤儿语义成立),再调用本函数,并在同一事务内完成插入决策
    (单事务模式,与 #174 收敛语义一致)。
    """
    surfaces: list[str] = []

    if (
        await session.execute(
            select(Document.source_id)
            .where(Document.source_id.startswith(f"{source_id}/", autoescape=True))
            .limit(1)
        )
    ).first() is not None:
        surfaces.append("documents")

    version_pred = DocumentVersion.source_id.startswith(
        f"{source_id}/", autoescape=True
    )
    if (
        await session.execute(
            select(DocumentVersion.id).where(version_pred).limit(1)
        )
    ).first() is not None:
        surfaces.append("document_versions")

    # chunk 无 source_id 字段:身份经 version 关联派生(同样只读 limit(1),
    # 不读取 chunk 原文)
    if (
        await session.execute(
            select(DocumentVersionChunk.id)
            .join(DocumentVersion, DocumentVersionChunk.version_id == DocumentVersion.id)
            .where(version_pred)
            .limit(1)
        )
    ).first() is not None:
        surfaces.append("document_version_chunks")

    if (
        await session.execute(
            select(IndexGeneration.id)
            .where(IndexGeneration.source_id == source_id)
            .limit(1)
        )
    ).first() is not None:
        surfaces.append("index_generations")

    if upload_orphan_subtree(source_id, uploads_root) is not None:
        surfaces.append("uploads_subtree")

    return surfaces
