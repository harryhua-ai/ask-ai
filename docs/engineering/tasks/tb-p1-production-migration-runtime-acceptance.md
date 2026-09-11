# TB-P1 — PRODUCTION MIGRATION / RUNTIME ACCEPTANCE 执行报告

Final verdict: **TB-P1 PRODUCTION = PARTIAL**

(第一部分 §1–13:迁移中止于 NUL,STOP — CODE FIX REQUIRED → 矫正任务;
第二部分 §14–22:v1.6.1 续执行——矫正已并 main、发布 v1.6.1、部署桥完成
迁移、rollout success、真实流式/GC dry-run/终局对账全 PASS;**非破坏重建
(Phase 8C)因新发现产品缺陷(RemoteSyncEmbedder 零客户端切批 → 422)被
阻断**——CODE FIX REQUIRED(新矫正);fail-safe 全部成立,回滚未触发——
无需回滚)

- 授权权威 main(任务起点):`2d7e416`;第一部分发布树 tag:**v1.6.0** @ `0502bc4`;
  第二部分发布树 tag:**v1.6.1** @ `98ab795`(现生产)
- 执行窗口:2026-09-11 12:14–12:55 UTC(基线 `20260911-121442`);
  续执行 2026-09-11 ~14:00–16:05 UTC(矫正集成→v1.6.1→迁移→验收)
- 执行通道:操作员授权 SSH(43.132.189.162,ubuntu;仓库变量
  PROD_SSH_HOST/USER)+ 冻结镜像 compose 一次性 sync 承载(与部署编排
  迁移桥同载体;发布镜像身份断言先行)

---

## 1. Pre-migration 生产身份(Phase 1 基线)

| 项 | 值 |
| --- | --- |
| 版本/SHA | **v1.5.0 @ `bb80c389c6d3`**(app_mode=production;/health 与镜像内 RELEASE.json 双证:built 2026-09-11T04:56:56Z,CI 34563566836) |
| GitHub Deployment | 6386829992 = success(2026-09-11T05:06Z) |
| 容器 | backend(healthy,RestartCount=0)/ sync-cron / sync-executor 全 v1.5.0;postgres16 / weaviate 1.28.0(healthy,up 3 周) |
| PG | documents 12,000 行 × 12 列(**无任何 P1 列**);P1 三表 **NONE**;15 enabled 数据源 |
| Weaviate | Document 类 21 properties(**无 generation_ordinal/generation_id**);**147,999 objects**;无备份模块 |
| 同步健康基线 | sync_log 7 天:2,541 总 / 130 failed(既有基线,5.1%) |
| 每源规模 | 最小 neomind-dashboard-local 17 篇 … 最大 ne301-local 5,534 篇 |

## 2. 备份 / 回滚证据(Phase 1)

- PG:`~/ask-ai-backups/ask_ai-pre-p1-20260911-121442.sql.gz`(9.7 MB,pg_dump 全量)
- Weaviate:`~/ask-ai-backups/weaviate-pre-p1-20260911-121442.tgz`(654 MB,volume `tesla-t4_weaviate_data` 快照)
- 回滚目标:**v1.5.0**(dispatch 重部署即可;P1 全部变更加性——旧代码忽略新
  列/新属性,故回滚不强制要求恢复 Weaviate;必要时两份备份均可恢复)
- 配置指纹:deploy/prod/docker-compose.yml md5 `70fd086528e7c866f0f5b3e828e6c17d`

## 3. 发布工程(迁移前置)

- 任务起点后 main 又前进 2 个正交 project-automation 提交(治理线并发工作);
  发布树冻结于 **v1.6.0 = `0502bc4`** = 接受 P1 树(2d7e416)+ 2 个**仅测试**
  的 CI 发布管线修正(见 §4)。
- 镜像:ghcr.io/harryhua-ai/ask-ai:v1.6.0(RELEASE.json 断言 version=1.6.0
  git_sha=0502bc4dc5ae…,CI 34599224380,test + build-and-push 双绿)。
- GitHub Release v1.6.0 已创建(deploy Guard 前置)。

## 4. 发布管线阻断修正(仅测试;零产品代码)

两次 tag 构建失败,逐一根因修复(均为本任务在发布管线新暴露的**测试环境
健壮性**问题,非 P1 语义):

1. `34597022450`:builder/projection 集成门 fixture 直连本地 Weaviate——
   v4 client 连接失败为 **raise** 而非返回 None,CI 无 Weaviate → fixture
   ERROR → build 门断。修复 = try/except → pytest.skip(与既有真实
   Weaviate 集成套件同模式)。commit `bf262b8`。
2. `34598547246`(两连败):`tests/runtime/test_manager.py::test_query_
   preempts_queued_sync`——release_s1 后 s2 worker 线程调度与主线程
   `index()` 断言竞态(Trace A 既有潜伏 flake,CI 慢机两次实证,本地恒绿)。
   修复 = 有界等待 s2:start 出现后再断言;排序契约一字未改。commit `0502bc4`。

## 5. Verify-Only(Phase 2)——诚实失败,分类如下

`--verify-only` 于冻结镜像内对生产执行 → **崩溃**:
`UndefinedColumn: documents.current_version_id does not exist`。

分类:**工具缺陷,非生产异常**——verifier 为「迁移后校验器」语义,对
legacy 库不能表达 eligible(本任务 gate 测试只覆盖了先迁移后验证路径,
legacy-only 路径从未被测试)。零 schema/数据变更、零伪 PASS(fail-closed
成立)。**未强行通过验证**;迁移资格改由直接对账证据独立确立(§6)。
建议(授权后另行处理):verify-only 增加 legacy 态识别(缺列 → 报
`{legacy: true, eligible: true}`)。

## 6. 迁移资格独立证据(替代 verify-only 的资格判定)

- PG:无任何 P1 列/表 = 纯净 legacy(无部分迁移残留);orphans=0;
  duplicate source_id=0;
- **对账:PG SUM(chunk_count) = 147,999 == Weaviate objects = 147,999**
  (账本↔投影逐对象一致)。

## 7. 迁移执行(Phase 3)——fail-closed 中止(本报告核心事件)

冻结镜像一次性 sync 承载(与部署桥同载体),日志
`~/ask-ai-backups/p1-migration-20260911-121442.log`:

| 阶段 | 结果 |
| --- | --- |
| 1 PG 补列/建表/索引 | ✅ 完成(5 列 + 3 表 + 2 索引,后续清点确认) |
| 2 版本回填 | ✅ 完成 **12,000/12,000**(legacy 代 ordinal=0;进度日志在案) |
| 3 Weaviate 补属性 | ✅ 完成(≤首批 flush 批量的对象已补 generation 属性,加性无害) |
| 4 内容真值回填 | ❌ **fail-closed 中止**:`ValueError: A string literal cannot contain NUL (0x00) characters.` |

**持久化落点(精确清点)**:document_version_chunks = **0 行**(首批 flush
的 chunk 插入即中止;versions/gens/schema 全在)。部分状态被加性设计约束在
无害面:旧代码(v1.5.0 在服)对新列/新属性零感知,服务零影响。

## 8. NUL 数据实证(只读全量扫描,147,999/147,999)

**2,437 objects / 5 documents** 含 NUL 字节——全部为早期 GitHub 连接器把
**二进制工件当文本**灌入的残留(`libcrypt.so.1*` 576、`libpcre2-8.so.0*`
1,836、`nunito-v16-latin-regular.woff2` 25;均属 `ne503-apic-69d3594b` 源)。
PG TEXT 物理不可存 NUL ⇒ I-1 持久真值对这些 chunk 原样不可满足;这批
"文本" 本无语言内容(二进制噪声),现役 TechnicalSafetyPolicy(G1 二进制
嗅探)已不会再摄入同类内容。

**STOP — CODE FIX REQUIRED**:修复属数据保真策略决策(迁移拷贝时剥离
`\x00` / 跳过并如实上报缺口 / 先修复这 5 篇文档数据),不在本任务授权内
自行改动已接受的迁移工具。中止后迁移容器已退出,无残留进程。

## 9. Rollout 决策:刻意不执行(Phase 5 未启动)

新代码在内容回填未完成时激活检索会 **fail-closed 成空集**(在服代过滤指向
legacy 代,而多数对象尚未补 generation 属性 → 过滤后零命中)= 全站检索
中断。故 rollout 等待迁移完成后另行执行(正式 deploy 编排按 tag 正常发起,
其自带 launcher_presentation 幂等迁移,与 P1 无冲突)。

## 10. 运行时健康(全程未被迁移影响)

- /health 三时点(基线/中止后/收尾)恒 `{"ok","1.5.0","bb80c389…"}`;
- www.camthink.ai 200;
- 零容器重启、零新增 DB/Weaviate 错误、零 ingestion 行为变化。

Phases 6–11(在服代契约生产实证 / 真实流式路径 / 非破坏重建 / 生命周期
转换 / GC dry-run / 终局对账)在迁移完成前**不具备执行前提**,依序顺延至
修复后的继续执行任务;四态契约本身已由合并树 12/12 门测试与生产代码
(= tag 冻结树)保证。

## 11. 异常与残余风险

1. **NUL 5 文档 / 2,437 对象**(§8)——迁移阻断根因;修复决策待授权。
2. **verify-only legacy 态崩溃**(§5)——工具缺陷,建议授权后修正。
3. **migrations.json 未登记 P1 迁移**——本任务以冻结镜像手工承载执行(与
   部署桥同载体);迁移完成后该缺口自动消解(迁移幂等,再登记仅为重复
   NO-OP),建议后续发布树补登以守清单契约。
4. 生产 sync 既有失败率 130/2541(7 天)为迁移前基线,与 P1 无关,原样记录。
5. 备份长期保留建议:两份 pre-p1 备份保留至 v1.6.0 生产验收闭环后再处置。

## 12. 当前生产身份与回滚就绪

- **生产 = v1.5.0 @ bb80c38(未变)**;健康;零服务损失;零未解释数据变更;
- 已落生产的新增态(加性、无害):P1 schema/版本/≤500 对象属性;
- 回滚 = 无需;若需要,恢复两份备份 + v1.5.0 重部署即回到基线;
- 镜像 v1.6.0(0502bc4)已构建、已发布、未部署;tag 与 GitHub Release 在案。

## 13. 恢复执行清单(下一任务输入)

1. 授权并合入 NUL 处置决策(建议:迁移工具拷贝时剥离 `\x00`,同批记录
   NUL 剔除计数入迁移日志;5 篇二进制文档由后续 sync 以现役安全过滤自然
   重治);
2. (建议同批)verify-only legacy 态识别修正;
3. 重新执行迁移(幂等:版本回填将 0 新建,内容回填续跑)== Phase 4-11 依序;
4. 正式 deploy v1.6.0 dispatch → 运行时验收全链。

---

# 第二部分:v1.6.1 续执行(矫正集成 → 迁移完成 → 运行时验收)

## 14. 矫正集成与 v1.6.1 发布(续执行前置)

- 矫正分支 `trace-b/p1-migration-corrective-20260911`(实现 `1063af3`,
  报告 `0560c0f`,基 `7f5acf6`)经独立 Role A 复审 **FINAL PASS**
  (零漂移 / FIX-1 双计与嵌套剥离深检 / FIX-2 三态 CLI 实证 / FIX-3 桥
  解析双条目 / RED→GREEN 10 例 / 零生产触碰 / v1.6.0 不可动)后并入 main:
  **merge = `98ab795`**(零冲突;`v1.6.0` tag 未动)。
- **v1.6.1**:annotated tag(`2d1e204`)peel = `98ab795a311e76955de264c55ef01cb5c59b8125`;
  GitHub Release id **387125067**(2026-09-11T14:58:47Z);镜像
  `ghcr.io/harryhua-ai/ask-ai:v1.6.1`(RELEASE.json version=1.6.1 /
  git_sha=98ab795;CI build run **34613346539** test+build 双绿)。
- FIX-3 生效:`deploy/prod/migrations.json` 已含 P1 迁移 → 本次迁移由
  **正式部署桥自动执行**(第一部分 §11.3 缺口消解,不再手工承载)。

## 15. 正式部署与迁移完成(部署桥承载,run 34614941406)

- 桥序列:dispatch → 身份冻结(tag→SHA)→ release-publish Guard →
  Deployment in_progress → `migrations.json` 双条目(launcher_presentation
  + P1)在**冻结 v1.6.1 镜像**一次性容器先行执行 → `update.sh` rollout →
  /health 双断言 → Deployment success。**迁移先于 rollout,失败即不 rollout**。
- P1 迁移记账(权威状态;幂等续跑语义):
  schema 5 列/3 表/2 索引;版本回填 **12,000/12,000**(legacy 代 ordinal=0);
  内容真值回填 **0 → 147,999**(= Σ chunk_count = Weaviate objects,1:1);
  补属性/幽灵 chunk 0;**NUL 矫正:5 文档 / 2,437 chunk 对象 / 397,890
  字符剥离**——仅作用于写入 PG 的文本拷贝,Weaviate 原文按契约不动。
- 幂等复跑:**NO-OP**(版本 0 / 补属性 0 / NUL 0-0-0)+ full verify PASS。
- Rollout:run **34614941406** = success;Deployment 记录
  `success v1.6.1 @ 98ab795a311e`;/health = `{"ok","1.6.1","98ab795a311e…"}`。

## 16. 运行时验收 A/B —— PASS

**A. 在服代权威(四态契约)**:生产代码(= v1.6.1 冻结树)provider 于
main.py lifespan 接线 PG 权威;生产在服集 = `[0]` × 12,000 篇(权威 join
查询实测);真实检索命中在服知识;`None→legacy / 非空→严格过滤 /
[]→零结果不发检索 / raise→FAIL CLOSED` 由合并树 12/12 门测试保证,空集与
故障路径依任务边界不在生产人为触发。

**B. 真实用户路径流式**(wiki-data.camthink.ai widget vhost → backend
:18000,POST /api/ask SSE,Origin 授权头):
- **Q1 产品/规格**(「NE301 的电池续航规格是什么?」):1×sources(含
  `wiki.camthink.ai/docs/neoeyes-ne301-series/ne301-battery-life`,带
  github `provenance_url`)+ **1,034×token** + done,0×error,exit=0,
  46,664 bytes → 产品 + **引用型证据** PASS;
- **Q2 商城/商业**(「NeoEyes NE301 在商城的售价和可选套餐是什么?」):
  5×WooCommerce store 来源(store/ne301、传感器扩展套件、主板、PoE 型号、
  配件)+ **487×token** + done,0×error,exit=0 → **商业/店源** PASS。
- 支持型问题未单列(Q1/Q2 已覆盖 产品+商业+引用 三类);两会话
  conversation_id 在案;backend 零新增 ERROR、RestartCount=0。

## 17. 非破坏重建(Phase 8C)——产品缺陷 STOP(本部分核心事件)

- 执行:最小源 `neomind-dashboard-local`(17 篇)经冻结 v1.6.1 镜像
  compose 一次性容器 `sync.py --source neomind-dashboard-local --reindex`
  (与部署桥同载体;日志 `~/ask-ai-backups/p1-reindex-dashboard.log`)。
- 结果:**失败**——`生成 1 构建失败(embed): batch embed failed: internal
  embeddings HTTP 422: {"detail":"batch too large: 488 > 16"}`。
- **根因(代码级,本任务只分类不修复)**:
  `_ingest_doc_batch` 将 ≤64 doc 的全部 chunk 拼平后**单次** `embed()`
  (`backend/pipeline/ingest.py:774-782`,注释假设「embedder 内部按
  batch_size 批处理」);本地 embedder 确实内部切批,而远程路径
  `RemoteSyncEmbedder.embed` 将全量列表直发单次 HTTP
  (`backend/embedder/remote.py:110-124`,**零客户端切批**);服务端
  `backend/api/internal_embeddings.py:46-52` 按 `EMBEDDER_BATCH_SIZE`
  (生产 =16)强制 422。
- **波及面**:15 个生产源中最小 93 chunks > 16 ⇒ **重建路径当前对全部
  生产源不可用**。增量同步现势安全(15:26Z v1.6.1 增量全部 success),
  但任一「≤64 doc 批 >16 chunk」的变更集将同样失败(运营风险,见 §22)。
- 潜伏史:远程嵌入运行时上线后生产仅跑过小增量;`--reindex` 是首个大批次
  消费者(16 篇 → 488 chunk 单批)。
- **fail-safe 不变量全部成立(失败运行的对照价值)**:
  1. **collection 未删除**(旧「先删 collection」已废除;`Document` 类
     147,999 objects 与基线精确一致;`generation_ordinal=1` 对象 = 0
     ——构建失败前零对象写入);
  2. 新代构建失败 → ordinal=1 行 `status=failed`、`activated_at=NULL`,
     **原子激活未发生**(0 行版本指向 gen 1);
  3. 17 篇 `current_version_id` 全部仍指 gen 0 → **在服连续性零损失**,
     失败后流式问答照常;
  4. gen 1 `purged_at=NULL`(failed ≠ GC 资格,§19 交叉印证)。
- 分类:**STOP — CODE FIX REQUIRED(新矫正任务)**。修复 = RemoteSyncEmbedder
  按 `settings.embedder_batch_size` 客户端切批(与本地 embedder 同参数源),
  属产品代码变更,不在本任务授权内对生产热修。

## 18. 生命周期转换(Phase 8D)——受阻记录

- **supersession**:被 8C 阻断(激活从未发生),无生产证据可采;
- 间接证据:failed 态代正确不入服(P 轴激活门在生产数据上生效);
- **tombstone/withdrawal**:生产无安全可逆用例,依任务边界不人为制造;
  **missing-candidate**:同(资格门运营化 = P2)。

## 19. GC dry-run(Phase 8E)—— PASS

冻结镜像一次性 `scripts/gc_lifecycle.py`(dry-run 默认,未传 `--apply`):

```json
{"now": "2026-09-11T16:01:36Z", "dry_run": true,
 "generations_eligible": [], "documents_eligible": [],
 "objects_deleted": 0, "chunk_rows_deleted": 0,
 "versions_deleted": 0, "documents_deleted": 0, "errors": []}
```

零物理删除;failed 代正确不具 GC 资格(仅 RETIRED+7 天);可解释 JSON
报告在案。

## 20. 终局对账(Phase 9)vs 迁移前基线

| 指标 | 基线(12:14Z) | 终态(16:05Z) | 判定 |
| --- | --- | --- | --- |
| documents | 12,000 | 12,000 | ✅ 不变 |
| document_versions | 0 | 12,000(全部 gen 0) | ✅ 1:1 回填 |
| document_version_chunks | 0 | 147,999 | ✅ = Σ chunk_count |
| Weaviate objects | 147,999 | 147,999(gen-1 对象 = 0) | ✅ collection 全程未动(含失败重建) |
| index_generations | 0 | 2:gen0 ready/activated;gen1 failed/未激活/未 purge | ✅ 失败重建留审计痕 |
| 在服集 | (legacy 无代) | `[0]` × 12,000 | ✅ |
| 引用完整性 | — | 孤儿版本 0 / 缺 current_version 0 / gen-1 版本 0 | ✅ |
| NUL(PG 拷贝) | (不可存) | 397,890 字符剥离(2,437 chunk/5 文档,如实记账) | ✅ |
| documents 新列 | 0 | 4/4(lifecycle/superseded_at/deleted_at/current_version_id) | ✅ 加性 |
| sync_log | 既有基线 | 仅新增 1 行 failed = 本次受控 reindex 尝试;15:26Z 增量全 success | ✅ |

## 21. 当前生产身份与回滚就绪(终态)

- **生产 = v1.6.1 @ `98ab795`**(部署桥部署,run 34614941406,Deployment
  success);RestartCount=0;零新增 ERROR;
- 回滚目标:v1.5.0(`bb80c38`)或 v1.6.0(`0502bc4`)均可 dispatch 重部署
  (P1 全加性,旧代码忽略新列/新属性);两份 pre-p1 备份(12:14Z)保留;
- 镜像 `ghcr.io/harryhua-ai/ask-ai:v1.6.1`;Release 387125067;
  tag peel = `98ab795`;工作流:build 34613346539 / deploy 34614941406。

## 22. 残余风险与后续任务清单

1. **RemoteSyncEmbedder 客户端切批缺陷(CODE FIX REQUIRED)**:重建路径
   全源不可用;大批量增量同样暴露。修复 + 门测试(批界不变量)+ 新 patch
   发布(建议 v1.6.2)+ 8C/8D 补验收(supersession 证据届时补采)。
2. `EMBEDDER_BATCH_SIZE=16` 与 ingest 64-doc 批的规模错配:即便切批修复,
   重建 14.8 万 chunk 的时长/嵌入预算仍需评估(分源灰度重建)。
3. NUL 5 篇二进制文档由后续 sync 按现役安全过滤自然重治——观察项。
4. v1.5.0 时代 sync 失败基线 130/2541(7 天)原样保留,与 P1 无关。
5. 两份 pre-p1 备份保留至本验收闭环归档后再处置。

---

TB-P1 PRODUCTION = PARTIAL
