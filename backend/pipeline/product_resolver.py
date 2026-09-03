"""Target Product Resolution(CamThink V1 Answer Correctness,Issue #5 契约 §2)。

问答目标产品解析 —— 确定性、零 LLM、禁止低置信度猜测:

    explicit user product(AskRequest.product)
    → 查询内显式型号(用户亲口说出的产品 = 最高文本信号)
    → page/host context(MSW 非信任元数据,仅在查询未点名产品时采用)
    → conversation-established product(仅在查询含设备指代词时启用:
      追问「这个设备」回指会话中确立的产品,避免把历史产品强加给新话题)
    → 歧义(deixis 在场但无处解析)= PRODUCT_AMBIGUOUS → 文本澄清
    → 无任何信号 = none(不做产品域收窄,保持既有全域行为)

输出 :class:`ProductResolution`:
- ``exact``       单目标(检索收窄到目标 + 共享资格集)
- ``comparison``  多目标(§10:双产品+共享,生成须归属)
- ``ambiguous``   需澄清
- ``unsupported`` 显式 hint 无法 canonicalize(PRODUCT_NOT_SUPPORTED)
- ``none``        不启用产品边界(既有行为,零回归)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.product_taxonomy import Taxonomy

MODE_NONE = "none"
MODE_EXACT = "exact"
MODE_COMPARISON = "comparison"
MODE_AMBIGUOUS = "ambiguous"
MODE_UNSUPPORTED = "unsupported"

SOURCE_EXPLICIT = "explicit"
SOURCE_QUERY = "query"
SOURCE_PAGE_CONTEXT = "page_context"
SOURCE_HISTORY = "history"
SOURCE_NONE = "none"

#: 会话回指扫描的历史消息条数(与 rewrite 的 3 轮窗口语义对齐)
_HISTORY_SCAN_MESSAGES = 6


@dataclass(frozen=True)
class ProductResolution:
    """目标产品解析结果(不可变,进 trace 供观测)。"""

    mode: str
    targets: tuple[str, ...] = ()
    source: str = SOURCE_NONE
    detail: dict[str, Any] = field(default_factory=dict)


def _first_context_product(
    page_context: dict[str, Any] | None, taxonomy: Taxonomy
) -> str | None:
    """page_context 的 product/product_id/sku 按序取首个可 canonicalize 的值。"""
    for key in ("product", "product_id", "sku"):
        value = (page_context or {}).get(key)
        if not value:
            continue
        slug = taxonomy.canonicalize(str(value))
        if slug is not None:
            return slug
    return None


def _history_products(
    history: list[dict] | None, taxonomy: Taxonomy
) -> tuple[str, ...]:
    """会话中用户轮次出现过的 canonical slugs(按最近出现顺序)。"""
    ordered: list[str] = []
    for message in reversed((history or [])[-_HISTORY_SCAN_MESSAGES:]):
        if str(message.get("role", "")) != "user":
            continue
        for slug in taxonomy.extract_products(str(message.get("content", ""))):
            if slug not in ordered:
                ordered.append(slug)
    return tuple(ordered)


def resolve_products(
    query: str,
    *,
    page_context: dict[str, Any] | None = None,
    history: list[dict] | None = None,
    explicit_hint: str | None = None,
    taxonomy: Taxonomy,
) -> ProductResolution:
    """按冻结优先级解析本轮问答的目标产品(纯函数,零 I/O)。"""
    # 1. explicit user product(结构化 hint):可解析 → 权威目标;
    #    不可解析 → PRODUCT_NOT_SUPPORTED(不猜、不回落,诚实上报)
    if explicit_hint:
        slug = taxonomy.canonicalize(explicit_hint)
        if slug is not None and taxonomy.is_targetable(slug):
            return ProductResolution(MODE_EXACT, (slug,), SOURCE_EXPLICIT)
        return ProductResolution(MODE_UNSUPPORTED, (), SOURCE_EXPLICIT)

    # 2. 查询内显式型号:用户本轮亲口点名的产品;≥2 个 = 比较模式(§10)
    query_products = taxonomy.extract_products(query)
    if len(query_products) == 1:
        return ProductResolution(MODE_EXACT, query_products, SOURCE_QUERY)
    if len(query_products) >= 2:
        return ProductResolution(MODE_COMPARISON, query_products, SOURCE_QUERY)

    deixis = taxonomy.has_device_deixis(query)

    # 3. page/host context:宿主页面确立的产品(查询未点名时采纳)
    context_slug = _first_context_product(page_context, taxonomy)
    if context_slug is not None and taxonomy.is_targetable(context_slug):
        return ProductResolution(
            MODE_EXACT, (context_slug,), SOURCE_PAGE_CONTEXT,
            {"deixis": deixis},
        )

    # 4. conversation-established:仅指代追问启用(无指代不回溯历史,
    #    避免「你们公司在哪」被历史产品误收窄)
    if deixis:
        history_products = _history_products(history, taxonomy)
        if len(history_products) == 1:
            return ProductResolution(MODE_EXACT, history_products, SOURCE_HISTORY)
        if len(history_products) >= 2:
            return ProductResolution(MODE_AMBIGUOUS, (), SOURCE_HISTORY)
        # 5. 指代在场但无处解析 → PRODUCT_AMBIGUOUS(文本澄清)
        return ProductResolution(MODE_AMBIGUOUS, (), SOURCE_NONE)

    return ProductResolution(MODE_NONE, (), SOURCE_NONE)
