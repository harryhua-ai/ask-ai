"""数据灌入管道(ingestion pipeline)。

把 RawDocument 串联到完整 RAG 数据流:
    RawDocument → chunk_document → embedder.embed → Weaviate(向量 + 原文)
                                              ↘ Postgres documents 表(doc 级去重)

设计要点:
- ``ingest_document`` 同步执行,默认只写 Weaviate;构造时传入
  ``session_factory``(SQLAlchemy 同步 sessionmaker)即可同步 upsert
  Postgres ``documents`` 表(用 ``content_hash`` 作主键去重)。
- 单 chunk 写 Weaviate 失败仅 warning,不中断后续 chunk;单 doc 失败仅 error,
  不中断 ``ingest_all`` 中其他文档(错误隔离)。
- 空 content / chunk_document 返回空列表时直接返回 0,跳过 Weaviate 与 Postgres。
- ``delete_document`` 同步删除 Weaviate 对象与 Postgres 行(若 session 提供)。
"""

import logging
import uuid
from typing import Any

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from backend.connectors.base import RawDocument
from backend.db.models import Document
from backend.embedder.base import Embedder
from backend.pipeline.chunk import chunk_document_semantic
from backend.pipeline.chunk_code import LANG_MAP as _CODE_LANG_MAP
from backend.pipeline.chunk_code import chunk_code

logger = logging.getLogger(__name__)


def _deterministic_uuid(source_id: str, chunk_index: int) -> str:
    """基于 source_id + chunk_index 生成确定性 UUID,重跑同 key 覆盖,保证幂等。

    多分支同 path 文件 source_id 含 branch,故 (source_id, chunk_index) 全局唯一,
    不会跨分支/跨文档冲突。
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source_id}#{chunk_index}"))


def _is_code(doc: RawDocument) -> bool:
    """判断 doc 是否应走代码 AST 分块(按文件扩展名)。

    扩展名取自 ``doc.metadata["path"]``;缺失时回退到 ``doc.source_id``
    最后一段(假设 source_id 形如 ``<repo>/<branch>/<path>``)。扩展名命中
    :data:`backend.pipeline.chunk_code.LANG_MAP`(即 tree-sitter 有 grammar
    支持的语言)时返回 True,否则 False(交给 Markdown / 文档语义分块)。

    Args:
        doc: 待判定的原始文档。

    Returns:
        是否按代码分块路由。
    """
    path = doc.metadata.get("path", "") if isinstance(doc.metadata, dict) else ""
    if not path and "/" in doc.source_id:
        path = doc.source_id.rsplit("/", 1)[-1]
    if "." not in path:
        return False
    ext = ("." + path.rsplit(".", 1)[-1]).lower()
    return ext in _CODE_LANG_MAP


class IngestionPipeline:
    """文档灌入管道:chunk → embed → 写 Weaviate(+ 可选 Postgres)。

    Attributes:
        _embedder: 嵌入模型,实现 :class:`backend.embedder.base.Embedder` 协议。
        _client: Weaviate Python client v4(``weaviate.WeaviateClient``)。
        _class_name: Weaviate collection 名称(默认 ``Document``)。
        _max_tokens / _overlap: 透传给 :func:`backend.pipeline.chunk.chunk_document`。
        _session_factory: 可选的同步 SQLAlchemy session 工厂。为 None 时
            跳过 Postgres 写入,便于纯内存测试 / 仅 Weaviate 部署。
    """

    def __init__(
        self,
        embedder: Embedder,
        weaviate_client: Any,
        class_name: str = "Document",
        max_tokens: int = 600,
        overlap: int = 50,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        """初始化灌入管道。

        Args:
            embedder: 嵌入模型实例(或任何实现 Embedder Protocol 的对象)。
            weaviate_client: Weaviate v4 client实例(已连接)。
            class_name: Weaviate collection 名称。
            max_tokens: 单 chunk 的 token 上限。
            overlap: 相邻 chunk 重叠的 token 数。
            session_factory: SQLAlchemy 同步 ``sessionmaker``(或任何返回
                ``Session`` 上下文管理器的 callable)。为 None 时跳过 Postgres 写入。
        """
        self._embedder = embedder
        self._client = weaviate_client
        self._class_name = class_name
        self._max_tokens = max_tokens
        self._overlap = overlap
        self._session_factory: sessionmaker[Session] | None = session_factory
        self._collection: Any = None

    # ------------------------------------------------------------------ #
    # Weaviate collection 初始化(惰性)
    # ------------------------------------------------------------------ #

    def _ensure_collection(self) -> None:
        """惰性获取 / 创建 Weaviate collection。

        Weaviate Python client v4 中,``collections.get(name)`` 不会真正发请求,
        只构造一个 Python 对象;真正校验存在性必须用 ``collections.exists(name)``。
        因此本方法:
            1. 先用 ``exists`` 探测 collection 是否已存在;
            2. 若不存在,调用 ``create`` 创建(定义与 RawDocument 对齐的 8 个 property);
            3. 最后用 ``get`` 拿到 Collection 代理并缓存到 ``self._collection``。

        网络故障 / 认证失败 / 超时等异常会**向上传播**,不再被误判为
        "collection 不存在"。生产环境推荐由独立迁移脚本预创建 collection,
        避免运行时竞态。
        """
        if self._collection is not None:
            return

        if not self._client.collections.exists(self._class_name):
            logger.info("Weaviate collection %s 不存在,尝试创建", self._class_name)
            from weaviate.classes.config import Configure, DataType, Property

            self._client.collections.create(
                name=self._class_name,
                vectorizer_config=Configure.Vectorizer.none(),
                properties=[
                    Property(name="source_id", data_type=DataType.TEXT),
                    Property(name="source_type", data_type=DataType.TEXT),
                    Property(name="product", data_type=DataType.TEXT),
                    Property(name="title", data_type=DataType.TEXT),
                    Property(name="text", data_type=DataType.TEXT),
                    Property(name="url", data_type=DataType.TEXT),
                    Property(name="chunk_index", data_type=DataType.INT),
                    Property(name="content_hash", data_type=DataType.TEXT),
                    # Phase 2A 新增
                    Property(name="channel_visibility", data_type=DataType.TEXT_ARRAY),
                    Property(name="doc_section", data_type=DataType.TEXT),
                    Property(name="chunk_type", data_type=DataType.TEXT),
                    # Task 6: 多分支元数据(P8),供检索时按 branch 过滤
                    Property(name="branch", data_type=DataType.TEXT),
                ],
            )

        self._collection = self._client.collections.get(self._class_name)

    # ------------------------------------------------------------------ #
    # 主入口
    # ------------------------------------------------------------------ #

    def ingest_document(self, doc: RawDocument) -> int:
        """灌入单篇文档:chunk → embed → Weaviate(+ 可选 Postgres)。

        流程:
            1. ``chunk_document`` 切分;空文档(空 content / 空切片)直接返回 0。
            2. ``embedder.embed`` 批量生成向量。
            3. 逐 chunk 写 Weaviate;**单 chunk 失败仅 warning**,继续后续 chunk。
            4. 若提供了 ``session_factory``,在 Postgres ``documents`` 表
               upsert doc 级元数据(content_hash 去重,更新 chunk_count)。

        Args:
            doc: 待灌入的原始文档。

        Returns:
            成功写入 Weaviate 的 chunk 数(0 表示空文档或全部失败)。
        """
        if _is_code(doc):
            chunks = chunk_code(doc, self._max_tokens, self._overlap)
        else:
            chunks = chunk_document_semantic(doc, self._max_tokens, self._overlap)
        if not chunks:
            logger.info("文档 %s 切分为空,跳过灌入", doc.source_id)
            return 0

        texts = [c.text for c in chunks]
        vectors = self._embedder.embed(texts)

        # 校验 embedder 返回向量数与 chunk 数一致,避免 zip 在向量缺失时静默截断
        if len(vectors) != len(chunks):
            raise RuntimeError(f"embedder 返回 {len(vectors)} 向量,期望 {len(chunks)}")

        self._ensure_collection()

        success_count = 0
        for chunk, vector in zip(chunks, vectors):
            try:
                # 兼容 list / np.ndarray:统一转 list[float] 供 Weaviate v4 使用
                vec_list = np.asarray(vector).tolist()
                props = {
                    "source_id": doc.source_id,
                    "source_type": doc.source_type,
                    "product": doc.product,
                    "title": doc.title,
                    "text": chunk.text,
                    "url": doc.url,
                    "chunk_index": chunk.chunk_index,
                    "content_hash": doc.content_hash,
                    # Phase 2A 新增
                    "channel_visibility": list(chunk.channel_visibility),
                    "doc_section": chunk.doc_section,
                    "chunk_type": chunk.chunk_type,
                    # Task 6: 多分支元数据(P8)
                    "branch": doc.branch,
                }
                # 确定性 UUID:基于 source_id + chunk_index,重跑同 key 覆盖,保证幂等不重复
                det_uuid = _deterministic_uuid(doc.source_id, chunk.chunk_index)
                try:
                    self._collection.data.insert(
                        properties=props, vector=vec_list, uuid=det_uuid
                    )
                except Exception:
                    # UUID 已存在(重跑/增量重灌),replace 覆盖保证幂等
                    self._collection.data.replace(
                        properties=props, vector=vec_list, uuid=det_uuid
                    )
                success_count += 1
            except Exception as exc:  # noqa: BLE001 - 单 chunk 失败不中断后续 chunk
                logger.warning(
                    "写入 Weaviate 失败 doc=%s chunk=%d: %s",
                    doc.source_id,
                    chunk.chunk_index,
                    exc,
                )

        # Postgres doc 级 upsert(若提供 session)
        if self._session_factory is not None:
            try:
                self._upsert_postgres(doc, success_count)
            except Exception as exc:  # noqa: BLE001 - Postgres 失败不影响 Weaviate
                logger.error("Postgres upsert 失败 doc=%s: %s", doc.source_id, exc)

        logger.info(
            "已索引 %s: %d/%d chunk 成功",
            doc.source_id,
            success_count,
            len(chunks),
        )
        return success_count

    def ingest_all(self, docs: list[RawDocument]) -> dict[str, int]:
        """批量灌入文档,单 doc 失败不中断后续。

        Args:
            docs: 待灌入的原始文档列表。

        Returns:
            ``{source_id: success_chunk_count}`` 字典;失败的 doc 计为 0。
        """
        results: dict[str, int] = {}
        for doc in docs:
            try:
                count = self.ingest_document(doc)
                results[doc.source_id] = count
            except Exception as exc:  # noqa: BLE001 - 单 doc 失败不中断批次
                # ingest_document 内部已对 chunk / Postgres 级异常做隔离,
                # 此处兜底防止 embed / chunk 阶段的异常中断整个批次
                logger.error("索引失败 %s: %s", doc.source_id, exc)
                results[doc.source_id] = 0
        return results

    def delete_document(self, source_id: str) -> None:
        """按 source_id 删除文档:先删 Weaviate,再删 Postgres(若提供)。

        Args:
            source_id: 文档在源系统内的唯一标识。
        """
        # Weaviate:删除该 source_id 的全部 chunk
        self._ensure_collection()
        try:
            self._collection.data.delete_many(
                where=self._collection.filter.by_property("source_id").equal(source_id)
            )
        except Exception as exc:  # noqa: BLE001 - Weaviate 删除失败不阻断 Postgres
            logger.warning("Weaviate 删除失败 source_id=%s: %s", source_id, exc)

        # Postgres:删除该 source_id 的 doc 行(content_hash 仍保留?不,
        # 用 source_id 而非 content_hash 删除,因为调用方只知 source_id)
        if self._session_factory is not None:
            try:
                self._delete_postgres(source_id)
            except Exception as exc:  # noqa: BLE001 - Postgres 删除失败不影响 Weaviate 已删除状态
                logger.error("Postgres 删除失败 source_id=%s: %s", source_id, exc)

    # ------------------------------------------------------------------ #
    # Postgres 辅助
    # ------------------------------------------------------------------ #

    def _upsert_postgres(self, doc: RawDocument, chunk_count: int) -> None:
        """在 Postgres ``documents`` 表 upsert doc 行。

        用 ``(content_hash, branch)`` 复合主键去重:同内容跨分支各留一行;同分支重复灌入更新 chunk_count / source_id /
        updated_at,不存在则插入新行。

        Args:
            doc: 原始文档(取 content_hash / source_id / title 等字段)。
            chunk_count: 本次成功写入 Weaviate 的 chunk 数。
        """
        assert self._session_factory is not None
        with self._session_factory() as session:
            existing = session.execute(
                select(Document).where(
                Document.content_hash == doc.content_hash, Document.branch == doc.branch
            )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    Document(
                        content_hash=doc.content_hash,
                        source_id=doc.source_id,
                        source_type=doc.source_type,
                        product=doc.product,
                        title=doc.title,
                        url=doc.url,
                        metadata_=doc.metadata,
                        branch=doc.branch,
                        chunk_count=chunk_count,
                    )
                )
            else:
                existing.source_id = doc.source_id
                existing.source_type = doc.source_type
                existing.product = doc.product
                existing.title = doc.title
                existing.url = doc.url
                existing.metadata_ = doc.metadata
                existing.branch = doc.branch
                existing.chunk_count = chunk_count
            session.commit()

    def _delete_postgres(self, source_id: str) -> None:
        """删除 Postgres ``documents`` 表中匹配 source_id 的全部行。

        注意:同一 source_id 可能对应多个 content_hash(如内容更新过),
        因此按 source_id 而非 content_hash 删除。

        Args:
            source_id: 文档源系统唯一标识。
        """
        assert self._session_factory is not None
        with self._session_factory() as session:
            session.execute(delete(Document).where(Document.source_id == source_id))
            session.commit()
