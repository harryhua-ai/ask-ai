# 意图 4 分类迁移 + 场景路由 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将意图分类从 3 类(product_question/business_inquiry/off_topic)迁移到 4 类(commercial/product/support/off_topic),按意图路由 boost 桶召回,按意图叠加回答风格,并修复 stream_answer 缺符号检索的 parity 缺口。

**Architecture:** 抽 `_retrieve_and_fuse()` 共享 helper 让 answer/stream_answer 走同一检索(主 hybrid + 符号 BM25 + intent boost 桶 → 单次三路 RRF)。意图分类器改 4 类 + few-shot 区分 commercial/product 边界。system_prompt 从 channel 绑定扩展为 channel(base)+ intent(风格)正交叠加。intent 实时落库(answer 填 RAGAnswer.intent;stream complete 事件带 intent → routes.py 提取)。

**Tech Stack:** Python 3.12 / FastAPI / pytest(单元测试用 MagicMock/AsyncMock,不依赖 Weaviate)/ SQLAlchemy / YAML 配置。

**Spec:** `docs/superpowers/specs/2026-08-04-intent-routing-design.md`(双路审核已收敛)

## Global Constraints

- 测试用 `TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test`(conftest drop_all 会清开发库)
- Python venv: `.venv/bin/python`(项目根)
- RRF 公式必须 `1.0/(k+rank+1)` rank 从 0(与现有 rrf.py:38 逐位一致,向后兼容)
- `source_type` / `chunk_type` 是 TEXT 标量属性(非数组),Filter 用 `equal` + `Filter.any_of` 合并多值;`channel_visibility` 是 TEXT_ARRAY 用 `contains_any`
- fail-open → `"product"`(最常见、最安全)
- 商务问题过渡期拒答(REJECT_BUSINESS),P1#5 接 WooCommerce 后改作答
- 不碰 working tree 未提交的 query_rewrite.py / conftest.py / widget/* 改动(其他 context)

---

## File Structure

| 文件 | 责任 | 操作 |
|---|---|---|
| `backend/pipeline/intent.py` | 4 类分类 + few-shot prompt | 修改 |
| `backend/retrieval/search.py` | 新增 `search_bucket`(BM25 + source_type/chunk_type 过滤) | 修改 |
| `backend/retrieval/rrf.py` | `rrf_fuse` 扩展变长 `*result_lists` | 修改 |
| `backend/pipeline/rag.py` | 抽 `_retrieve_and_fuse` + 意图路由 + 风格叠加 + RAGAnswer.intent + stream complete intent | 修改 |
| `config/system_prompt.yaml` | 新增 `intent_styles` 段 | 修改 |
| `backend/main.py` | 加载 intent_styles + 传 RAGOrchestrator | 修改 |
| `backend/api/routes.py` | complete 事件提取 intent + Conversation 写 intent_tag | 修改 |
| `backend/services/intent_tagger.py` | INTENT_CATEGORIES 改 4 类 | 修改 |
| `scripts/migrate_intent_tag_8to4.py` | 历史 8 类 → 4 类一次性迁移 | 新增 |
| `tests/pipeline/test_intent.py` | 4 类分类测试 | 修改 |
| `tests/retrieval/test_search.py` | search_bucket 测试 | 修改 |
| `tests/retrieval/test_rrf.py` | variadic + 向后兼容测试 | 修改 |
| `tests/pipeline/test_rag.py` | 路由 + parity + intent 落库测试 | 修改 |

---

## Task 1: rrf_fuse 扩展变长(向后兼容)

**Files:**
- Modify: `backend/retrieval/rrf.py`
- Test: `tests/retrieval/test_rrf.py`

**Interfaces:**
- Produces: `rrf_fuse(*result_lists: list[SearchResult], k: int = 60) -> list[SearchResult]`(N 路,空列表跳过,全空 → [])

- [ ] **Step 1: 写失败测试(variadic + 向后兼容)**

追加到 `tests/retrieval/test_rrf.py` 末尾:

```python
def test_rrf_fuse_variadic_three_lists():
    """三列表融合:每个 chunk 的分数 = 三路 Σ 1/(k+rank+1)。"""
    a = _make_sr(source_id="doc/a", chunk_index=0)
    b = _make_sr(source_id="doc/b", chunk_index=0)
    c = _make_sr(source_id="doc/c", chunk_index=0)
    out = rrf_fuse([a], [b], [c], k=60)
    assert len(out) == 3
    # a 在三路均 rank 0:3 * 1/61
    assert out[0].source_id == "doc/a"
    assert abs(out[0].score - 3 * (1.0 / (60 + 0 + 1))) < 1e-9


def test_rrf_fuse_variadic_skips_empty_lists():
    """空列表自动跳过,不贡献分数。"""
    a = _make_sr(source_id="doc/a", chunk_index=0)
    b = _make_sr(source_id="doc/b", chunk_index=0)
    out = rrf_fuse([a], [], [b], k=60)
    assert len(out) == 2


def test_rrf_fuse_variadic_all_empty():
    """全空 → []。"""
    assert rrf_fuse([], [], [], k=60) == []


def test_rrf_fuse_two_args_backward_compatible_score():
    """2 参调用分数与公式 1/(k+rank+1) 逐位一致(向后兼容语义)。"""
    a = _make_sr(source_id="doc/a", chunk_index=0)
    out = rrf_fuse([a], [], k=60)
    assert len(out) == 1
    assert abs(out[0].score - 1.0 / (60 + 0 + 1)) < 1e-9
```

(若 `test_rrf.py` 无 `_make_sr` helper,参考其现有 `SearchResult(...)` 直接构造方式;或加一个模块级 helper。)

- [ ] **Step 2: 运行测试,确认失败**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest tests/retrieval/test_rrf.py -x -q
```

Expected: FAIL(`rrf_fuse()` 现为 2 位置参数,3 参调用 TypeError)

- [ ] **Step 3: 实现 variadic rrf_fuse**

替换 `backend/retrieval/rrf.py` 的 `rrf_fuse` 函数体(保留 docstring,更新签名与公式说明):

```python
def rrf_fuse(
    *result_lists: list[SearchResult],
    k: int = 60,
) -> list[SearchResult]:
    """N 路 RRF 融合(变长参数),按 ``source_id + chunk_index`` 去重。

    对每路结果按出现顺序赋 rank(从 0 起),累加 ``1/(k + rank + 1)`` 到对应
    chunk 的融合分;同 chunk 出现在多路时分数相加(去重,保留首次出现的
    :class:`SearchResult` 作为代表)。空列表自动跳过。最终按融合分降序返回,
    代表结果的 ``score`` 更新为融合分。

    Args:
        *result_lists: 任意多路检索结果(hybrid / symbol / boost bucket ...)。
        k: RRF 平滑常数(默认 60);越大对 rank 差异越不敏感。

    Returns:
        融合去重后的 :class:`SearchResult` 列表(按融合分降序);所有路均空返回 ``[]``。
    """
    scores: dict[tuple[str, int], float] = defaultdict(float)
    rep: dict[tuple[str, int], SearchResult] = {}
    for lst in result_lists:
        for rank, r in enumerate(lst):
            key = (r.source_id, r.chunk_index)
            scores[key] += 1.0 / (k + rank + 1)
            if key not in rep:
                rep[key] = r
    if not scores:
        return []
    ordered = sorted(scores, key=lambda kk: -scores[kk])
    return [dataclasses.replace(rep[kk], score=scores[kk]) for kk in ordered]
```

同步更新模块 docstring 第 4 行的 `1/(k+rank)` 为 `1/(k+rank+1)`(代码 docstring bug,顺手修)。

- [ ] **Step 4: 运行全部 rrf 测试,确认通过**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest tests/retrieval/test_rrf.py -q
```

Expected: PASS(含原有 + 4 新)

- [ ] **Step 5: Commit**

```bash
git add backend/retrieval/rrf.py tests/retrieval/test_rrf.py
git commit -m "feat(rrf): rrf_fuse 扩展变长 *result_lists(单次 N 路,向后兼容)"
```

---

## Task 2: search_bucket 新增(BM25 + source_type/chunk_type 过滤)

**Files:**
- Modify: `backend/retrieval/search.py`(新增方法,紧随 `search_symbols`)
- Test: `tests/retrieval/test_search.py`

**Interfaces:**
- Consumes: `SearchResult`、`_to_search_result`(Task 前置存在)
- Produces: `HybridSearcher.search_bucket(query, source_types, chunk_types, limit, product_filter, channel) -> list[SearchResult]`

- [ ] **Step 1: 写失败测试**

追加到 `tests/retrieval/test_search.py`:

```python
def test_search_bucket_empty_query_returns_empty():
    """空 query → [](不调 Weaviate)。"""
    searcher = HybridSearcher(MagicMock(), MagicMock())
    assert searcher.search_bucket("", source_types=["filesystem"]) == []


def test_search_bucket_no_filters_returns_empty():
    """source_types 和 chunk_types 都 None → [](无过滤桶无意义)。"""
    searcher = HybridSearcher(MagicMock(), MagicMock())
    assert searcher.search_bucket("cellular fail", source_types=None, chunk_types=None) == []


def test_search_bucket_passes_source_type_filter():
    """source_types 构造 any_of(equal) 过滤并传给 bm25。"""
    client = MagicMock()
    collection = MagicMock()
    client.collections.get.return_value = collection
    collection.query.bm25.return_value = MagicMock(objects=[])
    searcher = HybridSearcher(client, MagicMock())
    searcher.search_bucket("query", source_types=["filesystem"])
    # bm25 被调用
    assert collection.query.bm25.called
    kwargs = collection.query.bm25.call_args.kwargs
    assert kwargs["query_properties"] == ["text"]


def test_search_bucket_passes_chunk_type_filter():
    """chunk_types 构造 any_of(equal) 过滤。"""
    client = MagicMock()
    collection = MagicMock()
    client.collections.get.return_value = collection
    collection.query.bm25.return_value = MagicMock(objects=[])
    searcher = HybridSearcher(client, MagicMock())
    searcher.search_bucket("query", chunk_types=["paragraph", "heading"])
    assert collection.query.bm25.called
```

- [ ] **Step 2: 运行测试,确认失败**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest tests/retrieval/test_search.py -k search_bucket -q
```

Expected: FAIL(`HybridSearcher` 无 `search_bucket` 属性)

- [ ] **Step 3: 实现 search_bucket**

在 `backend/retrieval/search.py` 的 `search_symbols` 方法之后(类的内部),新增:

```python
def search_bucket(
    self,
    query: str,
    source_types: list[str] | None = None,
    chunk_types: list[str] | None = None,
    limit: int = 30,
    product_filter: str | None = None,
    channel: str | None = None,
) -> list[SearchResult]:
    """BM25 召回(对 text 字段),按 source_type / chunk_type 过滤(boost 桶)。

    用于 per-intent 软路由:与主 hybrid 结果 RRF 融合,让 intent 相关 source
    (如 support 案例 filesystem、产品文档 docs)获得加权。query 用 extract_query
    输出(绕 rewrite,保关键词)。

    source_type / chunk_type 是 TEXT 标量属性(非数组),用 ``equal`` + ``Filter.any_of``
    合并多值(避免 contains_any 对多 token 值如 ``local_git`` 分词静默失效)。

    Args:
        query: 查询文本(通常为 extract_query 输出)。空 / 纯空白返回 ``[]``。
        source_types: 可选 source_type 白名单(如 ``["filesystem"]``)。
        chunk_types: 可选 chunk_type 白名单(如 ``["paragraph","heading","list","table"]``)。
            **source_types 和 chunk_types 都为 None 时返回 ``[]``**(无过滤桶无意义)。
        limit: 返回结果数上限。
        product_filter: 可选产品名过滤(boost 桶通常跨产品,调用方一般不传)。
        channel: 可选渠道过滤;非空时附加 channel_visibility contains_any。

    Returns:
        :class:`SearchResult` 列表。
    """
    if not query or not query.strip():
        logger.info("空 query,跳过 boost 桶 BM25 检索")
        return []
    if not source_types and not chunk_types:
        logger.info("boost 桶无 source_types/chunk_types 过滤,跳过(无意义)")
        return []

    collection = self._client.collections.get(self._class_name)
    from weaviate.classes.query import Filter

    filters_list: list = []
    if source_types:
        # TEXT 标量属性:equal + any_of 合并(OR 语义)
        filters_list.append(
            Filter.any_of(
                [Filter.by_property("source_type").equal(st) for st in source_types]
            )
        )
    if chunk_types:
        filters_list.append(
            Filter.any_of(
                [Filter.by_property("chunk_type").equal(ct) for ct in chunk_types]
            )
        )
    if product_filter:
        filters_list.append(Filter.by_property("product").equal(product_filter))
    if channel:
        filters_list.append(
            Filter.by_property("channel_visibility").contains_any([channel])
        )

    filters = (
        filters_list[0]
        if len(filters_list) == 1
        else Filter.all_of(filters_list)
    )

    resp = collection.query.bm25(
        query=query,
        query_properties=["text"],
        limit=limit,
        filters=filters,
        return_properties=[
            "source_id", "source_type", "product", "title", "url", "text",
            "chunk_index", "chunk_type", "doc_section", "channel_visibility",
            "symbol_name", "symbol_signature", "branch",
        ],
    )
    return [self._to_search_result(o) for o in resp.objects]
```

- [ ] **Step 4: 运行测试,确认通过**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest tests/retrieval/test_search.py -k search_bucket -q
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest tests/retrieval/test_search.py -q
```

Expected: PASS(4 新 + 原有全绿)

- [ ] **Step 5: Commit**

```bash
git add backend/retrieval/search.py tests/retrieval/test_search.py
git commit -m "feat(search): search_bucket BM25 召回(source_type/chunk_type 过滤,boost 桶)"
```

---

## Task 3: intent.py 4 分类迁移

**Files:**
- Modify: `backend/pipeline/intent.py`
- Test: `tests/pipeline/test_intent.py`

**Interfaces:**
- Produces: `VALID_CATEGORIES = ("commercial","product","support","off_topic")`,fail-open → `"product"`

- [ ] **Step 1: 写失败测试(替换/追加 test_intent.py)**

更新现有测试的 category 断言 + 加 commercial/product 边界 case:

```python
@pytest.mark.unit
async def test_classify_product_question_short():
    llm = _make_llm('{"category": "product", "reason": "产品咨询"}')
    result = await classify_intent("NE301怎么配置WiFi", llm)
    assert result.category == "product"


@pytest.mark.unit
async def test_classify_support():
    """故障排查/报错 → support。"""
    llm = _make_llm('{"category": "support", "reason": "故障排查"}')
    result = await classify_intent("NE101 蜂窝网络注册失败 CEREG 报错", llm)
    assert result.category == "support"


@pytest.mark.unit
async def test_classify_commercial():
    """纯价格/采购 → commercial。"""
    llm = _make_llm('{"category": "commercial", "reason": "价格咨询"}')
    result = await classify_intent("NE301的价格是多少?批量采购有折扣吗?", llm)
    assert result.category == "commercial"


@pytest.mark.unit
async def test_classify_product_capability_not_commercial():
    """能力/方案/选型 → product(非 commercial)。#15/#20 关键边界。"""
    llm = _make_llm('{"category": "product", "reason": "方案咨询"}')
    result = await classify_intent("NE301 支持热成像入侵检测吗?有演示视频吗?", llm)
    assert result.category == "product"


@pytest.mark.unit
async def test_classify_off_topic():
    llm = _make_llm('{"category": "off_topic", "reason": "闲聊"}')
    result = await classify_intent("今天天气怎么样?", llm)
    assert result.category == "off_topic"


@pytest.mark.unit
async def test_classify_fail_open_to_product():
    """异常 fail-open → product(非 product_question)。"""
    llm = AsyncMock()
    llm.generate.side_effect = RuntimeError("LLM down")
    result = await classify_intent("NE301 配置", llm)
    assert result.category == "product"


@pytest.mark.unit
async def test_classify_unknown_category_falls_back_to_product():
    """未知 category → product。"""
    llm = _make_llm('{"category": "unknown_cat", "reason": "x"}')
    result = await classify_intent("test", llm)
    assert result.category == "product"
```

(若 test_intent.py 有 `_make_llm` helper 沿用;否则加一个返回 AsyncMock 的 helper,`generate` 返回带 `.content` 的 mock。)

- [ ] **Step 2: 运行测试,确认失败**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest tests/pipeline/test_intent.py -q
```

Expected: FAIL(VALID_CATEGORIES 仍含 product_question)

- [ ] **Step 3: 实现 4 分类**

更新 `backend/pipeline/intent.py`:

```python
VALID_CATEGORIES = ("commercial", "product", "support", "off_topic")

_INTENT_PROMPT = """你是 CamThink 意图分类助手。判断用户输入属于以下哪类:

- commercial: 纯价格/采购/报价/渠道/库存/促销/商务合作(不涉及技术方案)
- product: CamThink 产品功能/参数/规格/选型/方案/竞品对比/适配/演示能力咨询
  (含"能否做 XX""XX 场景怎么选""有没有 XX 能力/视频"等方案选型问题)
- support: 故障排查/报错/集成/二次开发/代码/调试/寄存器/固件(L1-L3,含开发者)
- off_topic: 与 CamThink 产品无关的闲聊/天气/通用知识/纯竞品咨询

## 示例
- "NE301 多少钱 / 怎么采购" → commercial
- "NE301 支持热成像入侵检测吗 / 有演示视频吗" → product
- "建筑工地太阳能场景怎么选型" → product
- "NE101 蜂窝网络注册失败 / CEREG 报错" → support
- "Python 怎么读串口(与 CamThink 无关)" → off_topic

只输出 JSON: {{"category": "类别名", "reason": "简短理由"}}

## 用户输入
{query}
"""
```

`classify_intent` 中所有 `"product_question"` 替换为 `"product"`(3 处:默认值 / fail-open 默认值 / 未知 category 回退)。更新模块 docstring 的分类说明。

- [ ] **Step 4: 运行测试,确认通过**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest tests/pipeline/test_intent.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/intent.py tests/pipeline/test_intent.py
git commit -m "feat(intent): 4 分类迁移 commercial/product/support/off_topic + few-shot"
```

---

## Task 4: rag.py 抽 _retrieve_and_fuse + 意图路由 + RAGAnswer.intent + stream parity

**Files:**
- Modify: `backend/pipeline/rag.py`
- Test: `tests/pipeline/test_rag.py`

**Interfaces:**
- Consumes: Task 1 `rrf_fuse` variadic、Task 2 `search_bucket`、Task 3 4 类 intent
- Produces: `RAGOrchestrator._retrieve_and_fuse()`、`RAGAnswer.intent`、`INTENT_BOOST_FILTERS`、stream complete 事件含 `"intent"`

- [ ] **Step 1: 写失败测试(追加 test_rag.py)**

```python
@pytest.mark.unit
async def test_rag_routes_commercial_to_reject_business():
    """commercial 意图 → 检索前 REJECT_BUSINESS,不调 searcher。"""
    rag, searcher, reranker, llm = _build_orchestrator()
    llm.generate = AsyncMock(side_effect=[
        # classify_intent 返回 commercial
        _make_llm_response('{"category": "commercial", "reason": "价格"}'),
    ])
    result = await rag.answer("NE301 价格多少", channel="widget")
    assert "销售团队" in result.answer
    assert result.is_answered is False
    searcher.search.assert_not_called()


@pytest.mark.unit
async def test_rag_support_intent_triggers_search_bucket():
    """support 意图 → search_bucket(source_types=['filesystem']) 被调。"""
    sr = _make_sr()
    rag, searcher, reranker, llm = _build_orchestrator(searcher_results=[sr])
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    # classify → support;extract/rewrite 正常;generate 给答案
    llm.generate = AsyncMock(side_effect=[
        _make_llm_response('{"category": "support", "reason": "故障"}'),
        _make_llm_response("extracted"),
        _make_llm_response("rewritten"),
        _make_llm_response("answer"),
    ])
    await rag.answer("NE101 蜂窝网络注册失败", channel="widget")
    searcher.search_bucket.assert_called_once()
    kwargs = searcher.search_bucket.call_args.kwargs
    assert kwargs.get("source_types") == ["filesystem"]


@pytest.mark.unit
async def test_rag_product_intent_triggers_docs_bucket():
    """product 意图 → search_bucket(chunk_types=docs) 被调。"""
    sr = _make_sr()
    rag, searcher, reranker, llm = _build_orchestrator(searcher_results=[sr])
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    llm.generate = AsyncMock(side_effect=[
        _make_llm_response('{"category": "product", "reason": "产品"}'),
        _make_llm_response("extracted"),
        _make_llm_response("rewritten"),
        _make_llm_response("answer"),
    ])
    await rag.answer("NE301 功能", channel="widget")
    searcher.search_bucket.assert_called_once()
    assert searcher.search_bucket.call_args.kwargs.get("chunk_types") == [
        "paragraph", "heading", "list", "table"
    ]


@pytest.mark.unit
async def test_rag_answer_carries_intent_field():
    """RAGAnswer.intent 正确填充(product)。"""
    sr = _make_sr()
    rag, searcher, reranker, llm = _build_orchestrator(searcher_results=[sr])
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    llm.generate = AsyncMock(side_effect=[
        _make_llm_response('{"category": "product", "reason": "x"}'),
        _make_llm_response("e"),
        _make_llm_response("r"),
        _make_llm_response("answer"),
    ])
    result = await rag.answer("NE301 功能", channel="widget")
    assert result.intent == "product"


@pytest.mark.unit
async def test_rag_stream_complete_event_carries_intent():
    """stream_answer complete 事件含 'intent' 字段。"""
    sr = _make_sr()
    rag, searcher, reranker, llm = _build_orchestrator(searcher_results=[sr])
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    llm.generate = AsyncMock(side_effect=[
        _make_llm_response('{"category": "support", "reason": "x"}'),
        _make_llm_response("e"),
        _make_llm_response("r"),
    ])
    llm.stream = AsyncMock(return_value=iter(["ans"]))

    events = []
    async for ev in rag.stream_answer("NE101 故障", channel="widget"):
        events.append(json.loads(ev))

    complete = [e for e in events if e["type"] == "complete"][0]
    assert complete["intent"] == "support"


@pytest.mark.unit
async def test_rag_stream_answer_uses_symbol_and_bucket_parity():
    """stream_answer 也调 search_symbols + search_bucket(与 answer parity)。"""
    sr = _make_sr()
    rag, searcher, reranker, llm = _build_orchestrator(searcher_results=[sr])
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    llm.generate = AsyncMock(side_effect=[
        _make_llm_response('{"category": "product", "reason": "x"}'),
        _make_llm_response("e"),
        _make_llm_response("r"),
    ])
    llm.stream = AsyncMock(return_value=iter(["ans"]))
    async for _ in rag.stream_answer("NE301", channel="widget"):
        pass
    searcher.search_symbols.assert_called_once()
    searcher.search_bucket.assert_called_once()
```

- [ ] **Step 2: 运行测试,确认失败**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest tests/pipeline/test_rag.py -k "commercial or support_intent or product_intent or intent_field or complete_event or parity" -q
```

Expected: FAIL

- [ ] **Step 3: 实现 rag.py 改造**

**3a. 加 INTENT_BOOST_FILTERS + RAGAnswer.intent**:

文件顶部(`SOURCE_LABELS` 后)加:

```python
INTENT_BOOST_FILTERS: dict[str, dict] = {
    "support": {"source_types": ["filesystem"]},
    "product": {"chunk_types": ["paragraph", "heading", "list", "table"]},
    # "commercial": {"source_types": ["woocommerce"]},  # P1#5 启用
}
```

`RAGAnswer` dataclass 加字段 `intent: str`(在 `response_time_ms` 后)。

**3b. 加 `_retrieve_and_fuse` 方法**(类内,`_build_messages` 前):

```python
async def _retrieve_and_fuse(
    self,
    extracted: str,
    search_query: str,
    intent_category: str,
    *,
    product_filter: str | None,
    channel: str,
) -> list[SearchResult]:
    """统一检索 + 三路 RRF 融合(answer / stream_answer 共用,保证 parity)。

    主 hybrid(search_query) + 符号 BM25(extracted) + intent boost 桶(extracted)
    → 单次 rrf_fuse 三路融合。任一路异常 / 为空均降级,不中断主流程。
    """
    results = self._searcher.search(
        query=search_query, alpha=self._alpha, limit=self._recall_limit,
        product_filter=product_filter, channel=channel,
    )

    symbol_results: list[SearchResult] = []
    try:
        symbol_results = self._searcher.search_symbols(
            query=extracted, limit=self._recall_limit,
            product_filter=product_filter, channel=channel,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("符号召回失败,降级:%s", str(exc)[:200])

    bucket_results: list[SearchResult] = []
    bucket_cfg = INTENT_BOOST_FILTERS.get(intent_category)
    if bucket_cfg:
        try:
            # boost 桶跨产品(support 案例存为 product="knowledge"),不透传 product_filter
            bucket_results = self._searcher.search_bucket(
                query=extracted, limit=self._recall_limit,
                channel=channel, **bucket_cfg,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("boost 桶召回失败,降级:%s", str(exc)[:200])

    from backend.retrieval.rrf import rrf_fuse
    try:
        return rrf_fuse(results, symbol_results, bucket_results, k=60)
    except Exception as exc:  # noqa: BLE001
        logger.warning("RRF 融合失败,降级 hybrid 单路:%s", str(exc)[:200])
        return results
```

**3c. `_build_messages` 加 intent 参数 + 风格叠加**:

```python
def _build_messages(
    self, query, context, language, history, channel="widget", intent="product",
):
    base = self._channel_customizations.get(channel, self._system_prompt)
    style = self._intent_styles.get(intent, "")
    system_prompt = f"{base}\n\n{style}" if style else base
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    ...  # 其余不变
```

**3d. `__init__` 加 `intent_styles` 参数**:

```python
def __init__(self, ..., intent_styles: dict[str, str] | None = None):
    ...
    self._intent_styles = intent_styles or {}
```

**3e. `answer()` 改造**(替换意图分支 + 检索段 + RAGAnswer 构造):

意图分支:`business_inquiry` → `commercial`(拒答 REJECT_BUSINESS);`off_topic` 不变。
`effective_min = 1 if intent.category in ("product", "support") else self._min_results`
检索段替换为:
```python
fused = await self._retrieve_and_fuse(
    extracted, search_query, intent.category,
    product_filter=product_filter, channel=channel,
)
reranked = self._reranker.rerank(search_query, fused, top_k=self._top_k)
```
`_build_messages(..., intent=intent.category)`。
所有 `RAGAnswer(...)` 构造加 `intent=intent.category`(或拒答时 `intent=intent.category`)。

**3f. `stream_answer()` 改造**(同 answer,但 complete 事件加 `"intent": intent.category`):

所有 complete 事件的 JSON dict 加 `"intent": intent.category`。检索段同样调 `_retrieve_and_fuse`。

- [ ] **Step 4: 运行 rag 全测试,确认通过**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest tests/pipeline/test_rag.py -q
```

Expected: PASS(原有 + 6 新;原有测试若断言 `business_inquiry` 需同步改 `commercial`)

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/rag.py tests/pipeline/test_rag.py
git commit -m "feat(rag): _retrieve_and_fuse 共享 helper + 4 类路由 + stream parity + RAGAnswer.intent"
```

---

## Task 5: system_prompt.yaml intent_styles + main.py 加载

**Files:**
- Modify: `config/system_prompt.yaml`
- Modify: `backend/main.py`

- [ ] **Step 1: yaml 加 intent_styles 段**

在 `config/system_prompt.yaml` 末尾追加:

```yaml
intent_styles:
  commercial: |
    ## 回答风格(商务)
    聚焦价格/采购/渠道/库存;引导联系销售;不展开技术细节。
  product: |
    ## 回答风格(产品方案)
    选型/比对给推荐+理由;方案类给组合建议;参数规格精确引用。
  support: |
    ## 回答风格(技术支持)
    保留代码/寄存器/接口/错误码细节;故障排查给分步;定位链路完整。
```

- [ ] **Step 2: main.py 加载 intent_styles 并传 RAGOrchestrator**

在 `backend/main.py` 构造 `RAGOrchestrator` 处(约 291 行):

```python
prompt_config = load_yaml_config(settings.config_dir / "system_prompt.yaml")
intent_styles = prompt_config.get("intent_styles", {})
...
app.state.rag = RAGOrchestrator(
    ...,
    system_prompt=system_prompt,
    channel_customizations=channel_customizations,
    intent_styles=intent_styles,  # 新增
)
```

- [ ] **Step 3: 启动冒烟测试(确认无 import / 配置错误)**

```bash
.venv/bin/python -c "from backend.pipeline.rag import RAGOrchestrator, INTENT_BOOST_FILTERS; print('OK', list(INTENT_BOOST_FILTERS))"
.venv/bin/python -c "import yaml; c=yaml.safe_load(open('config/system_prompt.yaml')); print('styles:', list(c.get('intent_styles',{})))"
```

Expected: 两个都 OK,styles 含 commercial/product/support

- [ ] **Step 4: Commit**

```bash
git add config/system_prompt.yaml backend/main.py
git commit -m "feat(config): intent_styles 分风格 prompt + main.py 加载传参"
```

---

## Task 6: routes.py stream intent 提取 + Conversation 写入

**Files:**
- Modify: `backend/api/routes.py`

- [ ] **Step 1: 读 routes.py 找 complete 事件解析处 + Conversation 构造处**

```bash
grep -n "complete\|is_answered\|Conversation(\|intent" backend/api/routes.py | head -20
```

- [ ] **Step 2: 在 complete 事件解析处提取 intent**

在解析 complete 事件(json.loads)的位置,加 `intent = data.get("intent")`(与 `is_answered` / `language` / `elapsed` 同处提取)。

- [ ] **Step 3: Conversation 构造加 intent_tag**

```python
conv = Conversation(
    id=uuid.UUID(conversation_id),
    question=masked_message,
    answer=full_answer,
    channel=req.channel,
    language=language,
    sources=sources,
    is_answered=is_answered,
    response_time_ms=elapsed,
    intent_tag=intent,  # 新增(stream 路径实时落库)
)
```

- [ ] **Step 4: 冒烟测试**

```bash
.venv/bin/python -c "from backend.api.routes import router; print('routes import OK')"
```

- [ ] **Step 5: Commit**

```bash
git add backend/api/routes.py
git commit -m "feat(routes): stream complete 事件提取 intent + Conversation.intent_tag 实时落库"
```

---

## Task 7: intent_tagger.py 改 4 类 + 历史 8→4 迁移脚本

**Files:**
- Modify: `backend/services/intent_tagger.py`
- Create: `scripts/migrate_intent_tag_8to4.py`

- [ ] **Step 1: intent_tagger INTENT_CATEGORIES 改 4 类**

```python
INTENT_CATEGORIES = ["commercial", "product", "support", "off_topic"]

INTENT_PROMPT = f"""请分析以下用户问题,从这些意图类别中选择最合适的一个:
{chr(10).join(f"- {c}" for c in INTENT_CATEGORIES)}

- commercial: 价格/采购/渠道/库存/促销
- product: 产品功能/参数/选型/方案/演示能力
- support: 故障排查/集成/代码/调试
- off_topic: 与 CamThink 无关的闲聊/通用知识

只返回类别名称(不解释、不加引号)。

用户问题:{{question}}"""
```

- [ ] **Step 2: 写迁移脚本 `scripts/migrate_intent_tag_8to4.py`**

```python
"""历史 intent_tag 8 类 → 4 类一次性迁移(幂等)。

用法:
    python scripts/migrate_intent_tag_8to4.py [--dry-run]
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from backend.config import load_settings
from backend.db.session import get_engine

MAPPING = {
    "product_spec": "product",
    "getting_started": "product",
    "comparison": "product",
    "documentation": "product",
    "tech_support": "support",
    "api_reference": "support",
    "pricing": "commercial",
    "other": "off_topic",
}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    engine = get_engine(load_settings().postgres_dsn)
    total = 0
    async with engine.begin() as conn:
        for old, new in MAPPING.items():
            if args.dry_run:
                result = await conn.execute(
                    text("SELECT count(*) FROM conversations WHERE intent_tag = :t"),
                    {"t": old},
                )
                n = result.scalar() or 0
                print(f"[dry-run] {old} → {new}: {n} rows")
            else:
                result = await conn.execute(
                    text("UPDATE conversations SET intent_tag = :new WHERE intent_tag = :old"),
                    {"new": new, "old": old},
                )
                n = result.rowcount or 0
                print(f"{old} → {new}: {n} rows updated")
            total += n
    await engine.dispose()
    print(f"\n总计: {total} 行{'(dry-run)' if args.dry_run else '迁移完成'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 3: 冒烟测试**

```bash
.venv/bin/python -c "from backend.services.intent_tagger import INTENT_CATEGORIES; print(INTENT_CATEGORIES)"
.venv/bin/python scripts/migrate_intent_tag_8to4.py --dry-run
```

Expected: `[commercial, product, support, off_topic]` + dry-run 输出各行计数

- [ ] **Step 4: Commit**

```bash
git add backend/services/intent_tagger.py scripts/migrate_intent_tag_8to4.py
git commit -m "feat(tagger): 4 类改造 + 历史 8→4 迁移脚本(幂等)"
```

---

## Task 8: admin Conversations intent 标签 + 全量回归

**Files:**
- Modify: `admin/src/pages/Conversations.tsx`(若 intent 标签选项硬编码)

- [ ] **Step 1: 检查 admin intent 标签来源**

```bash
grep -rn "product_question\|business_inquiry\|product_spec\|tech_support\|intent_tag\|INTENT" admin/src/ | head -10
```

- [ ] **Step 2: 若硬编码旧标签,改 4 类**

把 intent 过滤选项改为 `commercial / product / support / off_topic`(若 admin 从后端动态拉标签则跳过此步)。

- [ ] **Step 3: 全量后端测试回归**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest tests/pipeline tests/retrieval -q
```

Expected: PASS(若 test_query_rewrite 因 working tree 未提交改动失败,记录但不在本 plan 范围)

- [ ] **Step 4: Commit(若有 admin 改动)**

```bash
git add admin/src/pages/Conversations.tsx 2>/dev/null && git commit -m "feat(admin): Conversations intent 标签改 4 类" || echo "admin 无需改(动态标签)"
```

---

## Task 9: e2e 回归验证

**Files:**
- No code change;run existing e2e

- [ ] **Step 1: 重启 backend(加载新代码)**

确认 backend 进程用了最新代码(若 long-running 进程需重启)。`scripts/e2e_real.py` 打 `http://localhost:8000/api/ask`。

- [ ] **Step 2: 跑 e2e 20 问**

```bash
.venv/bin/python scripts/e2e_real.py --limit 20 --out /tmp/e2e_intent_routing.json
.venv/bin/python scripts/e2e_real_review.py /tmp/e2e_intent_routing.json --out /tmp/e2e_intent_routing_review.md
```

- [ ] **Step 3: 核验关键 case**

- **#6**:答案根因含 SIM/运营商/CEREG(非"reset 清 APN");sources 含 support 案例文档
- **#15/#20**:不误拒 REJECT_BUSINESS(作为 product 答,或基于资料的合理拒答)
- **#10/#14**:零回归
- **#1–#9/#11–#13/#16–#19**:零回归

- [ ] **Step 4: 记录结果,若 #6/#15/#20 改善则完成**

在 PR 描述或 commit body 记录 e2e 对比(before/after)。

---

## Self-Review Checklist(实现完成后)

- [ ] `VALID_CATEGORIES` 4 类,fail-open → product
- [ ] rrf_fuse variadic + 2 参向后兼容 + 公式逐位一致
- [ ] search_bucket TEXT 标量用 equal+any_of(非 contains_any)
- [ ] _retrieve_and_fuse 被 answer + stream_answer 共用(parity)
- [ ] RAGAnswer.intent + stream complete 事件 intent + Conversation.intent_tag
- [ ] intent_styles yaml 驱动 + main.py 传参
- [ ] intent_tagger 4 类 + 迁移脚本幂等
- [ ] 全量单测绿 + e2e #6/#15/#20 改善 + 零回归
