"""文档分段管道(chunking pipeline)。

将 RawDocument 按结构性标题(## / ###)切分,合并过小片段,并对超长
section 执行 token 级硬切(带 overlap 滑窗)。输出多个不可变 Chunk
供后续灌入向量库。

设计要点:
- token 估算复用模块级缓存的 tiktoken 编码器(避免每次重载 BPE 合并表)。
- Chunk 为 frozen dataclass,字段包含文档溯源所需的全部元数据。
- chunk_document 对空 content / None content 返回空列表(见 docstring)。
- 超长 section(max_tokens 上限无法容纳)走 _hard_split_section 滑窗硬切,
  在窗口之间保留 overlap 个 token 的上下文,改善下游检索召回。
- _hard_split_section 使用 byte 偏移跟踪(decode_single_token_bytes) +
  byte→char 映射表,精确处理 UTF-8 多字节字符(中文 / emoji),避免
  decode([tid]) 产生的 U+FFFD 替换字符导致字符偏移漂移。
"""

import logging
import re
from dataclasses import dataclass
from functools import lru_cache

import tiktoken

from backend.connectors.base import RawDocument

logger = logging.getLogger(__name__)

# tiktoken 默认编码名(Task 21 BudgetLimiter 复用同编码,后续可抽到 config)。
_DEFAULT_ENCODING = "cl100k_base"


@lru_cache(maxsize=8)
def _get_encoding(encoding_name: str = _DEFAULT_ENCODING) -> tiktoken.Encoding:
    """返回(并缓存)tiktoken 编码器。

    tiktoken.get_encoding 每次调用都会重新加载 BPE 合并表(~1ms),
    在 chunking / budget 控制等热路径上累积可观开销。用 lru_cache 复用
    同名 Encoding 实例。

    Args:
        encoding_name: tiktoken 编码名(默认 cl100k_base,匹配 GPT-4/Ada)。

    Returns:
        tiktoken.Encoding 实例。
    """
    return tiktoken.get_encoding(encoding_name)


def _estimate_tokens(text: str) -> int:
    """估算文本 token 数(使用缓存的 cl100k_base 编码器)。"""
    return len(_get_encoding().encode(text))


@dataclass(frozen=True)
class Chunk:
    """文档分段后的不可变 chunk。

    所有字段在 chunk_document 内一次性填充;下游(embedder、weaviate writer、
    reranker)只读访问。

    Attributes:
        text: chunk 文本内容。
        document: 所属 RawDocument(溯源 + metadata 透传)。
        chunk_index: 当前 chunk 在所属文档内的顺序索引(从 0 起)。
        total_chunks: 所属文档切出的 chunk 总数。
        start_char: chunk.text 在 document.content 中的起始字符偏移。
        end_char: chunk.text 在 document.content 中的结束字符偏移(不含)。
        chunk_type: chunk 语义类型(heading / paragraph / code / list / table),
            Phase 2A Task 2 由 Markdown 语义块识别器填充。默认 ``"paragraph"``
            兼容现有 chunk_document 调用路径(全部按段落处理)。
        doc_section: chunk 所属文档章节路径(如 ``"安装 > 依赖"``),Phase 2A
            Task 2 填充。默认空串表示未标注。
        channel_visibility: 该 chunk 允许透出的渠道白名单(tuple 保证不可变),
            Phase 2A Task 5 由 connector 配置透传。默认 ``("widget", "api")``
            表示对所有渠道可见。
    """

    text: str
    document: RawDocument
    chunk_index: int
    total_chunks: int
    start_char: int
    end_char: int
    # Phase 2A 新增字段(均有默认值,保证现有调用零回归)
    chunk_type: str = "paragraph"
    doc_section: str = ""
    channel_visibility: tuple[str, ...] = ("widget", "api")
    # 函数级符号检索新增字段(均有默认值,兼容文档 chunk)
    symbol_name: str = ""
    symbol_signature: str = ""
    symbol_node_type: str = ""
    symbol_tokens: str = ""


@dataclass(frozen=True)
class SemanticBlock:
    """Markdown 语义块(不可变)。

    由 _identify_blocks 产出,描述一个 Markdown 块级元素(标题/代码块/列表/表格/段落)
    在原文中的字符范围与类型。

    Attributes:
        block_type: 块类型 — heading / paragraph / code / list / table。
        start_char: 在原文中的起始字符偏移(含)。
        end_char: 在原文中的结束字符偏移(不含)。
        heading_level: 标题级别 1-6;非标题块为 0。
    """

    block_type: str
    start_char: int
    end_char: int
    heading_level: int


def _build_byte_to_char_map(encoded: bytes) -> list[int]:
    """构建 byte 偏移 → 完整 UTF-8 字符数的映射表(O(N))。

    ``byte_to_char[b]`` 等价于 ``len(encoded[:b].decode("utf-8", errors="ignore"))``,
    即 ``encoded[:b]`` 范围内的完整 UTF-8 字符数量。位于多字节字符"内部"的
    byte 位置不会增加字符计数,直到该字符的全部字节都已消费。

    用于把 tiktoken BPE token 的 byte 偏移精确映射到 Python str 的字符偏移,
    避免 ``decode([tid])`` 对跨 UTF-8 字节边界的 token 返回 U+FFFD 替换字符
    (len=1) 导致的字符偏移正向漂移。

    Args:
        encoded: 已编码的 UTF-8 字节串。

    Returns:
        长度 ``len(encoded) + 1`` 的列表,索引为 byte 偏移,值为字符数。
    """
    n = len(encoded)
    byte_to_char = [0] * (n + 1)
    char_idx = 0
    i = 0
    while i < n:
        first = encoded[i]
        # UTF-8 首字节 → 字符字节宽度的判定
        if first < 0x80:
            width = 1
        elif first < 0xC0:
            # 意外的续字节(非法 UTF-8),按 1 字节跳过,不计字符
            width = 1
            byte_to_char[i + 1] = char_idx
            i += 1
            continue
        elif first < 0xE0:
            width = 2
        elif first < 0xF0:
            width = 3
        else:
            width = 4

        end = i + width
        if end <= n:
            # 字符完整:内部字节位置保持当前 char_idx,末尾递增
            for j in range(i + 1, end):
                byte_to_char[j] = char_idx
            char_idx += 1
            byte_to_char[end] = char_idx
            i = end
        else:
            # 字符不完整(截断),剩余位置保持 char_idx
            for j in range(i + 1, n + 1):
                byte_to_char[j] = char_idx
            break
    return byte_to_char


_FENCE_PATTERN = re.compile(r"^(?:```|~~~)", re.MULTILINE)
_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+", re.MULTILINE)
_LIST_PATTERN = re.compile(r"^\s*(?:[-*+]|\d+\.)\s", re.MULTILINE)
_TABLE_PATTERN = re.compile(r"^\|.*\|$", re.MULTILINE)


def _identify_blocks(content: str) -> list[SemanticBlock]:
    """识别 Markdown 语义块边界,保护代码块内的标题不被误判。

    扫描策略:
    1. 先用 _FENCE_PATTERN 找到所有代码块范围,记录为不可切分的 code 块。
    2. 在代码块范围外,用 _HEADING_PATTERN 找到标题边界。
    3. 在代码块范围外,用 _LIST_PATTERN / _TABLE_PATTERN 找到列表/表格边界。
    4. 两个相邻边界之间的文本若无其他类型标记,归为 paragraph。

    Args:
        content: Markdown 原文。

    Returns:
        SemanticBlock 列表,按 start_char 升序,覆盖 content 全部字符。
    """
    if not content:
        return []

    n = len(content)
    blocks: list[SemanticBlock] = []

    # Step 1: 找出所有代码块范围 (start_char, end_char)
    # 用开闭配对迭代:所有 fence 标记按出现顺序两两配对(第 0 个开 → 第 1 个闭,
    # 第 2 个开 → 第 3 个闭, ...) 独立匹配每个 fence 会同时命中开闭标记,
    # 导致闭合 fence 被误认为新的开启 fence。
    code_ranges: list[tuple[int, int]] = []
    fence_matches = list(re.finditer(r"^(?:```|~~~)", content, re.MULTILINE))
    for i in range(0, len(fence_matches) - 1, 2):
        open_m = fence_matches[i]
        close_m = fence_matches[i + 1]
        code_ranges.append((open_m.start(), close_m.end()))
        blocks.append(SemanticBlock(
            block_type="code", start_char=open_m.start(), end_char=close_m.end(),
            heading_level=0,
        ))

    def _in_code_range(pos: int) -> bool:
        return any(s <= pos < e for s, e in code_ranges)

    # Step 2: 识别标题边界(排除代码块内的)
    heading_positions: list[tuple[int, int, int]] = []  # (start, end, level)
    for m in _HEADING_PATTERN.finditer(content):
        if _in_code_range(m.start()):
            continue
        level = len(m.group(1))
        line_end = content.find("\n", m.start())
        if line_end == -1:
            line_end = n
        heading_positions.append((m.start(), line_end, level))

    # Step 3: 识别列表和表格的起始位置(排除代码块内的)
    list_positions: list[tuple[int, int]] = []
    for m in _LIST_PATTERN.finditer(content):
        if _in_code_range(m.start()):
            continue
        list_positions.append((m.start(), m.end()))

    table_positions: list[tuple[int, int]] = []
    for m in _TABLE_PATTERN.finditer(content):
        if _in_code_range(m.start()):
            continue
        table_positions.append((m.start(), m.end()))

    # Step 4: 构建非代码块区域的块
    # 收集所有边界点(代码块边界 + 标题/列表/表格起始)
    boundaries: set[int] = {0, n}
    for s, e in code_ranges:
        boundaries.add(s)
        boundaries.add(e)
    for s, end, _ in heading_positions:
        boundaries.add(s)
        boundaries.add(end)  # 标题行尾:让标题块只覆盖标题行本身,避免吸收后续段落文本
    for s, _ in list_positions:
        boundaries.add(s)
    for s, _ in table_positions:
        boundaries.add(s)

    sorted_boundaries = sorted(boundaries)
    heading_map = {s: lvl for s, _, lvl in heading_positions}
    list_starts = {s for s, _ in list_positions}
    table_starts = {s for s, _ in table_positions}

    for i in range(len(sorted_boundaries) - 1):
        start = sorted_boundaries[i]
        end = sorted_boundaries[i + 1]
        # 跳过代码块内部区域(已被 code 块覆盖)
        if any(cs <= start < ce for cs, ce in code_ranges):
            continue
        text = content[start:end].strip()
        if not text:
            continue
        if start in heading_map:
            blocks.append(SemanticBlock(
                block_type="heading", start_char=start, end_char=end,
                heading_level=heading_map[start],
            ))
        elif start in list_starts:
            blocks.append(SemanticBlock(
                block_type="list", start_char=start, end_char=end, heading_level=0,
            ))
        elif start in table_starts:
            blocks.append(SemanticBlock(
                block_type="table", start_char=start, end_char=end, heading_level=0,
            ))
        else:
            blocks.append(SemanticBlock(
                block_type="paragraph", start_char=start, end_char=end, heading_level=0,
            ))

    blocks.sort(key=lambda b: b.start_char)
    return blocks


def _classify_chunk_type(text: str) -> str:
    """根据 chunk 文本内容判断主导类型。

    判断逻辑(按优先级):
    1. 若文本以标题行开头(# / ## / ... / ######) → 'heading'
    2. 统计代码块行数(fence 内)、列表行数、表格行数,取占比最高的类型
    3. 默认 → 'paragraph'

    Args:
        text: chunk 文本。

    Returns:
        chunk_type ∈ {heading, paragraph, code, list, table}。
    """
    if not text:
        return "paragraph"

    lines = text.split("\n")

    # 标题检测:首行非空行是否为标题
    first_non_empty = next((ln for ln in lines if ln.strip()), "")
    if re.match(r"^#{1,6}\s+", first_non_empty):
        return "heading"

    total_lines = max(1, len([ln for ln in lines if ln.strip()]))
    code_lines = 0
    list_lines = 0
    table_lines = 0
    in_fence = False

    for ln in lines:
        stripped = ln.strip()
        if re.match(r"^(```|~~~)", stripped):
            in_fence = not in_fence
            continue
        if in_fence:
            code_lines += 1
        elif re.match(r"^\s*(?:[-*+]|\d+\.)\s", ln):
            list_lines += 1
        elif re.match(r"^\|.*\|$", stripped):
            table_lines += 1

    code_ratio = code_lines / total_lines
    list_ratio = list_lines / total_lines
    table_ratio = table_lines / total_lines

    if code_ratio >= 0.5:
        return "code"
    if list_ratio >= 0.4:
        return "list"
    if table_ratio >= 0.4:
        return "table"
    return "paragraph"


def _build_doc_section(heading_stack: list[tuple[int, str]]) -> str:
    """从标题层级栈构建 doc_section 路径字符串。

    heading_stack 中的每个元素为 (level, title),level ∈ [1, 6]。
    栈中的层级必须合法(不会出现 level 3 跟在 level 1 后面而跳过 level 2),
    因为调用方在 push 前已经做了 pop 操作。

    Args:
        heading_stack: 标题栈,按文档出现顺序排列。

    Returns:
        用 " > " 连接的标题路径;空栈返回空字符串。
    """
    return " > ".join(title for _, title in heading_stack)


def _split_by_structure(content: str) -> list[tuple[str, int]]:
    """按 Markdown 标题(## / ###)切分文本,返回 ``(section_text, start_offset)`` 元组列表。

    使用零宽 lookahead ``\\n(?=#{1,3}\\s)``,确保分隔符(``\\n``)不出现在
    结果中,让标题保留在每个 section 开头。

    ``start_offset`` 是 stripped section **内容** 在原文中的字符偏移,
    用于让后续管道跳过 ``content.find()`` 定位(对含前导空白 / 多换行的
    原文不可靠)。

    Args:
        content: 待切分的原始文本。

    Returns:
        ``(stripped_section, start_offset_in_content)`` 元组列表;
        空白片段被丢弃。
    """
    split_positions = [m.start() for m in re.finditer(r"\n(?=#{1,3}\s)", content)]
    # 每个 split 位置是 \n 的索引,+1 跳过 \n(它不属于下一个 section)
    boundaries = [0, *(p + 1 for p in split_positions), len(content)]

    result: list[tuple[str, int]] = []
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        part = content[start:end]
        stripped = part.strip()
        if not stripped:
            continue
        # stripped 内容在 part 中的偏移 = 前导空白长度
        strip_offset = len(part) - len(part.lstrip())
        result.append((stripped, start + strip_offset))
    return result


def _merge_small_sections(
    sections: list[tuple[str, int]],
    max_tokens: int,
) -> list[tuple[str, int]]:
    """把相邻小 section 合并到 max_tokens 以内的单元。

    策略:维护一个 buffer,尝试把当前 section append 到 buffer;若超限则
    flush buffer,开启新 buffer。**注意**:单个 section 本身超过 max_tokens
    时会被原样 append,交由 :func:`_hard_split_section` 二次切分。

    Args:
        sections: ``_split_by_structure`` 的输出—— ``(text, start_offset)`` 元组列表。
        max_tokens: 单个合并单元的 token 上限。

    Returns:
        ``(merged_text, start_offset)`` 元组列表;
        ``start_offset`` 取合并组中 **第一个** section 的偏移。
    """
    merged: list[tuple[str, int]] = []
    buffer_text = ""
    buffer_offset = 0
    for section_text, section_offset in sections:
        candidate = f"{buffer_text}\n\n{section_text}" if buffer_text else section_text
        if _estimate_tokens(candidate) <= max_tokens:
            if not buffer_text:
                buffer_offset = section_offset
            buffer_text = candidate
        else:
            if buffer_text:
                merged.append((buffer_text, buffer_offset))
            buffer_text = section_text
            buffer_offset = section_offset
    if buffer_text:
        merged.append((buffer_text, buffer_offset))
    return merged


def _hard_split_section(
    section: str,
    max_tokens: int,
    overlap: int,
) -> list[tuple[str, int, int]]:
    """对超长 section 做 token 级滑窗硬切。

    将 section 按 cl100k_base 切成 token id 序列,以 ``(max_tokens - overlap)``
    为步长滑窗,每个窗口解码回文本并记录在 section 内的 ``(start, end)`` 字符
    偏移。

    **Byte 偏移跟踪(C1 修复)**:使用 ``decode_single_token_bytes(tid)`` 跟踪
    BPE token 的 UTF-8 byte 偏移,再通过 :func:`_build_byte_to_char_map` 映射
    到 Python str 字符偏移。相比旧的 ``decode([tid])`` 逐 token 字符累加方案,
    能正确处理跨 UTF-8 字节边界的 BPE token(对中文 / emoji 不产生偏移漂移)。

    **窗口起始字符对齐**:若窗口起始 token 位于多字节字符的续字节位置
    (即 ``byte_to_char[b] == byte_to_char[b-1]``),``start_char`` 向后推进
    1 个字符,跳过不完整字符——否则该字符的另一半 token 属于上一个窗口,
    会导致 re-encode 后 chunk 的 token 数超出 max_tokens。

    边界:
    - 若 section 实际 token 数 <= max_tokens,原样返回 ``[(section, 0, len)]``。
    - 若 overlap >= max_tokens,将其钳制为 ``max_tokens // 2`` 并 warning,避免死循环。
    - 空窗口(``start_char >= end_char``,由续字节跳过产生)仍被返回,
      由 :func:`chunk_document` 的空 chunk 过滤兜底(I1)。

    Args:
        section: 待硬切的 section 文本。
        max_tokens: 单个 chunk 的 token 上限。
        overlap: 相邻 chunk 间重叠的 token 数。

    Returns:
        列表,每项为 ``(chunk_text, start_char_in_section, end_char_in_section)``。
    """
    if not section:
        return []
    if _estimate_tokens(section) <= max_tokens:
        return [(section, 0, len(section))]

    # 钳制 overlap,防止 step <= 0 死循环
    safe_overlap = min(overlap, max_tokens // 2)
    if safe_overlap != overlap:
        logger.warning(
            "overlap=%d 被钳制为 %d(max_tokens=%d)",
            overlap,
            safe_overlap,
            max_tokens,
        )
    step = max(1, max_tokens - safe_overlap)

    enc = _get_encoding()
    token_ids = enc.encode(section)
    encoded = section.encode("utf-8")
    n_bytes = len(encoded)
    byte_to_char = _build_byte_to_char_map(encoded)

    # 每个 token 的 (start_char, end_char, start_byte)。
    # start_byte 用于检测窗口起始是否落在多字节字符的续字节位置。
    offsets: list[tuple[int, int, int]] = []
    cursor_b = 0
    for tid in token_ids:
        try:
            tb = enc.decode_single_token_bytes(tid)
        except KeyError:
            # 特殊 token(罕见,如 BOS/EOS/prompt marker),退化到 decode 字符宽度。
            # 注意:此分支下 tb 可能与 encoded 的真实字节不一致,导致 cursor_b 漂移;
            # 普通文本不会走这里(cl100k_base encode 默认不产出 special token)。
            tb = enc.decode([tid]).encode("utf-8")
        start_b = min(cursor_b, n_bytes)
        end_b = min(cursor_b + len(tb), n_bytes)
        start_c = byte_to_char[start_b]
        end_c = byte_to_char[end_b]
        offsets.append((start_c, end_c, start_b))
        cursor_b += len(tb)

    pieces: list[tuple[str, int, int]] = []
    i = 0
    n_tokens = len(token_ids)
    while i < n_tokens:
        raw_start_c, _, start_b = offsets[i]
        # 窗口起始位于多字节字符中间(续字节位置)时,
        # start_char 向后推进 1 个字符,跳过不完整字符,
        # 避免 chunk 的 re-encode token 数超出 max_tokens。
        if 0 < start_b < n_bytes and byte_to_char[start_b] == byte_to_char[start_b - 1]:
            start_char = raw_start_c + 1
        else:
            start_char = raw_start_c
        # end_char 取窗口最后一个 token 的结束偏移;若越界则用 section 末尾。
        last_idx = min(i + max_tokens - 1, n_tokens - 1)
        end_char = offsets[last_idx][1]
        text = section[start_char:end_char]
        pieces.append((text, start_char, end_char))
        if last_idx == n_tokens - 1:
            break
        i += step
    return pieces


def chunk_document(
    doc: RawDocument,
    max_tokens: int = 600,
    overlap: int = 50,
) -> list[Chunk]:
    """把 RawDocument 切成多个 Chunk。

    流程:
        1. 空内容 / None 内容 → 返回 [](见 Returns 段)。
        2. 按 Markdown 标题切分;若无标题,整体视作单 section。
           切分阶段同时记录每个 section 在原文中的字符偏移,避免后续
           ``content.find()`` 对 stripped section 不可靠(I2)。
        3. 合并相邻小 section 到 max_tokens 以内。
        4. 对仍超过 max_tokens 的 section 走 :func:`_hard_split_section`
           滑窗硬切——使用 byte 偏移跟踪精确处理中文 / emoji(C1),
           相邻窗口间共享 overlap 个 token 的上下文。
        5. 过滤空 chunk(由续字节跳过 / 极小 max_tokens 产生)(I1),
           计算每个 chunk 在原文中的绝对 ``(start_char, end_char)``。

    Args:
        doc: 待切分的原始文档。
        max_tokens: 单 chunk 的 token 上限(默认 600,匹配 BGE-m3 推荐窗口)。
        overlap: 硬切时相邻 chunk 重叠的 token 数(默认 50,约占 max_tokens 8%)。

    Returns:
        Chunk 列表,顺序按原文出现次序;chunk_index 从 0 起递增,
        total_chunks 等于最终列表长度。**空 content / None content 返回空列表**
        (而不是一个空 chunk),便于上层 pipeline 直接 skip。
    """
    # 防御性:虽然 RawDocument.content 类型为 str,仍处理 None。
    content = doc.content
    if not content:
        return []

    # Step 1: 结构切分(带 section 在原文中的偏移)
    sections = _split_by_structure(content)
    if len(sections) <= 1:
        sections = [(content, 0)]

    # Step 2: 合并小 section(偏移随合并组首个 section 透传)
    merged = _merge_small_sections(sections, max_tokens)
    if not merged:
        merged = [(content, 0)]

    # Step 3: 对每个 merged section 做硬切(如需),并累加 section 偏移得到绝对偏移
    pieces: list[tuple[str, int, int]] = []
    for section_text, section_offset in merged:
        hard_pieces = _hard_split_section(section_text, max_tokens, overlap)
        for text, rel_s, rel_e in hard_pieces:
            # I1: 过滤空 chunk(由续字节跳过 / 极端边界产生)
            if not text:
                continue
            pieces.append((text, section_offset + rel_s, section_offset + rel_e))

    # Step 4: 构造不可变 Chunk
    total = len(pieces)
    chunks: list[Chunk] = [
        Chunk(
            text=text,
            document=doc,
            chunk_index=i,
            total_chunks=total,
            start_char=start,
            end_char=end,
            chunk_type="paragraph",
            doc_section="",
            channel_visibility=getattr(doc, "channel_visibility", ("widget", "api")),
        )
        for i, (text, start, end) in enumerate(pieces)
    ]
    return chunks


def chunk_document_semantic(
    doc: RawDocument,
    max_tokens: int = 600,
    overlap: int = 50,
) -> list[Chunk]:
    """语义分块:用 Markdown 语义边界替换固定窗口分块。

    流程:
        1. _identify_blocks 识别语义块(标题/代码块/列表/表格/段落),
           代码块受到保护,不会被标题边界切断。
        2. 维护标题层级栈,遇到新标题时弹出更深级别的标题。
        3. 合并相邻小块到 max_tokens 以内(复用 _merge_small_sections)。
        4. 对超过 max_tokens 的块走 _hard_split_section 滑窗硬切。
        5. 对每个切出的 chunk 用 _classify_chunk_type 标注类型,
           用 _build_doc_section 构建标题路径。
        6. channel_visibility 从 doc 继承。

    Args:
        doc: 待切分的原始文档。
        max_tokens: 单 chunk 的 token 上限(默认 600)。
        overlap: 硬切时相邻 chunk 重叠的 token 数(默认 50)。

    Returns:
        Chunk 列表,每个 chunk 填充 chunk_type / doc_section / channel_visibility。
    """
    content = doc.content
    if not content:
        return []

    blocks = _identify_blocks(content)
    if not blocks:
        return []

    # 构建 heading 栈追踪:遍历 blocks,遇到 heading 更新栈
    # 每个 block 的 doc_section = 该 block 之前的标题栈
    section_paths: list[list[tuple[int, str]]] = []
    heading_stack: list[tuple[int, str]] = []
    for block in blocks:
        if block.block_type == "heading":
            level = block.heading_level
            title_text = content[block.start_char:block.end_char].strip()
            # 去掉 # 前缀
            title_clean = re.sub(r"^#{1,6}\s+", "", title_text).strip()
            # 弹出栈中 >= 当前 level 的标题
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title_clean))
        section_paths.append(list(heading_stack))

    # 按语义块边界构造 (text, offset) 列表,供 _merge_small_sections 合并
    raw_sections: list[tuple[str, int]] = []
    block_paths: list[list[tuple[int, str]]] = []
    for block, path in zip(blocks, section_paths):
        text = content[block.start_char:block.end_char]
        raw_sections.append((text, block.start_char))
        block_paths.append(path)

    merged = _merge_small_sections(raw_sections, max_tokens)
    if not merged:
        merged = [(content, 0)]

    # 对 merged section 追踪其 doc_section:合并段可能跨越多个 heading,
    # 取合并组内最深 heading 栈(覆盖最完整的层级路径),避免只继承首个 block 的路径。
    # raw_sections 与 block_paths 已是平行数组,merged 是连续分组的 raw_sections,
    # 每组以首个 block 的 offset 标识;用 raw_i 游标在 merged 组间顺序推进。
    pieces: list[tuple[str, int, int, str, str]] = []  # text, start, end, chunk_type, doc_section
    raw_i = 0
    for m_idx, (section_text, section_offset) in enumerate(merged):
        next_off = merged[m_idx + 1][1] if m_idx + 1 < len(merged) else None
        deepest: list[tuple[int, str]] = []
        while raw_i < len(raw_sections) and (next_off is None or raw_sections[raw_i][1] < next_off):
            if len(block_paths[raw_i]) >= len(deepest):
                deepest = block_paths[raw_i]
            raw_i += 1
        doc_section = _build_doc_section(deepest)
        hard_pieces = _hard_split_section(section_text, max_tokens, overlap)
        for text, rel_s, rel_e in hard_pieces:
            if not text:
                continue
            abs_start = section_offset + rel_s
            abs_end = section_offset + rel_e
            chunk_type = _classify_chunk_type(text)
            pieces.append((text, abs_start, abs_end, chunk_type, doc_section))

    total = len(pieces)
    channel_vis = getattr(doc, "channel_visibility", ("widget", "api"))
    chunks: list[Chunk] = [
        Chunk(
            text=text,
            document=doc,
            chunk_index=i,
            total_chunks=total,
            start_char=start,
            end_char=end,
            chunk_type=ctype,
            doc_section=dsec,
            channel_visibility=channel_vis,
        )
        for i, (text, start, end, ctype, dsec) in enumerate(pieces)
    ]
    return chunks
