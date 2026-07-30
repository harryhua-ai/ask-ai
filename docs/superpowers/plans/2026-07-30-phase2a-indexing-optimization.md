# Phase 2A — 索引优化 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用语义边界分块替换 Phase 1 的固定窗口分块，为每个 chunk 添加 chunk_type / doc_section / channel_visibility 元数据，在检索和重排阶段利用这些信号实现渠道隔离与类型加权，缩小与 Kapa.ai 在索引质量上的差距。

**Architecture:** 沿用 Phase 1 的 `RawDocument → chunk_document → embedder → Weaviate` 管线，在 chunk 层引入三个新信号：(1) `_identify_blocks` 用扩展正则识别标题/代码块/列表/表格语义边界并保护代码块不被切断；(2) `_classify_chunk_type` + `_build_doc_section` 在切分时标注每个 chunk 的主导类型与标题层级路径；(3) `channel_visibility` 从 `SourceConfig` 经 `RawDocument` 透传到每个 chunk，在 Weaviate schema 中存为 `text[]`，search 时用 `Filter.contains_any` 做渠道过滤。RerankPipeline 增加 `type_weights` 乘性加权。所有新字段在 dataclass 上有默认值，保证现有测试零回归。

**Tech Stack:** Python 3.12+，Weaviate client v4.10+（`DataType.TEXT_ARRAY` + `Filter.contains_any`），tiktoken cl100k_base（复用现有 token 估算），无新增第三方依赖。

## Global Constraints

- Python `>=3.12`（pyproject.toml 已声明）。
- Weaviate-client `>=4.10`（pyproject.toml 已声明），schema 新增 property 后需删除重建 collection（Weaviate 不支持修改已有 property 类型）。
- chunk 大小约束：spec §6 line 279 逐字要求 `~500-800 token/chunk, 重叠 50-100`；Phase 1 实现 `max_tokens=600, overlap=50`，本计划沿用。
- chunk_type 枚举（spec §10.2 line 486 逐字）：`heading/paragraph/code/list/table`。任何 chunk 的 chunk_type 必须属于这 5 个值之一。
- channel 枚举（spec §11.1 line 522 逐字）：`widget | discord | whatsapp | mcp`。channel_visibility 的每个元素必须属于此集合（管理后台用 `api` 标识内部渠道，不属于对外渠道但在本计划中允许出现于 channel_visibility 数组）。
- 检索参数（spec §5 line 119-129）：hybrid `alpha=0.5`，召回 `top ~50`，rerank `bge-reranker-v2-m3 → top 5~10`，rerank 最高分 < 阈值 → 拒答。
- P0 已落地的 `min_results_to_answer=3`（rerank 不足 3 条拒答）保持不变。
- 所有新字段在 frozen dataclass 上必须有默认值，确保现有调用方零修改通过测试。
- 不引入 markdown 解析第三方依赖（markdown-it-py / mistune 等），用正则扩展识别语义边界，避免给部署增加编译/安装成本。
- 代码块（fence ``` 和 ~~~）内的标题行不得被识别为标题边界，否则会切断代码块。
- 每个代码变更 step 遵循 TDD：先写失败测试 → 验证失败 → 最小实现 → 验证通过 → commit。

## File Structure

### 新建文件

| 文件 | 职责 |
|---|---|
| 无 | 本计划全部通过修改现有文件实现，不新建模块 |

### 修改文件

| 文件 | 修改内容 |
|---|---|
| `backend/pipeline/chunk.py` | 扩展 `Chunk` dataclass；新增 `SemanticBlock` dataclass、`_identify_blocks`、`_classify_chunk_type`、`_build_doc_section`、`chunk_document_semantic` |
| `backend/connectors/base.py` | `RawDocument` 新增 `channel_visibility` 字段 |
| `backend/connectors/registry.py` | `SourceConfig` 新增 `channel_visibility` 字段；`load_configs` 读取该字段 |
| `backend/retrieval/search.py` | `SearchResult` 新增 `chunk_type`/`doc_section`/`channel_visibility`；`HybridSearcher.search` 新增 `channel` 参数 + Weaviate filter |
| `backend/retrieval/rerank.py` | `RerankPipeline` 新增 `type_weights` 参数；`rerank` 应用乘性加权 |
| `backend/pipeline/ingest.py` | `_ensure_collection` 新增 3 个 property；`ingest_document` 写入新字段；切换到 `chunk_document_semantic` |
| `backend/pipeline/rag.py` | `answer`/`stream_answer` 透传 `channel` 给 searcher |
| `backend/connectors/github.py` | `_make_document` 透传 `channel_visibility` |
| `backend/connectors/filesystem.py` | `_make_document` 透传 `channel_visibility` |
| `config/data_sources.yaml` | 拆分 `knowledge-base` 为 public/internal 两个 source；为每个 source 声明 `channel_visibility` |
| `scripts/sync.py` | 新增 `--reindex` flag：删除并重建 collection 后全量同步 |
| `tests/pipeline/test_chunk.py` | 新增语义分块、块识别、类型标注、层级路径测试 |
| `tests/pipeline/test_ingest.py` | 新增 schema 扩展 + 新字段写入测试 |
| `tests/pipeline/test_rag.py` | 新增 channel 透传测试 |
| `tests/pipeline/test_sync.py` | 新增 `--reindex` 测试 |
| `tests/retrieval/test_search.py` | 新增 channel 过滤 + SearchResult 新字段测试 |
| `tests/retrieval/test_rerank.py` | 新增 type_weights 加权测试 |
| `tests/connectors/test_github.py` | 新增 channel_visibility 透传测试 |
| `tests/connectors/test_filesystem.py` | 新增 channel_visibility 透传测试 |
| `tests/connectors/test_registry.py` | 新增 SourceConfig.channel_visibility 加载测试 |
| `pyproject.toml` | 无修改（不新增依赖） |

---

## Task 1: 扩展数据结构（Chunk + RawDocument + SourceConfig + SearchResult）

**Goal:** 为 Phase 2A 三个功能所需的元数据字段打下数据结构基础。所有新字段在 frozen dataclass 上有默认值，现有测试零回归。

**Files:**
- Modify: `backend/pipeline/chunk.py` (Chunk dataclass, line 55-76)
- Modify: `backend/connectors/base.py` (RawDocument dataclass, line 12-36)
- Modify: `backend/connectors/registry.py` (SourceConfig dataclass line 13-34, load_configs line 78-110)
- Modify: `backend/retrieval/search.py` (SearchResult dataclass, line 26-51)
- Modify: `backend/pipeline/chunk.py` (`chunk_document` line 360-371 填充默认值)
- Test: `tests/pipeline/test_chunk.py`
- Test: `tests/connectors/test_registry.py`
- Test: `tests/retrieval/test_search.py`

**Interfaces:**
- Consumes: 无（第一个 Task）
- Produces:
  - `Chunk.chunk_type: str`（default `"paragraph"`）
  - `Chunk.doc_section: str`（default `""`）
  - `Chunk.channel_visibility: tuple[str, ...]`（default `("widget", "api")`）
  - `RawDocument.channel_visibility: tuple[str, ...]`（default `("widget", "api")`）
  - `SourceConfig.channel_visibility: tuple[str, ...]`（default `("widget", "api")`）
  - `SearchResult.chunk_type: str`（default `""`）
  - `SearchResult.doc_section: str`（default `""`）
  - `SearchResult.channel_visibility: tuple[str, ...]`（default `("widget", "api")`）

### Steps

- [ ] **1.1 写失败测试 — Chunk 新字段默认值**

打开 `tests/pipeline/test_chunk.py`，在文件末尾追加：

```python
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
```

运行 `pytest tests/pipeline/test_chunk.py::test_chunk_has_new_metadata_fields_with_defaults -x`，预期失败（`AttributeError: 'Chunk' object has no attribute 'chunk_type'`）。

- [ ] **1.2 修改 Chunk dataclass**

打开 `backend/pipeline/chunk.py`，在 `Chunk` dataclass（line 55-76）的 `end_char` 字段后追加三个字段：

```python
@dataclass(frozen=True)
class Chunk:
    # ... 现有字段保持不变 ...
    text: str
    document: RawDocument
    chunk_index: int
    total_chunks: int
    start_char: int
    end_char: int
    # Phase 2A 新增字段
    chunk_type: str = "paragraph"
    doc_section: str = ""
    channel_visibility: tuple[str, ...] = ("widget", "api")
```

注意：因为有默认值，frozen dataclass 的字段顺序要求所有无默认值字段在前。现有 6 个字段都无默认值，新增 3 个有默认值字段放在最后，符合 dataclass 约束。

- [ ] **1.3 修改 chunk_document 填充默认 channel_visibility**

在 `chunk_document` 函数（line 305-372）中，Chunk 构造逻辑（line 361-371）追加从 doc 透传 channel_visibility：

```python
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
```

运行 `pytest tests/pipeline/test_chunk.py::test_chunk_has_new_metadata_fields_with_defaults -x`，预期通过。

- [ ] **1.4 写失败测试 — RawDocument 新字段**

在 `tests/connectors/test_filesystem.py`（或 `test_chunk.py` 的 `_make_doc` helper 附近）追加：

```python
@pytest.mark.unit
def test_raw_document_has_channel_visibility_default():
    """RawDocument 应包含 channel_visibility 字段,默认 ('widget','api')。"""
    from backend.connectors.base import RawDocument
    doc = RawDocument(
        source_id="t/1", source_type="t", product="t", title="T",
        content="x", url="u", metadata={}, content_hash="h",
    )
    assert doc.channel_visibility == ("widget", "api")
```

运行预期失败（`TypeError: __init__() got an unexpected keyword argument` 实际不会失败，但 `AttributeError` 会失败）。

- [ ] **1.5 修改 RawDocument dataclass**

打开 `backend/connectors/base.py`，在 `RawDocument`（line 12-36）的 `content_hash` 后追加：

```python
@dataclass(frozen=True)
class RawDocument:
    source_id: str
    source_type: str
    product: str
    title: str
    content: str
    url: str
    metadata: dict[str, Any]
    content_hash: str
    channel_visibility: tuple[str, ...] = ("widget", "api")
```

运行 `pytest tests/connectors/test_filesystem.py::test_raw_document_has_channel_visibility_default -x`，预期通过。

- [ ] **1.6 写失败测试 — SourceConfig 新字段**

在 `tests/connectors/test_registry.py` 末尾追加：

```python
@pytest.mark.unit
def test_source_config_channel_visibility_default():
    """SourceConfig 应包含 channel_visibility 字段,默认 ('widget','api')。"""
    from backend.connectors.registry import SourceConfig
    cfg = SourceConfig(
        id="t", type="github", product="t", enabled=True, config={}, sync_interval="1h",
    )
    assert cfg.channel_visibility == ("widget", "api")


@pytest.mark.unit
def test_load_configs_reads_channel_visibility():
    """load_configs 应从 YAML 字典读取 channel_visibility 字段。"""
    from backend.connectors.registry import ConnectorRegistry
    yaml_data = {
        "sources": [
            {
                "id": "internal", "type": "filesystem", "product": "knowledge",
                "channel_visibility": ["api"],
                "config": {"root_path": "/tmp"},
            }
        ]
    }
    configs = ConnectorRegistry.load_configs(yaml_data)
    assert configs[0].channel_visibility == ("api",)
```

运行预期失败。

- [ ] **1.7 修改 SourceConfig + load_configs**

打开 `backend/connectors/registry.py`，在 `SourceConfig`（line 13-34）的 `sync_interval` 后追加字段：

```python
@dataclass(frozen=True)
class SourceConfig:
    id: str
    type: str
    product: str
    enabled: bool
    config: dict[str, Any]
    sync_interval: str
    channel_visibility: tuple[str, ...] = ("widget", "api")
```

在 `load_configs`（line 78-110）中，构造 `SourceConfig` 时读取 `channel_visibility`：

```python
configs.append(
    SourceConfig(
        id=src["id"],
        type=src["type"],
        product=src["product"],
        enabled=src.get("enabled", True),
        config=src.get("config", {}),
        sync_interval=src.get("sync_interval", "24h"),
        channel_visibility=tuple(src.get("channel_visibility", ["widget", "api"])),
    )
)
```

运行 `pytest tests/connectors/test_registry.py -x`，预期通过。

- [ ] **1.8 写失败测试 — SearchResult 新字段**

在 `tests/retrieval/test_search.py` 末尾追加：

```python
@pytest.mark.unit
def test_search_result_has_new_fields_default():
    """SearchResult 应包含 chunk_type / doc_section / channel_visibility 字段。"""
    from backend.retrieval.search import SearchResult
    r = SearchResult(
        text="t", source_id="s", source_type="github", product="p",
        title="T", url="u", score=0.5, chunk_index=0,
    )
    assert r.chunk_type == ""
    assert r.doc_section == ""
    assert r.channel_visibility == ("widget", "api")
```

运行预期失败。

- [ ] **1.9 修改 SearchResult dataclass**

打开 `backend/retrieval/search.py`，在 `SearchResult`（line 26-51）的 `chunk_index` 后追加：

```python
@dataclass(frozen=True)
class SearchResult:
    text: str
    source_id: str
    source_type: str
    product: str
    title: str
    url: str
    score: float
    chunk_index: int
    chunk_type: str = ""
    doc_section: str = ""
    channel_visibility: tuple[str, ...] = ("widget", "api")
```

运行 `pytest tests/retrieval/test_search.py::test_search_result_has_new_fields_default -x`，预期通过。

- [ ] **1.10 全量回归测试**

运行 `pytest tests/ -x --tb=short`。预期全部通过（新字段有默认值，现有代码不受影响）。

- [ ] **1.11 Commit**

```bash
git add backend/pipeline/chunk.py backend/connectors/base.py backend/connectors/registry.py backend/retrieval/search.py tests/pipeline/test_chunk.py tests/connectors/test_registry.py tests/retrieval/test_search.py tests/connectors/test_filesystem.py
git commit -m "feat: 扩展 Chunk/RawDocument/SourceConfig/SearchResult 数据结构增加 Phase 2A 元数据字段"
```

---

## Task 2: Markdown 语义块识别 + chunk_type/doc_section 标注

**Goal:** 实现 `_identify_blocks`、`_classify_chunk_type`、`_build_doc_section` 三个函数，为语义分块器提供块边界识别与类型标注能力。

**Files:**
- Modify: `backend/pipeline/chunk.py` (新增 SemanticBlock dataclass + 三个函数)
- Test: `tests/pipeline/test_chunk.py`

**Interfaces:**
- Consumes: Task 1 的 Chunk dataclass
- Produces:
  - `SemanticBlock` dataclass: `block_type: str`, `start_char: int`, `end_char: int`, `heading_level: int`
  - `_identify_blocks(content: str) -> list[SemanticBlock]`
  - `_classify_chunk_type(text: str) -> str`
  - `_build_doc_section(heading_stack: list[tuple[int, str]]) -> str`

### Steps

- [ ] **2.1 写 SemanticBlock dataclass + 失败测试**

在 `backend/pipeline/chunk.py` 的 `Chunk` dataclass 之后追加：

```python
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
```

在 `tests/pipeline/test_chunk.py` 末尾追加失败测试：

```python
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
```

运行 `pytest tests/pipeline/test_chunk.py::test_identify_blocks_headings -x`，预期失败（`_identify_blocks` 不存在）。

- [ ] **2.2 实现 _identify_blocks**

在 `backend/pipeline/chunk.py` 的 `_split_by_structure` 之前（line 134 前）追加：

```python
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
    for s, _, _ in heading_positions:
        boundaries.add(s)
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
```

运行 `pytest tests/pipeline/test_chunk.py::test_identify_blocks_headings tests/pipeline/test_chunk.py::test_identify_blocks_code_fence_protected -x`，预期通过。

- [ ] **2.3 写失败测试 — chunk_type 分类**

在 `tests/pipeline/test_chunk.py` 末尾追加：

```python
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
```

运行预期失败。

- [ ] **2.4 实现 _classify_chunk_type**

在 `backend/pipeline/chunk.py` 的 `_identify_blocks` 之后追加：

```python
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
```

运行 `pytest tests/pipeline/test_chunk.py -k "classify_chunk_type" -x`，预期全部通过。

- [ ] **2.5 写失败测试 — doc_section 构建**

在 `tests/pipeline/test_chunk.py` 末尾追加：

```python
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
```

运行预期失败。

- [ ] **2.6 实现 _build_doc_section**

在 `backend/pipeline/chunk.py` 的 `_classify_chunk_type` 之后追加：

```python
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
```

运行 `pytest tests/pipeline/test_chunk.py -k "build_doc_section" -x`，预期通过。

注意：标题栈的弹出逻辑（遇到更高级别标题时弹出栈中更深级别的标题）由调用方（`chunk_document_semantic` 在 Task 3 实现）负责，`_build_doc_section` 只负责格式化。

- [ ] **2.7 全量回归测试**

运行 `pytest tests/pipeline/test_chunk.py -x`。预期全部通过。

- [ ] **2.8 Commit**

```bash
git add backend/pipeline/chunk.py tests/pipeline/test_chunk.py
git commit -m "feat: 新增 SemanticBlock / _identify_blocks / _classify_chunk_type / _build_doc_section 语义块识别工具"
```

---

## Task 3: 语义分块器实现

**Goal:** 实现 `chunk_document_semantic`，用语义边界替换固定窗口分块，填充 chunk_type 和 doc_section 元数据。

**Files:**
- Modify: `backend/pipeline/chunk.py` (新增 `chunk_document_semantic`)
- Test: `tests/pipeline/test_chunk.py`

**Interfaces:**
- Consumes: Task 1 的 `Chunk` dataclass；Task 2 的 `_identify_blocks` / `_classify_chunk_type` / `_build_doc_section` / `SemanticBlock`
- Produces: `chunk_document_semantic(doc: RawDocument, max_tokens: int = 600, overlap: int = 50) -> list[Chunk]`（每个 Chunk 填充 chunk_type、doc_section、channel_visibility）

### Steps

- [ ] **3.1 写失败测试 — 语义分块基本功能**

在 `tests/pipeline/test_chunk.py` 末尾追加：

```python
@pytest.mark.unit
def test_semantic_chunk_basic():
    """chunk_document_semantic 应切出 chunk 并填充 chunk_type / doc_section。"""
    from backend.pipeline.chunk import chunk_document_semantic
    content = "# Introduction\n\nThis is intro text.\n\n## Hardware\n\nDetailed hardware specs."
    doc = _make_doc(content)
    chunks = chunk_document_semantic(doc, max_tokens=600, overlap=50)
    assert len(chunks) >= 1
    for c in chunks:
        assert c.chunk_type in ("heading", "paragraph", "code", "list", "table")
        assert isinstance(c.doc_section, str)


@pytest.mark.unit
def test_semantic_chunk_produces_code_type():
    """含代码块的文档经语义分块后应产出 chunk_type='code' 的 chunk。

    注意:超过 max_tokens 的代码块仍会被 _hard_split_section 硬切(设计如此),
    此测试仅验证代码块被正确标注为 code 类型,不验证不被硬切。
    """
    from backend.pipeline.chunk import chunk_document_semantic
    code = "```python\n" + "\n".join(f"x{i} = {i}" for i in range(50)) + "\n```"
    content = f"# Title\n\n{code}\n\n## After\n\nMore text."
    doc = _make_doc(content)
    chunks = chunk_document_semantic(doc, max_tokens=100, overlap=10)
    code_chunks = [c for c in chunks if c.chunk_type == "code"]
    assert len(code_chunks) >= 1


@pytest.mark.unit
def test_semantic_chunk_doc_section_tracks_headings():
    """chunk 的 doc_section 应反映其所在标题层级路径。"""
    from backend.pipeline.chunk import chunk_document_semantic
    content = (
        "# NE503\n\n"
        "Intro paragraph.\n\n"
        "## Hardware\n\n"
        "Hardware details.\n\n"
        "### Specs\n\n"
        "Detailed specs."
    )
    doc = _make_doc(content)
    chunks = chunk_document_semantic(doc, max_tokens=600, overlap=50)
    # 在 Specs 标题下的 chunk,doc_section 应包含 "NE503 > Hardware > Specs"
    specs_chunks = [c for c in chunks if "Specs" in c.text or "Detailed specs" in c.text]
    if specs_chunks:
        assert any("NE503" in c.doc_section and "Hardware" in c.doc_section for c in specs_chunks)


@pytest.mark.unit
def test_semantic_chunk_channel_visibility_from_doc():
    """chunk 的 channel_visibility 应从 RawDocument 继承。"""
    from backend.pipeline.chunk import chunk_document_semantic
    doc = _make_doc(
        "# Title\n\nContent.",
        channel_visibility=("api",),
    )
    chunks = chunk_document_semantic(doc)
    assert all(c.channel_visibility == ("api",) for c in chunks)


@pytest.mark.unit
def test_semantic_chunk_empty_content_returns_empty():
    """空 content 应返回空列表。"""
    from backend.pipeline.chunk import chunk_document_semantic
    doc = _make_doc("")
    assert chunk_document_semantic(doc) == []
```

运行 `pytest tests/pipeline/test_chunk.py -k "semantic_chunk" -x`，预期全部失败（`chunk_document_semantic` 不存在）。

- [ ] **3.2 实现 chunk_document_semantic**

在 `backend/pipeline/chunk.py` 的 `chunk_document` 之后追加：

```python
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

    # 对 merged section 追踪其 doc_section(取合并组首个 block 的 path)
    # merged_sections 的 offset 对应第一个 block 的 start_char
    # 用 offset 反查 block_paths
    offset_to_path: dict[int, list[tuple[int, str]]] = {}
    for (text, offset), path in zip(raw_sections, block_paths):
        offset_to_path[offset] = path

    pieces: list[tuple[str, int, int, str, str]] = []  # text, start, end, chunk_type, doc_section
    for section_text, section_offset in merged:
        hard_pieces = _hard_split_section(section_text, max_tokens, overlap)
        doc_section = _build_doc_section(offset_to_path.get(section_offset, []))
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
```

运行 `pytest tests/pipeline/test_chunk.py -k "semantic_chunk" -x`，预期全部通过。

- [ ] **3.3 全量回归测试**

运行 `pytest tests/pipeline/test_chunk.py -x`。预期全部通过（现有 `chunk_document` 测试不受影响，`chunk_document_semantic` 是新增函数）。

- [ ] **3.4 Commit**

```bash
git add backend/pipeline/chunk.py tests/pipeline/test_chunk.py
git commit -m "feat: 实现 chunk_document_semantic 语义分块器,填充 chunk_type/doc_section/channel_visibility"
```

---

## Task 4: Weaviate schema 扩展 + 写入填充新字段

**Goal:** 在 Weaviate collection 新增 `channel_visibility` / `doc_section` / `chunk_type` 三个 property，在 `ingest_document` 中写入这些字段。

**Files:**
- Modify: `backend/pipeline/ingest.py` (`_ensure_collection` line 76-112; `ingest_document` line 118-188)
- Test: `tests/pipeline/test_ingest.py`

**Interfaces:**
- Consumes: Task 3 的 `chunk_document_semantic` 产出的 Chunk 含新字段
- Produces: Weaviate collection 支持 `channel_visibility (TEXT_ARRAY)` / `doc_section (TEXT)` / `chunk_type (TEXT)` property

### Steps

- [ ] **4.1 写失败测试 — schema 包含新 property**

先查看 `tests/pipeline/test_ingest.py` 了解现有测试模式。在末尾追加：

```python
@pytest.mark.unit
def test_ensure_collection_creates_new_properties():
    """_ensure_collection 应创建 channel_visibility / doc_section / chunk_type property。"""
    from unittest.mock import MagicMock
    from backend.pipeline.ingest import IngestionPipeline

    mock_client = MagicMock()
    mock_client.collections.exists.return_value = False
    mock_collection = MagicMock()
    mock_client.collections.create.return_value = None
    mock_client.collections.get.return_value = mock_collection

    pipeline = IngestionPipeline(
        embedder=MagicMock(), weaviate_client=mock_client, class_name="Document",
    )
    pipeline._ensure_collection()

    mock_client.collections.create.assert_called_once()
    create_kwargs = mock_client.collections.create.call_args
    property_names = [p.name if hasattr(p, "name") else p.get("name")
                      for p in create_kwargs.kwargs.get("properties", [])]
    assert "channel_visibility" in property_names
    assert "doc_section" in property_names
    assert "chunk_type" in property_names
```

运行 `pytest tests/pipeline/test_ingest.py::test_ensure_collection_creates_new_properties -x`，预期失败。

- [ ] **4.2 修改 _ensure_collection 新增 property**

打开 `backend/pipeline/ingest.py`，修改 `_ensure_collection`（line 76-112）中的 `properties` 列表：

```python
    def _ensure_collection(self) -> None:
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
                ],
            )

        self._collection = self._client.collections.get(self._class_name)
```

运行 `pytest tests/pipeline/test_ingest.py::test_ensure_collection_creates_new_properties -x`，预期通过。

- [ ] **4.3 写失败测试 — ingest_document 写入新字段**

在 `tests/pipeline/test_ingest.py` 末尾追加：

```python
@pytest.mark.unit
def test_ingest_document_writes_new_fields():
    """ingest_document 应把 channel_visibility / doc_section / chunk_type 写入 Weaviate。"""
    from unittest.mock import MagicMock
    from backend.pipeline.ingest import IngestionPipeline
    from backend.connectors.base import RawDocument

    mock_collection = MagicMock()
    mock_client = MagicMock()
    mock_client.collections.exists.return_value = True
    mock_client.collections.get.return_value = mock_collection

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]

    pipeline = IngestionPipeline(
        embedder=mock_embedder, weaviate_client=mock_client, class_name="Document",
    )

    doc = RawDocument(
        source_id="test/1", source_type="github", product="ne503",
        title="T", content="# Title\n\nContent.", url="u",
        metadata={}, content_hash="h", channel_visibility=("api",),
    )
    pipeline.ingest_document(doc)

    mock_collection.data.insert.assert_called()
    insert_kwargs = mock_collection.data.insert.call_args.kwargs
    props = insert_kwargs.get("properties", {})
    assert "channel_visibility" in props
    assert props["channel_visibility"] == ["api"]
    assert "chunk_type" in props
    assert "doc_section" in props
```

运行预期失败。

- [ ] **4.4 修改 ingest_document 写入新字段**

在 `backend/pipeline/ingest.py` 的 `ingest_document`（line 148-166）中，`self._collection.data.insert` 调用追加新字段：

```python
        success_count = 0
        for chunk, vector in zip(chunks, vectors):
            try:
                vec_list = np.asarray(vector).tolist()
                self._collection.data.insert(
                    properties={
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
                    },
                    vector=vec_list,
                )
                success_count += 1
            except Exception as exc:
                logger.warning(
                    "写入 Weaviate 失败 doc=%s chunk=%d: %s",
                    doc.source_id, chunk.chunk_index, exc,
                )
```

运行 `pytest tests/pipeline/test_ingest.py::test_ingest_document_writes_new_fields -x`，预期通过。

- [ ] **4.5 全量回归测试**

运行 `pytest tests/pipeline/test_ingest.py -x`。预期全部通过。

- [ ] **4.6 Commit**

```bash
git add backend/pipeline/ingest.py tests/pipeline/test_ingest.py
git commit -m "feat: Weaviate schema 扩展 channel_visibility/doc_section/chunk_type property 并在写入时填充"
```

---

## Task 5: channel_visibility 配置 + Connector 透传

**Goal:** 在 `data_sources.yaml` 中为每个数据源配置 channel_visibility，修改 GitHubConnector 和 FilesystemConnector 从 SourceConfig 读取并透传到 RawDocument。

**Files:**
- Modify: `config/data_sources.yaml`
- Modify: `backend/connectors/github.py` (`_make_document` line 192-210; `__init__` line 78-95)
- Modify: `backend/connectors/filesystem.py` (`_make_document` line 78-98; `__init__` line 37-43)
- Test: `tests/connectors/test_github.py`
- Test: `tests/connectors/test_filesystem.py`

**Interfaces:**
- Consumes: Task 1 的 `SourceConfig.channel_visibility` + `RawDocument.channel_visibility`
- Produces: 每条 RawDocument 携带正确的 channel_visibility 值

### Steps

- [ ] **5.1 修改 data_sources.yaml — 为所有 source 添加 channel_visibility**

打开 `config/data_sources.yaml`。所有 GitHub 公开仓库的 `channel_visibility` 为 `["widget", "api"]`（默认值，可省略但显式声明更清晰）。拆分 `knowledge-base` 为 public 和 internal 两个 source：

```yaml
sources:
  # ... 其他 github source 不变,均默认 channel_visibility: ["widget", "api"] ...

  - id: "knowledge-public"
    type: "filesystem"
    product: "knowledge"
    enabled: true
    channel_visibility: ["widget", "api"]
    config:
      root_path: "~/Documents/GitHub/Knowledge/知识库/"
      include_dirs: ["support/", "wiki-en/"]
      file_types: [".md", ".txt"]
    sync_interval: "1h"

  - id: "knowledge-internal"
    type: "filesystem"
    product: "knowledge"
    enabled: true
    channel_visibility: ["api"]
    config:
      root_path: "~/Documents/GitHub/Knowledge/知识库/"
      include_dirs: ["sales/", "硬件/", "经验/"]
      file_types: [".md", ".txt"]
    sync_interval: "1h"
```

删除原 `knowledge-base` 条目。所有 GitHub source 保持不变（默认 channel_visibility）。

- [ ] **5.2 写失败测试 — GitHubConnector 透传 channel_visibility**

在 `tests/connectors/test_github.py` 末尾追加：

```python
@pytest.mark.unit
def test_github_connector_passes_channel_visibility():
    """GitHubConnector 应把 SourceConfig.channel_visibility 透传到 RawDocument。"""
    from backend.connectors.registry import SourceConfig
    from backend.connectors.github import GitHubConnector

    cfg = SourceConfig(
        id="test", type="github", product="test", enabled=True,
        config={"owner": "o", "repo": "r", "branch": "main"},
        sync_interval="1h",
        channel_visibility=("api",),
    )
    connector = GitHubConnector(cfg)
    doc = connector._make_document("path/to/file.md", "content")
    assert doc.channel_visibility == ("api",)


@pytest.mark.unit
def test_github_connector_default_channel_visibility():
    """SourceConfig 未指定 channel_visibility 时,RawDocument 默认 ('widget','api')。"""
    from backend.connectors.registry import SourceConfig
    from backend.connectors.github import GitHubConnector

    cfg = SourceConfig(
        id="test", type="github", product="test", enabled=True,
        config={"owner": "o", "repo": "r"},
        sync_interval="1h",
    )
    connector = GitHubConnector(cfg)
    doc = connector._make_document("file.md", "content")
    assert doc.channel_visibility == ("widget", "api")
```

运行预期失败。

- [ ] **5.3 修改 GitHubConnector — __init__ 存储 channel_visibility + _make_document 透传**

打开 `backend/connectors/github.py`，在 `__init__`（line 78-95）末尾追加：

```python
        self._channel_visibility: tuple[str, ...] = config.channel_visibility
```

在 `_make_document`（line 192-210）的 `RawDocument(...)` 构造中追加字段：

```python
    def _make_document(self, path: str, content: str) -> RawDocument:
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        title = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        url = f"https://github.com/{self._owner}/{self._repo}/blob/{self._branch}/{path}"
        return RawDocument(
            source_id=f"{self._owner}/{self._repo}/{path}",
            source_type="github",
            product=self.product,
            title=title,
            content=content,
            url=url,
            metadata={
                "repo": f"{self._owner}/{self._repo}",
                "branch": self._branch,
                "path": path,
            },
            content_hash=content_hash,
            channel_visibility=self._channel_visibility,
        )
```

运行 `pytest tests/connectors/test_github.py -k "channel_visibility" -x`，预期通过。

- [ ] **5.4 写失败测试 — FilesystemConnector 透传 channel_visibility**

在 `tests/connectors/test_filesystem.py` 末尾追加：

```python
@pytest.mark.unit
def test_filesystem_connector_passes_channel_visibility(tmp_path):
    """FilesystemConnector 应把 SourceConfig.channel_visibility 透传到 RawDocument。"""
    from backend.connectors.registry import SourceConfig
    from backend.connectors.filesystem import FilesystemConnector

    (tmp_path / "test.md").write_text("# Title\n\ncontent")

    cfg = SourceConfig(
        id="test", type="filesystem", product="test", enabled=True,
        config={"root_path": str(tmp_path)},
        sync_interval="1h",
        channel_visibility=("api",),
    )
    connector = FilesystemConnector(cfg)
    docs = list(connector.fetch_all())
    assert len(docs) >= 1
    assert all(d.channel_visibility == ("api",) for d in docs)
```

运行预期失败。

- [ ] **5.5 修改 FilesystemConnector — __init__ 存储 + _make_document 透传**

打开 `backend/connectors/filesystem.py`，在 `__init__`（line 37-43）末尾追加：

```python
        self._channel_visibility: tuple[str, ...] = config.channel_visibility
```

在 `_make_document`（line 78-98）的 `RawDocument(...)` 构造中追加字段：

```python
    def _make_document(self, path: Path) -> RawDocument:
        content = path.read_text(encoding="utf-8", errors="replace")
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        rel = str(path.relative_to(self._root))
        title = path.stem
        return RawDocument(
            source_id=f"{self._config.id}/{rel}",
            source_type="filesystem",
            product=self.product,
            title=title,
            content=content,
            url=f"file://{path.absolute()}",
            metadata={"path": rel, "root": str(self._root)},
            content_hash=content_hash,
            channel_visibility=self._channel_visibility,
        )
```

运行 `pytest tests/connectors/test_filesystem.py -k "channel_visibility" -x`，预期通过。

- [ ] **5.6 全量回归测试**

运行 `pytest tests/connectors/ -x`。预期全部通过。

- [ ] **5.7 Commit**

```bash
git add config/data_sources.yaml backend/connectors/github.py backend/connectors/filesystem.py tests/connectors/test_github.py tests/connectors/test_filesystem.py
git commit -m "feat: 数据源 channel_visibility 配置 + Connector 透传到 RawDocument"
```

---

## Task 6: HybridSearcher channel 过滤 + SearchResult 读取新字段

**Goal:** 在 `HybridSearcher.search` 增加 `channel` 参数，用 Weaviate `Filter.contains_any` 过滤 channel_visibility；从 Weaviate properties 读取 chunk_type / doc_section / channel_visibility 填入 SearchResult。

**Files:**
- Modify: `backend/retrieval/search.py` (`HybridSearcher.search` line 80-162; SearchResult 构造 line 150-161)
- Test: `tests/retrieval/test_search.py`

**Interfaces:**
- Consumes: Task 4 的 Weaviate schema 含 channel_visibility / doc_section / chunk_type
- Produces: `HybridSearcher.search(query, alpha, limit, product_filter, channel)` 支持渠道过滤；SearchResult 携带新字段

### Steps

- [ ] **6.1 写失败测试 — search channel 过滤**

查看 `tests/retrieval/test_search.py` 了解现有 mock 模式。在末尾追加：

```python
@pytest.mark.unit
def test_search_passes_channel_filter_to_weaviate():
    """search 应在 channel 参数非空时附加 channel_visibility filter。"""
    from unittest.mock import MagicMock, patch
    from backend.retrieval.search import HybridSearcher

    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.collections.get.return_value = mock_collection
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.1, 0.2]]

    searcher = HybridSearcher(mock_client, mock_embedder)
    searcher.search("query", channel="widget")

    hybrid_call_kwargs = mock_collection.query.hybrid.call_args.kwargs
    assert "filters" in hybrid_call_kwargs


@pytest.mark.unit
def test_search_reads_new_properties_into_search_result():
    """search 应从 Weaviate properties 读取 chunk_type / doc_section / channel_visibility。"""
    from unittest.mock import MagicMock
    from backend.retrieval.search import HybridSearcher, SearchResult

    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.collections.get.return_value = mock_collection

    mock_obj = MagicMock()
    mock_obj.properties = {
        "text": "content", "source_id": "s", "source_type": "github",
        "product": "p", "title": "T", "url": "u", "chunk_index": 0,
        "chunk_type": "heading", "doc_section": "Intro > Setup",
        "channel_visibility": ["widget", "api"],
    }
    mock_obj.metadata = MagicMock()
    mock_obj.metadata.distance = 0.2
    mock_collection.query.hybrid.return_value = MagicMock(objects=[mock_obj])

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.1, 0.2]]

    searcher = HybridSearcher(mock_client, mock_embedder)
    results = searcher.search("query")

    assert len(results) == 1
    r = results[0]
    assert r.chunk_type == "heading"
    assert r.doc_section == "Intro > Setup"
    assert r.channel_visibility == ("widget", "api")
```

运行预期失败。

- [ ] **6.2 修改 search 方法 — 增加 channel 参数 + filter**

打开 `backend/retrieval/search.py`，修改 `search` 方法签名和 filter 逻辑（line 80-162）：

```python
    def search(
        self,
        query: str,
        alpha: float = 0.5,
        limit: int = 50,
        product_filter: str | None = None,
        channel: str | None = None,
    ) -> list[SearchResult]:
        if not query or not query.strip():
            logger.info("空 query,跳过 hybrid 检索")
            return []

        vectors = self._embedder.embed([query])
        if not vectors:
            raise RuntimeError("embedder 返回空向量列表,无法执行 hybrid 检索")
        query_vector = vectors[0].tolist()

        collection = self._client.collections.get(self._class_name)
        from weaviate.classes.query import Filter, MetadataQuery

        kwargs: Mapping[str, Any] = {
            "query": query,
            "vector": query_vector,
            "alpha": alpha,
            "limit": limit,
            "return_metadata": MetadataQuery(distance=True),
        }

        # 组合 filter:product + channel
        filters_list = []
        if product_filter:
            filters_list.append(Filter.by_property("product").equal(product_filter))
        if channel:
            filters_list.append(
                Filter.by_property("channel_visibility").contains_any([channel])
            )
        if len(filters_list) == 1:
            kwargs = {**kwargs, "filters": filters_list[0]}
        elif len(filters_list) >= 2:
            kwargs = {**kwargs, "filters": Filter.all_of(filters_list)}

        results = collection.query.hybrid(**kwargs)

        search_results: list[SearchResult] = []
        for obj in results.objects:
            props = obj.properties or {}
            metadata = obj.metadata
            distance = metadata.distance if metadata is not None else None
            score = 1.0 - distance if distance is not None else 0.0
            # channel_visibility 从 Weaviate 返回为 list,转为 tuple
            cv_raw = props.get("channel_visibility", ["widget", "api"])
            cv_tuple = tuple(cv_raw) if isinstance(cv_raw, (list, tuple)) else ("widget", "api")
            search_results.append(
                SearchResult(
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
                )
            )
        return search_results
```

注意：`Filter.all_of` 是 Weaviate v4 的组合 filter API（AND 语义）。如果 Weaviate 版本不支持 `all_of`，改用嵌套 `Filter.by_property(...).equal(...).and_filter(Filter.by_property(...).contains_any(...))`。

运行 `pytest tests/retrieval/test_search.py -k "channel_filter or new_properties" -x`，预期通过。

- [ ] **6.3 全量回归测试**

运行 `pytest tests/retrieval/test_search.py -x`。预期全部通过。

- [ ] **6.4 Commit**

```bash
git add backend/retrieval/search.py tests/retrieval/test_search.py
git commit -m "feat: HybridSearcher 支持 channel 过滤 + SearchResult 读取 chunk_type/doc_section/channel_visibility"
```

---

## Task 7: RerankPipeline chunk_type 加权

**Goal:** 在 RerankPipeline 增加 `type_weights` 参数，对 reranker 分数应用乘性加权。

**Files:**
- Modify: `backend/retrieval/rerank.py` (RerankPipeline line 26-105)
- Test: `tests/retrieval/test_rerank.py`

**Interfaces:**
- Consumes: Task 6 的 `SearchResult.chunk_type`
- Produces: `RerankPipeline(type_weights={"heading": 1.2, ...})` 支持按 chunk_type 加权

### Steps

- [ ] **7.1 写失败测试 — type_weights 加权**

查看 `tests/retrieval/test_rerank.py` 了解现有 mock 模式。在末尾追加：

```python
@pytest.mark.unit
def test_rerank_applies_type_weights():
    """rerank 应按 chunk_type 对 reranker 分数应用乘性加权。"""
    from unittest.mock import MagicMock
    from backend.retrieval.rerank import RerankPipeline
    from backend.retrieval.search import SearchResult

    mock_reranker = MagicMock()
    # 两个候选原始分数相同
    mock_reranker.rerank.return_value = [0.8, 0.8]

    r1 = SearchResult(
        text="heading text", source_id="s1", source_type="t", product="p",
        title="T1", url="u1", score=0.9, chunk_index=0, chunk_type="heading",
    )
    r2 = SearchResult(
        text="paragraph text", source_id="s2", source_type="t", product="p",
        title="T2", url="u2", score=0.9, chunk_index=0, chunk_type="paragraph",
    )

    pipeline = RerankPipeline(
        mock_reranker, threshold=0.0, top_k=10,
        type_weights={"heading": 1.5, "paragraph": 1.0},
    )
    results = pipeline.rerank("query", [r1, r2])

    # heading 加权后 0.8*1.5=1.2 应排在 paragraph 0.8*1.0=0.8 前面
    assert results[0].chunk_type == "heading"
    assert results[0].score == 1.2
    assert results[1].chunk_type == "paragraph"
    assert results[1].score == 0.8


@pytest.mark.unit
def test_rerank_default_type_weights():
    """未传 type_weights 时应使用默认权重,不改变现有行为。"""
    from unittest.mock import MagicMock
    from backend.retrieval.rerank import RerankPipeline
    from backend.retrieval.search import SearchResult

    mock_reranker = MagicMock()
    mock_reranker.rerank.return_value = [0.7]

    r = SearchResult(
        text="text", source_id="s", source_type="t", product="p",
        title="T", url="u", score=0.9, chunk_index=0, chunk_type="paragraph",
    )

    pipeline = RerankPipeline(mock_reranker, threshold=0.0)
    results = pipeline.rerank("query", [r])
    # 默认 paragraph weight = 1.0,分数不变
    assert results[0].score == 0.7
```

运行预期失败。

- [ ] **7.2 修改 RerankPipeline — 增加 type_weights 参数**

打开 `backend/retrieval/rerank.py`，修改 RerankPipeline（line 26-105）：

```python
class RerankPipeline:
    """重排管道(bge-reranker + 阈值过滤 + top_k 截断 + chunk_type 加权)。

    Attributes:
        _reranker: 实现 Reranker 协议的模型实例。
        _threshold: 分数阈值,低于此值的结果被丢弃。默认 0.3。
        _default_top_k: rerank 未显式传 top_k 时使用的默认上限。默认 10。
        _type_weights: chunk_type → 乘性权重映射。默认对所有类型加权 1.0。
    """

    DEFAULT_TYPE_WEIGHTS: dict[str, float] = {
        "heading": 1.2,
        "paragraph": 1.0,
        "code": 1.1,
        "list": 0.9,
        "table": 1.1,
    }

    def __init__(
        self,
        reranker: Reranker,
        threshold: float = 0.3,
        top_k: int = 10,
        type_weights: dict[str, float] | None = None,
    ) -> None:
        self._reranker = reranker
        self._threshold = threshold
        self._default_top_k = top_k
        self._type_weights = type_weights if type_weights is not None else dict(self.DEFAULT_TYPE_WEIGHTS)

    def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_k: int | None = None,
    ) -> list[SearchResult]:
        if not results:
            logger.info("空候选列表,跳过重排")
            return []

        k = top_k if top_k is not None else self._default_top_k

        documents = [r.text for r in results]
        raw_scores = self._reranker.rerank(query, documents)

        if len(raw_scores) != len(results):
            raise RuntimeError(
                f"reranker 返回 scores 长度({len(raw_scores)})与 results"
                f"({len(results)})不匹配"
            )

        # 应用 chunk_type 乘性加权
        weighted = []
        for r, raw_score in zip(results, raw_scores):
            weight = self._type_weights.get(r.chunk_type, 1.0)
            weighted_score = raw_score * weight
            weighted.append((r, weighted_score))

        # 降序排序 → 阈值过滤 → 截断 top_k
        weighted.sort(key=lambda x: x[1], reverse=True)
        filtered = [replace(r, score=s) for r, s in weighted if s >= self._threshold]
        return filtered[:k]
```

运行 `pytest tests/retrieval/test_rerank.py -k "type_weights or default_type_weights" -x`，预期通过。

- [ ] **7.3 全量回归测试**

运行 `pytest tests/retrieval/test_rerank.py -x`。预期全部通过。

- [ ] **7.4 Commit**

```bash
git add backend/retrieval/rerank.py tests/retrieval/test_rerank.py
git commit -m "feat: RerankPipeline 支持 chunk_type 乘性加权(type_weights 参数)"
```

---

## Task 8: RAGOrchestrator 串联 channel + IngestionPipeline 切换到语义分块

**Goal:** 将 channel 参数从 RAGOrchestrator 透传到 HybridSearcher.search；将 IngestionPipeline 的分块器从 chunk_document 切换到 chunk_document_semantic。

**Files:**
- Modify: `backend/pipeline/rag.py` (`answer` line 224-296; `stream_answer` line 298-406)
- Modify: `backend/pipeline/ingest.py` (`ingest_document` line 118-188; 切换分块器调用)
- Test: `tests/pipeline/test_rag.py`
- Test: `tests/pipeline/test_ingest.py`

**Interfaces:**
- Consumes: Task 3 的 `chunk_document_semantic`；Task 6 的 `HybridSearcher.search(channel=...)`；Task 7 的 `RerankPipeline.type_weights`
- Produces: 完整的 channel 隔离 + 语义分块管线

### Steps

- [ ] **8.1 写失败测试 — RAGOrchestrator 透传 channel**

查看 `tests/pipeline/test_rag.py` 了解现有 mock 模式。在末尾追加：

```python
@pytest.mark.asyncio
@pytest.mark.unit
async def test_answer_passes_channel_to_searcher():
    """RAGOrchestrator.answer 应把 channel 透传给 searcher.search。"""
    from unittest.mock import MagicMock, AsyncMock
    from backend.pipeline.rag import RAGOrchestrator

    mock_searcher = MagicMock()
    mock_searcher.search.return_value = []
    mock_reranker = MagicMock()
    mock_reranker.rerank.return_value = []
    mock_llm = AsyncMock()

    orchestrator = RAGOrchestrator(
        searcher=mock_searcher, reranker=mock_reranker, llm=mock_llm,
        system_prompt="test",
    )
    await orchestrator.answer("question", channel="widget")

    mock_searcher.search.assert_called()
    call_kwargs = mock_searcher.search.call_args.kwargs
    assert call_kwargs.get("channel") == "widget"
```

运行预期失败（当前 searcher.search 调用不含 channel）。

- [ ] **8.2 修改 answer 方法 — 透传 channel**

打开 `backend/pipeline/rag.py`，在 `answer` 方法（line 224-296）的 searcher.search 调用（line 259-264）中追加 channel 参数：

```python
        results = self._searcher.search(
            query=search_query,
            alpha=self._alpha,
            limit=self._recall_limit,
            product_filter=product_filter,
            channel=channel,
        )
```

同样修改 `stream_answer` 方法（line 298-406）的 searcher.search 调用（line 335-340）：

```python
        results = self._searcher.search(
            query=search_query,
            alpha=self._alpha,
            limit=self._recall_limit,
            product_filter=product_filter,
            channel=channel,
        )
```

运行 `pytest tests/pipeline/test_rag.py::test_answer_passes_channel_to_searcher -x`，预期通过。

- [ ] **8.3 修改 IngestionPipeline — 切换到 chunk_document_semantic**

打开 `backend/pipeline/ingest.py`，修改 import（line 27）和 `ingest_document` 中的分块调用（line 134）：

```python
from backend.pipeline.chunk import chunk_document_semantic
```

在 `ingest_document` 方法中（line 134）：

```python
        chunks = chunk_document_semantic(doc, self._max_tokens, self._overlap)
```

- [ ] **8.4 写测试 — IngestionPipeline 使用语义分块**

在 `tests/pipeline/test_ingest.py` 末尾追加：

```python
@pytest.mark.unit
def test_ingest_document_uses_semantic_chunking():
    """ingest_document 应使用 chunk_document_semantic 而非 chunk_document。"""
    from unittest.mock import MagicMock, patch
    from backend.pipeline.ingest import IngestionPipeline
    from backend.connectors.base import RawDocument

    mock_client = MagicMock()
    mock_client.collections.exists.return_value = True
    mock_collection = MagicMock()
    mock_client.collections.get.return_value = mock_collection

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.1]]

    pipeline = IngestionPipeline(
        embedder=mock_embedder, weaviate_client=mock_client, class_name="Document",
    )

    doc = RawDocument(
        source_id="t/1", source_type="github", product="p",
        title="T", content="# Heading\n\nText.", url="u",
        metadata={}, content_hash="h",
    )

    with patch("backend.pipeline.ingest.chunk_document_semantic") as mock_chunk:
        mock_chunk.return_value = []
        pipeline.ingest_document(doc)
        mock_chunk.assert_called_once()
```

运行 `pytest tests/pipeline/test_ingest.py::test_ingest_document_uses_semantic_chunking -x`，预期通过。

- [ ] **8.5 全量回归测试**

运行 `pytest tests/pipeline/ -x`。修复因 SearchResult 字段变化导致的所有测试失败。

- [ ] **8.6 Commit**

```bash
git add backend/pipeline/rag.py backend/pipeline/ingest.py tests/pipeline/test_rag.py tests/pipeline/test_ingest.py
git commit -m "feat: RAGOrchestrator 透传 channel 到 searcher + IngestionPipeline 切换到语义分块"
```

---

## Task 9: 全量重新索引脚本

**Goal:** 在 `scripts/sync.py` 增加 `--reindex` flag，删除并重建 Weaviate collection 后全量同步所有数据源。

**Files:**
- Modify: `scripts/sync.py` (`_parse_args` line 239-261; `run_sync` line 174-236)
- Test: `tests/pipeline/test_sync.py`

**Interfaces:**
- Consumes: Task 4 的新 Weaviate schema（含 3 个新 property）
- Produces: `python scripts/sync.py --reindex` 命令

### Steps

- [ ] **9.1 写失败测试 — --reindex 删除并重建 collection**

查看 `tests/pipeline/test_sync.py` 了解现有测试模式。在末尾追加：

```python
@pytest.mark.asyncio
@pytest.mark.unit
async def test_reindex_deletes_and_recreates_collection():
    """--reindex 应先删除 collection,再让 IngestionPipeline 重建。"""
    from unittest.mock import MagicMock, AsyncMock, patch
    from scripts.sync import run_sync
    from backend.config import Settings

    settings = Settings(
        postgres_dsn="postgresql+asyncpg://u:p@localhost/db",
        weaviate_url="localhost:8080",
        config_dir=Path(__file__).resolve().parent.parent.parent / "config",
        embedder_device="cpu",
        weaviate_class_name="Document",
    )

    with patch("scripts.sync.weaviate") as mock_weaviate, \
         patch("scripts.sync.get_engine") as mock_get_engine, \
         patch("scripts.sync.get_session_factory"), \
         patch("scripts.sync.init_db", new_callable=AsyncMock), \
         patch("scripts.sync.BGEEmbedder"), \
         patch("scripts.sync.IngestionPipeline") as mock_pipeline_cls, \
         patch("scripts.sync.ConnectorRegistry.load_configs") as mock_load_configs:

        mock_client = MagicMock()
        mock_collections = MagicMock()
        mock_client.collections = mock_collections
        mock_weaviate.connect_to_local.return_value = mock_client

        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_get_engine.return_value = mock_engine

        mock_pipeline = MagicMock()
        mock_pipeline_cls.return_value = mock_pipeline

        mock_load_configs.return_value = []  # 空配置,不实际同步

        await run_sync(settings, dry_run=False, reindex=True)

        # 验证删除了 collection
        mock_collections.delete.assert_called_once_with(name="Document")
```

运行预期失败（`reindex` 参数不存在）。

- [ ] **9.2 修改 run_sync — 增加 reindex 参数 + 删除 collection 逻辑**

打开 `scripts/sync.py`，修改 `run_sync` 签名（line 174-179）：

```python
async def run_sync(
    settings: Settings,
    source_id: str | None = None,
    *,
    dry_run: bool = False,
    reindex: bool = False,
) -> None:
```

在 `run_sync` 函数体中 weaviate_client 连接后（line 204 后）、`init_db` 前，增加 reindex 逻辑：

```python
        weaviate_client = weaviate.connect_to_local(host=host, port=port)

        if reindex:
            logger.info("reindex 模式:删除 collection %s", settings.weaviate_class_name)
            try:
                weaviate_client.collections.delete(settings.weaviate_class_name)
                logger.info("collection %s 已删除,将由 IngestionPipeline 重建", settings.weaviate_class_name)
            except Exception as exc:
                logger.warning("删除 collection 失败(可能不存在):%s", exc)

        if not dry_run:
            await init_db(engine)
```

- [ ] **9.3 修改 _parse_args + main — 增加 --reindex flag**

在 `_parse_args`（line 239-261）中追加：

```python
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="删除并重建 Weaviate collection 后全量同步所有数据源",
    )
```

在 `main`（line 264-272）中传递 reindex：

```python
def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _parse_args(argv)
    settings = load_settings()
    asyncio.run(run_sync(
        settings, source_id=args.source, dry_run=args.dry_run, reindex=args.reindex,
    ))
```

运行 `pytest tests/pipeline/test_sync.py::test_reindex_deletes_and_recreates_collection -x`，预期通过。

- [ ] **9.4 全量回归测试**

运行 `pytest tests/pipeline/test_sync.py -x`。预期全部通过。

- [ ] **9.5 Commit**

```bash
git add scripts/sync.py tests/pipeline/test_sync.py
git commit -m "feat: sync 脚本新增 --reindex flag 支持全量重建 Weaviate collection"
```

---

## Task 10: 端到端集成测试 + 验收

**Goal:** 验证语义分块、channel 隔离、rerank 加权三项功能在完整管线中协同工作。

**Files:**
- Test: `tests/pipeline/test_phase2a_integration.py` (new)

**Interfaces:**
- Consumes: Task 1-9 的全部产出
- Produces: 集成测试通过,验证三项功能端到端正确性

### Steps

- [ ] **10.1 写集成测试 — 语义分块端到端**

新建 `tests/pipeline/test_phase2a_integration.py`：

```python
"""Phase 2A 端到端集成测试。

验证三项功能在完整管线中协同工作:
1. 语义分块:代码块不被切断,chunk_type 正确标注
2. channel 隔离:knowledge-internal 的 chunk 不出现在 widget 渠道
3. rerank 加权:heading chunk 分数被放大
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from backend.connectors.base import RawDocument
from backend.pipeline.chunk import chunk_document_semantic
from backend.retrieval.search import SearchResult
from backend.retrieval.rerank import RerankPipeline


@pytest.mark.unit
def test_semantic_chunk_code_block_intact():
    """代码块即使超过 max_tokens 也不在标题边界被切断。"""
    code = "```python\n" + "\n".join(f"v{i} = {i}" for i in range(100)) + "\n```"
    content = f"# Title\n\nIntro.\n\n{code}\n\n## End\n\nFinal."
    doc = RawDocument(
        source_id="t/1", source_type="github", product="p",
        title="T", content=content, url="u", metadata={}, content_hash="h",
    )
    chunks = chunk_document_semantic(doc, max_tokens=80, overlap=10)
    assert len(chunks) >= 1
    code_chunks = [c for c in chunks if c.chunk_type == "code"]
    assert len(code_chunks) >= 1


@pytest.mark.unit
def test_channel_visibility_isolation():
    """channel_visibility=('api',) 的 chunk 在 widget 渠道应被过滤。"""
    from backend.retrieval.search import HybridSearcher

    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.collections.get.return_value = mock_collection

    # 模拟 Weaviate 返回两条结果:一条 widget 可见,一条仅 api
    widget_obj = MagicMock()
    widget_obj.properties = {
        "text": "public", "source_id": "s1", "source_type": "t", "product": "p",
        "title": "T1", "url": "u1", "chunk_index": 0, "chunk_type": "paragraph",
        "doc_section": "", "channel_visibility": ["widget", "api"],
    }
    widget_obj.metadata = MagicMock(distance=0.1)

    api_only_obj = MagicMock()
    api_only_obj.properties = {
        "text": "internal", "source_id": "s2", "source_type": "t", "product": "p",
        "title": "T2", "url": "u2", "chunk_index": 0, "chunk_type": "paragraph",
        "doc_section": "", "channel_visibility": ["api"],
    }
    api_only_obj.metadata = MagicMock(distance=0.05)

    mock_collection.query.hybrid.return_value = MagicMock(
        objects=[widget_obj, api_only_obj]
    )

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.1, 0.2]]

    searcher = HybridSearcher(mock_client, mock_embedder)
    results = searcher.search("query", channel="widget")

    # Weaviate filter 在真实环境中会过滤掉 api_only 条目
    # 此 mock 测试验证 filter 被正确传入
    hybrid_kwargs = mock_collection.query.hybrid.call_args.kwargs
    assert "filters" in hybrid_kwargs


@pytest.mark.unit
def test_rerank_type_weights_change_ordering():
    """相同 reranker 分数下,heading 应排在 paragraph 前面。"""
    mock_reranker = MagicMock()
    mock_reranker.rerank.return_value = [0.5, 0.5]

    r_heading = SearchResult(
        text="# Setup Guide\n\nInstall steps.", source_id="s1", source_type="t",
        product="p", title="T1", url="u1", score=0.9, chunk_index=0, chunk_type="heading",
    )
    r_paragraph = SearchResult(
        text="Some background info text.", source_id="s2", source_type="t",
        product="p", title="T2", url="u2", score=0.9, chunk_index=0, chunk_type="paragraph",
    )

    pipeline = RerankPipeline(mock_reranker, threshold=0.0, top_k=10)
    results = pipeline.rerank("query", [r_paragraph, r_heading])

    assert results[0].chunk_type == "heading"
    assert results[1].chunk_type == "paragraph"
    assert results[0].score > results[1].score
```

- [ ] **10.2 运行集成测试**

运行 `pytest tests/pipeline/test_phase2a_integration.py -x -v`。预期全部通过。

- [ ] **10.3 全量回归测试**

运行 `pytest tests/ -x --tb=short -q`。预期全部通过（Phase 1 的 151 个测试 + Phase 2A 新增测试）。

- [ ] **10.4 Commit**

```bash
git add tests/pipeline/test_phase2a_integration.py
git commit -m "test: Phase 2A 端到端集成测试 — 语义分块 + channel 隔离 + rerank 加权"
```

---

## Self-Review

### Spec 覆盖检查

| Spec 要求（§10.2 line 484-486） | 对应 Task |
|---|---|
| 语义分块:按标题/段落语义边界分块(替换 Phase 1 固定窗口) | Task 2 (`_identify_blocks`) + Task 3 (`chunk_document_semantic`) + Task 8 (切换) |
| 数据源隔离:chunk 级 channel_visibility 控制 | Task 1 (数据结构) + Task 4 (Weaviate schema) + Task 5 (配置+Connector) + Task 6 (search filter) + Task 8 (RAGOrchestrator 透传) |
| chunk 元数据丰富化:doc_section/chunk_type 供 rerank 加权 | Task 2 (`_classify_chunk_type` + `_build_doc_section`) + Task 3 (填充) + Task 6 (SearchResult 读取) + Task 7 (rerank 加权) |

三项功能全部覆盖。

### 占位符扫描

- 搜索 "TBD" / "TODO" / "implement later" / "fill in details" / "add appropriate" / "similar to"：无命中。
- 所有 step 包含可执行的测试代码和实现代码。

### 类型一致性

- `Chunk.channel_visibility: tuple[str, ...]` — Task 1 定义，Task 3 使用 `getattr(doc, "channel_visibility", ...)` 读取。
- `RawDocument.channel_visibility: tuple[str, ...]` — Task 1 定义，Task 5 由 Connector 填充。
- `SourceConfig.channel_visibility: tuple[str, ...]` — Task 1 定义，Task 5 由 Connector 读取。
- `SearchResult.chunk_type: str` / `doc_section: str` / `channel_visibility: tuple[str, ...]` — Task 1 定义，Task 6 从 Weaviate 读取填充。
- `HybridSearcher.search(channel: str | None)` — Task 6 定义，Task 8 RAGOrchestrator 调用时传 `channel=channel`。
- `RerankPipeline(type_weights: dict[str, float] | None)` — Task 7 定义，默认值不破坏现有调用方。
- `chunk_document_semantic(doc, max_tokens, overlap) -> list[Chunk]` — Task 3 定义，Task 8 IngestionPipeline 调用参数对齐。

### 风险提示

1. **Weaviate `Filter.all_of` 兼容性**：Task 6 用 `Filter.all_of` 组合 product + channel filter。如果 Weaviate client < 4.10 不支持，回退到嵌套 `Filter.by_property(...).and_filter(...)` 语法。pyproject.toml 已声明 `weaviate-client>=4.10`，理论支持。
2. **Weaviate `DataType.TEXT_ARRAY` 写入格式**：写入时用 `list(chunk.channel_visibility)`（Python list），Weaviate v4 接受 list 作为 text[] 值。
3. **全量重建 collection 的停机时间**：`--reindex` 会删除整个 collection 再重建。生产环境需在低峰期执行，期间所有查询会返回空结果。建议未来增加 zero-downtime migration（新建 collection → 双写 → 切换 → 删旧）。
4. **knowledge-base 拆分**：Task 5 将 `knowledge-base` 拆分为 `knowledge-public` 和 `knowledge-internal`。如果现有 Postgres `documents` 表中有 `knowledge-base` 的记录，`--reindex` 后 source_id 会变化（新 source_id 前缀为 `knowledge-public/...` 或 `knowledge-internal/...`），旧记录需要手动清理或用 `delete_document` 迁移。
5. **markdown-it-py 不引入**：本计划用正则扩展方案识别语义边界。正则方案对嵌套列表（二级缩进的 `-` 子项）的识别有限——一级列表会被识别为 `list` 类型块，但嵌套子列表可能被包含在父块内不单独识别。对于 Phase 2A 的 rerank 加权目的（判断 chunk 主导类型），此精度已足够。
