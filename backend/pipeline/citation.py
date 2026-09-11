"""引用完整性保障层(P1 Citation Integrity)。

CIT-01(引用索引完整性)与 CIT-02(主张↔证据完整性)的确定性执行点。
三个组件共用同一套权威编号集合:

1. :func:`build_citation_context` —— 以访客可见 sources(公开白名单 + 去重 +
   截 5)为唯一权威编号集合拼装 LLM 上下文:可引用资料带 ``[N]`` 编号;
   参与生成但不可见的内容(filesystem 内部案例等)进「背景资料」段,无编号、
   禁止引用。从根上消灭「LLM 编号集 ≠ 访客编号集」的结构性错位。
2. :class:`CitationStreamFilter` —— 流式确定性校验:逐字符状态机解析
   ``[N]`` 标记(容忍跨 token 拆分),悬空 / 越界 / ``[0]`` 标记在下行前剔除;
   标记解析时对自上一标记(或段首)以来的文本窗口做数值支持校验
   (CIT-02 V1 边界):窗口内的显著数字若在所引来源文本中找不到,剔除该
   标记——移除虚假引用权威,不改写主张文本。代码块与 Markdown 链接不按
   引用标记处理。
3. :func:`validate_citations` —— 同步路径与 complete 事件的幂等终验
   (对完整答案跑一遍同样的规则,防御纵深)。

设计约束(Planner 冻结):
- CIT-01 全确定性,不依赖 prompt 措辞;
- CIT-02 为最强合理 V1 边界:数值级必要条件校验(无二次 LLM 调用),
  非数值能力类主张依赖 prompt 契约,残余语义局限在执行报告中显式声明;
- 校验只剔除引用标记,不删改答案正文(不改写语义);
- 不泄漏内部源内容到校验错误信息。
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from backend.retrieval.search import SearchResult

if TYPE_CHECKING:
    from backend.product_taxonomy import Taxonomy

# --------------------------------------------------------------------------- #
# 权威可见性 / 展示常量(自 rag.py 迁入:citation 是唯一定义点,rag 反向引用)
# --------------------------------------------------------------------------- #

SOURCE_LABELS = {
    "github": "[GitHub]",
    "wiki": "[Wiki]",
    "website": "[官网]",
    "web_crawl": "[官网]",
    "blog": "[博客]",
    "filesystem": "[知识库]",
}

# 对外展示的 source 类型白名单(终端用户可见的 sources 列表)。
# 注意(P0 PC-01):这只是**展示层**过滤,不是信任边界——生成前的授权由
# chunk 级 channel_visibility 检索过滤(主防线)+ SourceVisibilityGuard
# (backend/services/source_visibility.py,纵深)强制执行。
PUBLIC_SOURCE_TYPES: frozenset[str] = frozenset(
    {"local_git", "github", "woocommerce", "website", "web_crawl"}
)

# 第一方知识案例(#28):knowledge-support-cases 管道产出的官方案例记录
# (source_type=filesystem 且 product=knowledge)是第一方权威事实来源,
# 可作为**有编号的可引用来源**参与组合;展示以标题呈现、不外泄文件系统
# 路径(url 置空),来源身份按 source_id 匹配。显式 ``internal`` 可见性
# 标记的 chunk 仍排除(降级背景段)——隐私豁免是显式配置,不做类型推断。
CASE_SOURCE_TYPE = "filesystem"
CASE_PRODUCT = "knowledge"
_INTERNAL_VISIBILITY_MARKER = "internal"


def is_first_party_case_source(
    source_type: str | None,
    product: str | None,
    channel_visibility: object = (),
) -> bool:
    """chunk 是否属于第一方知识案例(可按标题引用、路径不外泄)。"""
    if source_type != CASE_SOURCE_TYPE or (product or "") != CASE_PRODUCT:
        return False
    visibility = (
        tuple(channel_visibility) if isinstance(channel_visibility, (list, tuple)) else ()
    )
    return _INTERNAL_VISIBILITY_MARKER not in visibility

_I18N_PREFIXES = (
    "/i18n/en/docusaurus-plugin-content-docs/current/",
    "/i18n/zh-CN/docusaurus-plugin-content-docs/current/",
)


def normalize_source_path(url: str) -> str:
    """归一化来源 URL,使同一文档的翻译版本去重。

    去除 Docusaurus i18n 路径前缀,使 ``docs/foo.md`` 与
    ``i18n/en/.../foo.md`` 映射到同一 key。
    """
    for prefix in _I18N_PREFIXES:
        if prefix in url:
            return url.replace(prefix, "/docs/")
    return url


# --------------------------------------------------------------------------- #
# 权威编号上下文构建
# --------------------------------------------------------------------------- #

CITABLE_SECTION_HEADER = "## 可引用资料"
BACKGROUND_SECTION_HEADER = "## 背景资料(仅供理解上下文,禁止引用,严禁在其内容后标注 [N])"


@dataclass
class CitationContext:
    """权威编号上下文。

    Attributes:
        context: 拼装好的 LLM 上下文文本(可引用段 + 可选背景段)。
        source_texts: 编号(1-based)→ 该源全部 chunk 文本,数值支持校验的数据基础。
        source_products: 编号(1-based)→ 该源 chunk 的原始 product 标签
            (CIT-03 产品资格校验 + 逐证据归属展示的数据基础)。
        stats: 构建统计(写入 trace 供审查)。
    """

    context: str
    source_texts: dict[int, list[str]] = field(default_factory=dict)
    source_products: dict[int, str] = field(default_factory=dict)
    stats: dict = field(default_factory=dict)


def build_citation_context(
    reranked: list[SearchResult],
    sources: list[dict],
    taxonomy: "Taxonomy | None" = None,
) -> CitationContext:
    """以访客可见 ``sources`` 为唯一权威编号集合拼装 LLM 上下文。

    Args:
        reranked: 重排(或降级 fused)后的 SearchResult 列表。
        sources: ``RAGOrchestrator._extract_sources`` 的输出——访客可见
            来源列表(公开白名单 + 归一化去重 + 截 5),编号即列表序。
        taxonomy: 产品 taxonomy(缺省取进程默认);用于逐证据产品归属
            展示(Issue #5 契约 §6)与 CIT-03 资格校验数据。

    Returns:
        :class:`CitationContext`。公开源 chunk 按其所属源的编号归组;
        第 5 个公开页之外的 chunk 从上下文丢弃(否则可被引用但访客不可见);
        非公开但参与生成的 chunk(filesystem 内部案例等)进背景资料段。
    """
    if taxonomy is None:
        from backend.product_taxonomy import get_taxonomy

        taxonomy = get_taxonomy()
    url_to_idx: dict[str, int] = {}
    case_idx_by_source: dict[str, int] = {}
    for i, s in enumerate(sources):
        # path-less 案例(url='')不注册 URL 键:空串键会让所有无 URL chunk
        # 误配到同一编号;案例身份只走 case_idx_by_source(source_id 匹配)。
        if s.get("url"):
            url_to_idx[normalize_source_path(s["url"])] = i + 1
        # 第一方知识案例:path-less 来源(url 置空),身份按 source_id 匹配。
        if s.get("source_id"):
            case_idx_by_source[s["source_id"]] = i + 1
        # CIT-URL 集成桥:sources[].url 呈现 canonical 时,原 GitHub blob URL
        # 保留在 provenance_url;rerank 候选仍带原始 URL,须映射到同一编号,
        # 否则 wiki chunk 全部落入 dropped_public_chunks、编号权威断裂。
        provenance = s.get("provenance_url")
        if provenance:
            url_to_idx.setdefault(normalize_source_path(provenance), i + 1)
    source_texts: dict[int, list[str]] = defaultdict(list)
    source_products: dict[int, str] = {}
    background_chunks: list[str] = []
    dropped_public_chunks = 0

    # INC-1 血统修订:终组合逐项身份(仅元数据,零内容)
    citable_ids: list[dict] = []
    background_ids: list[dict] = []
    dropped_public_ids: list[dict] = []

    for r in reranked:
        idx = url_to_idx.get(normalize_source_path(r.url))
        if (
            idx is None
            and is_first_party_case_source(r.source_type, r.product, r.channel_visibility)
        ):
            # #28:第一方知识案例按 source_id 匹配 path-less 编号来源
            idx = case_idx_by_source.get(r.source_id)
        if idx is not None:
            source_texts[idx].append(r.text or "")
            source_products.setdefault(idx, r.product or "")
            # citation_no = 来源序号(引用编号语义不变:同源 chunk 同号)
            citable_ids.append(
                {"source_id": r.source_id, "chunk_index": r.chunk_index, "citation_no": idx}
            )
        elif r.source_type in PUBLIC_SOURCE_TYPES or is_first_party_case_source(
            r.source_type, r.product, r.channel_visibility
        ):
            # 公开但排在可见集合之外:保留即可被引用 → 不可见引用,丢弃
            dropped_public_chunks += 1
            dropped_public_ids.append({"source_id": r.source_id, "chunk_index": r.chunk_index})
        else:
            # 授权参与生成但不对外展示(如 filesystem 内部案例)→ 背景资料
            background_chunks.append(r.text or "")
            background_ids.append({"source_id": r.source_id, "chunk_index": r.chunk_index})

    citable_parts: list[str] = []
    for i, s in enumerate(sources, 1):
        chunks = source_texts.get(i)
        if not chunks:
            continue
        label = SOURCE_LABELS.get(s.get("type", ""), f"[{s.get('type', '?')}]")
        product_attribution = taxonomy.display_name(source_products.get(i, ""))
        body = "\n\n".join(chunks)
        citable_parts.append(
            f"[{i}] {label} {s.get('title', '')}\nURL: {s.get('url', '')}"
            f"\n产品: {product_attribution}\n\n{body}"
        )

    if citable_parts:
        context = CITABLE_SECTION_HEADER + "\n\n" + "\n\n---\n\n".join(citable_parts)
    else:
        context = CITABLE_SECTION_HEADER + "\n\n(无可引用资料)"

    if background_chunks:
        context += (
            "\n\n" + BACKGROUND_SECTION_HEADER + "\n\n" + "\n\n---\n\n".join(background_chunks)
        )

    stats = {
        "public_chunks": sum(len(v) for v in source_texts.values()),
        "background_chunks": len(background_chunks),
        "dropped_public_chunks": dropped_public_chunks,
        # INC-1 血统修订:逐项身份表(citable.citation_no = 引用编号语义)
        "citable": citable_ids,
        "background": background_ids,
        "dropped_public": dropped_public_ids,
    }
    return CitationContext(
        context=context,
        source_texts=dict(source_texts),
        source_products=dict(source_products),
        stats=stats,
    )


# --------------------------------------------------------------------------- #
# 数值支持校验(CIT-02 V1 边界:确定性必要条件筛查)
# --------------------------------------------------------------------------- #

_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
# 数字后紧邻这些字符视为带物理/商业单位(单数字如 7V/5% 才参与校验,
# 避免把"第 1 步"这类普通小数字误伤)
_UNIT_CHARS = set("%°VAWhzwkKMGm")

_FULLWIDTH_DIGITS = {ord(c): ord(c) - ord("０") + ord("0") for c in "０１２３４５６７８９"}


def _normalize_digits(text: str) -> str:
    """数字匹配前的归一化:全角转半角、去千分位逗号。"""
    return re.sub(r"(?<=\d),(?=\d)", "", text.translate(_FULLWIDTH_DIGITS))


def _significant_numbers(text: str) -> list[str]:
    """提取需要做存在性校验的显著数字。

    规则:数值 ≥ 10、含小数点、或紧邻单位字符(7V / 5% / 2.5W)。
    返回去符号的数字串(如 "59" / "2.5" / "1200")。
    """
    out: list[str] = []
    for m in _NUM_RE.finditer(text):
        num = m.group(0)
        digits = num.lstrip("+-")
        followed = text[m.end() : m.end() + 2]
        has_unit = followed[:1] in _UNIT_CHARS or (
            followed[:1] == " " and followed[1:2] in _UNIT_CHARS
        )
        try:
            value = float(num)
        except ValueError:  # pragma: no cover - 正则保证可解析
            continue
        if value >= 10 or "." in digits or has_unit:
            out.append(digits)
    return out


def _number_supported(num: str, texts: list[str]) -> bool:
    """数字 ``num`` 是否在任一来源文本中出现(带数字边界,防 59≠1590 误匹配)。"""
    pat = re.compile(rf"(?<!\d){re.escape(num)}(?!\d)")
    return any(pat.search(_normalize_digits(t)) for t in texts)


def numbers_supported(window: str, texts: list[str]) -> bool:
    """窗口内全部显著数字都能在 ``texts`` 中找到 → 该引用有数值支持。"""
    nums = _significant_numbers(window)
    return all(_number_supported(n, texts) for n in nums)


# --------------------------------------------------------------------------- #
# 流式确定性校验过滤器
# --------------------------------------------------------------------------- #

_MAX_MARKER_DIGITS = 3  # [999] 以内才算引用标记形状;[1234](年份等)原样透传

# INC-6:逐标记验证事件上限(trace 有界;超出仅计数,以 truncated 标记)
_MAX_VALIDATION_EVENTS = 32


class CitationStreamFilter:
    """token 流上的引用标记确定性校验器。

    - 增量解析 ``[N]``:跨 token 拆分("[" / "2" / "]")通过 holdback 缓冲处理;
    - ``[N]`` 后紧跟 ``(`` 视为 Markdown 链接文本,不按引用处理;
    - ``` 代码围栏内不做任何标记处理(不破坏代码内容);
    - 悬空(越界 / ``[0]``)标记直接剔除;合法标记解析时做数值支持校验,
      无据则剔除标记(移除虚假引用权威),两者均计入 stats;
    - 文本窗口 = 自上一个标记解析处(或空行段界)以来已下发的文本,
      逐段归因(CIT-G007 多源映射保持);
    - INC-6:每个解析完成的标记追加一条**显式验证结果**(四态 outcome +
      reason + 窗口字符数,零正文),强制行为与既有逐字节一致——分类不改
      任何剔除/保留决策(词表权威:backend.pipeline.claim_validation)。
    """

    def __init__(
        self,
        n_sources: int,
        source_texts: dict[int, list[str]] | None = None,
        source_products: dict[int, str] | None = None,
        eligible_slugs: frozenset[str] | set[str] | None = None,
    ) -> None:
        """CIT-03:``source_products`` + ``eligible_slugs`` 同时提供时启用
        产品资格校验(编号所属产品不在资格集 → 剔除标记);两者缺省时
        行为与 CIT-01/02 基线逐字节一致。
        """
        self._n = n_sources
        self._texts = source_texts or {}
        self._products = source_products or {}
        self._eligible = eligible_slugs
        self._pending = ""  # holdback:"[" + 若干数字(未决标记)
        self._candidate = ""  # 已成形 "[N]",等待下一个字符排除链接形态
        self._in_fence = False
        self._backtick_run = 0
        self._window = ""  # 当前段的已下发文本(数值归因窗口)
        self.stats = {
            "markers_seen": 0,
            "dangling_dropped": 0,
            "unsupported_dropped": 0,
            "ineligible_product_dropped": 0,
            # INC-6:结果分类(计数不截断,与事件上限解耦)
            "outcome_counts": {
                "SUPPORTED": 0,
                "UNSUPPORTED": 0,
                "UNVALIDATABLE": 0,
                "NOT_APPLICABLE": 0,
            },
            "validation_events": [],
            "validation_events_truncated": False,
        }

    # -- 内部工具 ---------------------------------------------------------- #

    def _record_validation(self, citation_no: int, outcome: str, reason: str, window: str) -> None:
        """追加一条有界验证事件并累计结果计数(零正文;不改变任何强制决策)。"""
        self.stats["outcome_counts"][outcome] += 1
        events = self.stats["validation_events"]
        if len(events) < _MAX_VALIDATION_EVENTS:
            events.append(
                {
                    "citation_no": citation_no,
                    "outcome": outcome,
                    "reason": reason,
                    "window_chars": len(window),
                }
            )
        else:
            self.stats["validation_events_truncated"] = True

    def _emit(self, out: list[str], text: str) -> None:
        out.append(text)
        self._window += text
        # 段界重置:窗口只保留当前段(空行之后的文本),避免跨段数字误归因
        idx = self._window.rfind("\n\n")
        if idx >= 0:
            self._window = self._window[idx + 2 :]

    def _resolve_marker(self, out: list[str], marker: str) -> None:
        """解析合法形状的 ``[N]``:范围 → 产品资格(CIT-03)→ 数值支持。"""
        n = int(marker[1:-1])
        self.stats["markers_seen"] += 1
        window = self._window
        self._window = ""
        if not (1 <= n <= self._n):
            self._record_validation(n, "UNSUPPORTED", "dangling_marker", window)
            self.stats["dangling_dropped"] += 1
            return
        if self._eligible is not None:
            from backend.product_taxonomy import get_taxonomy

            product_slug = get_taxonomy().canonicalize(self._products.get(n, ""))
            if product_slug is None or product_slug not in self._eligible:
                # sibling 编号不支持 target-specific claim:剔除引用权威,
                # 不改写主张文本(与 CIT-01/02 同语义)。
                self._record_validation(n, "UNSUPPORTED", "product_ineligible", window)
                self.stats["ineligible_product_dropped"] += 1
                return
        texts = self._texts.get(n, [])
        if texts and not numbers_supported(window, texts):
            self._record_validation(n, "UNSUPPORTED", "numeric_unsupported", window)
            self.stats["unsupported_dropped"] += 1
            return
        # INC-6:通过强制检查的标记按窗口真值分类(行为不变,仅显式化):
        # 空/纯空白窗口 = 无主张可验证;无显著数值(或无源文本可校验)=
        # 无可成立的确定性必要条件;其余 = 全部可判定检查通过。
        if not window.strip():
            self._record_validation(n, "NOT_APPLICABLE", "vacuous_window", window)
        elif not texts or not _significant_numbers(window):
            self._record_validation(
                n, "UNVALIDATABLE", "no_deterministic_necessary_condition", window
            )
        else:
            self._record_validation(n, "SUPPORTED", "all_checks_passed", window)
        self._emit(out, marker)

    def _flush_pending(self, out: list[str]) -> None:
        if self._pending:
            self._emit(out, self._pending)
            self._pending = ""

    # -- 公开接口 ---------------------------------------------------------- #

    def feed(self, chunk: str) -> str:
        """喂入一个 LLM token,返回可安全下发的文本(可能为空)。"""
        out: list[str] = []
        for ch in chunk:
            if ch == "`":
                self._backtick_run += 1
                if self._backtick_run >= 3:
                    self._in_fence = not self._in_fence
                    self._backtick_run = 0
            else:
                self._backtick_run = 0

            if self._candidate:
                # 已成形 "[N]":看下一个字符排除链接形态 [N](url)
                if ch == "(":
                    self._emit(out, self._candidate + ch)
                else:
                    self._resolve_marker(out, self._candidate)
                    self._step(out, ch)
                self._candidate = ""
                continue

            if self._pending:
                if ch.isdigit() and len(self._pending) < 1 + _MAX_MARKER_DIGITS:
                    self._pending += ch
                elif ch == "]" and len(self._pending) >= 2:
                    self._candidate = self._pending + "]"
                    self._pending = ""
                else:
                    self._flush_pending(out)
                    self._step(out, ch)
                continue

            self._step(out, ch)
        return "".join(out)

    def _step(self, out: list[str], ch: str) -> None:
        """普通字符步进(候选/挂起为空时)。"""
        if not self._in_fence and ch == "[":
            self._pending = "["
            return
        self._emit(out, ch)

    def finish(self) -> str:
        """流结束:冲刷 holdback。完整形状标记就地解析,未成形按字面量。"""
        out: list[str] = []
        if self._candidate:
            self._resolve_marker(out, self._candidate)
            self._candidate = ""
        self._flush_pending(out)
        return "".join(out)


def validate_citations(
    answer: str,
    n_sources: int,
    source_texts: dict[int, list[str]] | None = None,
    source_products: dict[int, str] | None = None,
    eligible_slugs: frozenset[str] | set[str] | None = None,
) -> tuple[str, dict]:
    """对完整答案做幂等引用终验(同步路径 / complete 事件防御纵深)。

    CIT-03:提供 ``source_products`` + ``eligible_slugs`` 时同步执行产品
    资格校验;缺省时行为与基线一致。

    Returns:
        (校验后的答案, stats)——只剔除悬空/无据/产品不合格标记,不改写其他文本。
    """
    f = CitationStreamFilter(
        n_sources=n_sources,
        source_texts=source_texts,
        source_products=source_products,
        eligible_slugs=eligible_slugs,
    )
    out = f.feed(answer)
    out += f.finish()
    return out, dict(f.stats)
