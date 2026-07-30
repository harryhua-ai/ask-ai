"""文档分段管道(chunking pipeline)单元测试。

覆盖:
- brief 两个基础 case(短文档单 chunk、长文档多 chunk)
- 空 content / None content 返回空列表
- 单个超长 section(> max_tokens)的硬切 + overlap 滑窗
- chunk_index / total_chunks 一致性
- start_char / end_char 与原文对齐
- overlap 钳制(overlap >= max_tokens 时 warning)
- token 编码器缓存命中
"""

import logging

import pytest
import tiktoken

from backend.connectors.base import RawDocument
from backend.pipeline.chunk import (
    Chunk,
    _estimate_tokens,
    _get_encoding,
    chunk_document,
)


def _make_doc(content: str, **overrides: object) -> RawDocument:
    """构造默认 RawDocument,允许测试覆盖字段。"""
    defaults: dict[str, object] = {
        "source_id": "test/1",
        "source_type": "filesystem",
        "product": "test",
        "title": "T",
        "content": content,
        "url": "https://example.com",
        "metadata": {},
        "content_hash": "abc",
    }
    defaults.update(overrides)  # type: ignore[arg-type]
    return RawDocument(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# brief 两个基础测试
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_chunk_short_document():
    """短文档应返回单个 chunk,且字段对齐。"""
    doc = _make_doc("This is a short doc.", title="Short")
    chunks = chunk_document(doc, max_tokens=500, overlap=50)
    assert len(chunks) == 1
    assert isinstance(chunks[0], Chunk)
    assert chunks[0].text == "This is a short doc."
    assert chunks[0].document == doc
    assert chunks[0].chunk_index == 0
    assert chunks[0].total_chunks == 1


@pytest.mark.unit
def test_chunk_long_document_splits():
    """长文档应切成多个 chunk,每个 chunk_index 合法、text 非空。"""
    content = "\n\n".join(
        [f"## Section {i}\n\nParagraph content for section {i}." for i in range(50)]
    )
    doc = _make_doc(
        content,
        source_id="test/2",
        source_type="github",
        product="ne503",
        title="Big Doc",
        url="https://github.com/test",
        metadata={"path": "docs/big.md"},
        content_hash="def",
    )
    chunks = chunk_document(doc, max_tokens=200, overlap=20)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.chunk_index >= 0
        assert len(chunk.text) > 0


# --------------------------------------------------------------------------- #
# 额外覆盖:空内容 / None 内容
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_chunk_empty_content_returns_empty_list():
    """空字符串 content 应返回空列表,而不是一个空 chunk。"""
    doc = _make_doc("")
    chunks = chunk_document(doc)
    assert chunks == []


@pytest.mark.unit
def test_chunk_none_content_returns_empty_list():
    """None content 的防御性兜底,返回空列表。

    RawDocument.content 的类型契约上为 str,不应为 None——此测试仅防止
    上游 connector 违约时 chunking 管道静默 crash(防御性编程)。
    """
    doc = _make_doc("placeholder")
    # 用 dataclasses.replace 不可行(frozen),直接绕过类型系统:
    object.__setattr__(doc, "content", None)  # type: ignore[arg-type]
    chunks = chunk_document(doc)
    assert chunks == []


# --------------------------------------------------------------------------- #
# 额外覆盖:超长 section 硬切 + overlap 滑窗
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_chunk_single_oversized_section_gets_hard_split():
    """单个 section 超过 max_tokens 时,应被硬切成多个 chunk。"""
    # 一个无标题的超长段落(无法靠结构性切分),强制触发 _hard_split_section。
    long_text = "alpha " * 2000  # 约 12000 字符 >> max_tokens=128
    doc = _make_doc(long_text)
    chunks = chunk_document(doc, max_tokens=128, overlap=16)
    assert len(chunks) > 1
    # 每个 chunk 都不应该超过 max_tokens(允许 ±2 token 的解码边界误差)
    for chunk in chunks:
        assert _estimate_tokens(chunk.text) <= 128 + 2
        assert len(chunk.text) > 0


@pytest.mark.unit
def test_hard_split_overlap_present():
    """overlap > 0 时,相邻硬切 chunk 的尾部 / 头部应有字符重叠。"""
    # 构造重复 token 序列,便于断言重叠区域内容一致。
    body = "chunkxyz " * 500  # 重复的可识别 token
    doc = _make_doc(body)
    chunks = chunk_document(doc, max_tokens=64, overlap=16)
    assert len(chunks) >= 2
    # 验证:chunk[i] 的末尾与 chunk[i+1] 的开头存在字符级重叠(至少 1 字符)
    found_overlap = False
    for i in range(len(chunks) - 1):
        tail = chunks[i].text[-20:]
        head = chunks[i + 1].text[:20]
        # 检查 tail 是否有任何子串出现在 head(用最长公共子串的简化版)
        for window in range(min(len(tail), len(head)), 0, -1):
            if window > 0 and tail[-window:] == head[:window]:
                found_overlap = True
                break
        if found_overlap:
            break
    assert found_overlap, "相邻 chunk 之间应该存在 overlap 重叠区域"


@pytest.mark.unit
def test_overlap_clamping_warns_when_overlap_too_large(caplog):
    """overlap >= max_tokens 时应被钳制到 max_tokens//2 并发出 warning。"""
    body = "word " * 1000
    doc = _make_doc(body)
    with caplog.at_level(logging.WARNING, logger="backend.pipeline.chunk"):
        chunks = chunk_document(doc, max_tokens=32, overlap=64)
    # 仍然要切出 chunk(钳制后能正常运转)
    assert len(chunks) > 1
    # 至少有一条 WARNING 日志提到"钳制"
    assert any("钳制" in rec.message for rec in caplog.records)


# --------------------------------------------------------------------------- #
# 额外覆盖:chunk_index / total_chunks 一致性
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_chunk_index_total_consistency():
    """chunk_index 应为 0..n-1,total_chunks 应等于 len(chunks)。"""
    content = "\n\n".join([f"## H{i}\n\nbody {i} " * 10 for i in range(20)])
    doc = _make_doc(content)
    chunks = chunk_document(doc, max_tokens=150, overlap=20)
    assert len(chunks) >= 2
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_index == i
        assert chunk.total_chunks == len(chunks)


# --------------------------------------------------------------------------- #
# 额外覆盖:start_char / end_char 对齐内容
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_start_end_char_align_with_content():
    """每个 chunk 的 start_char:end_char 切片应等于 chunk.text。"""
    content = "\n\n".join([f"## Section {i}\n\nBody text {i}." for i in range(10)])
    doc = _make_doc(content)
    chunks = chunk_document(doc, max_tokens=200, overlap=20)
    assert len(chunks) >= 1
    for chunk in chunks:
        sliced = doc.content[chunk.start_char : chunk.end_char]
        assert sliced == chunk.text, (
            f"chunk_index={chunk.chunk_index} 偏移未对齐: "
            f"start={chunk.start_char} end={chunk.end_char}"
        )


@pytest.mark.unit
def test_start_end_char_monotonic_non_overlapping_when_no_overlap_hard_split():
    """无硬切(全部走 merge 路径)时,start_char 应单调递增且不重叠。"""
    # 每个 section 都小,会被合并;max_tokens 足够大避免硬切。
    content = "\n\n".join([f"## S{i}\n\nshort." for i in range(5)])
    doc = _make_doc(content)
    chunks = chunk_document(doc, max_tokens=1000, overlap=0)
    for i in range(len(chunks) - 1):
        assert chunks[i].end_char <= chunks[i + 1].start_char


# --------------------------------------------------------------------------- #
# 额外覆盖:编码器缓存
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_get_encoding_caches_singleton():
    """_get_encoding 多次调用应返回同一个 Encoding 实例(lru_cache 命中)。"""
    enc1 = _get_encoding()
    enc2 = _get_encoding()
    enc3 = _get_encoding("cl100k_base")
    assert enc1 is enc2
    assert enc1 is enc3


@pytest.mark.unit
def test_estimate_tokens_matches_tiktoken():
    """_estimate_tokens 应与直接调用 tiktoken 结果一致。"""
    text = "Hello, world! 你好,世界!"
    expected = len(tiktoken.get_encoding("cl100k_base").encode(text))
    assert _estimate_tokens(text) == expected


# --------------------------------------------------------------------------- #
# 额外覆盖:默认参数
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_chunk_default_arguments_work():
    """默认 max_tokens=600 / overlap=50 在中等长度文档上应正常工作。"""
    content = "\n\n".join([f"## H{i}\n\ncontent {i}" for i in range(5)])
    doc = _make_doc(content)
    chunks = chunk_document(doc)
    assert len(chunks) >= 1
    for chunk in chunks:
        assert isinstance(chunk, Chunk)
        assert chunk.text


# --------------------------------------------------------------------------- #
# 多字节内容(中文 / emoji)硬切——C1 回归覆盖
#
# 旧实现的 _hard_split_section 用 decode([tid]) 累加字符长度,对跨 UTF-8 字节
# 的 BPE token 返回 U+FFFD(len=1)而非真实字节宽度,导致字符偏移正向漂移,
# chunk 实际 token 数超出 max_tokens 10-20%。以下 3 个测试以零容差断言验证
# byte 偏移跟踪修复(decode_single_token_bytes + byte_to_char 映射)。
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_hard_split_respects_max_tokens_for_chinese():
    """纯中文长段落硬切后,**所有** chunk 的 token 数 <= max_tokens(零容差)。

    回归 C1:旧实现因 decode([tid]) 多字节漂移,chunk 实际 token 数可达
    max_tokens * 1.1~1.2。byte 偏移跟踪修复后应严格 <= max_tokens。
    """
    content = "你好世界测试文档段落 " * 200
    doc = _make_doc(content)
    chunks = chunk_document(doc, max_tokens=64, overlap=8)
    assert len(chunks) > 1
    for chunk in chunks:
        actual = _estimate_tokens(chunk.text)
        assert actual <= 64, f"chunk {chunk.chunk_index} token 数 {actual} > max_tokens=64"


@pytest.mark.unit
def test_hard_split_respects_max_tokens_for_emoji():
    """emoji + 中文混合内容硬切后,**所有** chunk 的 token 数 <= max_tokens(零容差)。

    emoji(4 字节 UTF-8)和中文(3 字节 UTF-8)都可能被 BPE 拆成多个
    续字节 token,验证 byte 偏移跟踪对 3/4 字节序列同样精确。
    """
    content = "文档段落 A🎉文档段落 B " * 100
    doc = _make_doc(content)
    chunks = chunk_document(doc, max_tokens=64, overlap=8)
    assert len(chunks) > 1
    for chunk in chunks:
        actual = _estimate_tokens(chunk.text)
        assert actual <= 64, f"chunk {chunk.chunk_index} token 数 {actual} > max_tokens=64"


@pytest.mark.unit
def test_hard_split_no_empty_chunks_for_multibyte():
    """多字节内容硬切不应产生空 chunk(I1 空 chunk 过滤回归)。

    旧实现对续字节 token 调用 decode([tid]) 返回 U+FFFD,偏移漂移后
    section[start:end] 可能返回空串,直接构造空 Chunk。修复后应全部非空。
    """
    content = "你好世界测试文档段落 " * 200
    doc = _make_doc(content)
    chunks = chunk_document(doc, max_tokens=64, overlap=8)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.text, f"chunk {chunk.chunk_index} 为空"
        assert len(chunk.text) > 0


# --------------------------------------------------------------------------- #
# Phase 2A:Chunk 新增元数据字段默认值
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_chunk_has_new_metadata_fields_with_defaults():
    """Chunk dataclass 应包含 chunk_type / doc_section / channel_visibility 字段且默认值合法。"""
    doc = _make_doc("hello")
    chunks = chunk_document(doc)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.chunk_type == "paragraph"
    assert c.doc_section == ""
    assert c.channel_visibility == ("widget", "api")


# --------------------------------------------------------------------------- #
# Phase 2A Task 2:SemanticBlock / _identify_blocks / _classify_chunk_type /
# _build_doc_section 语义块识别工具
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_identify_blocks_headings():
    """_identify_blocks 应识别 H1-H6 标题块并标注 heading_level。"""
    from backend.pipeline.chunk import _identify_blocks
    content = "# Title\n\n## Subtitle\n\nSome text."
    blocks = _identify_blocks(content)
    heading_blocks = [b for b in blocks if b.block_type == "heading"]
    assert len(heading_blocks) >= 2
    assert heading_blocks[0].heading_level == 1
    assert heading_blocks[1].heading_level == 2


@pytest.mark.unit
def test_identify_blocks_code_fence_protected():
    """代码块内的 # 行不应被识别为标题。"""
    from backend.pipeline.chunk import _identify_blocks
    content = "```python\n# This is a comment, not a heading\nprint('hello')\n```\n\n## Real Heading"
    blocks = _identify_blocks(content)
    heading_blocks = [b for b in blocks if b.block_type == "heading"]
    code_blocks = [b for b in blocks if b.block_type == "code"]
    assert len(code_blocks) >= 1
    assert len(heading_blocks) == 1
    assert heading_blocks[0].heading_level == 2


@pytest.mark.unit
def test_classify_chunk_type_detects_code():
    """_classify_chunk_type 应识别以代码块为主的 chunk 为 'code'。"""
    from backend.pipeline.chunk import _classify_chunk_type
    text = "```python\nprint('hello')\nimport os\n```"
    assert _classify_chunk_type(text) == "code"


@pytest.mark.unit
def test_classify_chunk_type_detects_list():
    """_classify_chunk_type 应识别列表为主的 chunk 为 'list'。"""
    from backend.pipeline.chunk import _classify_chunk_type
    text = "- item one\n- item two\n- item three\n"
    assert _classify_chunk_type(text) == "list"


@pytest.mark.unit
def test_classify_chunk_type_detects_table():
    """_classify_chunk_type 应识别表格为主的 chunk 为 'table'。"""
    from backend.pipeline.chunk import _classify_chunk_type
    text = "| Col A | Col B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
    assert _classify_chunk_type(text) == "table"


@pytest.mark.unit
def test_classify_chunk_type_defaults_paragraph():
    """普通文本应分类为 'paragraph'。"""
    from backend.pipeline.chunk import _classify_chunk_type
    assert _classify_chunk_type("This is a normal paragraph of text.") == "paragraph"


@pytest.mark.unit
def test_build_doc_section_from_heading_stack():
    """_build_doc_section 应从标题层级栈拼接路径。"""
    from backend.pipeline.chunk import _build_doc_section
    stack = [(1, "Introduction"), (2, "Hardware"), (3, "Specs")]
    assert _build_doc_section(stack) == "Introduction > Hardware > Specs"


@pytest.mark.unit
def test_build_doc_section_empty_stack():
    """空标题栈应返回空字符串。"""
    from backend.pipeline.chunk import _build_doc_section
    assert _build_doc_section([]) == ""


@pytest.mark.unit
def test_build_doc_section_multi_level():
    """多层标题栈应拼接出完整路径(弹出逻辑由调用方负责)。"""
    from backend.pipeline.chunk import _build_doc_section
    stack = [(1, "A"), (2, "B"), (3, "C")]
    assert _build_doc_section(stack) == "A > B > C"
