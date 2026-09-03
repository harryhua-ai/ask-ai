# CAMTHINK V1 — Source Center Integration Gate(#16+#17+#18)报告

- 日期:2026-09-03
- **STATUS: CANDIDATE READY**
- **BASELINE: `ce52af421cd201fa64daf01c3f0e6fd32ac48a70`**(S0 集成基线)
- **FINAL_COMMIT: `272f570ad5194f36c05146a9a06f5b35be872be8`**
- BRANCH: `integration/source-center-16-17-18-20260903`(已推 origin,远端哈希核验一致)
- WORKTREE: `.worktrees/sc-integration`
- **PRODUCTION_MUTATIONS: NONE**

## SOURCE_COMMITS(三个独立 Planner PASS 候选,均基座 ce52af4)

| 候选 | tip | 文件数 |
| --- | --- | --- |
| #16 Repo Simple Mode | `bfb5547c7f49c63dd5c42bdfb4bf963be313da54` | 11 |
| #17 Website Simple Mode | `880282aa32daf5847878fcc70fcdade9778c9f44` | 8 |
| #18 Async Delete | `8eb1e9dc92f5ab3b80383ee71801ae11284d4d81` | 13 |

## INTEGRATION_METHOD / TOPOLOGY

三次 `merge --no-ff`(00371cd #16 → 97fa1de #17 → e27f7f0 #18)+ 2 个集成兼容修复提交(86a893a、272f570)。热点四文件(useDataSources.ts / DataSources.tsx / types/api.ts / data_sources.py)两两重叠为真,冲突手工并集解决。

## CONFLICTS / CONFLICT_RESOLUTIONS

| # | 文件 | 冲突 | 裁决 |
| --- | --- | --- | --- |
| C1 | data_sources.py imports | #16/#17 发现端点导入 vs #18 生命周期导入 | 并集;后续 #18 合并再撞一次,并集保留(期间遗漏 `run_in_threadpool`,86a893a 恢复) |
| C2 | data_sources.py delete/retry 端点 | HEAD(旧同步删除残段)vs #18(异步 request_deletion+worker kick) | **#18 语义获胜**(retry=异步重入队);残留未用 `Document` 导入清除 |
| C3 | DataSources.tsx imports | #16 RepoDiscoveryPanel vs #18 isDeletionInFlight/isSyncEligible | 并集 |
| C4 | DataSources.tsx 表单重置(openCreate/openEdit) | #16 discovery 状态重置 vs #17 website discovery 状态重置 | 并集(两组 reset 共存,互不覆盖) |
| C5 | **语义冲突(记录)** | **#16 有意移除「拉取分支后自动预填 file_types」(C10,冻结测试反向断言"不再预填") vs #17 树内继承自基线的旧 C10 块(测试断言"自动预填")** | **#16 有意变更获胜**:页面移除 C10 块+导入;依据=#16 用例带 #16 前缀属其冻结契约,而 #17 冻结契约仅涉 Website Simple Mode 全链路(robots/sitemap/zero-discovery/同域),该 C10 断言是 #17 未跟随基线变更的**携带覆盖**,非 #17 冻结语义;#17 Website 能力零受损。非静默:本报告明示 |
| C6 | 测试 mock 工厂(DataSources.test.tsx / FinalPolish.test.tsx) | #18 新增 hooks(useRetryDeleteDataSource)渲染期调用,mock 工厂(显式枚举式)缺项 → 44 用例模块级崩 | 补 `useRetryDeleteDataSource` 与 `fetchWebsiteDiscovery` mock 项(测试基建兼容,未弱化任何断言) |

## PRESERVED_16 ✓

`POST /data-sources/discover-repo`(data_sources.py:529)只读发现→S0 推荐→确认写回既有 config 词表(file_types/exclude_dirs),无第二 ingestion authority;Advanced repo 配置(branches/clone_path/preview-branches)全部在位;Technical Safety 在发现层标记+灌入层照检(test_safety_secrets 绿)。冻结测试「拉取分支后不再把仓库全部后缀预填进 file_types」绿。

## PRESERVED_17 ✓

`POST /data-sources/preview-website`(:580)→ build_website_preview 按 PD-3 顺序(robots Sitemap: → 显式 sitemap_url → generic 回退 → index 全同域子表);zero discovery 显式呈现(200+空 candidates+冻结告警);cross-domain 跳过带 evidence(test_preview_website_cross_domain_reason_surfaced 绿);仅写既有 web_crawl config;无 JS/OCR/PDF/image/跨域爬虫;fetch 经 run_in_threadpool(504 防线)。

## PRESERVED_18 ✓

`DELETE /{source_id}` 202 受理(:399)→ ACTIVE→DELETE_REQUESTED→DELETING→removed 持久生命周期;失败→DELETE_FAILED→`POST /{source_id}/delete/retry` 202(:426)重入队;refresh/restart 可恢复(deletion worker,main.py 挂载);active/pending sync 碰撞安全阻止;deny-by-default(Stage⑩语义源 lifecycle);purge 安全验证完整(账本 UUID 点删+孤儿扫+残留校验,移入 source_deletion 服务)。

## COMBINATION_TESTS(A-F)

- A(同页三能力并存):tsc -b 0 错 + DataSources.test.tsx 42/42(内含 #16 Simple Mode 用例、web_crawl 四字段用例、lifecycle 徽标数据渲染)✓
- B(data_sources.py 端点并容):grep 实证 discover-repo/preview-website/DELETE 202/delete-retry 202/201 创建/upload/sync 202 全部在位 ✓
- C(hooks/types 并集):符号级核验 fetchRepoDiscovery/fetchWebsiteDiscovery/fetchPreviewFileTypes/RepoDiscoveryResult/WebsiteDiscoveryResult/lifecycle_state/isDeletionInFlight/isSyncEligible/delete+retry hooks 全在,无互相覆盖 ✓
- D(discovery×lifecycle 互不破坏):test_data_source_deletion_lifecycle + test_source_lifecycle(deny-by-default)绿 ✓
- E(sync/health/progress/history 不回退):sync trigger/504 golden/SyncRun/test_useTriggerSync 绿 ✓
- F(Safety/同域/lifecycle safety):safety_secrets/ingest_safety/website 跨域证据用例绿 ✓

## BACKEND_TESTS / ADMIN_TESTS / BUILD

- 后端全量(离线隔离):**1275 passed / 6 skipped / 0 failed(36-37s)**
- Admin vitest:**37 文件 203/203 全过**
- Admin build:`tsc -b` 0 错 + `vite build` 成功
- `git diff --check ce52af4 HEAD`:干净

## REGRESSIONS

**NONE**(最终态零失败)。过程中暴露并修复的集成缺陷见 CONFLICT_RESOLUTIONS C1(遗漏导入)与 C6(mock 缺项)——均为集成兼容问题,非候选缺陷。

## KNOWN_LIMITATIONS

1. ruff 对 S0 携带文件存在 12 项风格级发现(S0 集成基线报告已归类,候选自带,未修);
2. #16 移除 C10 自动预填后,「仓库全部后缀自动列出」能力仅存于 Repo Simple Mode 的 discovery 推荐(Advanced 手动路径需自填或用 discovery)——#16 冻结契约本身如此;
3. store 站点公网 DNS/CORS 为生产侧既有边界,与本集成无关。

## REPORT_PATH

docs/implementation/CAMTHINK_V1_SOURCE_CENTER_16_17_18_INTEGRATION_GATE_2026-09-03.md(本文件)
