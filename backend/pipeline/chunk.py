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
    """

    text: str
    document: RawDocument
    chunk_index: int
    total_chunks: int
    start_char: int
    end_char: int


def _split_by_structure(content: str) -> list[str]:
    """按 Markdown 标题(## / ###)切分文本,保留标题行。

    使用零宽 lookahead,确保分隔符(`\\n## `)不出现在结果中,从而让标题
    保留在每个 section 开头。

    Args:
        content: 待切分的原始文本。

    Returns:
        非空 section 列表(已 strip)。空白片段被丢弃。
    """
    parts = re.split(r"\n(?=#{1,3}\s)", content)
    return [p.strip() for p in parts if p.strip()]


def _merge_small_sections(sections: list[str], max_tokens: int) -> list[str]:
    """把相邻小 section 合并到 max_tokens 以内的单元。

    策略:维护一个 buffer,尝试把当前 section append 到 buffer;若超限则
    flush buffer,开启新 buffer。**注意**:单个 section 本身超过 max_tokens
    时会被原样 append,交由 _hard_split_section 二次切分。

    Args:
        sections: 已按结构切分的 section 列表。
        max_tokens: 单个合并单元的 token 上限。

    Returns:
        合并后的 section 列表(每项可能含多个原始 section)。
    """
    merged: list[str] = []
    buffer = ""
    for section in sections:
        candidate = f"{buffer}\n\n{section}" if buffer else section
        if _estimate_tokens(candidate) <= max_tokens:
            buffer = candidate
        else:
            if buffer:
                merged.append(buffer)
            buffer = section
    if buffer:
        merged.append(buffer)
    return merged


def _hard_split_section(
    section: str,
    max_tokens: int,
    overlap: int,
) -> list[tuple[str, int, int]]:
    """对超长 section 做 token 级滑窗硬切。

    将 section 按 cl100k_base 切成 token id 序列,以 (max_tokens - overlap)
    为步长滑窗,每个窗口解码回文本并记录在 section 内的 (start, end) 字符
    偏移。

    边界:
    - 若 section 实际 token 数 <= max_tokens,原样返回 [(section, 0, len)]。
    - 若 overlap >= max_tokens,将其钳制为 max_tokens // 2 并 warning,避免死循环。

    Args:
        section: 待硬切的 section 文本。
        max_tokens: 单个 chunk 的 token 上限。
        overlap: 相邻 chunk 间重叠的 token 数。

    Returns:
        列表,每项为 (chunk_text, start_char_in_section, end_char_in_section)。
    """
    if not section:
        return []
    if _estimate_tokens(section) <= max_tokens:
        return [(section, 0, len(section))]

    # 钳制 overlap,防止 step <= 0 死循环
    safe_overlap = min(overlap, max_tokens // 2)
    if safe_overlap != overlap:
        logger.warning(
            "overlap=%d 被 钳制为 %d(max_tokens=%d)",
            overlap,
            safe_overlap,
            max_tokens,
        )
    step = max(1, max_tokens - safe_overlap)

    enc = _get_encoding()
    token_ids = enc.encode(section)

    # 用解码每个 token 切片的方式建立 token_idx -> (start_char, end_char) 映射。
    # tiktoken 提供 decode_offline 但不保证 byte-aligned;逐 token 解码以拿到
    # 精确字符偏移,代价是 O(N) 解码调用(N = token 数)。
    offsets: list[tuple[int, int]] = []
    cursor = 0
    for tid in token_ids:
        piece = enc.decode([tid])
        end = cursor + len(piece)
        offsets.append((cursor, end))
        cursor = end

    pieces: list[tuple[str, int, int]] = []
    i = 0
    n = len(token_ids)
    while i < n:
        start_char = offsets[i][0]
        # end_char 取窗口最后一个 token 的结束偏移;若越界则用 section 末尾。
        last_idx = min(i + max_tokens - 1, n - 1)
        end_char = offsets[last_idx][1]
        text = section[start_char:end_char]
        pieces.append((text, start_char, end_char))
        if last_idx == n - 1:
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
        3. 合并相邻小 section 到 max_tokens 以内。
        4. 对仍超过 max_tokens 的 section 走 _hard_split_section 滑窗硬切,
           每个窗口解码为独立 chunk,相邻窗口间共享 overlap 个 token 的上下文。
        5. 计算每个 chunk 在原文中的绝对 (start_char, end_char)。

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

    # Step 1: 结构切分
    sections = _split_by_structure(content)
    if len(sections) <= 1:
        sections = [content]

    # Step 2: 合并小 section
    merged = _merge_small_sections(sections, max_tokens)
    if not merged:
        merged = [content]

    # Step 3: 对每个 merged section 做硬切(如需),并记录 (text, abs_start, abs_end)
    pieces: list[tuple[str, int, int]] = []
    search_cursor = 0  # str.find 的起点,在原文中向后推进以定位 section 起点
    for section in merged:
        # 在原文中定位 section 起点(允许跳过中间已消耗的字符)。
        rel_start = content.find(section, search_cursor)
        if rel_start < 0:
            # 极端情况:section 经 strip 后与原文片段不再完全匹配(理论上不会
            # 发生,因为 _merge_small_sections 只用 \n\n 拼接)。退化用 0 偏移。
            logger.warning(
                "无法在原文中定位 section(start_char 失效),文档 source_id=%s",
                doc.source_id,
            )
            rel_start = search_cursor
        abs_end_base = rel_start + len(section)

        hard_pieces = _hard_split_section(section, max_tokens, overlap)
        for text, rel_s, rel_e in hard_pieces:
            pieces.append((text, rel_start + rel_s, rel_start + rel_e))

        search_cursor = abs_end_base

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
        )
        for i, (text, start, end) in enumerate(pieces)
    ]
    return chunks
