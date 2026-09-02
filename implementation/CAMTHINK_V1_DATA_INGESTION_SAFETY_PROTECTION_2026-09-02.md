# CAMTHINK V1 — 阶段1 数据导入安全保护 执行报告
# DATA INGESTION SAFETY & CORPUS PROTECTION — EXECUTION REPORT

- 日期:2026-09-02
- Gate:阶段1「数据导入安全保护」(IMPLEMENTATION + VERIFICATION,SINGLE CODEX)
- 上游合同:Data Source Reliability Product Contract & UX v1.1 Final Revision(docs 仓 `9b5581e`),Planner FINAL REVIEW=PASS
- 生产污染数据(.hef 62 篇/39,155 chunks):**DEFERRED BY PRODUCT OWNER**,本 Gate 未触碰

---

## 1. Executive Result

**PASS(自评,待 Planner FINAL REVIEW)**。三个 Golden Incident 的工程修复全部落地并有回归锁定:

- **G1 `.hef` 事故**:建立通用 Technical Safety Boundary(`backend/connectors/safety.py`)——binary 内容嗅探 + 模型/二进制工件扩展名类 + 硬尺寸上限,**全部在昂贵 parse/chunk/tokenize/embed 之前生效**;管理员 `file_types` 配置不可绕过;`.hef` 只是类名单一员,不是补丁。
- **G2 Admin Delete TEXT equal**:删除路径重写为「账本确定性 UUID 点删 + 迭代器实扫边界内对象 UUID 兜底 + 残留=0 验证」;`Filter.by_property("source_id").equal` 原语从代码中清除(静态断言测试锁定)。
- **G3 空/畸形发现**:web_crawl 全量轮 `discovered == 0`(显式键)→ 判「不完整发现」,禁止破坏性退休,孤儿保留+上报;G003b 既有「可证明成员缺席→精确退休」冻结语义不回退。

规模:12 文件,+1290/−72;新增测试 4 个文件 37 用例;全量相关回归 **848 passed / 3 skipped**(skip=真实 Weaviate 门控用例,无本地实例,与基线既有惯例一致)。

## 2. Baseline / Final Commit

- BASELINE:`193f206a3d0e8695f1c40766a1ba54667fcba2fb`(main,生产冻结源)
- 分支:`worktree-exec/ingest-safety-20260902`(独立 worktree `.worktrees/ingest-safety`,.env 物理复制)
- IMPLEMENTATION_COMMIT:`f481f94`(实现+测试,已推 origin)
- FINAL_COMMIT:`f481f94`(报告入 docs 仓,不混入代码仓)

## 3. Root Cause / Existing Architecture Findings

1. **G1 根因**:ingestion 链路对「文件能否被安全文本化」零防线。github/filesystem connector 在 `read_text(errors="replace")` 后直接进 chunk(regex/tiktoken);ExclusionPolicy 的 BINARY_EXT 仅 15 个媒体/压缩扩展名,`.hef` 等模型工件完全未知;`max_file_size` 语义只作用于非源码且默认 None。实测 84MB 二进制 → 单核 100%。
2. **关键实证**:`neoruntime` 仓内 `deploy/nginx/runtime/bin/nginx` 是**无扩展名 ELF 二进制**——证明仅扩展名方案必然漏网,内容嗅探为必需(已实现并测试)。
3. **G2 根因**:`data_sources.py:_purge_source_corpus_sync` 账本段用 `Filter.by_property("source_id").equal(sid)` 删除——Weaviate TEXT 过滤是分词语义,与 P0-A 生产误删事故同源。
4. **G3 根因**:`_discover_source_docs` 的完整性判定只看覆盖率(accepted>0 且 extracted/accepted≥80%);空 sitemap 与畸形 sitemap(200+坏 XML,解析静默返回空)都产生 `discovered=0/accepted=0`,被误判「完整发现」→ 空成员集 → 孤儿全部 EXTRA_CONFIRMED_RETIRED。
5. **R4 根因**:tiktoken `encode()` 默认对 `<|...|>` 特殊 token 字面量抛异常(生产实证于 neoruntime-apps);单文档异常进 failed 清单 → `ingest_all` raise → 整轮 failed。

## 4. Technical Safety Design

新模块 `backend/connectors/safety.py`:

- `TechnicalSafetyPolicy.check_path(rel, size)`(廉价,读内容前):MODEL_ARTIFACT_EXTS 类名单(hef/onnx/pt/npy/so/elf/wasm/whl… 30+)+ 硬尺寸上限。
- `TechnicalSafetyPolicy.check_content(content)`(内存文本,chunk 前):头部 8KB NUL 检测 + 控制字符占比(>5%)+ U+FFFD 解码残留占比(>5%)。**中文/Unicode 合法文本三类信号均为 0,不误伤**(专项测试)。
- 阈值语义:管理员配置只能**调低**硬上限,绝对钳制 64MB(84MB 级事故物在任何配置下被尺寸兜住)。
- 接线位置(纵深两道):
  - **connector 层(pre-read)**:github `_should_include_path`(fetch_all/fetch_changes 共用单点)、filesystem `_is_technically_safe`(fetch_all/fetch_changes)——巨型/工件文件**连读取都不发生**;
  - **pipeline 层(pre-chunk)**:`ingest_document` 与 `_ingest_doc_batch` Phase 1 对 RawDocument.content 嗅探——覆盖 web_crawl/woocommerce 及一切伪装内容。
- 可观察性:`connector.safety_stats` / `pipeline.safety_stats` = `{"excluded": N, "reasons": {...}}` + warning 日志。

## 5. Knowledge Eligibility Foundation

- `KnowledgeRole` 12 角色 + 路径启发 `classify_role`(vendor/test/generated/build/示例/文档/配置/源码/排障)+ `recommendation_for`(include/exclude/review,合同默认表)。
- `FileAdmission` machine-readable 原语:`path/size/technical_safe/technical_reason/knowledge_role/recommendation/policy_result/eligible`——阶段6 Repository Scan 可直接消费。
- **语义分离锁定**:vendor/test/生成物 → `technical_safe=True` + `recommendation="exclude"`;二进制内容 → `technical_safe=False` + role=BINARY(专项断言)。
- **本 Gate 不强制 Layer 2 排除**:推荐是信息,不是行为——现有摄取行为不变(AC6 无回归);强制纳入策略留给 Admin Policy Gate。实现范围决策,非语义变更。

## 6. Size Threshold Evidence(INITIAL ENGINEERING DEFAULT)

数据(2026-09-02 只读统计,git trees + 本仓):

| 样本 | 文本类文件 | max | p99 | p95 | 备注 |
|---|---|---|---|---|---|
| neoruntime@main | 1488 | 1.24MB(nginx ELF,无扩展名) | 255KB | 90KB | 最大合法文本 = vendor 头 json.hpp 898KB |
| neoruntime-apps@main | 182 | 236KB(main.py) | ~236KB | 62KB | 1.9MB "文本"实为 .mp4(已有 BINARY_EXT 拦) |
| ask-ai 本仓 | 全量 | 243KB(package-lock.json) | — | — | GENERATED |
| .hef 工件 | 11 | 82.1MB | — | — | 最小 0.2MB → 尺寸无法单独区分工件 |

**选定**:`review_size_limit = 1MB`(高于全部已知合法文本,超限=技术上安全但建议人工确认);`hard_size_ceiling = 16MB`(4× 最大合法文本;落入 regex/tokenize 病态区前阻断);`ABSOLUTE_HARD_SIZE_MAX = 64MB`(配置钳制上限)。误报风险:合法 >16MB 纯文本当前证据为零;漏报风险:.hef 6.8MB 级不触尺寸线,由扩展名类+嗅探主防(纵深)。全部可按源 config(`review_size_limit`/`hard_size_ceiling`)调低。**不宣称科学最优,标注 INITIAL ENGINEERING DEFAULT。**

## 7. Expensive Pipeline Boundary

顺序保证:`path+size 廉价判定(读前)→ read → 内容嗅探(chunk 前)→ chunk → tokenize → embed → index`。测试证明:`hard_size_ceiling=2` 时 `Path.read_text` 被断言**从未调用**(giant 文件连读取都不发生);伪装二进制文档的 chunker/tokenizer/embedder 三者 spy 均未被触达。

## 8. Safe Source Delete Fix

`_purge_source_corpus_sync` 三段式重写:
1. 账本段:`uuid5(source_id, 0..chunk_count-1)` 全集 `Filter.by_id().contains_any` 分批(500)点删——与 ingest prune/delete_document 同一文档局部保证;
2. 孤儿段:迭代器全扫 + `startswith(prefix+"/")` 客户端边界过滤 → 收集**实际对象 UUID** → `delete_by_id` 逐个删(读侧 TEXT 前缀仅用于判断,删侧只点名 UUID);
3. 验证段:再次边界扫描,残留>0 → RuntimeError → 端点转 502,配置与账本原样保留可重试。
`equal/like` TEXT 删除原语零残留;测试断言过滤器夹带的 UUID 全部属于本源、`src-a-sibling`/`src-a-xxx`/`src-ab` 三类相似前缀源对象逐一幸存(含真实 Weaviate 门控用例)。

## 9. Discovery Completeness Fix

`_discover_source_docs` 新守卫:仅当 run_stats **显式报告 `discovered == 0`**(真实 web_crawl 全量轮恒写该键)→ `complete=False`,孤儿处置一律 KEEP+上报。语义精确性:
- 合法空源与畸形 sitemap 在 web_crawl 侧不可区分 → 保守 KEEP(与合同「UNKNOWN/INCOMPLETE ≠ AUTHORITATIVE EMPTY」一致);页面级真实消失仍由状态文件差集正常删除;
- **G003b 冻结语义不回退**:primitive connector(git/fs/woo,抽取即权威枚举)与 `discovered` 键缺失形态不受守卫影响;`discovered>0 & accepted=0`(robots/规则全拒,可证明允许集为空)仍为 complete——有专项测试锁定。
- 守卫与既有覆盖率规则(<80% → 不完整,9bbf587)正交叠加。

## 10. Document-Level Failure Isolation

`chunk.py` 两处 tiktoken `encode` 加 `disallowed_special=()`:源码中的字面 `<|endoftext|>` 按普通文本计 token,不再抛异常(生产实证的单文档炸整轮路径,根因修复)。管线内容嗅探排除的文档计 0/不入 failed 清单(单坏文档不拖垮整轮);既有 per-doc/per-chunk/批级错误隔离全部保留。

## 11. Files Changed

| 文件 | 变更 |
|---|---|
| `backend/connectors/safety.py` | **新增** Technical Safety + Knowledge Eligibility 原语 |
| `backend/connectors/github.py` | +13:import、constructor safety、`_should_include_path` pre-read 检查 |
| `backend/connectors/filesystem.py` | +30:同上(fetch_all/fetch_changes 双入口) |
| `backend/pipeline/ingest.py` | +24:pipeline 内容嗅探两处 + safety_stats |
| `backend/pipeline/chunk.py` | ±8:两处 `disallowed_special=()` |
| `backend/api/admin/data_sources.py` | purge 三段式重写 |
| `scripts/sync.py` | G3 完整性守卫 |
| tests/ | 新增 4 文件 + 重写 1 个既有直调用例 |

无任何无关文件/重构/格式化波及(black 初跑波及 chunk/github/data_sources 既有格式,已回退并最小重放)。

## 12. Tests Added(37 用例,4 新文件 + 1 重写)

- `tests/connectors/test_safety.py`(18):任务书 §15 T1-T11 全覆盖 + 绝对钳制 + 中文不误伤 + Role/推荐矩阵 + connector 级 file_types 不可绕过 + 超大文件 pre-read 证明。
- `tests/pipeline/test_ingest_safety.py`(4):管线嗅探、文档级隔离不 raise、解码质量、特殊 token 正常灌入。
- `tests/scripts/test_discovery_completeness.py`(8):G3 矩阵(请求失败/畸形空 sitemap/全拒可证/低覆盖/权威非空/primitive 空源/键缺失兼容/**不完整禁删+完整退休对照**)。
- `tests/api/admin/test_data_source_delete_document_local.py`(4+1 gated):删除 A 三兄弟幸存、过滤.UUID 无夹带、残留验证 raise、静态禁令断言、真实 Weaviate 门控。
- `tests/api/admin/test_data_source_delete.py`:直调用例按 UUID 语义重写。

## 13. Tests Actually Executed + Results

| 套件 | 结果 |
|---|---|
| 新增 4 文件 + chunk 回归 | 70 passed |
| tests/api/admin/(delete 全量+data_sources) | 全绿(含 DB,TEST_DATABASE_URL=ask_ai_test) |
| tests/pipeline + connectors + scripts + services | 610 passed, 3 skipped |
| **tests/api 全量** | **238 passed** |
| **最终全量组合(pipeline+connectors+scripts+services+api)** | **848 passed, 3 skipped**(skip=真实 Weaviate 门控,基线既有惯例) |

black(仅本 Gate 文件,波及已回退)、ruff(本 Gate 文件无新增违规;基线既有 3 处遗留未动,记 FOLLOW-UP)。

## 14. Acceptance Criteria AC1–AC16

| AC | 结果 | 证据 |
|---|---|---|
| AC1 通用防线非单扩展名补丁 | PASS | 嗅探+类名单+尺寸三层;无扩展名 ELF/伪装 .txt 用例绿 |
| AC2 昂贵管线前生效 | PASS | read_text 未调用断言;chunk/embed spy 未触达断言 |
| AC3 管理员不可绕过 | PASS | file_types 含 .hef 仍被拒(test_t11);配置钳制 64MB |
| AC4 技术安全与知识价值分离 | PASS | FileAdmission 双字段;vendor/test technical_safe=True 用例 |
| AC5 vendor/test 不误标 unsafe | PASS | 同上专项断言 |
| AC6 源码/配置/文档能力不退化 | PASS | .py/.c/.yaml/.md 放行用例;code-aware chunking 回归(test_chunk 46 用例绿);hybrid/符号检索路径零改动 |
| AC7 双阈机制+证据支撑 | PASS | §6 证据表;1MB/16MB 标注 INITIAL DEFAULT |
| AC8 删除无 TEXT matching | PASS | 静态断言 + `grep by_property` 零残留 |
| AC9 兄弟/相似源幸存 | PASS | 三类相似前缀对象逐一断言(含真实 Weaviate gated) |
| AC10 不完整发现禁破坏性退休 | PASS | discovered==0 → delete 断言未调用 |
| AC11 权威空 vs 失败/不完整 工程区分 | PASS | 完整性显式键语义 + 对照用例 |
| AC12 单文档失败无 source-wide 破坏 | PASS | 特殊 token 根因修复 + 隔离用例 |
| AC13 P0-A DOCUMENT-LOCAL 保持 | PASS | test_ingest_prune_document_local 全绿;新删除路径同保证 |
| AC14 必测项实跑全过 | PASS | §13 |
| AC15 无生产访问/mutation/部署 | PASS | 全程本地 worktree;生产零接触 |
| AC16 未越界 | PASS | §16 Scope Audit |

## 15. Regression Results

848 passed / 3 skipped(gated)。关键锁定:P0-A 文档局部 prune 套件全绿;G003b 成员缺席精确退休语义保持(与 G3 守卫的交互经 Planner 修正语义后专项锁定:守卫只认显式 `discovered==0` 键);增量窗口/覆盖门/一致性自愈/health 语义套件零回归。

## 16. Scope Audit

BASELINE 193f206 → FINAL f481f94:无 worker isolation / 无 Health 实现 / 无 progress UI / 无 scheduler 重构 / 无 run-state 持久化 / 无 production 访问与 mutation / 未清理 DEFERRED 污染语料 / 无 Frozen Contract 语义修改。`git status` 干净,无他窗改动混入。

## 17. Follow-ups / Tech Debt

1. `utils/budget.py:36` 的 tiktoken encode 同样无 disallowed_special 保护(查询路径,非本 Gate 范围);
2. ruff 基线既有 3 处遗留(data_sources import 序列等)未动,避免无关 diff;
3. web_crawl 单页无尺寸上限(HTTP 文本,风险低)——可在阶段1 后续或阶段5 加 content-length 上限;
4. filesystem 根目录消失 → 静默空枚举在该 connector 上仍等于「权威空」(无 run_stats);G3 守卫只覆盖显式键形态,fs 的目录失踪保护记为后续(当前删除面本就保守:fetch_deleted 恒空,风险敞口仅 reconciliation 退休);
5. Layer 2 推荐的强制执行与 Needs Review 批准流 → 阶段6/7;
6. 真实 Weaviate 集成用例依赖本地 21100 实例,CI 环境沿用仓库既有 skip 惯例。

## 18. Production Access Statement

PRODUCTION_ACCESS: NONE · PRODUCTION_MUTATION: NONE · SYNC_TRIGGERED: NONE · 生产 .hef 污染(62 篇/39,155 chunks)保持 DEFERRED,未触碰。

## 19. Final Status

**PASS(自评)**——AC1-AC16 全过;Golden G1/G2/G3 全部有真实回归锁定;Planner 可基于 diff(f481f94)+ 本报告做独立 FINAL REVIEW。
