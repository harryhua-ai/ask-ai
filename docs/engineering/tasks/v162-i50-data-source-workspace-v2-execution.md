# #50 Admin Data Source Workspace V2 — B1 执行报告(v1.6.2)

任务:B1(#50);合同:`docs/engineering/tasks/v162-i50-data-source-workspace-v2-contract.md`(FROZEN);
计划:`docs/engineering/tasks/v162-iteration-plan.md`(§3 所有权矩阵 / §5 治理 / §8 B1 prompt)。
日期:2026-09-12。

## 1. Starting main SHA

- 基线:origin/main = **0590a82**(分支 `b1/data-source-workspace-v2-20260912` 自此创建;迭代计划正文写 57717ea 谱系,实际起点以 Role A 派单指令 0590a82 为准)。

## 2. Changed files(origin/main..HEAD)

```
 admin/src/App.tsx                                 |   3 +
 admin/src/hooks/useDataSourceWorkspace.ts         |  81 +
 admin/src/lib/dataSourceLifecycle.ts              | 212 +
 admin/src/pages/DataSourceDetail.tsx              | 612 +
 admin/src/pages/DataSources.tsx                   |  16 +-
 admin/src/types/dataSourceWorkspace.ts            | 119 +
 admin/tests/DataSources.test.tsx                  |  47 +-
 admin/tests/dataSourceLifecycle.test.ts           | 188 +
 admin/tests/dataSources/DataSourceDetail.test.tsx | 466 +
 backend/api/admin/data_sources.py                 | 400 +-
 backend/api/admin/schemas.py                      | 112 +
 tests/api/admin/test_data_source_workspace.py     | 533 +
 12 files changed, 2774 insertions(+), 15 deletions(-)
```

提交谱系(候选前):
- `0ab821a` test(i50-b1): RED(三份新测试文件先行)
- `c2a1da0` feat(i50-b1): 实现(端点族 + 映射模块 + 详情工作面 + 列表入口)
- (本报告提交)

## 3. Implementation decisions(工程 HOW,合同不规定处)

### 3.1 端点形状(全部只读 GET,挂在既有 data_sources router,零新 router 注册)

| 端点 | 语义 |
| --- | --- |
| `GET /api/admin/data-sources/{source_id}/documents` | 逐源文档清单:`page/size`(默认 1/20,size≤100)+ `lifecycle`(L 轴词表过滤,非法值 400)+ `search`(title/url/复合身份 ilike 子串,`%`/`_`/`\` 转义)。响应含过滤后 `total` 与**不受过滤影响**的全源聚合:`ledger_total`(LIKE 前缀口径,与 `/sync-health` document_count 同源)、`lifecycle_counts`(逐 L 轴)、`serving_count`(SERVING ∧ 现行版本可解析)、`current_count`(active ∧ 现行版本可解析)。排序 updated_at desc nulls last, source_id。 |
| `GET /api/admin/data-sources/{source_id}/documents/detail?doc_source_id=…` | 单文档真相。**复合身份 `<source_id>/<branch>/<rel_path>` 含斜杠 → 经 query 参数传递**,规避 path 段斜杠编码歧义(路由设计决策,前端 hooks 同约定)。文档行缺席/不属于本源 → 404 `后端无此记录`;`current_version`/`generation` 缺席 → 显式 `null`。真相载荷:lifecycle、serving、chunk_count、created_at/updated_at(仅权威时间戳)、superseded_by/superseded_at、deleted_at、现行版本(version_seq/status/chunks_total=持久 chunk 账本计数/source_version/valid_from/valid_to)、所属生成(ordinal/status/doc_count/chunk_count/failure/activated_at/retired_at)。 |
| `GET /api/admin/data-sources/{source_id}/generations` | 逐源生成列表,ordinal 倒序;`failure` JSONB 原样透出;`serving_ordinals` = 权威在服代序集合(active_generation 口径)的源内投影。 |

- **在服判定(权威,前端零重判)**:`Document.lifecycle ∈ DocLifecycle.SERVING (active, missing_candidate)` ∧ `current_version_id` 可解析到 document_versions 行 —— 与 `active_generation_ordinals` 同一关系语义(missing_candidate 宽限期保上一代服务)。
- **在场诚实纪律**:行/真相仅暴露后端真实存在的列;`source_version` 为 null 原样;不出现 content-role/discovered/last-seen。
- RBAC:三端点均 `require_role("admin","editor","viewer")`(viewer 可读);无任何 POST/PATCH/DELETE。

### 3.2 运营三桶逐态映射(B1 冻结设计;实现 = `admin/src/lib/dataSourceLifecycle.ts` `bucketOfDocument`)

| L 轴状态 | 桶 | 可解释理由 |
| --- | --- | --- |
| `active` ∧ serving | **Current** | 现行版本可解析的权威在服集合(current_version_id ⋈ SERVING 的严格无风险子集) |
| `active` ∧ ¬serving(现行版本悬挂) | **Needs Attention** | 账本行存在但现行版本缺失 → "现行版本:后端无此记录(无法证明在服)" |
| `missing_candidate` | **Needs Attention** | 源同步报告缺失的权威标记;原因文案同时说明宽限期内仍由上一代服务 |
| `discovered` | **Needs Attention** | 账本仅有发现记录,尚未灌入(无现行版本) |
| `superseded` | **Retired** | 已接替;原因 = superseded_by(缺接替者记录 → "接替者:后端无此记录")+ superseded_at |
| `deleted` | **Retired** | 墓碑;原因 = deleted_at(墓碑时间) |
| 未知未来状态 | **Needs Attention** | 原文透传,不静默、不编造语义 |

源级桶计数(同一映射的聚合投影,数学封闭):`retired = superseded + deleted`;`current = current_count`(权威 SQL 计数);`attention = ledger_total − current − retired`。

### 3.3 前端详情工作面(`admin/src/pages/DataSourceDetail.tsx`)

- 路由 **`/data-sources/:sourceId`**(对 #51 的 FROZEN INTERFACE,未改动);列表行新增「详情」按钮进入(只读下钻),列表页同步/编辑/删除/可观测性展开等既有能力零改动。
- 信息层级(合同 UX Intent 逐项):源身份与配置摘要(复用 `/data-sources` 列表读面与 `TYPE_LABELS`/`sourceLocation`)→ 同步与健康(复用 SyncStatusPanel/SourceHealthPanel/SyncHistoryPanel 三面板与既有 `/sync-status` `/sync-health` `/sync-runs` 读面)→ 内容清单(搜索防抖 300ms、生命周期下拉过滤、分页、行展开「查看真相」)→ 索引生成可见性 → 最近变化(同步历史)。
- **主操作仅**:查看/搜索/过滤/分页/既有同步触发(展开的 SyncStatusPanel 内 onRetry → 既有 `useTriggerSync`)。**零**编辑/删除/重索引等破坏性控件。
- LoadError 三态纪律:清单/真相/生成三个新查询失败均 LoadError(真相用 compact 变体);空源/空生成显式空态文案(生成缺席含"后端无此记录")。
- 未配置源(id 不存在于 data_sources)→ 显式「后端无此记录」卡片。

### 3.4 计数真相(AC5)呈现

- 已证:账本文档数(ledger_total)、逐 L 轴计数、在服(含宽限)计数、三桶计数、生成 doc_count/chunk_count、现行版本持久 chunk 计数(chunks_total)。
- 显式注记(不可证处):「已索引(向量库)计数不由账本直接证明——实际索引规模以最近同步一致性证据(健康面板)与在服代计数为准」。不渲染任何伪造的 indexed 列。

## 4. Reused vs new surfaces

**复用(零语义改动)**:三面板组件(SyncStatusPanel/SyncHistoryPanel/SourceHealthPanel)、`/sync-status` `/sync-health` `/sync-runs` `/analytics/source-health` 读面、apiFetch、LoadError、Pagination、Badge 变体、DataSources 页 `TYPE_LABELS`/`sourceLocation`(改为导出复用,不复制第二份)、require_role viewer 读约定、`DocLifecycle`/`GenerationStatus` 词表、LIKE 前缀 document_count 口径。

**新增**:后端三只读端点 + 六个 schema;`admin/src/lib/dataSourceLifecycle.ts`(单一权威映射模块);`admin/src/pages/DataSourceDetail.tsx`;`admin/src/hooks/useDataSourceWorkspace.ts`(+types 文件,独立于既有 hooks 文件以最小化集成冲突面);App.tsx 一条路由;DataSources.tsx 一个入口按钮。

## 5. RED evidence

| 套件 | RED 实证 |
| --- | --- |
| `tests/api/admin/test_data_source_workspace.py` | **17 failed / 4 passed**(端点不存在 → 404;非法过滤 400 未实现;lifecycle_counts 键缺失)。提交 `0ab821a`。 |
| `admin/tests/dataSourceLifecycle.test.ts` | 模块缺失 → transform 失败(Test Files 1 failed, no tests)。 |
| `admin/tests/dataSources/DataSourceDetail.test.tsx` | 页面/hook 模块缺失 → transform 失败(no tests)。 |

(映射模块首次 GREEN 时暴露 2 处实现缺陷并修正:`servingTimestamp` 误传对象导致原因文案出现 `[object Object]`;测试对时间戳函数用法修正——RED→fix→GREEN 实证。)

## 6. Tests & results

| 套件 | 结果 |
| --- | --- |
| 后端 targeted:`tests/api/admin/test_data_source_workspace.py` | **21 passed**(GREEN) |
| 后端 adjacent 回归:test_data_sources / _c10 / _c9_edit / test_sync_health_derivation | 16 passed |
| admin vitest 全量 | **348 passed / 348**(48 files),含新增 38(映射模块)+ 13(详情面)+ 46(列表页,含新详情入口导航用例) |
| 后端全量回归:`pytest tests/ -q`(TEST_DATABASE_URL=ask_ai_test,lock wrapper 串行,HF_HUB_OFFLINE=1) | **2448 passed / 8 skipped / 0 failed**(§6.1 含 7 例环境性失败定位与复绿记录) |
| ruff(改动文件:data_sources.py / schemas.py / test_data_source_workspace.py) | **0 error** |

### 6.1 全量回归

- **`pytest tests/ -q`(TEST_DATABASE_URL=ask_ai_test,lock wrapper 串行,HF_HUB_OFFLINE):`2448 passed / 8 skipped / 0 failed`(113s)。**
- 过程中的 7 例环境性失败(非本任务代码)已定位并复绿:
  - 4× `tests/embedder/test_bge.py` + 2× `tests/pipeline/test_ingest_ledger_identity.py`:worktree 本地 HF 模型缓存不完整(bge-m3 权重缺失/缺 reranker)→ 以 symlink 共享主仓完整缓存后 22+2 例全绿;
  - 1× `tests/test_lifespan_smoke.py`:`create_all` 与并发 agent 对共享 ask_ai_test 的并发建表竞态(pg_type 唯一冲突)→ 单独重跑 8/8 绿;
  - 教训(留给 Integration):全量回归必须 `HF_HUB_OFFLINE=1` + 完整本地模型缓存,否则 HF 网络拉取会使套件假死。

## 7. Runtime verification scope(合同 §Runtime;实际执行 = Integration B / 部署验收阶段)

走查脚本(生产或生产等价全栈伺服面;全程零 SSH/SQL/Weaviate 操作,比对仅在验收取证时使用):

1. **真实源 A(wiki-documents-local)**:列表页 → 行「详情」→ 内容清单搜索一条已知文档标题 → 展开真相:确认 lifecycle=在服(active)、serving=在服、现行版本 #N 与生成归属、canonical 身份 `<source_id>/main/<rel_path>` 与 URL 可见。
2. **真实源 B(woocommerce-mall)**:详情面内容清单过滤 `active` → 任选商品页行:确认可用状态徽章与 canonical URL(url 列/真相面板);对照 `/sync-health` 该源 document_count 与清单 ledger_total 一致。
3. **真实 Needs-Attention 样例**:利用生产 `index_generations` 中 **failed 的 ordinal=1 审计行**(或任一 missing_candidate 文档):生成区显示「构建失败」badge + failure JSONB 原文(error/stage);文档行则显示缺失原因(宽限文案)。
4. **psql 抽查比对**(仅验收取证):`SELECT lifecycle, chunk_count, updated_at FROM documents WHERE source_id LIKE 'wiki-documents-local/%' LIMIT 5;` 与界面行值逐项一致;`SELECT ordinal, status, failure FROM index_generations WHERE source_id='<src>' ORDER BY ordinal DESC;` 与生成区一致。
5. **RBAC 抽查**:viewer 登录可见详情面全部只读内容,无编辑/删除控件。

本任务内已完成的等价验证:真实本地 PG(ask_ai_test)上以账本真实行驱动 21 个端到端断言(含空源/全退役源/失败生成/缺席记录),UI 侧以 fixture 数据走查四问与三桶(13 例)。生产走查按迭代计划 §4/§5 推迟至 Integration B 组合树与部署验收执行。

## 8. Scope audit(显式证明)

- **零生产 mutation**:分支未 merge、未部署、未触碰生产;新端点零写路径(POST/PATCH/DELETE 缺失,测试断言 405);测试仅在隔离库 ask_ai_test 用随机前缀数据自清理。
- **零 deploy**:无 CI/镜像/compose 变更。
- **零语义变更**:P1 lifecycle/generation 状态机零改动(仅 `import` 词表);检索/排序/引用零改动;既有端点零行为改动(16 例 adjacent 回归绿)。
- **只读端点族**:三端点全部 GET + viewer 可读。
- **FORBIDDEN 逐项核验**:
  - per-item 破坏性控件:无(详情面主操作仅查看/搜索/过滤/分页/既有同步触发);
  - 独立 Knowledge 模块:无(详情面挂在数据源路由下);
  - Overview 标签页复制:无;
  - 虚构字段:无(content-role/discovered/last-seen 在类型、schema、UI 三层均不存在);
  - Weaviate 直连:无(后端读面仅查 Postgres 账本;前端零 Weaviate 调用);
  - retention/时长设置 UI:无;
  - P1/lifecycle/generation 语义变更:无。
- 其他 track 面(Analytics/tech、SystemInfo/system)零触碰(git diff 仅 §2 清单文件)。

## 9. Unresolved risks

1. **租户隔离冲突面**:`admin/tests/DataSources.test.tsx`(加 MemoryRouter 包裹 + 1 用例)、`admin/src/types/api.ts` 未动、`useDataSources.ts` 未动——预期冲突面已压到最小;B2 的 `/data-sources/{source_id}` 深链在本分支已可用。
2. **大源清单性能**:LIKE 前缀 + 每源 5 次聚合查询(总/逐态/在服/Current/分页),源文档数十万级时可能需索引调优(`documents` 现有 source_id 前缀查询与 /sync-health 同口径,无新增慢于既有模式);未做分页游标化(合同未要求)。
3. **搜索语义**:ilike 子串命中 title/url/身份;无分词/排序权重(检索语义变更属 FORBIDDEN,保持最小)。
4. **删除在途源**:源处于 delete_requested/deleting 时清单仍可读(账本行未删)——如实呈现,无特殊拦截(只读观察面语义)。
5. **生成列表无分页**:按源 ordinal 数量小(同步构建节奏),暂全量倒序返回;超大历史源可后续加 page(非合同项)。
6. **运行时走查未执行**:按计划显式推迟至 Integration B/部署;Issue 关闭前置依赖生产可见面核验。

## 10. Candidate SHA

- 候选 = 本报告提交时 HEAD:`b1/data-source-workspace-v2-20260912`(0ab821a → c2a1da0 → 本提交)。

## 11. Verdict

**B1-DATA-SOURCE-WORKSPACE-V2 = CANDIDATE READY**。
