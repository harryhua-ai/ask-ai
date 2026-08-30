# 函数级符号检索 — 方案 1 设计

- **日期**:2026-08-03(修正版,基于独立复审)
- **状态**:待用户审阅
- **关联**:ask-ai 总体设计 §5 / §12.3、`2026-07-31-codebase-analysis-design.md`

---

## 1. 背景

ask-ai 需要函数级精确召回(开发者代码层问题,如"NE301 怎么用 I2C 读电池监控寄存器""mm-iot-sdk 的 AWS OTA 怎么集成")。

**代码现状(核对源码)**:
- **意图系统**(`backend/pipeline/intent.py:18`):`VALID_CATEGORIES = ("product_question", "business_inquiry", "off_topic")`。`product_question` 覆盖 SDK / 配置 / 故障排查 / 开发者代码问题(intent.py:22);`off_topic` 与 `business_inquiry` 在检索**前**就被拒(`rag.py:291-310`),**只有 `product_question` 到达检索层**
- **规划中的迁移**:product_question → commercial/product/support/off_topic(memory + 总体设计 §5);迁移后 `support` 取代 product_question 覆盖开发者代码层。本 spec 用代码现状名 `product_question`,迁移后同理适用
- **函数级分块已实现**(`backend/pipeline/chunk_code.py`,Phase 1.5):tree-sitter AST 按 函数/类/方法/结构体 切,每个 code chunk = 一个函数级单元,symbol/signature 已提取并拼到 text 前缀
- **真正缺口**:symbol 未独立成可检索字段 → 符号精确匹配弱

本 spec 是「方案 1」:symbol 元数据独立化 + 符号 BM25 + RRF。**不做 SCIP**(方案 2,跨文件引用/类型,§7 按需)。

## 2. 目标 / 非目标

**目标**:
1. symbol 元数据(symbol_name / signature / node_type + **拆分版 symbol_tokens**)作为独立字段(Chunk + Weaviate schema)
2. 独立符号 BM25 召回(**用原始 query,绕过 rewrite**)+ 与 hybrid 通过 RRF 融合 → rerank
3. 覆盖所有代码语言(Python / C / C++ / Rust / **TS / TSX** / JS / Bash),含 camelCase / PascalCase 符号

**非目标**(方案 2 SCIP,§7 按需):
- 跨文件引用("谁调用 foo")、类型层级 / 结构体字段枚举

## 3. 设计

### 3.1 Chunk dataclass 加字段(`backend/pipeline/chunk.py:56`)

```python
symbol_name: str = ""           # 函数/类/方法/结构体名;文档 chunk 为空
symbol_signature: str = ""      # 节点首行签名(最长 80 字符)
symbol_node_type: str = ""      # tree-sitter 节点类型(如 function_definition);本期元数据,不参与召回,供未来按节点类型过滤/展示
symbol_tokens: str = ""         # 拆分版(camelCase/PascalCase/snake_case → 空格小写),供 BM25 分词
```

默认空串,兼容文档 chunk(`chunk_document` / `chunk_document_semantic` 零改)。

### 3.2 chunk_code 提取并填充(`backend/pipeline/chunk_code.py`)—— 4 处改动

pieces 从 5 元组 `(text, start, end, symbol, signature)` 改 **6 元组加 `node_type`**。涉及 **4 处**:
1. `_collect_sections` 组装 sections 处(约 218/240/249)
2. `_build_chunks` 解构 + 填充 symbol_name/signature/node_type/symbol_tokens(约 261/280)
3. `chunk_code` 无 grammar 兜底(约 339)
4. `chunk_code` 主路径 pieces 组装(约 349-355)

`symbol_tokens` 由 `symbol_name` 经拆分函数生成(camelCase/PascalCase/snake_case → 空格小写,如 `BatteryReadI2C` → `battery read i2c`、`ne301_init` → `ne301 init`)。保留 text 前缀拼接(向后兼容)。

### 3.3 Weaviate schema 加字段 + props(`backend/pipeline/ingest.py`)

**Property**(加到 `branch` 之后,`_ensure_collection` 行 136-149):
- `symbol_name`(TEXT)、`symbol_signature`(TEXT)、`symbol_node_type`(TEXT)、`symbol_tokens`(TEXT)

**symbol_tokens 解决 camelCase 分词**:Weaviate 默认 WORD 分词器不拆 `BatteryReadI2C`(索引为单 token),query "I2C" 无法命中。预存拆分版 `symbol_tokens`("battery read i2c"),WORD 分词器能索引出 `i2c`,query 端 Weaviate 同样分词即可匹配。snake_case(下划线)本就可拆,但统一走 symbol_tokens 简化逻辑。

**props 构造共 3 处**(全需加 symbol 字段):
1. `ingest_document` 主路径(约 201-216)
2. `ingest_document` 批失败兜底(约 258-271)
3. `_ingest_doc_batch`(约 403-416)

**推荐:抽 `_build_props(chunk, doc)` 辅助函数消除 3 处重复**(避免漏改兜底致数据不一致)。文档 chunk 这些字段写空串。

### 3.4 检索层(`backend/retrieval/search.py`)—— 独立符号召回 + RRF

**现状**:hybrid(dense + BM25)默认对**所有** TEXT property 跑 BM25(search.py 未传 `query_properties` 即证)。加 symbol 字段后 BM25 自动覆盖,但 hybrid 用的 `search_query` 是 rewrite 后的(见 §3.4b 问题)。

**a) 符号召回(独立,用原始 query)**:
- 新增 BM25 query 仅对 `symbol_tokens` 字段,query 用**原始 query(extract_query 输出,rewrite 前)**
- 理由:`search_query`(rewrite 后)可能意译掉标识符(如 "I2C"→"两线串行总线"),符号匹配需保留标识符;故符号召回复用 extract_query 输出
- 召回 top-K

**b) hybrid(保留,用 search_query)**:
- 现有 hybrid(dense + BM25 on text)用 `search_query`(rewrite 后,语义优),不变

**c) RRF 融合**:
- hybrid 结果 + 符号召回结果 → RRF(k=60)→ 按 **`source_id + chunk_index`** 去重合并(与 `_deterministic_uuid` ingest.py:35-41 一致)→ 送 rerank(bge-reranker-v2-m3,用 search_query)
- `query_properties` boosting(如 `symbol_tokens^3`)是可选优化,但因 hybrid 用 search_query(可能丢标识符),非主力;主力是 a) 的独立符号召回

**SearchResult**(`search.py:26-64`):加 `symbol_name` / `symbol_signature` 字段(从 Weaviate props 读)。rerank 用 `r.text` 不强制需要,但供调试 / 溯源 / 未来展示。

### 3.5 rag.py 管线(`backend/pipeline/rag.py`)—— query 流向

**现状管线**(核对 rag.py:290-326):
```
classify_intent(290) → [off_topic/business_inquiry 检索前拒,291-310]
→ extract_query(313) → rewrite_query(314) → search(search_query,315)
→ rerank(323) → pruner(326) → generate
```

**插入符号召回**:
- `extract_query` 输出(`extracted`,rewrite 前)→ 喂给符号 BM25 召回(保留标识符)
- `rewrite_query` 输出(`search_query`)→ 喂给 hybrid(语义优)
- 两路 RRF 融合 → rerank(用 search_query)

**意图范围**:只有 `product_question` 到检索层(off_topic/business_inquiry 检索前拒),符号召回对到达检索的 query 启用,无需按意图开关。未来迁移 support 后同理。

## 4. schema 迁移策略

| 策略 | 优点 | 缺点 |
|---|---|---|
| **A. 幂等重建**(drop + 重灌) | 简单;deterministic UUID(ingest.py:35-41,source_id+chunk_index)保证幂等,加 symbol 不改切分逻辑,UUID 稳定 | 重跑全量 ~2.5h(tesla-t4) |
| **B. 增量加 property**(若 v4 支持) | 不重跑;老 chunk symbol 空也能用(靠前缀) | 依赖 v4 兼容性,老 chunk symbol 字段空需补 |

**推荐 A**(简单可靠,且本就要重测全量 e2e)。**写 plan 前验证 Weaviate v4 加 property 支持**,若可行无坑降级 B。

## 5. 风险

| 风险 | 缓解 |
|---|---|
| **camelCase/PascalCase 分词**(Weaviate WORD 不拆) | `symbol_tokens` 拆分版字段(§3.3),单测验证 TS/JS/Rust 类型命中 |
| **rewrite 丢标识符**(search_query 意译) | 符号召引用 extract_query 输出(§3.5) |
| RRF k 值调参 | 起步 k=60,按 e2e 调 |
| symbol_tokens 拆分规则(PascalCase 边界,如 `HTMLParser`→`html parser`) | 标准 camel/snake 拆分 + 单测覆盖边界 |
| schema 重建 ~2.5h | 幂等可重跑;或增量加 property |

> ~~hybrid 多字段 BM25 支持不确定~~(已澄清:hybrid 默认覆盖所有 TEXT,非风险)

## 6. 验收

- **开发者问题命中精确函数**:如"NE301 I2C 读电池监控"召回 `battery_read_i2c` 类函数(symbol_tokens 匹配),非整文件
- **camelCase 符号命中**:TS/JS/Rust 类型(如 `BatteryReadI2C`)能被 "I2C" query 命中(symbol_tokens 拆分生效)
- **e2e 回归**:原 20 问不退步 + 新增 5-10 代码层开发者问题测例(TS_record / support 案例提取)
- **现有单测零回归**:`test_chunk_code` / `test_search` / `test_ingest` 全绿(元组 / props 改动)
- **非代码 query 不受干扰**:产品 / 文档问题召回不退步(符号召回对非代码 query 天然低分)
- 新增单测:chunk_code symbol 填充(各语言)、symbol_tokens 拆分、符号 BM25 + RRF 融合

## 7. 后续(方案 2 SCIP,按需)

方案 1 上线后,分析实际开发者问题分布:
- 若以"找函数 / 看实现"为主 → **方案 1 够,不做 SCIP**
- 若"谁调用 / 跨文件关系 / 类型层级"刚需 → Python / Rust / TS 加 SCIP(工具链成熟);**C/C++ 谨慎**(`scip-clang` 需 `compile_commands.json`,ESP-IDF + HaLow + mm-iot-sdk 构建系统,高风险)

SCIP 不在本 spec 范围,单独立项。

---

## 待用户确认

1. ~~所有意图 vs 仅 support 跑符号召回~~(已澄清伪命题:只有 `product_question` 到检索层,符号召回对其启用)
2. **schema 迁移**:幂等重建(推荐 A)vs 增量加 property(B,需验证 v4 支持)
3. **范围**:本 spec 只做方案 1(不含 SCIP)—— 确认?
