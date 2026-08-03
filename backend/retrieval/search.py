"""Weaviate hybrid 检索。

将 BGE-m3 dense 向量与 Weaviate 内置 BM25 sparse 检索按 ``alpha`` 权重融合,
返回统一的 :class:`SearchResult` 列表供下游重排 / LLM 引用使用。

关键设计:
- ``alpha=0.5`` 即 dense:sparse = 50:50(Weaviate hybrid 语义,无需手动调 sparse)。
- 距离(distance)→ 相似度(score)的简单转换:``score = 1.0 - distance``。
  ``distance=None`` / ``metadata=None`` 时退化为 0.0,保证不抛错。
- 空 query 直接返回 ``[]``,不触发 embedder / Weaviate,节省成本。
- Weaviate 调用失败时异常向上传播,由调用方决定重试 / 降级策略。
- ``embedder`` 必须返回与输入数量一致的向量,否则 ``RuntimeError``(与
  :mod:`backend.pipeline.ingest` 一致)。
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from backend.embedder.base import Embedder

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchResult:
    """单条 hybrid 检索结果(不可变)。

    字段与 :mod:`backend.pipeline.ingest` 中 Weaviate ``Document`` collection
    的 8 个 property 对齐(``content_hash`` 不对外暴露)。

    Attributes:
        text: chunk 原文。
        source_id: 文档在源系统内的唯一标识(如 ``github-ne503/README.md``)。
        source_type: 数据源类型(``github`` / ``filesystem`` 等)。
        product: 产品标识(``ne503`` / ``ask-ai`` 等)。
        title: 文档标题。
        url: 文档可访问 URL(可为空字符串)。
        score: 相似度分数。检索阶段由 ``1 - distance`` 得出,理论 ∈ [0.0, 1.0];
            rerank 阶段会被 ``type_weights`` 乘性加权(最高 ×1.2),故重排后可能 > 1.0。
        chunk_index: 该 chunk 在原文中的序号。
        chunk_type: chunk 语义类型(``heading`` / ``paragraph`` / ``code`` /
            ``list`` / ``table``)。默认空串表示未被 Phase 2A Task 2 标注,
            ``HybridSearcher.search`` 从 Weaviate property 填充。
        doc_section: chunk 所属文档章节路径。默认空串表示未标注。
        channel_visibility: 该 chunk 允许透出的渠道白名单(tuple 保证不可变),
            Phase 2A Task 6 在 HybridSearcher 中用于按渠道过滤。默认
            ``("widget", "api")`` 对所有渠道可见。
    """

    text: str
    source_id: str
    source_type: str
    product: str
    title: str
    url: str
    score: float
    chunk_index: int
    # Phase 2A 新增字段(均有默认值,保证现有 HybridSearcher.search 零回归;
    # Task 4/6 会从 Weaviate property 填充这些字段)
    chunk_type: str = ""
    doc_section: str = ""
    channel_visibility: tuple[str, ...] = ("widget", "api")
    # 函数级符号检索新增字段(默认空串,兼容非代码 chunk)
    symbol_name: str = ""
    symbol_signature: str = ""


class HybridSearcher:
    """Weaviate hybrid 检索器(BGE-m3 dense + BM25 sparse)。

    Attributes:
        _client: Weaviate Python client v4(``weaviate.WeaviateClient``)。
        _embedder: 嵌入模型实例(实现 :class:`backend.embedder.base.Embedder` 协议)。
        _class_name: Weaviate collection 名称(默认 ``Document``)。
    """

    def __init__(
        self,
        weaviate_client: Any,
        embedder: Embedder,
        class_name: str = "Document",
    ) -> None:
        """初始化检索器。

        Args:
            weaviate_client: 已连接的 Weaviate v4 client实例。
            embedder: 嵌入模型(实现 Embedder Protocol)。
            class_name: Weaviate collection 名称。
        """
        self._client = weaviate_client
        self._embedder = embedder
        self._class_name = class_name

    def search(
        self,
        query: str,
        alpha: float = 0.5,
        limit: int = 50,
        product_filter: str | None = None,
        channel: str | None = None,
    ) -> list[SearchResult]:
        """执行 hybrid 检索。

        流程:
            1. 空 query 直接返回 ``[]``,不调用 embedder / Weaviate。
            2. ``embedder.embed([query])`` 生成 query 向量;返回为空时抛
               ``RuntimeError``,避免后续 ``[0]`` 索引掩盖根因。
            3. 构造 hybrid 参数;``product_filter`` / ``channel`` 非空时组合
               ``Filter``(AND 语义)附加到查询。
            4. Weaviate 异常向上传播(不吞);空结果集合返回 ``[]``。
            5. ``distance`` → ``score`` 转换;``metadata`` 为 ``None`` 时 score 退化为 0.0。

        Args:
            query: 用户查询文本。空字符串 / 仅空白直接返回 ``[]``。
            alpha: dense vs sparse 权重,``0.0`` 纯 BM25、``1.0`` 纯 dense。
                默认 ``0.5`` 即 50:50 混合。
            limit: 返回结果数上限。
            product_filter: 可选的产品名过滤(精确匹配 ``product`` property)。
            channel: 可选的渠道过滤(``widget`` / ``discord`` / ``api`` 等);
                非空时附加 ``Filter.by_property("channel_visibility").contains_any``
                限制结果只含声明了对该渠道可见的 chunk。

        Returns:
            ``SearchResult`` 列表(按 Weaviate 返回顺序,未重新排序)。

        Raises:
            RuntimeError: embedder 返回空向量列表。
            Exception: Weaviate 调用失败时原样向上传播。
        """
        # 防御:空 / 纯空白 query 直接返回,避免不必要的 embed / 网络调用
        if not query or not query.strip():
            logger.info("空 query,跳过 hybrid 检索")
            return []

        # embed → query_vector;若 embedder 异常返回空列表,主动抛错(与 ingestion 一致)
        vectors = self._embedder.embed([query])
        if not vectors:
            raise RuntimeError("embedder 返回空向量列表,无法执行 hybrid 检索")
        query_vector = vectors[0].tolist()

        collection = self._client.collections.get(self._class_name)

        # 延迟导入:weaviate 类仅在运行时需要,避免在 import 阶段强依赖 weaviate
        from weaviate.classes.query import Filter, MetadataQuery

        kwargs: Mapping[str, Any] = {
            "query": query,
            "vector": query_vector,
            "alpha": alpha,
            "limit": limit,
            "return_metadata": MetadataQuery(distance=True),
        }

        # 组合 filter:product + channel(AND 语义)
        filters_list: list = []
        if product_filter:
            filters_list.append(
                Filter.by_property("product").equal(product_filter)
            )
        if channel:
            filters_list.append(
                Filter.by_property("channel_visibility").contains_any([channel])
            )
        if len(filters_list) == 1:
            kwargs = {**kwargs, "filters": filters_list[0]}
        elif len(filters_list) >= 2:
            kwargs = {**kwargs, "filters": Filter.all_of(filters_list)}

        # hybrid 调用失败时异常向上传播,由调用方决定重试 / 降级
        results = collection.query.hybrid(**kwargs)

        return [self._to_search_result(obj) for obj in results.objects]

    def _to_search_result(self, obj: Any) -> SearchResult:
        """Weaviate 对象 → SearchResult(含 symbol 字段,search_symbols 复用)。

        Args:
            obj: Weaviate 查询返回的对象(``obj.properties`` / ``obj.metadata``)。

        Returns:
            :class:`SearchResult` 实例;distance → score(``1 - distance``,
            ``None`` 退化为 0.0);channel_visibility list → tuple。
        """
        props = obj.properties or {}
        metadata = obj.metadata
        distance = metadata.distance if metadata is not None else None
        score = 1.0 - distance if distance is not None else 0.0
        cv_raw = props.get("channel_visibility", ["widget", "api"])
        cv_tuple = (
            tuple(cv_raw)
            if isinstance(cv_raw, (list, tuple))
            else ("widget", "api")
        )
        return SearchResult(
            text=props.get("text", ""),
            source_id=props.get("source_id", ""),
            source_type=props.get("source_type", ""),
            product=props.get("product", ""),
            title=props.get("title", ""),
            url=props.get("url", ""),
            score=score,
            chunk_index=props.get("chunk_index", 0),
            chunk_type=props.get("chunk_type", ""),
            doc_section=props.get("doc_section", ""),
            channel_visibility=cv_tuple,
            symbol_name=props.get("symbol_name", ""),
            symbol_signature=props.get("symbol_signature", ""),
        )
