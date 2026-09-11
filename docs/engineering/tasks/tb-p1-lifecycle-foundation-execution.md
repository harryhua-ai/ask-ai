# TB-P1-LIFECYCLE-FOUNDATION — Phase 1 Implementation 执行报告

Status: **CANDIDATE READY**(REVIEW FIX 后第二候选;待 Role A 复审;未并 main;未部署;零生产触碰)

- 分支:`trace-b/p1-lifecycle-implementation-20260911`
- 实现基线:`b6100cf`(契约谱系 6aa5a9c + main 39723c2 的再基线合并,代码面 = v1.5.0 已接受代码)
- 首候选实现 commit:`e071f45`(Role A REVIEW FIX REQUIRED 对其检索语义);
- REVIEW FIX commit:`551b14c`(fail-closed 检索契约,见 §11);
- 组合树基线:origin/main `faa9bf2`(merge 提交 `bce2298`,零冲突);
- 报告 commit = 本文件所在提交。
- 契约:`docs/engineering/tasks/tb-p1-lifecycle-foundation-plan.md` @ 6aa5a9c(Role A FINAL PASS)
- Freeze 权威:`docs/product/initiatives/KNOWLEDGE-INTEGRITY-INITIATIVE-FREEZE.md` @ 915b5f7

---

## 1. Baseline 复核(变异前)

- 授权基线:main = `39723c2`;实际 `ls-remote`/本地一致,无漂移。
- 契约祖先链核实:915b5f7(Freeze 修订)→ 6aa5a9c(契约 FINAL PASS)。
- **漂移分类**:实现分支先于授权基于契约谱系创建,而契约谱系未含 Trace A
  (Release 1)代码。授权后 R1 收口解锁集成门 → 执行 `39723c2` 入契约谱系的
  再基线合并(`b6100cf`,merge 提交,零冲突);`git diff 39723c2..b6100cf -- backend/ scripts/`
  为空 = 代码面与授权基线逐字节一致,仅文档谱系并入。契约语义未被重释。
- 实现前基线测试地板(b6100cf):`2208 passed / 8 skipped`。
- **授权后 main 漂移终态(REVIEW FIX 集成刻复核)**:main 已前移至
  `faa9bf2`(39723c2..faa9bf2 = project-automation 治理线:workflow ×3 +
  scripts/project_automation + tests/project_automation + docs;中途曾为
  2bc9e02)。与候选改动集**文件级零交集**(comm 校验 = 0),属正交治理谱系。
  按指令已将 origin/main faa9bf2 **集成入候选分支**(merge `bce2298`,
  自动合并零冲突;候选仍未并 main)。

## 2. 实现架构

### 2.1 状态模型(FC-2/FC-3;P 轴无 ACTIVE)

- **L 轴**(documents.lifecycle):`discovered / active / superseded /
  missing_candidate / deleted`;派生集合 `SERVING = (active, missing_candidate)`
  (缺席宽限保上一代服务)、`WITHDRAWN = (superseded, deleted)`。
- **P 轴**(index_generations.status):`pending / processing / ready / failed /
  retired`,**无 ACTIVE**;激活 = `documents.current_version_id` 指针选择合格
  READY 代,不建模 READY→ACTIVE。
- **服务选择唯一权威**(I-1):active 代序集合 = `documents(current_version_id,
  lifecycle ∈ SERVING) ⋈ document_versions.generation_ordinal` 的
  `DISTINCT` 计算(`active_generation_ordinals_sync/async`)——不建独立指针
  列,不引入第二权威;墓碑/接替提交即时退出该集合(撤出 ≤1 天的强形态:
  激活事务提交即撤出)。

### 2.2 生成物理表示(P1-B)

- 生成 = 构建单元:`index_generations(ordinal 唯一,全局 max+1 行锁分配;
  status;doc/chunk 计数;failure JSONB;withdrawn_at/retired_at/
  gc_eligible_at/purged_at)`。
- Weaviate 对象加性属性:`generation_ordinal`(INT,**检索过滤用**)与
  `generation_id`(TEXT,仅审计展示)。INT 过滤精确语义,规避 TEXT 分词
  误命中(PA-0F 教训推广)。
- chunk UUID 命名空间拆分(P1-B 红线):
  - legacy(ordinal=0):`uuid5(source_id#i)` 寻址**不变**(兼容既有对象);
  - 新代:`uuid5(source_id#generation_id#chunk_index)`——旧版本对象在
    新代构建/验证/激活全程原位不动(失败隔离,I-5)。
- 持久内容副本(I-1):`document_version_chunks(version_id, chunk_index,
  text, props JSONB 快照)`;Weaviate 永不是唯一副本;重建 = 结构等价
  (存储文本再生向量,非比特相等)。

### 2.3 GenerationBuilder(P1-C/D/E/F 执行单元)

`build_generation(docs, source_id, force_rebuild, progress)` 六相:

1. **判定**(FC-6):incoming vs PG 现行版本 content_hash/metadata_hash →
   UNCHANGED / METADATA_CHANGED / CONTENT_CHANGED / NEW_VERSION;
2. Phase 1-2 安全过滤 + 切分 + 跨文档批量 embed(任一失败 → 整代 failed);
3. Phase 3 写对象(生成命名空间 UUID + generation props;insert_many 分块
   + replace 回退);
4. Phase 4 **激活前验证**(逐文档新代命名空间对象数 == chunk 数,I-5);
5. Phase 5 **原子激活**(单事务):版本行 + chunk 副本落库 +
   `activate_document_version`(前任 superseded 留痕 valid_to/
   superseded_by_version_id;指针翻转;lifecycle 恢复内置)+ 代转 READY +
   activated_at —— 服务视角要么旧版要么新版,绝无混合(P1-D);
6. Phase 6 前任代撤出退休:`retire_generation_if_withdrawn`(零 active 引用
   → RETIRED + `gc_eligible_at = +7 天`,§8a)。

失败路径(P1-C):`IngestFailures` raise(既有契约,零激活);失败代
failed + 失败证据 + **GC 即时资格**(`gc_eligible_at=now`);已写对象按
本文档新代命名空间确定性 UUID best-effort 点删(P0-A);在服代分毫不动。

- **metadata-only**(FC-5):不重嵌、不分叉版本/身份;账本先行
  (documents 行 + version.metadata_hash + 持久副本 props 同步),对象侧
  文档级 props 原位 merge update(向量不动;失败降级为下轮 metadata 变更自愈)。
- **真值修复 / P1-A / P1-E 共用**:`repair_documents(source_ids,
  source_id_scope)` 从 PG 持久 chunk 副本重物化对象(零源抓取,签名无
  connector);版本身身份不变,代归属原子切换(merge 进事务再翻转);
  无持久副本 → `unrepairable` 如实上报,调用方回退源抓取 force_rebuild。
- `--reindex`(P1-E):废除"先删 collection 再重灌";改为逐源 fetch_all →
  `force_rebuild=True` 新代构建 → 验证 → 原子激活,全程零服务损失。

### 2.4 检索在服投影(P1-D 消费面)

- `HybridSearcher(generation_filter_provider=...)`:三路径(search /
  search_symbols / search_bucket)统一 **fail-closed 契约**(Role A
  REVIEW FIX `551b14c` 冻结;权威先于 embed/检索裁决):
  - provider 缺省 → legacy 兼容:不加生成过滤(未迁移部署零回归);
  - provider 返回非空 ordinals → 严格过滤:filters_list 首位注入 INT 过滤
    (单代 equal、多代 contains_any);
  - provider 返回 `[]` → 权威服务集为空 → **零检索结果**:先于 embed/检索
    直接返回,绝不发检索请求(无过滤 = 无限制检索,会复活 GC 前物理残留的
    已撤代/墓碑对象);
  - provider 抛错 → **FAIL CLOSED**:异常向上传播,连 embed 都不发生
    (绝不无限制检索;与 Weaviate 失败同类,交调用方既有错误路径)。
- wiring:`backend/main.py` lifespan 以 sync 会话工厂构造 provider 注入;
  `vector_consistency` 与 admin analytics 同口径仅计 SERVING 文档
  (withdrawn 文档对象即时退出期望/实际/补灌/孤儿口径,`VectorGapReport
  .withdrawn_chunk_count` 单列呈现)。

### 2.5 GC 地基(FC-4;物理清除唯一接口)

`lifecycle_gc.sweep(session_factory, pipeline, tombstone_days=None, apply=False)`:

- RETIRED 代:`gc_eligible_at <= now ∧ purged_at IS NULL` → 按版本命名空间
  确定性 UUID 点删对象 + 删持久 chunk 行 + `purged_at` 盖章;版本元数据行
  **保留**(链可回放);
- 被接替文档:`superseded_at + 7 天` → 对象/版本/chunk/文档行全清;
- 墓碑文档:`deleted_at + tombstone_days`,**None = 关闭,不设隐式默认**
  (30 天默认已废除,`lifecycle_gc_tombstone_days` 配置缺省 None);
- dry-run 默认;删除动作全部入 `GCReport`;CLI `scripts/gc_lifecycle.py`
  (dry-run 默认,`--apply` 显式)。

## 3. Schema / 迁移设计

`scripts/migrate_p1_lifecycle_foundation.py` 四阶段,全加性、幂等:

1. **PG**:`ADD COLUMN IF NOT EXISTS` ×5(lifecycle NOT NULL DEFAULT 'active'
   / current_version_id / superseded_by / superseded_at / deleted_at)+
   P1 三表 `create(checkfirst=True)` + 两索引;列存在性校验 fail-closed。
2. **Weaviate**:`add_property` 幂等补 `generation_ordinal`(INT)/
   `generation_id`(TEXT);collection 不存在则跳过(全新部署由 init 自建)。
3. **版本回填**(PG-only):`ensure_legacy_generation`(确定性 UUID
   `uuid5(..."ask-ai:p1:legacy-initial-generation")`,ordinal=0,幂等锚)→
   逐 `current_version_id IS NULL` 行 `ensure_initial_version`(seq=1,
   legacy 代,current 指针)。
4. **内容回填**(Weaviate→PG 单向拷贝):单趟 iterator;无 ordinal 对象补
   `{generation_ordinal: 0, generation_id: legacy}`(data.update merge,
   不传 vector、不 replace、不删);对象 text/props → chunk 行(exists 检查
   幂等;幽灵对象只计数不写)。
5. **验证(fail-closed)**:PG 无 null-current / 无同源双 active;Weaviate
   无缺 ordinal 对象;legacy 对象数 == PG legacy SUM(chunk_count)。
   任一违背 → RuntimeError(重跑迁移收敛)。`--verify-only` 只读。

## 4. Legacy 迁移实证(真实 PG + 真实 Weaviate)

`tests/db/test_migration_p1_lifecycle.py`:每用例创建一次性数据库
`ask_ai_p1mig_test`,建 **v1.5.0 旧形态**(create_all 后 DROP P1 五列三表;
账本行用旧列原生 SQL 插入),再跑迁移全链:

- 补列/建表幂等(连跑两次无副作用;列/表齐备);
- 版本回填:2 行 → 2 初始版本(legacy 代 ordinal=0、seq=1、active、指针
  就位);二跑 +0(幂等);
- 内容回填:3 个 legacy 形态对象 → `chunks_inserted=3 / props_backfilled=3 /
  ghost=0`;chunk 文本与对象逐一一致;对象 ordinal 全部补 0;二跑 0/0(幂等);
- 验证通过(null_current=0 / multi_active=0 / legacy 3==3);
- fail-closed 负例:注入同源双 active → RuntimeError;注入无 ordinal 对象 →
  RuntimeError(重跑迁移可收敛);
- **零重嵌结构性证据**:迁移模块无 embedder 依赖(`embed(`/BGEEmbedder
  不在源码),回填不传 vector。

## 5. Gate P1-A..H 证据索引

| Gate | 语义 | 证据(测试文件::用例) |
| --- | --- | --- |
| P1-A | 持久真理投影重建 | `tests/pipeline/test_projection_rebuild.py::test_projection_wipe_and_rebuild_from_persisted_truth_only`(collection 整删→repair 重建→结构等价/版本身份不变/零源抓取)、`::test_repair_unrepairable_reports_migration_gap_without_source`;builder 侧 `test_repair_documents_rebuilds_from_persisted_truth` |
| P1-B | 新代物理表示 | `test_generation_builder.py::test_first_build_creates_generation_version_and_namespace_objects`(生成命名空间 UUID 存在、legacy 寻址零命中、generation_ordinal INT 属性落对象、持久副本落库) |
| P1-C | 失败隔离/零激活 | `::test_embed_failure_means_zero_activation_and_serving_unchanged`(IngestFailures、current 不变、单版本、失败代 failed+即时 GC 资格、旧代对象原位、新代命名空间零残留、服务集仍旧代)、`::test_validation_failure_zero_activation`(验证先于激活 I-5) |
| P1-D | 原子激活/Current Truth 恰一次 | `::test_content_change_activates_new_version_and_switches_serving_once`(exactly-one active、前任 superseded 留痕、指针单翻转、服务集即时换代、旧代对象保留);lifecycle 侧 `test_activation_supersedes_predecessor_and_flips_pointer_exactly_once` |
| P1-E | 全量重建非破坏(--reindex) | `::test_force_rebuild_creates_new_generation_not_inplace_overwrite`(UNCHANGED 文档 force_rebuild → 新代新版本,旧代对象原位,服务集换代);sync 层 `tests/pipeline/test_sync.py::test_reindex_rebuilds_generation_without_collection_delete`(collections.delete 零调用红线) |
| P1-F | metadata-only / UNCHANGED | `::test_unchanged_doc_skips_embed_and_generation`(零 embed/零新代/零分叉)、`::test_metadata_only_updates_props_without_reembed_or_fork`(零重嵌、同版本 id、metadata_hash 更新、对象 props + 持久副本 props 同步) |
| P1-G | 迁移幂等/兼容 | `tests/db/test_migration_p1_lifecycle.py` 全 7 用例(§4) |
| P1-H | GC 地基 | `tests/services/test_lifecycle_gc.py` 5 用例(资格时序 7 天、墓碑默认关闭+显式配置、dry-run 默认、apply 精确 UUID 点删 P0-A、purged 幂等、serving 永不入资格);lifecycle 侧 `test_retire_only_after_withdrawal_and_gc_eligible_plus_7d`、`test_tombstone_idempotent_and_non_destructive` |

词表/权威面守卫:`tests/services/test_document_lifecycle.py` 12 用例
(P 轴无 ACTIVE、§8a 常量冻结(7 天/≤1 天/无 30 天回用)、SERVING/WITHDRAWN
划分、active 集随 lifecycle/指针即时演进、FC-6 判定、metadata_hash 序无关、
legacy 代确定性单例、初始版本幂等);检索过滤接缝(fail-closed 契约,§11):
`tests/retrieval/test_search_generation_filter.py` 12 用例(provider None
三路径 legacy 兼容/非空 ordinals 三路径严格过滤/权威空集 `[]` 三路径零结果
且 embed·检索零调用/provider 抛错三路径 FAIL CLOSED 异常传播且 embed·检索
零调用/双代 contains_any/注入-结果透传正交)。

## 6. 测试结果

- 全量回归(实现完成后,`TEST_DATABASE_URL` 隔离测试库):
  **`2297 passed / 8 skipped / 0 failed`**(基线地板 2208 passed/8 skipped;
  增量 = 新门测试 + 接缝适配,零既有语义回退)。
- 真实基础设施:门测试跑真实 Postgres(TEST_DATABASE_URL)+
  真实 Weaviate 1.28(主容器 8080,生产同构 compose;不可达 skip)。
- `ruff check`:全部改动文件 **0 error**(仓库既有历史文件不属本轮范围)。

### 门测试驱动的实现缺陷修正(RED→fix→GREEN 实证)

1. `create_generation` 对聚合查询加 `FOR UPDATE` → PG
   `FeatureNotSupported`(ordinal 分配在生产必崩)→ 改为锁 max-ordinal 行;
2. `build_generation` 账本状态取自早期会话对象 → ready 代被记为
   processing → 以 Phase-5 权威行回填 accounting;
3. metadata-only 对象更新以 `UUID` 对象调用 client `data.update` →
   404 → `str(uuid)`(与全链其余写路径对齐);
4. repair 代归属翻转作用于 detached ORM 实例 → 翻转静默丢失 →
   `session.merge` 入事务再翻转(测试捕获的正确性缺陷,非风格)。

### 接缝适配说明(既有测试,意图不变)

`test_sync*.py` 家族的 fake pipeline 面向旧 `ingest_all` 编排;P1 经
`GenerationBuilder` 接缝驱动(`asyncio.to_thread` 包 `build_generation`)。
统一打桩(`_StubBuilder`:build 委托旧 fake ingest_all,保留进度回调/失败
语义;repair 默认全修复),断言意图逐条保留;gap-heal 三用例改断更强契约
(真值修复只动缺口文档 + `fetch_all` 零调用)。W6 快照两用例改打桩墓碑原语
(删除循环语义 = 逻辑墓碑),时序断言不变。

## 7. Scope Audit(逐文件分类)

| 文件 | 分类 | 说明 |
| --- | --- | --- |
| backend/db/models.py | EXPECTED | P1 schema:3 新表 + documents 5 列 |
| backend/services/document_lifecycle.py | EXPECTED | 新:词表/判定/原语/active 集/代管理 |
| backend/pipeline/generation_builder.py | EXPECTED | 新:生成构建/原子激活/真值修复 |
| backend/pipeline/ingest.py | EXPECTED | 加性:UUID 助手、generation props、write_collection_objects 提取、`RerankPipeline.rerank_scored` 式超集视图等价;既有 ingest/delete 路径行为不变 |
| backend/services/vector_consistency.py | EXPECTED | 服务集口径(SERVING);withdrawn 单列呈现 |
| backend/retrieval/search.py | EXPECTED | 在服代过滤接缝(缺省零回归) |
| scripts/sync.py | EXPECTED | 编排:builder 驱动/墓碑/账本计数/--reindex 重建 |
| scripts/migrate_p1_lifecycle_foundation.py | EXPECTED | 迁移工具(P1 交付物) |
| scripts/gc_lifecycle.py | EXPECTED | GC CLI(P1 交付物) |
| backend/main.py | REQUIRED SUPPORTING | lifespan 注入 provider(检索 wiring) |
| backend/api/admin/analytics.py | REQUIRED SUPPORTING | 分析计数对齐 SERVING 口径(withdrawn 不再计现役;无新 UI/API) |
| backend/config.py | REQUIRED SUPPORTING | `lifecycle_gc_tombstone_days`(缺省 None,无隐式默认) |
| tests/**(11 文件) | REQUIRED SUPPORTING | 接缝适配(意图保留)+ 新门测试 |

**禁止域核查**:freshness/SLA、缺席确认策略、reconciliation 循环、引用
probing、时序执行、CURRENT/HISTORICAL、UNCLASSIFIED、Woo 变体、#28、新排序
算法、evidence-reservation、Claim/Graph/GraphRAG、Admin Knowledge UI、数据源
清单 UI、#30 UI、connector 重设计、Trace A 残余修复 —— **均未触碰**。
v1.5.0 兼容面(Trace A 回答/检索排序/引用/可见性/同步失败安全/#18 删除/
P0-A/vector consistency/corpus repair)保持;唯一语义演进 = 契约显式取代的
两点(原位覆写 → 版本演进;--reindex 先删后灌 → 生成重建)。

## 8. 残余风险 / 已知边界

1. `_reconcile_orphan_vectors` 账本修复分支经 `ensure_initial_version` 落
   legacy 初始版本,但其 chunk 副本暂缺(迁移缺口)——后续 repair/refill
   演进补齐;已由 G005 回归锁定(零 embedding 修复,不删除)。
2. corpus_repair(既有物理修复工具)未纳入 P1 语义(授权范围外,原样保留)。
3. 墓碑专项窗(`lifecycle_gc_tombstone_days`)未设默认,运营化归 P5——在
   显式配置前,deleted 文档仅逻辑删除,永不自动物理清除(符合冻结语义)。
4. 本报告的迁移演练针对**一次性空库 + 合成 legacy 数据**;生产部署时应按
   运行手册先在生产库快照/维护窗内执行 `--verify-only`,再执行迁移
   (脚本本身幂等,重跑收敛)。
5. metadata-only 对象侧更新失败时降级为"账本已真、下轮自愈"(设计行为);
   在 Weaviate 异常持续场景,对象 props 可能落后账本,以 PG 为权威不受影响。

## 9. Runtime Acceptance Plan(部署前置,独立任务)

1. 真实 LLM 流式端到端(生产路径)在候选构建上回归:Preparing→首 token
   原位替换→渐进增长→追问同链(v1.4.0 验收口径复用);
2. 迁移演练已在测试库完成(§4);生产执行 = 维护窗内 `--verify-only` →
   迁移 → 冒烟(widget/admin/backend health)→ SyncLog/SyncRun 记账核对;
3. `--reindex` 真源演练:单源 `--reindex`,断言重建期间检索可用、零
   collection 删除、代序演进与 SyncLog 记账一致;
4. GC 演练:dry-run 报告人工复核 → `--apply` 单代试点;
5. Production Runtime Acceptance 证据归档后,方可申请集成评审与部署。

## 10. 零生产触碰确认

- 本轮全部变更限于实现分支工作树;`main` 未动(授权基线 39723c2;其上的
  project-automation 前进系其它轨道工作,本候选仅在自身分支集成之);
- 未执行任何部署(workflow 零 dispatch);生产 deployments 无新增;
- 生产 Postgres / 生产 Weaviate / 生产配置零触碰;
- 测试全部指向隔离测试库(`ask_ai_test`)、一次性演练库
  (`ask_ai_p1mig_test`,用后即删)与本机开发容器上的专用探针 collection
  (P1GenProbe/P1ProjProbe/P1MigProbe,用后即删)。

---

## 11. Role A REVIEW FIX(第二候选;551b14c)

**裁决**:首候选 e071f45 → REVIEW FIX REQUIRED——在服代检索语义不得 fail-open。

### 11.1 冻结契约(已实现)

| provider 行为 | 语义 | 实现 |
| --- | --- | --- |
| None | legacy 兼容 | 三路径不加生成过滤(不变) |
| 非空 ordinals | 严格过滤 | `_generation_ordinal_filter`(单代 equal/多代 contains_any)注入 filters_list 首位(不变) |
| 返回 `[]` | 权威服务集为空 | **先于 embed/检索裁决,直接返回 `[]`**,绝不发检索请求(旧:不加过滤=无限制检索) |
| 抛错 | 权威不可得 | **FAIL CLOSED:异常向上传播**(旧:吞错降级为不加过滤);连 embed 都不发生 |

fail-closed 手段选择 = **显式异常**(与 Weaviate 失败同类,交由调用方既有
错误路径;空结果路径用于权威空集这一"合法零答案")。理由:已撤代/墓碑对象
在 GC 前物理残留,无限制检索会复活非现役知识。

实现:`HybridSearcher._active_generation_filter` →
`_active_generation_ordinals`(返回权威集合,None=legacy/[]=空权威集/异常
传播);`search` / `search_symbols` / `search_bucket` 三路径统一"先取权威
再决策"——空集与异常路径均发生在 embedder 与 Weaviate 调用之前;main.py
lifespan wiring 注释同步。

### 11.2 RED→GREEN 实证

- RED(修复前跑新契约测试):`12 用例中 10 RED`——3× 空权威集返回了检索
  结果、3× provider 失败未抛且继续检索(6 违约)+ 3× 非空过滤用例先因测试
  脚手架笔误(NameError)失败、修正脚手架后转 GREEN(实证既有非空过滤
  语义未回归);None 兼容与注入透传 2 用例即 GREEN。
- GREEN(551b14c):`tests/retrieval/test_search_generation_filter.py`
  **12/12 passed**——None 兼容(三路径)、非空过滤(search/symbols/bucket)、
  空权威集零结果且 embed/检索零调用(三路径)、provider 失败三路径异常
  传播且 embed/检索零调用、双代 contains_any、注入/结果透传正交。

### 11.3 REVIEW FIX 改动文件

| 文件 | 变更 |
| --- | --- |
| backend/retrieval/search.py | fail-closed 契约(§11.1);三路径权威先决 |
| backend/main.py | wiring 注释同步(fail-open 描述废除) |
| tests/retrieval/test_search_generation_filter.py | 冻结契约 12 用例(重写) |
| tests/api/admin/test_analytics.py | 测试隔离缺陷修复(自持种子):test_signal_present_on_all_items 原依赖其它用例残留的 data_sources 行,空库必假红;与本 FIX 语义无关,属全套件确定性必要项 |

**未触碰**(按要求):lifecycle schema / 迁移模型 / 生成架构 / 墓碑 GC
默认与策略 / 排序与 reranker / 引用行为 / P2+ 语义(墓碑专项保留仍归 P5)。

### 11.4 组合树验证(与 main 集成)

- origin/main 集成刻 = `faa9bf2`(project-automation ACTIVE 线);merge
  `bce2298` 自动合并**零冲突**(文件级零交集,comm=0);
- 组合树全量回归:**`2380 passed / 8 skipped / 0 failed`**
  (= P1 线 2303 + project-automation 线 77,双侧零回归);
- 候选**未并 main**;main 停留 faa9bf2 未动。

---

TB-P1-LIFECYCLE-FOUNDATION-IMPLEMENTATION = CANDIDATE READY
