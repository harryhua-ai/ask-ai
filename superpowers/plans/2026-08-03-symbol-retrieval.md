# 函数级符号检索 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给开发者代码层问题(`product_question`,未来 `support`)加函数级精确召回 —— symbol 元数据独立化 + 独立符号 BM25(用原始 query 绕过 rewrite)+ RRF 融合。

**Architecture:** 复用现有 tree-sitter 函数级分块(`chunk_code.py` 已实现),把 symbol/signature/node_type 从 text 前缀提取为独立元数据字段(Chunk + Weaviate schema),新增 `symbol_tokens` 拆分版解决 camelCase 分词;检索层独立符号 BM25(用 `extract_query` 输出)+ hybrid(`search_query`)RRF 融合 → rerank。**不做 SCIP**。

**Tech Stack:** Python 3.12 / tree-sitter / Weaviate v4 / pytest / async

## Global Constraints

- **实现依赖 tesla-t4 orchestrator 的 `ingest.py` 改动提交**(working tree 现有 293 行未提交,batch 优化)。派实现 orchestrator **前必须确认 `ingest.py` 已 commit**,避免冲突。
- 测试必设 `TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test`(conftest `drop_all` 会清开发库)。
- 本 plan 改 `chunk_code.py` / `chunk.py` / `ingest.py` / `retrieval/search.py` / `rag.py` —— 与 tesla-t4 在跑的 `ingest.py` 同文件,实现前确认。
- 测试用现有 `_make_weaviate_client()` MagicMock helper(`tests/pipeline/test_ingest.py:48`),**不要假设 conftest 有 weaviate fixture**。
- spec:`docs/superpowers/specs/2026-08-03-symbol-retrieval-design.md`(复审通过)。

---

## File Structure

| 文件 | 职责 | 改动 |
|---|---|---|
| `backend/pipeline/chunk.py` | Chunk dataclass | 加 4 字段 |
| `backend/pipeline/chunk_code.py` | tree-sitter 代码分块 | 提取 symbol 元数据 + 派生 symbol_tokens(4 处元组改动)|
| `backend/pipeline/ingest.py` | Weaviate schema + 写入 | 加 4 Property + 抽 `_build_props` |
| `backend/retrieval/search.py` | hybrid 检索 + SearchResult | 加 `_to_search_result` + 符号 BM25 召回 + RRF + SearchResult 字段 |
| `backend/retrieval/rrf.py` | RRF 融合 | 新建 |
| `backend/pipeline/rag.py` | RAG 管线 | 插入符号召回(用 extract_query)+ RRF |
| `tests/pipeline/test_chunk_code.py` / `test_ingest.py` / `test_rag.py` / `tests/retrieval/test_search.py` / `test_rrf.py` | 单测 | TDD |

---

## Task 1: Chunk dataclass 加 symbol 字段

**Files:**
- Modify: `backend/pipeline/chunk.py:88`(`Chunk` dataclass,`channel_visibility` 后)
- Test: `tests/pipeline/test_chunk.py`

**Interfaces:**
- Produces: `Chunk` 新增 4 字段(默认空串,兼容文档 chunk)

- [ ] **Step 1: 写失败测试**

```python
# tests/pipeline/test_chunk.py
def test_chunk_symbol_defaults_empty():
    """Chunk 新增 symbol 字段默认空串,兼容文档 chunk。"""
    from backend.pipeline.chunk import Chunk
    from backend.connectors.base import RawDocument
    doc = RawDocument(source_id="t", source_type="filesystem", product="x",
                     title="T", content="c", url="", metadata={}, content_hash="h",
                     branch="")  # branch 有默认值(base.py:46),显式传更清晰
    c = Chunk(text="x", document=doc, chunk_index=0, total_chunks=1,
              start_char=0, end_char=1)
    assert c.symbol_name == ""
    assert c.symbol_signature == ""
    assert c.symbol_node_type == ""
    assert c.symbol_tokens == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/pipeline/test_chunk.py::test_chunk_symbol_defaults_empty -v`
Expected: FAIL(`Chunk 无 symbol_name 属性`)

- [ ] **Step 3: 加字段**

```python
# backend/pipeline/chunk.py Chunk dataclass(channel_visibility 后)
    symbol_name: str = ""
    symbol_signature: str = ""
    symbol_node_type: str = ""
    symbol_tokens: str = ""
```

- [ ] **Step 4: 跑测试确认通过 + 现有 chunk 测试零回归**

Run: `pytest tests/pipeline/test_chunk.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/chunk.py tests/pipeline/test_chunk.py
git commit -m "feat(chunk): Chunk 加 symbol 元数据字段(name/signature/node_type/tokens)"
```

---

## Task 2: chunk_code 提取 symbol 元数据 + 派生 symbol_tokens

**Files:**
- Modify: `backend/pipeline/chunk_code.py`(`_collect_sections` 约 218/240/249 / `_build_chunks` 约 261/280 / `chunk_code` 兜底约 339 / 主路径约 349-355)
- Test: `tests/pipeline/test_chunk_code.py`

**Interfaces:**
- Consumes: Task 1 的 Chunk 字段
- Produces: `chunk_code` 输出的 Chunk 填 symbol 字段;`_split_symbol_name(name) -> str`

- [ ] **Step 1: 写失败测试 —— _split_symbol_name**

```python
# tests/pipeline/test_chunk_code.py
from backend.pipeline.chunk_code import _split_symbol_name

def test_split_symbol_camel_case():
    assert _split_symbol_name("BatteryReadI2C") == "battery read i2c"

def test_split_symbol_pascal_with_acronym():
    assert _split_symbol_name("HTMLParser") == "html parser"

def test_split_symbol_snake_case():
    assert _split_symbol_name("ne301_init") == "ne301 init"

def test_split_symbol_digit_boundary():
    """数字→大写无小写后继不拆(I2C 整体);数字→大写+小写拆(NE301 + Config)。"""
    assert _split_symbol_name("readI2C") == "read i2c"        # I2C 整体
    assert _split_symbol_name("NE301Config") == "ne301 config"  # NE301 + Config
    assert _split_symbol_name("I2C") == "i2c"                  # I2C 整体

def test_split_symbol_empty():
    assert _split_symbol_name("") == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/pipeline/test_chunk_code.py -k split_symbol -v`
Expected: FAIL(`_split_symbol_name` 不存在)

- [ ] **Step 3: 实现 _split_symbol_name**

```python
# backend/pipeline/chunk_code.py
import re

# 边界规则:
#   小写→大写:camelCase 边界(readI2C → read + I2C)
#   大写→大写+小写:缩写词边界(HTMLParser → HTML + Parser)
#   数字→大写+小写:NE301 + Config(数字后接新词)
#   数字→大写无小写:I2C 整体(不拆,2→C 后无小写)
_CAMEL_BOUNDARY = re.compile(
    r"(?<=[a-z])(?=[A-Z])"        # 小写→大写
    r"|(?<=[A-Z])(?=[A-Z][a-z])"  # 大写→大写+小写
    r"|(?<=[0-9])(?=[A-Z][a-z])"  # 数字→大写+小写
)

def _split_symbol_name(name: str) -> str:
    """camelCase/PascalCase/snake_case → 空格小写;缩写词(I2C/NE301)整体保留。"""
    if not name:
        return ""
    s = name.replace("_", " ")
    s = _CAMEL_BOUNDARY.sub(" ", s)
    return " ".join(tok.lower() for tok in s.split() if tok)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/pipeline/test_chunk_code.py -k split_symbol -v`
Expected: PASS(5 测例全过,含 I2C/NE301 数字边界)

- [ ] **Step 5: 写失败测试 —— chunk_code 填 symbol**

```python
def test_chunk_code_fills_symbol_fields():
    from backend.pipeline.chunk_code import chunk_code
    from backend.connectors.base import RawDocument
    src = "def battery_read_i2c(addr):\n    return i2c_read(addr)\n"
    doc = RawDocument(source_id="ne301/main.c", source_type="local_git",
                      product="ne301", title="main.c", content=src, url="",
                      metadata={"path": "main.c"}, content_hash="h", branch="main")
    chunks = chunk_code(doc)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.symbol_name == "battery_read_i2c"
    assert c.symbol_tokens == "battery read i2c"
    assert c.symbol_node_type == "function_definition"
    assert "battery_read_i2c" in c.symbol_signature

def test_chunk_code_symbol_fields_empty_for_no_grammar():
    from backend.pipeline.chunk_code import chunk_code
    from backend.connectors.base import RawDocument
    doc = RawDocument(source_id="r/x.txt", source_type="local_git", product="x",
                      title="x", content="hello", url="",
                      metadata={"path": "x.txt"}, content_hash="h", branch="main")
    chunks = chunk_code(doc)
    assert chunks[0].symbol_name == ""
    assert chunks[0].symbol_tokens == ""
```

- [ ] **Step 6: 跑失败 → pieces 5→6 元组(4 处)+ _build_chunks 填字段**

改动 4 处(按 spec §3.2):
1. `_collect_sections`:sections 收集时附 `node_type`(从 `node.type`),pieces 元组加 `node_type` → 6 元组 `(text, start, end, symbol, signature, node_type)`
2. `_build_chunks`:解构 6 元组,填 `symbol_name`/`symbol_signature`/`symbol_node_type`;派生 `symbol_tokens = _split_symbol_name(symbol)`
3. `chunk_code` 无 grammar 兜底(约 339):pieces 用空 symbol/node_type(6 元组)
4. `chunk_code` 主路径组装(约 349-355):6 元组透传

```python
# _build_chunks 内
for i, (text, start, end, symbol, signature, node_type) in enumerate(pieces):
    prefix = _symbol_prefix(doc, path, symbol, signature)
    chunks.append(
        Chunk(
            text=prefix + text, document=doc, chunk_index=i, total_chunks=total,
            start_char=start, end_char=end, chunk_type="code", doc_section="",
            channel_visibility=channel_vis,
            symbol_name=symbol,
            symbol_signature=signature,
            symbol_node_type=node_type,
            symbol_tokens=_split_symbol_name(symbol),
        )
    )
```

- [ ] **Step 7: 跑通过 + 现有 chunk_code 测试零回归**

Run: `pytest tests/pipeline/test_chunk_code.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/pipeline/chunk_code.py tests/pipeline/test_chunk_code.py
git commit -m "feat(chunk_code): 提取 symbol 元数据 + 派生 symbol_tokens(camelCase 拆分)"
```

---

## Task 3: Weaviate schema 加 Property + 抽 _build_props

**Files:**
- Modify: `backend/pipeline/ingest.py`(`_ensure_collection` 行 111-153,Property 列表 136-150 + 3 处 props:主路径 201-216 / 兜底 258-271 / `_ingest_doc_batch` 403-416)
- Test: `tests/pipeline/test_ingest.py`

**Interfaces:**
- Consumes: Task 1 Chunk 字段
- Produces: schema 4 新 Property;`_build_props(chunk, doc) -> dict`

- [ ] **Step 1: 写失败测试 —— schema 含 symbol 字段**

```python
# tests/pipeline/test_ingest.py
def test_collection_has_symbol_properties():
    from backend.pipeline.ingest import IngestionPipeline
    client = _make_weaviate_client()  # 现有 helper(test_ingest.py:48)
    p = IngestionPipeline.__new__(IngestionPipeline)  # 绕 __init__
    p._client = client
    p._class_name = "Document"
    p._embedder = None
    p._session_factory = None
    p._collection = None  # __init__ 未跑,手动设(否则 _ensure_collection 行 125 AttributeError)
    p._ensure_collection()
    cols = client.collections.get("Document")
    props = {pp.name for pp in cols.config.get().properties}
    assert "symbol_name" in props
    assert "symbol_tokens" in props
    assert "symbol_signature" in props
    assert "symbol_node_type" in props
```

- [ ] **Step 2: 跑失败 → 加 Property**

在 `_ensure_collection` 的 `Property(...)` 列表(行 136-150,`branch` 后)加:

```python
Property(name="symbol_name", data_type=DataType.TEXT),
Property(name="symbol_signature", data_type=DataType.TEXT),
Property(name="symbol_node_type", data_type=DataType.TEXT),
Property(name="symbol_tokens", data_type=DataType.TEXT),
```

- [ ] **Step 3: 跑通过**

Run: `pytest tests/pipeline/test_ingest.py::test_collection_has_symbol_properties -v`
Expected: PASS

- [ ] **Step 4: 写失败测试 —— _build_props 含 symbol**

```python
def test_build_props_contains_symbol():
    from backend.pipeline.ingest import _build_props
    from backend.pipeline.chunk import Chunk
    from backend.connectors.base import RawDocument
    doc = RawDocument(source_id="ne301/main.c", source_type="local_git", product="ne301",
                      title="main.c", content="x", url="", metadata={"path": "main.c"},
                      content_hash="h", branch="main")
    chunk = Chunk(text="t", document=doc, chunk_index=0, total_chunks=1,
                  start_char=0, end_char=1, chunk_type="code",
                  symbol_name="battery_read_i2c", symbol_tokens="battery read i2c",
                  symbol_node_type="function_definition", symbol_signature="def ...")
    props = _build_props(chunk, doc)
    assert props["symbol_name"] == "battery_read_i2c"
    assert props["symbol_tokens"] == "battery read i2c"
    assert props["symbol_node_type"] == "function_definition"
```

- [ ] **Step 5: 跑失败 → 抽 _build_props + 3 处调用**

```python
# backend/pipeline/ingest.py
def _build_props(chunk, doc) -> dict:
    """从 Chunk + RawDocument 构造 Weaviate properties(消除 3 处重复)。"""
    return {
        "source_id": doc.source_id, "source_type": doc.source_type,
        "product": doc.product, "title": doc.title, "text": chunk.text,
        "url": doc.url, "chunk_index": chunk.chunk_index,
        "content_hash": doc.content_hash,
        "channel_visibility": list(chunk.channel_visibility),
        "doc_section": chunk.doc_section, "chunk_type": chunk.chunk_type,
        "branch": doc.branch,
        "symbol_name": chunk.symbol_name,
        "symbol_signature": chunk.symbol_signature,
        "symbol_node_type": chunk.symbol_node_type,
        "symbol_tokens": chunk.symbol_tokens,
    }
```

3 处 props 构造(主路径 201-216 / 兜底 258-271 / `_ingest_doc_batch` 403-416)替换为 `_build_props(chunk, doc)` 调用。

- [ ] **Step 6: 跑通过 + 现有 ingest 测试零回归**

Run: `pytest tests/pipeline/test_ingest.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/pipeline/ingest.py tests/pipeline/test_ingest.py
git commit -m "feat(ingest): schema 加 symbol Property + 抽 _build_props 统一 3 处写入"
```

---

## Task 4: SearchResult 加 symbol + 抽 _to_search_result

**Files:**
- Modify: `backend/retrieval/search.py`(`SearchResult` 26-64 + 内联构造 186-198)
- Test: `tests/retrieval/test_search.py`

**Interfaces:**
- Produces: SearchResult 加 `symbol_name`/`symbol_signature`;`HybridSearcher._to_search_result(obj) -> SearchResult`(重构内联构造,Task 5 复用)

- [ ] **Step 1: 写失败测试**

```python
def test_search_result_symbol_defaults():
    from backend.retrieval.search import SearchResult
    r = SearchResult(text="t", source_id="s", source_type="local_git",
                     product="ne301", title="T", url="", score=0.5, chunk_index=0)
    assert r.symbol_name == ""
    assert r.symbol_signature == ""
```

- [ ] **Step 2: 加字段 + 抽 _to_search_result**

`SearchResult` 加:
```python
    symbol_name: str = ""
    symbol_signature: str = ""
```

把 `search` 内联构造(search.py:186-198)重构为方法:
```python
# backend/retrieval/search.py HybridSearcher
def _to_search_result(self, obj) -> SearchResult:
    """Weaviate 对象 → SearchResult(含 symbol 字段,Task 5 search_symbols 复用)。"""
    props = obj.properties
    return SearchResult(
        text=props.get("text", ""),
        source_id=props.get("source_id", ""),
        source_type=props.get("source_type", ""),
        product=props.get("product", ""),
        title=props.get("title", ""),
        url=props.get("url", ""),
        score=1.0 - (obj.metadata.distance if obj.metadata and obj.metadata.distance is not None else 1.0),
        chunk_index=props.get("chunk_index", 0),
        chunk_type=props.get("chunk_type", ""),
        doc_section=props.get("doc_section", ""),
        channel_visibility=tuple(props.get("channel_visibility", ("widget", "api"))),
        symbol_name=props.get("symbol_name", ""),
        symbol_signature=props.get("symbol_signature", ""),
    )
```

`search` 内联处替换为 `self._to_search_result(o)`。

- [ ] **Step 3: 跑通过 + commit**

```bash
pytest tests/retrieval/test_search.py -v
git add backend/retrieval/search.py tests/retrieval/test_search.py
git commit -m "feat(search): SearchResult 加 symbol + 抽 _to_search_result(Task 5 复用)"
```

---

## Task 5: 符号 BM25 召回(独立,用原始 query)

**Files:**
- Modify: `backend/retrieval/search.py`(`HybridSearcher.search_symbols`)
- Test: `tests/retrieval/test_search.py`

**Interfaces:**
- Consumes: Task 3 schema(`symbol_tokens`)+ Task 4 `_to_search_result`
- Produces: `search_symbols(query, limit, product_filter, channel) -> list[SearchResult]`

- [ ] **Step 1: 写失败测试**

```python
def test_search_symbols_bm25_hits_symbol_tokens():
    """符号 BM25 on symbol_tokens 命中 camelCase 符号(query 'I2C' 命中 BatteryReadI2C)。"""
    from backend.retrieval.search import HybridSearcher
    from tests.pipeline.test_ingest import _make_weaviate_client
    # 预置:用 _make_weaviate_client mock,配置返回 symbol_name=BatteryReadI2C / symbol_tokens="battery read i2c"
    client = _make_weaviate_client()
    # mock col.query.bm25 返回含 BatteryReadI2C 的对象(参照现有 _make_weaviate_client mock 模式)
    searcher = HybridSearcher(client, embedder=None)
    results = searcher.search_symbols(query="I2C", limit=10)
    assert any(r.symbol_name == "BatteryReadI2C" for r in results)
```

> 测试预置:沿用 `_make_weaviate_client()` 的 MagicMock 模式,配置 `col.query.bm25(...).objects` 返回 mock 对象(properties 含 symbol_name/symbol_tokens)。参照 `test_ingest.py` 现有 mock 写法。

- [ ] **Step 2: 跑失败 → 实现 search_symbols**

```python
# backend/retrieval/search.py HybridSearcher
def search_symbols(self, query: str, limit: int = 30,
                   product_filter: str | None = None,
                   channel: str = "widget") -> list[SearchResult]:
    """独立符号 BM25 召回(对 symbol_tokens),用原始 query(绕过 rewrite 保标识符)。"""
    col = self._client.collections.get(self._class_name)
    from weaviate.classes.query import Filter
    filters = Filter.by_property("channel_visibility").contains_any([channel])
    if product_filter:
        filters = filters & Filter.by_property("product").equal(product_filter)
    resp = col.query.bm25(
        query=query, query_properties=["symbol_tokens^3"],  # boost symbol_tokens
        limit=limit, filters=filters, return_properties=[
            "source_id", "source_type", "product", "title", "url", "text",
            "chunk_index", "chunk_type", "doc_section", "channel_visibility",
            "symbol_name", "symbol_signature", "branch",
        ],
    )
    # BM25 无 distance:score 用 metadata.score(若有)或 0.0(RRF 会重排,score 不参与 rerank)
    return [self._to_search_result(o) for o in resp.objects]
```

> 注:`query_properties` 参数名 + `^3` boost 语法实现时查 Weaviate v4 文档确认(spec §3.4 reviewer 已核:hybrid 默认覆盖所有 TEXT,此处显式 boost symbol_tokens)。BM25 结果 `score` 由 RRF 重排,rerank 用 `r.text` 不依赖 score。

- [ ] **Step 3: 跑通过 + commit**

```bash
pytest tests/retrieval/test_search.py -v
git add backend/retrieval/search.py tests/retrieval/test_search.py
git commit -m "feat(search): 独立符号 BM25 召回(search_symbols,用原始 query)"
```

---

## Task 6: RRF 融合

**Files:**
- Create: `backend/retrieval/rrf.py`
- Test: `tests/retrieval/test_rrf.py`

**Interfaces:**
- Produces: `rrf_fuse(hybrid, symbol, k=60) -> list[SearchResult]`,按 `source_id + chunk_index` 去重

- [ ] **Step 1: 写失败测试**

```python
# tests/retrieval/test_rrf.py
def test_rrf_dedup_by_source_id_chunk_index():
    from backend.retrieval.rrf import rrf_fuse
    from backend.retrieval.search import SearchResult
    a = SearchResult(text="a", source_id="s1", source_type="local_git", product="p",
                     title="T", url="", score=0.9, chunk_index=0)
    b = SearchResult(text="a", source_id="s1", source_type="local_git", product="p",
                     title="T", url="", score=0.8, chunk_index=0)  # 同 chunk,去重
    c = SearchResult(text="c", source_id="s2", source_type="local_git", product="p",
                     title="T2", url="", score=0.7, chunk_index=0)
    out = rrf_fuse([a], [b, c], k=60)
    assert len(out) == 2  # a/b 合并 + c
    assert out[0].source_id == "s1"  # a/b RRF 加分最高

def test_rrf_empty_inputs():
    from backend.retrieval.rrf import rrf_fuse
    assert rrf_fuse([], [], k=60) == []
```

- [ ] **Step 2: 跑失败 → 实现 rrf_fuse**

```python
# backend/retrieval/rrf.py
import dataclasses
from collections import defaultdict
from backend.retrieval.search import SearchResult

def rrf_fuse(hybrid: list[SearchResult], symbol: list[SearchResult],
             k: int = 60) -> list[SearchResult]:
    """RRF 融合两路结果,按 source_id+chunk_index 去重(score = 1/(k+rank) 累加)。"""
    scores: dict[tuple[str, int], float] = defaultdict(float)
    rep: dict[tuple[str, int], SearchResult] = {}
    for rank, r in enumerate(hybrid):
        key = (r.source_id, r.chunk_index)
        scores[key] += 1.0 / (k + rank + 1)
        if key not in rep:
            rep[key] = r
    for rank, r in enumerate(symbol):
        key = (r.source_id, r.chunk_index)
        scores[key] += 1.0 / (k + rank + 1)
        if key not in rep:
            rep[key] = r
    ordered = sorted(scores, key=lambda kk: -scores[kk])
    # 更新 score 为 RRF 融合分(rerank 用 text 不依赖,便于调试);frozen dataclass 用 replace
    return [dataclasses.replace(rep[kk], score=scores[kk]) for kk in ordered]
```

> `dataclasses.replace` 对真实 `SearchResult`(frozen dataclass)正确;Task 7 测试用 `_make_sr` 真实 SearchResult(非 MagicMock),与此一致。

- [ ] **Step 3: 跑通过 + commit**

```bash
pytest tests/retrieval/test_rrf.py -v
git add backend/retrieval/rrf.py tests/retrieval/test_rrf.py
git commit -m "feat(retrieval): RRF 融合(source_id+chunk_index 去重,k=60,score 更新)"
```

---

## Task 7: rag.py 管线插入符号召回 + RRF

**Files:**
- Modify: `backend/pipeline/rag.py`(检索段 313-323)
- Test: `tests/pipeline/test_rag.py`

**Interfaces:**
- Consumes: Task 5 `search_symbols` + Task 6 `rrf_fuse`
- Produces: `extract_query → [符号召回(extracted) ‖ rewrite_query → hybrid] → RRF → rerank`

- [ ] **Step 1: 写失败测试 —— 管线含符号召回**

```python
# tests/pipeline/test_rag.py(加新测例,复用现有 import RAGOrchestrator + _make_sr / _make_llm_response / _intent_response)
@pytest.mark.unit
async def test_rag_uses_symbol_recall_and_rrf():
    """符号召回(用 extract_query 输出)+ hybrid(search_query)RRF 融合送 rerank。"""
    from unittest.mock import AsyncMock, MagicMock
    searcher = MagicMock()
    # 用真实 SearchResult(_make_sr,非 MagicMock)—— rrf_fuse 的 dataclasses.replace 需 dataclass 实例
    a = _make_sr(text="a", source_id="s1")
    b = _make_sr(text="b", source_id="s2")
    searcher.search.return_value = [a]           # hybrid 返回 [a]
    searcher.search_symbols.return_value = [b]   # 符号召回返回 [b]
    reranker = MagicMock()
    reranker.rerank.return_value = [a, b]         # 透传,便于断言输入
    llm = AsyncMock()
    # classify_intent → extract_query → rewrite_query → generation(4 个 generate)
    llm.generate.side_effect = [
        _intent_response("product_question"),
        _make_llm_response("i2c battery"),          # extract_query 输出(符号召回用)
        _make_llm_response("i2c battery monitor"),  # rewrite_query 输出(hybrid 用)
        _make_llm_response("answer"),
    ]
    # 内联构造(参照 test_rag.py:114;不用 _build_orchestrator —— 它用 return_value 非 side_effect)
    rag = RAGOrchestrator(searcher, reranker, llm, system_prompt="test")
    await rag.answer("NE301 I2C 读电池监控", "widget")  # answer(query, channel) 位置参数
    # hybrid 用 search_query(rewrite 后),search_symbols 用 extracted(rewrite 前)
    searcher.search.assert_called_once()
    assert searcher.search.call_args.kwargs["query"] == "i2c battery monitor"
    searcher.search_symbols.assert_called_once()
    assert searcher.search_symbols.call_args.kwargs["query"] == "i2c battery"
    # rerank 收到 RRF 融合结果(两路)
    assert len(reranker.rerank.call_args.args[1]) == 2
```

> 类名 `RAGOrchestrator`(rag.py:89,非 `RAGPipeline`);helper `_make_sr`/`_make_llm_response`/`_intent_response` 是 test_rag.py 模块级(同文件复用,不用 import);`answer(query, channel)` 位置参数(参照行 115)。

- [ ] **Step 2: 跑失败 → 改 rag.py 检索段**

```python
# backend/pipeline/rag.py(约 313-323)
extracted = await extract_query(query, self._llm)  # 原始 query(符号召回用)
search_query = await rewrite_query(extracted, conversation_history, self._llm)

# hybrid(rewrite 后,语义优)+ 符号召回(extract_query 输出,绕过 rewrite 保标识符)
hybrid_results = self._searcher.search(
    query=search_query, alpha=self._alpha, limit=self._recall_limit,
    product_filter=product_filter, channel=channel)
symbol_results = self._searcher.search_symbols(
    query=extracted, limit=self._recall_limit,
    product_filter=product_filter, channel=channel)

from backend.retrieval.rrf import rrf_fuse
fused = rrf_fuse(hybrid_results, symbol_results, k=60)
reranked = self._reranker.rerank(search_query, fused, top_k=self._top_k)
```

- [ ] **Step 3: 跑通过 + 现有 rag 测试零回归**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test pytest tests/pipeline/test_rag.py -v`
Expected: PASS(现有 mock side_effect 链已是 classify→extract→rewrite→generate,本测试加符号召回断言;若现有测试断言 search 调用次数,需适配 search_symbols 新调用)

- [ ] **Step 4: Commit**

```bash
git add backend/pipeline/rag.py tests/pipeline/test_rag.py
git commit -m "feat(rag): 管线插入符号召回(extract_query)+ RRF 融合"
```

---

## Task 8: schema 迁移 + 全量重索引

**Files:**
- `scripts/migrate_add_symbol_props.py`(若增量加 property)或 `scripts/sync.py`(若重建)
- Test: 手动验证

- [ ] **Step 1: 验证 Weaviate v4 加 property 支持**

```bash
python -c "from weaviate.classes.config import Property; import weaviate; print([m for m in dir(weaviate.classes.config.Configure)])"
# 查 collection.config.add_property() 是否支持增量加字段不删数据
```

- [ ] **Step 2a(若 v4 支持增量):迁移脚本**

```python
# scripts/migrate_add_symbol_props.py
"""增量加 symbol Property(若 v4 支持),老 chunk symbol 空后续重索引补。"""
from weaviate.classes.config import Property, DataType
# col.config.add_property(Property(name="symbol_name", data_type=DataType.TEXT)) ...
```

- [ ] **Step 2b(若不支持):drop + sync 全量重建**

```bash
TEST_DATABASE_URL=... python scripts/sync.py  # ~2.5h(tesla-t4,deterministic UUID 幂等)
```

- [ ] **Step 3: 验证 symbol 字段有值**

```bash
curl -s http://localhost:8080/v1/graphql -X POST -H "Content-Type: application/json" \
  -d '{"query":"{ Aggregate { Document(where:{path:[\"symbol_name\"],operator:NotEqual,valueText:\"\"}) { meta { count } } } }"}'
# 期望:代码 chunk symbol_name 非空计数 > 0
```

- [ ] **Step 4: Commit(若写迁移脚本)**

```bash
git add scripts/migrate_add_symbol_props.py
git commit -m "chore(migrate): symbol Property 迁移(若 v4 增量支持)"
```

---

## Task 9: e2e 回归 + camelCase 验收

- [ ] **Step 1: 现有单测全绿**

Run: `TEST_DATABASE_URL=... pytest tests/pipeline/test_chunk_code.py tests/pipeline/test_ingest.py tests/retrieval/ tests/pipeline/test_rag.py -v`
Expected: 全 PASS(零回归)

- [ ] **Step 2: camelCase 符号命中 e2e**

```python
# tests/e2e/test_symbol_recall.py
def test_developer_question_hits_function():
    """开发者问题(NE301 I2C 读电池监控)命中精确函数,非整文件。"""
    # 索引 ne301 代码(含 battery_read_i2c)
    # 问 "NE301 怎么用 I2C 读电池监控寄存器"
    # 断言:rerank top 结果含 symbol_name == battery_read_i2c(或 i2c_read 类)
```

- [ ] **Step 3: e2e 回归(原 20 问不退步)**

Run: TS_record 20 问批量脚本,对比召回/答案。
Expected: 不退步 + 新增 5-10 代码层问题测例通过

- [ ] **Step 4: 非代码 query 不受干扰**

验证产品 / 文档问题召回不退步(符号召回对非代码 query 天然低分,RRF 不抬高)

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/test_symbol_recall.py
git commit -m "test(e2e): 符号召回 camelCase 命中 + 20 问零回归"
```

---

## Self-Review(plan 自审,写完跑)

1. **Spec 覆盖**:§3.1(Task 1)/ §3.2(Task 2)/ §3.3(Task 3)/ §3.4(Task 4-6)/ §3.5(Task 7)/ §4(Task 8)/ §6(Task 9)全覆盖 ✓
2. **Placeholder scan**:无 TBD/TODO;Weaviate v4 API 细节(query_properties / add_property)标注"实现时验证",非 placeholder ✓
3. **接口一致**:`_split_symbol_name` / `_build_props` / `_to_search_result` / `search_symbols` / `rrf_fuse` 跨 task 签名一致;RRF 去重 key `source_id + chunk_index` 全程一致 ✓
4. **可跑性**:测试用现有 `_make_weaviate_client()` helper(不假设 fixture);Task 3 测试补 `_collection=None`;Task 5 复用 Task 4 `_to_search_result`;Task 7 测试完整 mock(searcher/reranker/llm side_effect 链)✓
5. **依赖**:1→2,3;4 独立;5 依赖 3,4;6 独立;7 依赖 5,6;8 依赖 3;9 依赖全 ✓
6. **Global constraint**:ingest.py 冲突前置 + TEST_DATABASE_URL + 用现有 helper ✓

---

## Execution Handoff

- **Subagent-Driven**(推荐):每 Task 派 fresh subagent + 两阶段 review
- **前提**:tesla-t4 orchestrator 的 `ingest.py` 已 commit(避免冲突)。派 orchestrator 前确认:`git log backend/pipeline/ingest.py` 最新 commit 非 working-tree 未提交状态。
