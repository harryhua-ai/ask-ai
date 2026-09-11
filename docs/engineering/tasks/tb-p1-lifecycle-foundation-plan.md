# TB-P1-LIFECYCLE-FOUNDATION Engineering Contract(Trace B Phase 1 —— 知识生命周期地基)

- **Task ID**:`tb-p1-lifecycle-foundation`(Initiative 级文档谱系别名:INGESTION-LIFECYCLE-P1,见 Discovery §15)
- **Status**:**CANDIDATE READY**(待 Role A 评审;本任务为契约定义,零实现、零迁移、零生产触碰)
- **性质**:PHASE 1 ENGINEERING CONTRACT DEFINITION——把已接受的 Initiative Freeze P1 交接转化为可执行工程契约;实现设计权(工程 HOW)归后续执行代理,本契约只冻结 WHAT / 边界 / 可观测验收语义。
- **父 Initiative**:Knowledge Integrity(Trace B / Release 2);Freeze = `docs/product/initiatives/KNOWLEDGE-INTEGRITY-INITIATIVE-FREEZE.md`(97cac3f,FINAL PASS)

## Authoritative Sources(全部已接受,本文不得回退)

| # | 来源 | 状态 |
|---|---|---|
| S1 | `docs/engineering/discovery/KNOWLEDGE-FRESHNESS-RETRIEVAL-INTEGRITY-DISCOVERY.md`(e94a673 + b8969ca/f73092b 修正) | FINAL PASS |
| S2 | `docs/product/initiatives/ADMIN-KNOWLEDGE-OPS-UX-DEFINITION.md`(7ce0111 + b8969ca;§2 四轴状态模型 = A-1 权威定义) | FINAL PASS |
| S3 | `docs/product/initiatives/KNOWLEDGE-INTEGRITY-INITIATIVE-FREEZE.md`(97cac3f;§2 不变量 / §3 阶段所有权 / §5 验收模型 / §7 P1 交接) | FINAL PASS |
| S4 | Issue #13 身份冻结契约链:`docs/implementation/CAMTHINK_V1_DATA_INTEGRITY_RECONCILIATION_DISCOVERY_2026-09-03.md`(D1/D2/D3 + §10 正确语料契约)+ `…_IMPLEMENTATION_2026-09-03.md` + `…_INTEGRATION_GATE_2026-09-03.md` | 已冻结已集成 |
| S5 | 关联既有冻结纪律:#18 源删除生命周期(S0)、P0-A/PA-0F 删除局部性禁令、#45 DocFailure 契约、生产部署编排(#10,迁移桥先于 rollout 先例) | 已接受 |

## Baseline(基线)

- **调查基线(代码证据)**:Trace A Release 1 候选 = main `bb80c389c6d38aa2474f383b60f3aec0de7397a1`(2026-09-11 本地 = origin,工作树干净)。本文全部 `file:line` 证据以该树为准。
- **本契约分支基线(Trace B 文档谱系)**:`97cac3f3319b4e5b5c381ed3a6533822de7de012`(= product/knowledge-integrity-freeze-20260911 tip),分支 `trace-b/p1-lifecycle-foundation-contract-20260911`。遵守 Freeze §4 隔离纪律:Trace B 文档/实现未经显式集成闸不得并入 main。
- **基线漂移声明**:bb80c38 与 97cac3f 两树间,本文引用的生命周期证据文件全部零漂移,唯一例外 = `backend/pipeline/ingest.py:215-217`(`_evidence_props` 增加 `product=doc.product` 实参,Trace A INC-2a 谱系;与生命周期语义无关)。
- **若 main 因 Trace A Release 1 收口而前移**:执行代理开工时须重新记录新基线;本文冻结的产品语义不因基线移动而改写。

## Objective(目标)

建立知识生命周期地基,使以下性质**首次**对产品成立:

> 持久真相 + 稳定 canonical 文档身份 + 显式文档版本 + 可重建服务投影 + 基于生成的索引 + 原子激活 + 失败隔离 + 显式接替/墓碑语义。

目标产品结果:**新文档版本或重建索引生成可以在不摧毁当前在服生成的前提下被准备与验证**;持久真相足以重建服务投影;文档身份/版本/生命周期事实的权威在向量索引之外(Postgres)。

对应 Freeze §5 P1 Gate(冻结验收锚):全量重建零服务中断;同文档两现役版本不可共存;FAILED 新代不破坏 ACTIVE 代;墓碑/接替语义符合冻结状态机;投影可重建性首次可证明;真实部署冒烟证据(后者属部署后 Runtime Acceptance,本契约定义要求,本任务不部署)。

---

## Current-State Evidence(现状证据;全部 CURRENT REPOSITORY FACT,除非标注)

### 身份与账本

| # | 证据 | 级别 |
|---|---|---|
| E1 | `documents` 表主键 = `source_id` 复合路径串 `<source>/<branch>/<rel>`;`content_hash` 为指纹索引非身份;每真实文档一行;同 hash 不同路径合法共存(`backend/db/models.py:41-67`;Issue #13 D1/D2 冻结,契约链见 S4) | FACT + 已冻结契约 |
| E2 | chunk 寻址 = 确定性 `uuid5(NAMESPACE_URL, f"{source_id}#{chunk_index}")`,重跑同 key 覆盖保证幂等(`backend/pipeline/ingest.py:127-133`) | FACT + 已冻结契约(#13 确定性 UUID 家族) |
| E3 | 账本行内容变更**原位覆写**(`_upsert_postgres` 按 source_id 原地更新 content_hash/chunk_count,"单行原位演进,无旧行残留"),**无任何版本历史**(`backend/pipeline/ingest.py:947-989`) | FACT |
| E4 | `documents` 表无 last_seen_at / source_version / etag / deleted_at / lifecycle / generation 任何列(`backend/db/models.py:55-66`) | FACT |
| E5 | 源级生命周期仅删除族:`data_sources.lifecycle_state` NULL=ACTIVE / delete_requested / deleting / delete_failed;**删除成功 = 整行删除,无 DELETED 墓碑**(`backend/db/models.py:206-213`;`backend/services/source_lifecycle.py:30-84`;#18) | FACT + 已冻结契约(源级) |

### 内容驻留(持久真相缺口核心)

| # | 证据 | 级别 |
|---|---|---|
| E6 | 归一化 chunk 文本**只存在于 Weaviate `text` 属性**(`COLLECTION_PROPERTIES`,`backend/pipeline/ingest.py:175-201,247`);PG `documents` 无内容列 → **Weaviate 是内容唯一持久副本**(I-1 违反) | FACT |
| E7 | 源消失后无法重建:重建需重新 fetch 外部源;#48 ghost 半径(github 改名滑出删除窗 → 旧路径 corpus 永久残留,Discovery §0)、KNOWLEDGE-STALE-LEDGER 生产 26 行死账修复(Discovery §2.4)为生产实证 | FACT |

### 写入 / 更新 / 删除行为

| # | 证据 | 级别 |
|---|---|---|
| E8 | 内容变更传播 = 确定性 UUID **原地覆盖**(`insert_many` → 已存在 UUID 回退 `data.replace`,`backend/pipeline/ingest.py:419-468`):旧版本内容在任何验证之前即被销毁;部分失败时靠"全部成功才 prune"(`ingest.py:486-487,520-557`)与下轮重试兜底 | FACT |
| E9 | 删除 = **立即物理删除**:`connector.fetch_deleted(since)` → `delete_document()`(Weaviate 按自身确定性 UUID 点删 + PG 行删除,无墓碑无确认链,`backend/pipeline/ingest.py:900-941`);删除正确性完全依赖连接器窗口(fs/woo `fetch_deleted` 恒 `[]`;git 改名滑窗 = ghost,Discovery §1 三问) | FACT |
| E10 | 删除纪律(P0-A 冻结):删侧只点名对象确定性 UUID,**禁止任何 TEXT 属性过滤删除**(PA-0F 事故:分词语义误删兄弟文档,生产实证 web_crawl 359→163;`ingest.py:523-541`;`backend/services/source_deletion.py:18-20`) | FACT + 已冻结契约 |
| E11 | `--reindex` = **先删整个 collection 再重灌**(`scripts/sync.py:1238-1249`;docstring 自认"期间服务不可用(零停机迁移为后续工作)"`sync.py:1224`);测试钉死该行为(`tests/pipeline/test_sync.py:625-671`) | FACT |

### 索引 / 服务选择

| # | 证据 | 级别 |
|---|---|---|
| E12 | **无任何生成/集合版本概念**:`generation_id / collection_version / dual collection / atomic swap` 全仓零命中;服务路径 = 固定单集合 `Document`(`WEAVIATE_CLASS_NAME`,`backend/config.py:90`),`HybridSearcher` 直接 `collections.get(class_name)`(`backend/retrieval/search.py:137,148,198,260,338`),无间接层 | FACT |
| E13 | Weaviate 对象**无任何时间戳属性**;5 个 evidence_* 元数据存在但运行期恒 unknown 且显式冻结不参与决策(Discovery §1) | FACT |
| E14 | 一致性设施只读或有界:verify_source_vectors 只读(孤儿仅 warning,`backend/services/vector_consistency.py:54-165`);corpus_repair 四动作 dry-run 默认、按确定性 UUID 点删、PROD_MUTATION_AUTHORIZATION_REQUIRED(`backend/services/corpus_repair.py:19-45,140-303`);源删除 purge 三段式(账本段 uuid5 点删 → 孤儿段全迭代扫 + 按实际 UUID 删 → 验证段残量>0 raise 不假报成功,`backend/services/source_deletion.py:353-423`) | FACT |
| E15 | 同步窗口纪律:仅 status=success 推进增量窗口(失败不推过缺口,`scripts/sync.py:445-469,930`);ingest_all 任一 doc 失败统一 raise(IngestFailures)记 SyncLog failed(`backend/pipeline/ingest.py:559-647`);孤儿对账删除仅在完整权威枚举确认后执行(EXTRA_CONFIRMED_RETIRED,`sync.py:825-843`) | FACT + 既守纪律 |

### 迁移机制与测试面

| # | 证据 | 级别 |
|---|---|---|
| E16 | PG 迁移现状:`init_db` = `create_all`(只建缺失表,**不补已有表新列**,`backend/db/session.py:95-104`);实际迁移 = 幂等加列脚本族(`scripts/migrate_*.py`,`ADD COLUMN IF NOT EXISTS` 先例)+ 部署编排迁移桥先于 rollout(v1.4.0 事件先例);无 Alembic(session.py docstring 自认"生产环境应使用 Alembic"但不存在) | FACT |
| E17 | Weaviate 增量迁移先例:属性加列幂等(`migrate_add_evidence_meta_props.py`,"只动 schema 不写对象数据")+ 零重嵌回填(`migrate_backfill_evidence_meta.py`,dry-run 默认、绝不改 text/传 vector/删对象) | FACT |
| E18 | 身份迁移先例:`migrate_documents_path_identity.py`(PK (content_hash,branch)→source_id;重复行保 latest 合并;幂等;回滚在新契约共存行存在时**拒绝**执行) | FACT |
| E19 | 钉死现状行为的测试(全量 2035 test functions;CI 跳过 tests/api/admin、tests/scripts/test_sync_db.py、tests/embedder、tests/e2e):`tests/pipeline/test_ingest_ledger_identity.py:127` `test_content_change_updates_row_in_place`(钉死原位覆写);`tests/pipeline/test_ingest.py:983,1015`(upsert 单次执行无 legacy delete / 原位更新不被抢占);`tests/pipeline/test_sync.py:625` (钉死 --reindex 删 collection);`tests/db/test_documents_pk.py`(路径 PK 契约);`tests/pipeline/test_ingest_ledger_identity.py:145-166`(删一路径同内容兄弟存活 + 精确 uuid5 点删);`tests/db/test_migration_path_identity.py`(真实 DDL 演练 + 回滚拒绝) | FACT |

---

## Investigation Findings(现状 RCA——为什么当前架构不能满足 P1)

逐条回答任务指令十问(全部 CURRENT REPOSITORY FACT,证据见上表):

1. **持久归一化内容现在存于何处?** 只在 Weaviate `text` 属性(E6)。PG 账本仅元数据。→ I-1 违反:Weaviate 是唯一持久副本。
2. **源消失后,当前 PG + 源能否再现服务向量?** 不能(E7):内容不在 PG,重建必须重新 fetch 源;源已消失即永久不可重建。#48 ghost 与 STALE-LEDGER 死账为生产实证。
3. **当前文档/版本身份如何表示?** 文档身份 = source_id 路径串 PK(#13 冻结);chunk 身份 = uuid5(source_id#i);**版本维度不存在**(E1-E4)。
4. **两个历史版本能否在不双双现役的情况下共存?** 不能(E3、E8):同路径内容变更 = 原位覆写 + UUID 覆盖,旧版本即时销毁;跨路径同内容合法共存但两者都是独立"现役"文档(D2 report-only),非版本关系;部分失败时短暂出现混合 chunk 集(裁剪延后)。
5. **今天 reindex 发生什么?** 先删整个 collection(E11),期间服务不可用/空索引;filesystem 源必须在 mac 补灌的部署约束放大该窗口(CLAUDE.md Critical Constraints)。
6. **部分失败能否污染/移除在服向量?** reindex 路径可以(整个 collection 已删);常规路径:覆盖写语义下内容变更在任何验证前销毁旧版本(E8);错误删除报告立即物理生效(E9);已有缓解 = 成功才 prune(E8)、失败不推窗口(E15)、删侧 UUID 点名(E10)——但均非"保留上一代"语义。
7. **今天服务生成如何选择?** 无选择(E12):固定单集合直接查询;没有指针、没有别名、没有双代。
8. **生命周期真相存于何处?** 文档级:无处存储(隐式 = 行存在 ∧ 向量存在;删除 = 行消失);源级:仅删除族 lifecycle_state(E5);向量索引不含任何生命周期事实,也不得反推(I-1)。
9. **哪些数据必须在迁移中不破坏?** 生产 documents 全量行与 Weaviate 全量对象(uuid5 寻址)、data_sources、sync 账本族;现有确定性 ID 不得变更;在服行为不得中断(E16-E18 给出迁移机制先例)。
10. **哪些现行假设/测试需要契约保全或替换?** 保全:路径 PK / 无抢占 / 确定性 UUID 稳定性 / prune 与删除文档局部性 / 源删除状态机 / 修复工具红线 / 同步窗口纪律。替换(语义被 P1 显式取代):`test_content_change_updates_row_in_place`(原位覆写 → 新版本演进)、`test_reindex_deletes_and_recreates_collection`(先删后灌 → 生成重建+原子激活)。详见 Compatibility Boundary。

**结论**:当前架构 = "单代、原位覆写、物理删除、无生成、内容单副本(且唯一副本在投影层)"。P1 的八项性质**全部缺失或冲突**;其中 E6(内容单副本)与 E11/E12(先删后灌 + 无生成选择)是最大的两个结构缺口,前者决定持久真相工程,后者决定生成原子化工程。

---

## Frozen Product Contract(冻结产品契约——实现不得违反)

以下为 ACCEPTED PRODUCT INVARIANT(来源 S1-S3;**不是**工程 HOW):

**FC-1(I-1 持久真相,D-1 修正冻结)**
- 持久化归一化文档真相必须留存,版本绑定,且**足以重建服务投影**;
- 载体可为 Postgres **或**关联的持久 content-addressed 存储——**载体选择保留为工程决策**(本契约不冻结);
- Weaviate 永远不得成为唯一持久副本;
- lifecycle / version / identity 元数据权威 = Postgres;禁止从向量索引反推任何生命周期事实。

**FC-2(I-2 正交状态模型,A-1;P1 只落地 L 轴 + P 轴地基)**
- lifecycle(L)/ reachability(R)/ processing·index-generation(P)/ freshness(F)为四条独立状态轴,禁止合并为组合枚举;混合态必须可表达(如 ACTIVE×UNREACHABLE×FRESH、SUPERSEDED×READY);
- L 轴词汇(权威定义 = S2 §2):DISCOVERED / ACTIVE / SUPERSEDED / MISSING_CANDIDATE / DELETED(DELETED = 墓碑,保留元数据+版本链至 GC);
- P 轴词汇:PENDING / PROCESSING / READY / FAILED / RETIRED;
- **P1 不实现** R 轴与 F 轴策略(P2),不实现任何 freshness 语义;
- 检索资格派生式(L=ACTIVE ∧ 源 enabled ∧ active generation READY)作为 P1 的可观测定义落地,但**逻辑资格门/时态执行属 P3**——P1 只需该派生为真且可检测。

**FC-3(I-5 生成模型,D-2/D-3 冻结)**
- 双代共存 + 显式 active generation;激活 = 从服务视角**原子**的指针翻转(PG 权威;服务选择按 D-2 = active_generation 过滤方向);失败候选代不得破坏在服代;激活成功后旧代转 RETIRED;RETIRED 代按保留窗 GC(默认 30 天,可配,D-3);
- 生成生命周期冻结为:`PENDING → PROCESSING → READY → ACTIVE(在服) → RETIRED`,FAILED 为 READY 前终态旁路;
- **可观测验收语义冻结;物理实现细节(UUID 命名空间、属性落点、回填机制)保留为工程决策**(Freeze §6 SAFE TO DEFER 明示归属 P1 契约,由执行代理在 FC-3 框架内定)。

**FC-4(I-6 删除/生命周期安全——P1 只提供状态与转换原语)**
- 原语必须就绪:ACTIVE / SUPERSEDED / 墓碑(DELETED,逻辑删除,非立即物理销毁)/ RETIRED 代 / successor·alias 关系;
- **P1 不得实现** P2 的消失确认策略(完整清单宽限轮数、探针、对账循环):这些机制就位后调用 P1 原语即可,不得要求 P2 发明新存储语义;
- 既有源级 #18 状态机与 P0-A 删除纪律原样保留,文档级新原语不得削弱它们。

**FC-5(#13 身份冻结兼容)**
- `source_id` 路径身份与确定性 UUID 家族保持兼容;普通内容更新**不得**造成身份分叉(身份保持、版本演进);
- metadata-only 变更不得分叉身份、不得触发不必要的重嵌入(在安全可避免的前提下);
- 跨路径同内容合法共存原则不变(D2:报告不合并;引用层 collapse 属 P3,不在 P1);
- 别名/接替语义按 D-5 冻结(自动接链可撤销;P1 落地数据地基,裁决操作面属 P5)。

**FC-6(变更类别)**
- 权威变更类别必须足以区分:内容变更(需新处理)/ 元数据-only 变更(避免不必要重嵌)/ 身份/接替变更;类别集 = UNCHANGED / CONTENT_CHANGED / METADATA_CHANGED / NEW_VERSION / SUPERSEDED 或契约等价表示;内部枚举命名 = 工程 HOW。

---

## Engineering Boundary(工程边界)

**Code EXPECTED(预期触碰域)**:`backend/db/models.py`(+ 新迁移脚本 `scripts/migrate_*`)、`backend/pipeline/ingest.py`、`scripts/sync.py`、`backend/retrieval/search.py`(服务选择只限 active-generation 透明过滤)、新增生成管理/版本服务模块(`backend/services/` 惯例位置)、相关测试(`tests/pipeline/`、`tests/db/`、`tests/services/`)。

**Code CONDITIONAL(按需)**:`backend/api/admin/`(仅当既有端点因 schema 演进需要兼容处理;**不得**新增 Admin Ops 端点/面板)、连接器文件(仅限 source-native 版本元数据字段的被动携带;**不得**重设计连接器语义)、`backend/config.py`(新配置项,如 GC 保留窗)。

**FORBIDDEN**:`widget/**`;检索/重排语义变更(alpha/RRF/reranker/证据预留,F-1' 谱系冻结);citation 行为变更;Trace A Release 1 代码回退或修改;`repair_corpus` / `vector_consistency` 既有红线弱化;生产部署。

**System**:PG schema 演进(加性、幂等)+ Weaviate schema/数据演进(幂等,先例 E17/E18)。两者都属本契约 Migration Boundary 管辖,本契约任务不写任何迁移/实现代码。

---

## Migration Boundary(迁移边界——实现阶段的义务,本任务不写代码)

1. **存量 documents 行**:不得丢行、不得改 source_id、确定性 chunk UUID 家族不变;旧行必须获得合法 lifecycle/版本/生成语义(如 lifecycle=ACTIVE + 初始版本行 + 归入初始 active generation),语义为工程 HOW,可观测结果为验收对象;
2. **存量 Weaviate 对象**:不得要求强制全量重嵌/全量重灌作为新模型生效的前提("避免在新模型被证明前强制破坏性全量重建"为硬约束);先例 = E17(零重嵌回填)+ E18(零向量迁移);
3. **在服行为**:迁移全程 serving 不中断;迁移后检索结果对既有语料行为中性(回填使过滤透明);
4. **幂等与 fail-closed**:迁移脚本可重复执行;失败时保留原状可回滚/可恢复,回滚路径必须文档化并演练(先例 E18 的"拒绝回滚"诚实语义可借鉴);
5. **部署衔接**:迁移须与生产部署编排兼容(迁移桥先于 rollout,v1.4.0 先例 E16);本任务不部署,但实现不得假设"手动机器上跑脚本"为唯一路径;
6. **测试库安全**:迁移测试必须走 TEST_DATABASE_URL 隔离(conftest drop_all 先例,E19),不得触碰开发/生产库。

## Compatibility Boundary(兼容边界)

除非被本契约显式取代,以下已接受行为原样保全:

- **Trace A 已接受答案行为**、引用语义、检索/重排语义(hybrid/RRF/reranker/证据预留)、5 源可见帽等全部不变;
- **同步成功/失败安全语义**不变:失败不推增量窗口、单源失败不中断批次、IngestFailures 结构化诊断(#45)保留;
- **源级生命周期与删除纪律**不变(#18、P0-A、#18 purge 验证段);
- **无附带产品行为变更**:P1 交付后,对未发生版本变更的语料,答案/引用/检索表现必须与 bb80c38 行为等价(回归面验证);
- **显式取代清单**(仅限以下两点,其余全保):① 文档内容变更的账本语义由"单行原位覆写"变为"版本链演进"(E19 ①号测试替换);② `--reindex` 的"先删后灌"不再是非破坏重建的权威路径,被"新代重建+原子激活"取代(E19 ②号测试替换);`--reindex` 旗标本身的处置(降级/重命名/保留兼容)属工程 HOW,但**先删后灌不得再是任何权威重建路径**(Gate P1-E)。

---

## Acceptance Gates(验收闸;全部须确定性可判定)

> 实现代理拥有测试的具体设计权;下列各闸给出 PASS 的可观测语义与最低验证面。所有仓内闸必须可在 mac local 测试环境(TEST_DATABASE_URL 隔离 + 本地 Weaviate)复跑。

### Gate P1-A — 持久真相(投影可重建)

**语义**:仅凭持久化权威真相(PG / 关联 content-addressed 存储)即可重建一个等价服务投影,**不依赖** Weaviate 现存对象为唯一来源。
**PASS 要求**:可复现的重建测试——给定持久真相,重建产出与在服投影**结构等价**(chunk 集合、逐 chunk 归一化文本、content_hash、计数一致;向量可由同嵌入模型再生——**不要求位相等**,嵌入设备/批次差异容忍为契约语义,实现须把等价判据写进测试);源已消失的文档同样可重建(此为与现状的本质区别,呼应 E7)。

### Gate P1-B — 版本完整性

**语义**:普通内容更新正确创建/演进版本状态;历史版本可审计;仅预期当前版本在服;metadata-only 变更不分叉身份。
**PASS 要求**:(a) 同路径连续两次内容变更 → 版本链 ≥ 3 节点(含初始),旧版本留痕可查询,`SUPERSEDED` 关系成立,检索只见当前版本;(b) metadata-only 变更(title/url/分类)→ 身份不变、无新内容版本、无重嵌(可由 embed 调用计数证明);(c) 同 hash 不同路径共存契约(E19)仍绿。

### Gate P1-C — 生成失败隔离

**语义**:N 代在服 → N+1 代开始构建 → N+1 代失败 ⇒ N 代持续原样服务;无部分替换、无破坏性清理、无服务中断。
**PASS 要求**:故障注入测试(嵌入失败/写库失败/验证不过三类至少各一)后断言:在服代对象集与激活指针均未变化、检索结果未变化、失败代状态可观测(FAILED + 失败证据)。

### Gate P1-D — 原子激活

**语义**:N 代在服、N+1 代 READY → 激活 ⇒ 服务切换为 N+1 是**单一有效状态转移**;外部观察不到混合/半切换代;N 仅在激活成功后转 RETIRED。
**PASS 要求**:激活过程中的并发读测试(或等价的转移原子性证明)——任一读取时刻,观察到的服务代要么全 N 要么全 N+1;激活指针翻转失败时服务保持 N(fail-closed);N 转 RETIRED 严格后于 N+1 生效。

### Gate P1-E — 全量重建零服务损失

**语义**:全量重建期间,零"因先删上一代导致"的服务中断;破坏性 `--reindex` 不再是权威重建路径。
**PASS 要求**:全量重建走生成路径(新代构建 → 验证 → 原子激活);重建全程检索可用且结果逐步收敛;兼容边界 §显式取代 ②落实(测试替换 + `--reindex` 先删后灌不再可达,或仅存于显式废弃标记下不可为权威路径)。

### Gate P1-F — 接替/墓碑地基

**语义**:版本接替关系有表示;墓碑化不要求立即物理删除;P2 未来可直接调用生命周期转换原语。
**PASS 要求**:(a) 接替链查询 API/服务存在且被测试覆盖;(b) 墓碑化后:元数据+版本链保留、对象退出服务资格、物理清除仅发生在 GC 窗口(D-3 默认 30 天,可配);(c) 提供 P2 将消费的显式转换原语(带前置条件校验),P2 无需新存储语义即可驱动;**不得**实现 P2 消失确认策略本身。

### Gate P1-G — 遗留迁移

**语义**:以逼真遗留状态(bb80c38 形态:存量 documents 行 + 存量 Weaviate 对象)证明迁移正确。
**PASS 要求**:迁移成功;迁移后现有 active 文档全部可服务且检索行为中性;幂等(重复执行 no-op);中途失败 fail-closed(原状可恢复);回滚/恢复路径文档化并测试;**全程零重嵌、零强制全量重建**。

### Gate P1-H — 回归

**语义**:无未解释回归。
**PASS 要求**:后端全量测试绿(bb80c38 谱系报告全量 2227 绿,F-1' 集成记录;CI 跳过集除外,E19);显式取代的两测试按 Compatibility Boundary 替换且其替换件覆盖原防护意图(防抢占/防误删意图不得丢失);admin/widget vitest 与 tsc 零改动要求(本契约 EXPECTED 域不含前端;若 CONDITIONAL 兼容触碰发生,需连带用例);`ruff check` + `ruff format --check` 干净;任何偏离 baseline 的测试结果逐条解释。

---

## Regression Requirements(回归要求汇总)

- 全量:`TEST_DATABASE_URL=…ask_ai_test uv run pytest tests/ -q`(隔离红线不变);
- 重点保全族(必须绿):tests/db/test_documents_pk.py、tests/pipeline/test_ingest_ledger_identity.py(除显式取代件)、tests/pipeline/test_ingest.py(除显式取代件)、tests/db/test_migration_path_identity.py、tests/pipeline/test_sync.py(除显式取代件)、tests/scripts/test_sync_run_core.py、test_sync_gap_heal.py、test_sync_coverage.py、tests/services/test_vector_consistency.py、test_corpus_repair.py、test_source_lifecycle.py、tests/api/admin/test_data_source_delete*.py;
- 生命周期族验收语料锚(Freeze §7):#48 ghost 半径与 KNOWLEDGE-STALE-LEDGER 死账类场景作为 Gate P1-A/P1-F 的动机案例出现在测试叙事中;其**完整产品修复**仍归 P2(citation)/P2(对账),P1 只证明原语就绪;
- 全量回归 + 各 Gate 测试纳入执行报告;CI(build-image.yml)现状跳过集不因本任务扩大。

## Runtime Acceptance Requirements(运行时验收要求——部署后;本任务不部署)

仓内绿是 P1 收口的**必要非充分**条件。P1 最终闭环必须以真实部署观测证明:

1. 生成切换期间服务持续可用(无 5xx/空结果窗口可归因于切换);
2. 注入失败候选生成(真实环境)后在服代完好;
3. 运行时生成身份与预期一致(health/诊断可查,先例 = verify_runtime_identity 双断言模式);
4. 重建路径对真实持久状态可执行(P1-A 的生产形态);
5. 不存在意外在服的第二个 active 代;
6. 冒烟证据(截图/请求记录)按仓库 Real-World Gate 惯例归档(先例:v140-runtime-20260910 证据目录模式)。

执行代理须在执行报告中交付上述 Runtime Acceptance **计划**(可执行步骤清单),实际执行归部署授权窗口,不在实现任务内。

---

## Forbidden Scope(显式禁止吸收;违反即违约)

P1 **不得**吸收:freshness SLA;source_verified_at 操作语义;源可达性策略;slim/完整清单对账循环;消失确认逻辑;引用探活/citation validity 作业;INVALID 引用策略实现;检索逻辑资格门与时态执行;CURRENT/HISTORICAL 执行;UNCLASSIFIED 激活语义(P3 契约前必须回 Product);WooCommerce 变体摄取;#28 变体收口;证据预留扩展;新排序算法;Claim/Graph/GraphRAG;Admin Knowledge Operations 端点/面板/知识 UI 实现;广泛连接器重设计;Trace A Bug Fix 残余(F-1' 残余两 Scope Expansion 提案与本文无关);GC 策略变更(D-3 已定基,仅落地接口)。共享文件触碰不构成导入后期行为的授权。

## Deliverables(交付物——实现任务)

1. 隔离 Trace B 实现分支(不并入 main 直至 Release 1 收口或 Role A 变更基线;Freeze §4 纪律);
2. PG schema 演进 + 幂等迁移脚本(含遗留回填语义)+ 迁移演练测试(真实 DDL 先例 E18/E19 模式);
3. Weaviate 演进(如需)幂等脚本 + 零重嵌回填路径(E17 模式);
4. 生成管理/版本/接替原语服务模块 + ingest/sync/search 接线;
5. Gate P1-A..P1-H 测试实现与通过证据;
6. 执行报告 `docs/engineering/tasks/tb-p1-lifecycle-foundation-execution.md`(v2.0 §77 字段惯例):逐 Gate 结果、回归账本、迁移爆炸半径实录、Runtime Acceptance 计划;
7. 回复:报告路径 + commit SHA + 状态(P1-LIFECYCLE-FOUNDATION-IMPLEMENTATION = CANDIDATE READY / BLOCKED)。

## Dependencies(依赖)

- S1-S5(权威源;#13 身份链为身份演进的直接前置);
- 既有机制:#18 源生命周期服务、sync_requests/sync_runs 执行面、vector_consistency/corpus_repair(重建与一致性设施复用点)、生产部署编排迁移桥(部署期,非本任务);
- 环境假设:mac local = 测试主场(四环境策略);TEST_DATABASE_URL 隔离;本地 Weaviate 可用于 Gate 演练;
- Trace A 隔离:实现分支基于本契约分支谱系;bb80c38 主线冻结期内不合入。

## Risks(风险)

| # | 风险 | 缓解方向(契约级) |
|---|---|---|
| R1 | 生产库/大集合上迁移失败(v1.4.0 迁移未跑先例) | 幂等 + fail-closed + 部署桥前置 + Gate P1-G 真实 DDL 演练 |
| R2 | 持久内容存储带来写入放大/库膨胀(D-1 载体未冻结) | 载体=工程决策(可选 content-addressed/压缩/去重);Gate P1-A 只验可重建性 |
| R3 | 重建等价判据过严(嵌入位相等不可达:GPU/CPU、批次差异) | 契约已定:结构等价 + 同模型可再生向量,不要求位相等(Gate P1-A) |
| R4 | active-generation 过滤引入检索性能退化 | 属工程 HOW;执行代理须在报告中给出查询面证据(先例:where-filter 已在用,Discovery §3 Haystack 结论 REUSE DIRECTLY) |
| R5 | 双写(账本/投影)迁移窗口不一致 | Gate P1-D fail-closed 语义 + P1-G 中性验证;一致性披露设施(E14)保留兜底 |
| R6 | 与 Trace A Release 1 收口竞态(共享文件) | Freeze §4:先获集成闸方所有,另一方 rebase 契约化;实现分支不并 main |
| R7 | 范围蠕变(吸收 P2+ 行为) | Forbidden Scope 逐条对照;Role A 评审把关 |

## Open Engineering Choices(刻意保留给执行代理的工程选择)

以下均为 ENGINEERING DESIGN CHOICE(非产品开放问题,不得借"开放"之名重开产品语义):

1. **持久内容载体**:PG 表 vs 关联 content-addressed 存储 vs 混合(D-1 显式保留;含压缩/去重/引用计数策略);
2. **生成的物理表示**:在 D-2 冻结方向(active generation 权威在 PG + 原子翻转 + 服务按 active 代过滤)框架内,generation 标识落点(对象属性/集合组织)、UUID 命名空间扩展方案(discovery §4B `source_id#generation#chunk_index` 或等价)、回填机制自定;
3. **版本模型的 schema 细节**:DocumentVersion 表形态、version_seq/valid_from/superseded_by 的具体列设计(产品语义要求的最小字段集见 FC-2/FC-5/FC-6;精确 schema = HOW);
4. **迁移工具形态**:继续幂等脚本族 vs 引入 Alembic(E16 现状两可;满足 Migration Boundary 即可);
5. **连接器 source-native 版本字段的落地顺序与承载方式**(git commit_sha / web lastmod / woo date_modified / fs mtime+size;字段支持为契约要求,逐连接器填充可渐进,不得为此重设计连接器行为);
6. **重建验证装置形态**(Gate P1-A 的测试/工具实现);
7. **`--reindex` 旗标的最终处置**(废弃/重命名/兼容保留),以 Gate P1-E 为准。

---

## Execution Handoff(执行交接——增量提示词)

```text
# 任务:TB-P1-LIFECYCLE-FOUNDATION(Trace B Phase 1 —— 知识生命周期地基实现)

先读权威契约(按序):
- docs/product/initiatives/KNOWLEDGE-INTEGRITY-INITIATIVE-FREEZE.md(97cac3f,§2/§5/§7)
- docs/engineering/tasks/tb-p1-lifecycle-foundation-plan.md(本契约 = 唯一工程权威)
- docs/implementation/CAMTHINK_V1_DATA_INTEGRITY_RECONCILIATION_{DISCOVERY,IMPLEMENTATION}_2026-09-03.md(#13 身份链)

Source of Truth:仓库现状证据 + 上述冻结文档;调查基线 main bb80c38;分支基线 97cac3f。
Objective:使"投影可重建、失败不回退、接替可追溯"首次成立(契约 Objective 节八项性质)。
Frozen Product Contract:FC-1..FC-6(I-1/I-2/I-5/I-6 + D-1/D-2/D-3/D-5 + #13 兼容 + 变更类别)——逐条不可违反。
Hard Boundaries:Engineering/Migration/Compatibility/Forbidden 四节;零 P2+ 行为吸收;
  Trace B 分支隔离(不并 main);不部署;不碰生产;显式取代仅限两测试件(Compatibility 节)。
Acceptance:Gate P1-A..P1-H 全绿 + 全量回归绿(显式取代件按契约替换)+
  执行报告含 Runtime Acceptance 计划。
Deliverable:实现分支 commit + 迁移脚本 + Gate 测试 +
  docs/engineering/tasks/tb-p1-lifecycle-foundation-execution.md(v2.0 §77 字段);
  回复报告路径 + commit SHA + 状态(CANDIDATE READY / BLOCKED)。

红线:不动 widget/检索重排语义/citation 行为/Trace A 发布代码;删侧只点名 UUID;
  零重嵌遗留迁移;先删后灌不再成为权威重建路径;报告前不得宣告完成。
```

(契约任务到此为止:不实现、不迁移、不并 main、不触碰生产。)
