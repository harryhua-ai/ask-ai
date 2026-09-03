"""数据灌入管道(ingestion pipeline)。

把 RawDocument 串联到完整 RAG 数据流:
    RawDocument → chunk_document → embedder.embed → Weaviate(向量 + 原文)
                                              ↘ Postgres documents 表(doc 级去重)

设计要点:
- ``ingest_document`` 同步执行,默认只写 Weaviate;构造时传入
  ``session_factory``(SQLAlchemy 同步 sessionmaker)即可同步 upsert
  Postgres ``documents`` 表(按 ``source_id`` 路径身份 upsert,Issue #13)。
- 单 chunk 写 Weaviate 失败仅 warning,不中断后续 chunk;单 doc 失败仅 error,
  不中断 ``ingest_all`` 中其他文档(错误隔离)。
- 空 content / chunk_document 返回空列表时直接返回 0,跳过 Weaviate 与 Postgres。
- ``delete_document`` 同步删除 Weaviate 对象与 Postgres 行(若 session 提供)。
"""

import logging
import uuid
from collections.abc import Callable
from typing import Any

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from backend.connectors.base import RawDocument
from backend.connectors.safety import (
    TechnicalSafetyPolicy,
    new_safety_stats,
    record_safety_exclusion,
)
from backend.db.models import Document
from backend.embedder.base import Embedder
from backend.embedder.fallback import CpuFallbackError, SyncEmbedderHandle, classify_cuda_failure
from backend.pipeline.chunk import chunk_document_semantic
from backend.pipeline.chunk_code import LANG_MAP as _CODE_LANG_MAP
from backend.pipeline.chunk_code import chunk_code
from backend.services.sync_runs import (
    STAGE_CHUNK,
    STAGE_EMBED,
    STAGE_INDEX,
    STAGE_SAFETY_FILTER,
)

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


def _build_props(chunk: "Any", doc: RawDocument) -> dict:
    """从 Chunk + RawDocument 构造 Weaviate properties(消除 3 处重复构造)。

    覆盖 ingest_document 主路径 / batch 整体失败回退 / _ingest_doc_batch 三处
    props 构造,统一字段集(含 symbol_* 元数据),避免漏写字段。

    Args:
        chunk: :class:`backend.pipeline.chunk.Chunk` 实例。
        doc: 所属 :class:`RawDocument`。

    Returns:
        Weaviate object properties dict(含 source_id / product / text /
        channel_visibility / branch / symbol_* 等全部字段)。
    """
    return {
        "source_id": doc.source_id,
        "source_type": doc.source_type,
        "product": doc.product,
        "title": doc.title,
        "text": chunk.text,
        "url": doc.url,
        "chunk_index": chunk.chunk_index,
        "content_hash": doc.content_hash,
        "channel_visibility": list(chunk.channel_visibility),
        "doc_section": chunk.doc_section,
        "chunk_type": chunk.chunk_type,
        "branch": doc.branch,
        "symbol_name": chunk.symbol_name,
        "symbol_signature": chunk.symbol_signature,
        "symbol_node_type": chunk.symbol_node_type,
        "symbol_tokens": chunk.symbol_tokens,
    }


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
        # 技术安全第二道防线(Layer 1 内容嗅探):拦截扩展名伪装/无扩展名的
        # 二进制内容,防止其进入 chunk/tokenize/embed(G1 事故纵深防御)。
        self._safety = TechnicalSafetyPolicy()
        self.safety_stats = new_safety_stats()

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
                    # 函数级符号检索:symbol 元数据独立 property
                    Property(name="symbol_name", data_type=DataType.TEXT),
                    Property(name="symbol_signature", data_type=DataType.TEXT),
                    Property(name="symbol_node_type", data_type=DataType.TEXT),
                    Property(name="symbol_tokens", data_type=DataType.TEXT),
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
               upsert doc 级元数据(source_id 路径身份,更新 chunk_count)。

        Args:
            doc: 待灌入的原始文档。

        Returns:
            成功写入 Weaviate 的 chunk 数(0 表示空文档或全部失败)。
        """
        verdict = self._safety.check_content(doc.content)
        if not verdict.safe:
            # 文档级隔离:排除该文档,不影响同批其他文档,不计入 failed
            # (产品合同 §10.2:bad document ≠ source-wide consequence)
            record_safety_exclusion(
                self.safety_stats, doc.source_id, verdict.reason, verdict.detail
            )
            return 0
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

        # 旧 chunk 集合上界必须在账本被本次 upsert 覆盖**之前**读取,
        # 否则 prune 会拿新计数当旧计数,漏删或多删。
        previous_count = self._get_stored_chunk_count(doc.source_id)

        # 批量写入 Weaviate(insert_many),已存在 UUID 回退单条 replace(幂等覆盖)。
        # 远程 Weaviate 经 SSH tunnel 时,N chunk 逐条往返延迟极高;
        # 改为 1 次 batch 提交,已存在对象按 per-object 错误回退 replace。
        import weaviate as _wv

        data_objs: list = []
        props_list: list[dict] = []
        uuid_list: list = []
        for _chunk, _vector in zip(chunks, vectors):
            _vec_list = np.asarray(_vector).tolist()
            _props = _build_props(_chunk, doc)
            _det_uuid = _deterministic_uuid(doc.source_id, _chunk.chunk_index)
            props_list.append(_props)
            uuid_list.append(_det_uuid)
            data_objs.append(
                _wv.classes.data.DataObject(properties=_props, vector=_vec_list, uuid=_det_uuid)
            )
        success_count = 0
        try:
            result = self._collection.data.insert_many(data_objs)
            # v4 官方返回:errors 键 = 对象在本次 insert_many 中的原始下标。
            # all_responses 已废弃且仅保留末尾 MAX_STORED_RESULTS 条,不可用于记账。
            failed_idx = sorted(result.errors.keys())
            success_count = len(data_objs) - len(failed_idx)
            # 已存在的 UUID:回退单条 replace 保证幂等覆盖
            for _i in failed_idx:
                try:
                    self._collection.data.replace(
                        properties=props_list[_i],
                        vector=np.asarray(vectors[_i]).tolist(),
                        uuid=uuid_list[_i],
                    )
                    success_count += 1
                except Exception as exc2:  # noqa: BLE001
                    logger.warning(
                        "replace 回退失败 doc=%s idx=%d: %s",
                        doc.source_id,
                        _i,
                        str(exc2)[:200],
                    )
        except Exception as exc:  # noqa: BLE001 - batch 整体失败,回退逐条 insert/replace
            logger.warning(
                "insert_many 整体失败 doc=%s,回退逐条: %s",
                doc.source_id,
                str(exc)[:200],
            )
            for _chunk, _vector in zip(chunks, vectors):
                try:
                    _vec_list = np.asarray(_vector).tolist()
                    _props = _build_props(_chunk, doc)
                    _det_uuid = _deterministic_uuid(doc.source_id, _chunk.chunk_index)
                    try:
                        self._collection.data.insert(
                            properties=_props, vector=_vec_list, uuid=_det_uuid
                        )
                    except Exception:  # noqa: BLE001 - insert failure tries replace
                        self._collection.data.replace(
                            properties=_props, vector=_vec_list, uuid=_det_uuid
                        )
                    success_count += 1
                except Exception as exc2:  # noqa: BLE001 - 单 chunk 失败不中断后续 chunk
                    logger.warning(
                        "写入 Weaviate 失败 doc=%s chunk=%d: %s",
                        doc.source_id,
                        _chunk.chunk_index,
                        str(exc2)[:200],
                    )

        # Postgres doc 级 upsert(若提供 session)
        if self._session_factory is not None:
            try:
                self._upsert_postgres(doc, success_count)
            except Exception as exc:  # noqa: BLE001 - Postgres 失败不影响 Weaviate
                logger.error("Postgres upsert 失败 doc=%s: %s", doc.source_id, exc)

        # 全部 chunk 写成功后清理超出范围的陈旧对象(部分失败时留待下轮重试)
        if success_count == len(chunks):
            self._prune_stale_chunks(doc.source_id, len(chunks), previous_count=previous_count)

        logger.info(
            "已索引 %s: %d/%d chunk 成功",
            doc.source_id,
            success_count,
            len(chunks),
        )
        return success_count

    def _get_stored_chunk_count(self, source_id: str) -> int | None:
        """读 Postgres 账本中该文档已记录的 chunk 数(旧 chunk 集合上界)。

        取同 source_id 的 ``MAX(chunk_count)``(保守上界;同 source_id 多行在
        ``_upsert_postgres`` 的旧版本清理后至多为 1,MAX 仅防御性)。无
        session_factory / 无行 / 读数失败 → ``None``(调用方 fail-safe 不 prune)。
        """
        if self._session_factory is None:
            return None
        try:
            from sqlalchemy import func, select

            with self._session_factory() as session:
                value = session.execute(
                    select(func.max(Document.chunk_count)).where(Document.source_id == source_id)
                ).scalar_one_or_none()
                return int(value) if value is not None else None
        except Exception as exc:  # noqa: BLE001 - 账本不可得 → 不 prune(fail-safe)
            logger.warning(
                "读取文档 %s 的账本 chunk_count 失败,本次跳过 prune: %s", source_id, str(exc)[:200]
            )
            return None

    def _prune_stale_chunks(
        self, source_id: str, current_count: int, previous_count: int | None = None
    ) -> None:
        """删除本文档收缩后超出新 chunk 数的陈旧对象(PRUNE IS DOCUMENT-LOCAL)。

        不变量(P0-A 冻结):**prune 文档局部** —— 只能删除由本文档自己的
        ``(source_id, chunk_index)`` 决定性 UUID 点名的对象,结构上不可能触及
        任何其他文档(含同前缀 / 同 token / 相似路径)。

        事故根因(2026-09-02 PA-0F):旧实现用 TEXT 属性 ``source_id`` 的
        ``equal`` 过滤,而 Weaviate 对 TEXT 的过滤是**分词语义** ——
        ``equal("site/blog")`` 会命中 ``site/blog/ai-species`` 等所有共享 token
        的兄弟文档,收缩文档的 prune 连带删除兄弟文档 chunks(生产实证
        web_crawl 359 → 163)。故禁止任何基于 TEXT 属性过滤的删除。

        Args:
            source_id: 文档唯一标识。
            current_count: 本次成功写入的 chunk 数。
            previous_count: 账本记录的旧 chunk 数(写前读取)。``None`` 表示
                旧集合不可知 → **fail-safe 不删**(残留交由一致性校验披露),
                绝不猜测删除范围。
        """
        if previous_count is None or previous_count <= current_count:
            return
        stale_uuids = [
            _deterministic_uuid(source_id, i) for i in range(current_count, previous_count)
        ]
        self._ensure_collection()
        try:
            from weaviate.classes.query import Filter

            # 按 UUID 点删(document-local);分批防大 payload
            for start in range(0, len(stale_uuids), 500):
                self._collection.data.delete_many(
                    where=Filter.by_id().contains_any(stale_uuids[start : start + 500])
                )
        except Exception as exc:  # noqa: BLE001 - 清理失败不阻断灌入
            logger.warning("清理陈旧 chunk 失败 source_id=%s: %s", source_id, str(exc)[:120])

    def ingest_all(
        self, docs: list[RawDocument], *, progress: "Callable[[str, int], None] | None" = None
    ) -> dict[str, int]:
        """批量灌入文档,单 doc 失败不中断后续,但整体失败时 raise。

        跨 doc 累积 chunk 后一次性 embed(embedder 内部按 ``batch_size`` 批处理),
        充分利用 GPU;再按 doc 批量写 Weaviate。

        契约(2026-08-17):处理完全部 doc 后,若存在灌入失败的 doc
        (embed / 写库异常),统一 raise ``RuntimeError``——由调用方
        (``scripts/sync.py``)记 SyncLog status=failed,增量窗口不推过缺口。
        计 0 不再代表失败(仅代表合法空文档),避免二者混淆导致的静默丢数。

        Args:
            docs: 待灌入的原始文档列表。

        Returns:
            ``{source_id: success_chunk_count}`` 字典;全部成功时返回。

        Raises:
            RuntimeError: 任一 doc 灌入失败(部分 doc 可能已成功写入,
                重试幂等:source_id 路径 upsert + 确定性 UUID 覆盖写)。
        """
        results: dict[str, int] = {}
        failed: list[str] = []
        batch_size = 64  # 每批 64 doc:控制内存,跨 doc 累积满 batch_size embed
        total = len(docs)
        for start in range(0, len(docs), batch_size):
            batch = docs[start : start + batch_size]
            done = min(start + batch_size, total)
            try:
                if progress is not None:
                    # CORRECTION A:SAFETY_FILTER 批界真实计数(每 doc 均过
                    # TechnicalSafetyPolicy 检查,done=进入过滤器的 doc 数)
                    progress(STAGE_SAFETY_FILTER, done)
                    progress(STAGE_CHUNK, done)  # 批界回调:chunk 相位(同步缓冲用)
                results.update(self._ingest_doc_batch(batch, failed))
                if progress is not None:
                    progress(STAGE_EMBED, done)
                    progress(STAGE_INDEX, done)
            except CpuFallbackError:
                # GPU→CPU 已经是本 run 唯一允许的设备切换;CPU 再失败必须
                # 直接成为终局错误,不能退回逐 doc 重试或重新触发回退。
                raise
            except Exception as exc:  # noqa: BLE001 - 整批失败回退逐 doc
                logger.error("批处理失败(start=%d): %s,回退逐 doc", start, str(exc)[:200])
                for doc in batch:
                    try:
                        results[doc.source_id] = self.ingest_document(doc)
                    except Exception as exc2:  # noqa: BLE001
                        logger.error("索引失败 %s: %s", doc.source_id, exc2)
                        results[doc.source_id] = 0
                        failed.append(doc.source_id)
        if failed:
            preview = ", ".join(failed[:10])
            if len(failed) > 10:
                preview += ", ..."
            raise RuntimeError(
                f"{len(failed)} 个文档灌入失败(可能 embed/写库故障,需重试): {preview}"
            )
        return results

    def _ingest_doc_batch(
        self, docs: list[RawDocument], failed: list[str] | None = None
    ) -> dict[str, int]:
        """跨 doc 批处理:chunk → 批量 embed → 按 doc 批量写 Weaviate + Postgres。

        将多 doc 的 chunk 文本拼成一个列表统一 embed(embedder 内部按
        ``batch_size`` 切批),消除逐 doc 小 batch 的 GPU 固定开销。

        Args:
            docs: 待灌入的原始文档列表。
            failed: 失败 doc 的 source_id 收集列表(可选)。提供时,批内
                切分 / 逐 doc 回退失败的 doc 会被追加进去,供 ``ingest_all``
                统一 raise;缺省时保持旧的静默计 0 行为(直接调用方兼容)。
        """
        import weaviate as _wv

        results: dict[str, int] = {}
        # Phase 1:逐 doc 切分(CPU)
        doc_chunks: list[tuple[RawDocument, list]] = []
        for doc in docs:
            try:
                verdict = self._safety.check_content(doc.content)
                if not verdict.safe:
                    record_safety_exclusion(
                        self.safety_stats, doc.source_id, verdict.reason, verdict.detail
                    )
                    results[doc.source_id] = 0
                    continue
                if _is_code(doc):
                    chunks = chunk_code(doc, self._max_tokens, self._overlap)
                else:
                    chunks = chunk_document_semantic(doc, self._max_tokens, self._overlap)
                if not chunks:
                    logger.info("文档 %s 切分为空,跳过灌入", doc.source_id)
                    results[doc.source_id] = 0
                    continue
                doc_chunks.append((doc, chunks))
            except Exception as exc:  # noqa: BLE001
                logger.error("索引失败 %s: %s", doc.source_id, str(exc)[:200])
                results[doc.source_id] = 0
                if failed is not None:
                    failed.append(doc.source_id)
        if not doc_chunks:
            return results

        # Phase 2:拼平所有 chunk 文本,一次性 embed(embedder 内部按 batch_size 批处理)
        all_texts: list[str] = []
        spans: list[tuple[int, int]] = []  # (start, end) into all_texts per doc
        for _doc, chunks in doc_chunks:
            s = len(all_texts)
            all_texts.extend(c.text for c in chunks)
            spans.append((s, len(all_texts)))
        try:
            all_vectors = self._embedder.embed(all_texts)
        except CpuFallbackError:
            # A failed CPU transition is terminal and must not enter the
            # existing per-document isolation path.
            raise
        except Exception as exc:
            reason = classify_cuda_failure(exc)
            if reason is not None and isinstance(self._embedder, SyncEmbedderHandle):
                detail = f"{type(exc).__name__}: {exc}"[:500]
                if not self._embedder.fallback_to_cpu(reason, detail):
                    raise CpuFallbackError(
                        f"CPU fallback unavailable after {reason}: {detail}",
                        reason=reason,
                        detail=detail,
                    ) from exc
                try:
                    all_vectors = self._embedder.embed(all_texts)
                except Exception as cpu_exc:
                    raise CpuFallbackError(
                        f"CPU fallback failed after {reason}: "
                        f"{type(cpu_exc).__name__}: {cpu_exc}",
                        reason=reason,
                        detail=(
                            f"{type(exc).__name__}: {exc}; CPU fallback failed: "
                            f"{type(cpu_exc).__name__}: {cpu_exc}"
                        ),
                    ) from cpu_exc
                if len(all_vectors) != len(all_texts):
                    raise CpuFallbackError(
                        f"CPU fallback returned {len(all_vectors)} vectors,"
                        f" expected {len(all_texts)}",
                        reason=reason,
                        detail=(
                            f"{type(exc).__name__}: {exc}; CPU fallback returned "
                            f"{len(all_vectors)} vectors, expected {len(all_texts)}"
                        ),
                    )
                logger.warning(
                    "批量 embed GPU 故障(%s),已切换 CPU(%d docs/%d texts)",
                    reason,
                    len(doc_chunks),
                    len(all_texts),
                )
            elif isinstance(self._embedder, SyncEmbedderHandle) and self._embedder.fallback_reason:
                # A CPU model that was already selected after GPU fallback has
                # no safe alternate device or retry path.  CPU failure is a
                # real run failure, not a reason to re-encode per document.
                fallback_reason = self._embedder.fallback_reason
                raise CpuFallbackError(
                    f"CPU fallback failed after {fallback_reason}: "
                    f"{type(exc).__name__}: {exc}",
                    reason=fallback_reason,
                    detail=(
                        f"{self._embedder.fallback_detail or 'GPU fallback'}; "
                        f"CPU encode failed: {type(exc).__name__}: {exc}"
                    ),
                ) from exc
            else:
                # 非 CUDA 故障保留既有逐 doc 同设备隔离路径;绝不换设备。
                logger.error(
                    "批量 embed 失败(%d texts): %s,回退逐 doc",
                    len(all_texts),
                    str(exc)[:200],
                )
                for doc, _chunks in doc_chunks:
                    try:
                        results[doc.source_id] = self.ingest_document(doc)
                    except Exception as exc2:  # noqa: BLE001
                        logger.error("索引失败 %s: %s", doc.source_id, exc2)
                        results[doc.source_id] = 0
                        if failed is not None:
                            failed.append(doc.source_id)
                return results
        if len(all_vectors) != len(all_texts):
            raise RuntimeError(f"embedder 返回 {len(all_vectors)} 向量,期望 {len(all_texts)}")
        if isinstance(self._embedder, SyncEmbedderHandle):
            # Counts both the transition batch and subsequent sticky CPU
            # batches; explicit CPU mode has no fallback_reason and is not
            # counted as automatic fallback.
            self._embedder.record_cpu_batch(len(doc_chunks))

        # Phase 3:构造整批对象 → 单次 insert_many(跨 doc,1 次往返)→ replace 回退 → 按 doc 统计
        self._ensure_collection()
        all_objs: list = []
        all_props: list[dict] = []
        all_uuids: list = []
        all_vecs_flat: list = []
        obj_spans: list[tuple[int, int]] = []
        for idx, (doc, chunks) in enumerate(doc_chunks):
            s, e = spans[idx]
            vecs = all_vectors[s:e]
            o_start = len(all_objs)
            for chunk, vector in zip(chunks, vecs):
                vec_list = np.asarray(vector).tolist()
                props = _build_props(chunk, doc)
                det_uuid = _deterministic_uuid(doc.source_id, chunk.chunk_index)
                all_props.append(props)
                all_uuids.append(det_uuid)
                all_vecs_flat.append(vec_list)
                all_objs.append(
                    _wv.classes.data.DataObject(properties=props, vector=vec_list, uuid=det_uuid)
                )
            obj_spans.append((o_start, len(all_objs)))
        # 分块 insert_many(跨 doc,WRITE_CHUNK/块),避免大 payload 触发 gRPC 超时;
        # 失败对象(已存在 UUID / 块级 gRPC 失败)用预计算向量走单条 replace 回退(不重算 embed)
        WRITE_CHUNK = 128
        failed_idx: set[int] = set()
        for _ws in range(0, len(all_objs), WRITE_CHUNK):
            _we = min(_ws + WRITE_CHUNK, len(all_objs))
            try:
                _result = self._collection.data.insert_many(all_objs[_ws:_we])
                # 同上:errors 键 = 块内原始下标,加块偏移映射回全局下标
                for _i in _result.errors:
                    failed_idx.add(_ws + _i)
            except Exception as exc:  # noqa: BLE001 - 块级失败:整块对象走 replace 回退
                logger.warning(
                    "insert_many 块失败(offset=%d,%d objs): %s,整块 replace",
                    _ws,
                    _we - _ws,
                    str(exc)[:120],
                )
                failed_idx.update(range(_ws, _we))
        replace_failed: set[int] = set()  # replace 回退也失败的对象索引(写库彻底失败)
        for fi in failed_idx:  # replace 回退(用预计算向量,不重 embed)
            try:
                self._collection.data.replace(
                    properties=all_props[fi],
                    vector=all_vecs_flat[fi],
                    uuid=all_uuids[fi],
                )
            except Exception as exc2:  # noqa: BLE001
                logger.warning("replace 回退失败 uuid=%s: %s", all_uuids[fi], str(exc2)[:120])
                replace_failed.add(fi)
        # 按 doc 统计成功数(insert 成功 + replace 回退成功计成功;replace 也失败计失败)
        for idx, (doc, chunks) in enumerate(doc_chunks):
            o_s, o_e = obj_spans[idx]
            total = o_e - o_s
            n_failed_in_doc = sum(1 for i in range(o_s, o_e) if i in replace_failed)
            success_count = total - n_failed_in_doc
            if failed is not None and n_failed_in_doc > 0:
                # 写库彻底失败(insert 失败且 replace 也失败)→ 记入 failed,由 ingest_all raise
                failed.append(doc.source_id)
            # 旧 chunk 集合上界必须在账本被本次 upsert 覆盖之前读取(P0-A)
            previous_count = self._get_stored_chunk_count(doc.source_id)
            if self._session_factory is not None:
                try:
                    self._upsert_postgres(doc, success_count)
                except Exception as exc:  # noqa: BLE001
                    logger.error("Postgres upsert 失败 doc=%s: %s", doc.source_id, exc)
            # 全部 chunk 写成功后清理超出范围的陈旧对象(部分失败时留待下轮重试)
            if success_count == total:
                self._prune_stale_chunks(doc.source_id, total, previous_count=previous_count)
            logger.info(
                "已索引 %s: %d/%d chunk 成功",
                doc.source_id,
                success_count,
                total,
            )
            results[doc.source_id] = success_count
        return results

    def delete_document(self, source_id: str) -> None:
        """按 source_id 删除文档:先删 Weaviate,再删 Postgres(若提供)。

        P0-A 文档局部性:Weaviate 侧只按本文档自己的确定性 UUID 点删
        (uuid5(source_id, 0..chunk_count-1)),绝不用 TEXT 属性过滤
        (分词语义会误删同 token 兄弟文档)。账本无行(计数不可知)时
        fail-safe 不删 Weaviate,残留交由一致性校验披露。

        Args:
            source_id: 文档在源系统内的唯一标识。
        """
        stored_count = self._get_stored_chunk_count(source_id)
        if stored_count is None:
            logger.warning(
                "delete_document: 文档 %s 无账本读数,跳过 Weaviate 删除(防跨文档误删);"
                "残留 chunk 交由一致性校验披露",
                source_id,
            )
        else:
            self._ensure_collection()
            try:
                from weaviate.classes.query import Filter

                for start in range(0, stored_count, 500):
                    self._collection.data.delete_many(
                        where=Filter.by_id().contains_any(
                            [
                                _deterministic_uuid(source_id, i)
                                for i in range(start, min(start + 500, stored_count))
                            ]
                        )
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

        Issue #13(D1/D2):主键 = ``source_id``(路径身份),按路径 upsert —
        同路径重复灌入原地更新 content_hash/chunk_count(内容变更亦然,单行
        原位演进,无旧行残留);不同 source/path 即使 ``content_hash`` 相同
        也各自成行,**禁止任何"同 hash 已存在行"被另一路径抢占改写 source_id**
        (旧内容寻址 PK 的行归属翻转缺陷在此根除)。内容指纹 ``content_hash``
        保留索引,供同内容检测类查询使用。

        Args:
            doc: 原始文档(取 content_hash / source_id / title 等字段)。
            chunk_count: 本次成功写入 Weaviate 的 chunk 数。
        """
        assert self._session_factory is not None
        with self._session_factory() as session:
            existing = session.execute(
                select(Document).where(Document.source_id == doc.source_id)
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
                existing.content_hash = doc.content_hash
                existing.source_type = doc.source_type
                existing.product = doc.product
                existing.title = doc.title
                existing.url = doc.url
                existing.metadata_ = doc.metadata
                existing.branch = doc.branch
                existing.chunk_count = chunk_count
            session.commit()

    def _delete_postgres(self, source_id: str) -> None:
        """删除 Postgres ``documents`` 表中该 source_id(路径身份)的账本行。

        Issue #13 后 source_id 为主键,单路径恰一行;按 source_id 删除即精确
        移除该文档(同内容其他路径行不受影响)。
        """
        assert self._session_factory is not None
        with self._session_factory() as session:
            session.execute(delete(Document).where(Document.source_id == source_id))
            session.commit()
