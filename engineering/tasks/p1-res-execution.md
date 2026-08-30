# Execution Report: P1-RES(admin 可见性修复 + 数据残留收口)

> **Review 结论(2026-08-30)**:判定 PARTIAL,**Task 1 放行**——已快进推送 main(`88a4c9f..5ca3dfe`,线性),CI run 33309522266 触发;不部署(Non-goal)。Task 2 的 D4 缺陷立项与否、Task 4 孤儿拍板待产品窗口。

> **契约**:`docs/engineering/contracts/p1-admin-visibility-and-data-residuals.md`(冻结)
> **执行日期**:2026-08-30 | **执行者**:Engineering Executor
> **状态总评**:**PARTIAL**(Task 1/3/4 = PASS;Task 2 = PARTIAL,触发契约预留的"如实报告"分支,并发现一项疑似产品缺陷,证据齐备上报)

## 1. Baseline Commit

`88a4c9f`(main = origin/main,执行前复核一致)

## 2. Final Commit

- **Task 1**:`5ca3dfe`(分支 `worktree-exec/admin-visibility`,worktree `.claude/worktrees/admin-visibility`)——**未 push,等 Review 放行**
- Task 2/3/4:数据/git 操作,无代码提交

## 3. Files Changed

| 文件 | 变更 | 说明 |
|---|---|---|
| `backend/retrieval/search.py` | +64/-42 | 新增 `_visibility_probe_channel` 映射 + 三处过滤点接入 |
| `tests/retrieval/test_admin_visibility.py` | +154 新增 | 8 个 TDD 测试 |
| `scripts/sync.py` 等代码 | **无改动**(Non-goal 遵守) | |

格式说明:diff 含 3 处 black 对基线既有非规范格式的重排(`product_filter` 块、`cv_raw` 块等),纯格式无语义,全量测试验证;若基线该文件本就 black-clean 则不会出现。

## 4. Task 1:admin 可见性修复 —— **PASS**

**实现(HOW,契约未规定)**:模块级映射 `{"admin": "widget"}` + `_visibility_probe_channel()`;三处过滤点(`search` hybrid / `search_symbols` / `search_bucket`)统一经映射取探测渠道。

**Discrepancy D1(实现假设修正)**:契约点名两处过滤点(`:164`/:208`),实测存在**第三处同款过滤**(`search_bucket`,`:291` boost 桶)。只改两处则 admin 的 per-intent 软路由桶仍零命中,违背 Objective"管理员所见 = 访客所见"→ 三处同改。

**TDD 证据**:
- 红:`ImportError: cannot import name '_visibility_probe_channel'`(实现不存在)
- 绿:`8 passed`(映射语义 2 + 三处过滤点 admin→widget 3 + 三处回归等价 3)
- 断言方式:捕获传给 Weaviate 的 Filter 对象,`repr` 渲染 `value=['widget']`(admin)与 `value=['<渠道>']`(回归四渠道);组合过滤器递归展开 `_FilterValue`

**验收核验**:
- T1-1 ✅ admin 探测渠道 = widget → 默认可见性源与显式 `(widget)` 源均可命中
- T1-2 ✅ widget/api/discord/mcp 过滤目标 = 渠道本身,与基线等价(逐渠道断言)
- T1-3 ✅ 全量 `507 passed, 3 skipped`(排除 embedder/e2e,CI 口径;TEST_DATABASE_URL 已设);ruff 全仓 78 行 = main 78 行**零新增**;black/isort 改动文件全过
- 异常记录:首跑全量出现 1-2 例 `test_analytics_business` 失败,单独跑/复跑/基线同文件均通过 → 判定测试隔离性偶发,与本改动无关(retrieval 单文件改动)

## 5. Task 2:ne503-sdk-local 窗口修复 + 残留清理 —— **PARTIAL**

**执行序列(全部留证)**:
1. rename 提交定位:`525fa00`(2026-08-20T16:12:10+08:00,"rebrand SDK to neoruntime_ipc_sdk")
2. **Discrepancy D2**:仅重置 sync_log 窗口会被 `_remote_has_updates`(SHA 相等→跳过)短路 → **配对操作**:容器内 clone(`/root/ask-ai-corpus/neoruntime-sdks`)`reset --hard 8212788`(rename 前)+ sync_log 该源**全部** rename 后 success 行(49 行)压回 `2026-08-18T16:00Z`;`effective_last_success_at=2026-08-18 16:00 UTC` 实证
3. 单源同步:**`success, items_updated=470`** ——新路径(neoruntime_ipc_sdk)文档灌入(T2-1 前半 ✅);日志:窗口 `2026-08-18T16:00+00:00`、`抓取到 93 篇`、4 条 hailo 旧路径 stat 失败(已被 rename 移除)
4. **15 篇对照表(T2-2)**:清理前 2 篇不一致(inference.py pg21/wv[0..24] 多余 5;camera_pb2.py pg21/wv[0..18] 缺 2)+ 13 篇孤儿(pg 无 wv 有,共 111 chunks);清理:pg `DELETE 2` 行 + wv 按确定性 UUID 点名删 **136 对象**;清理后 **15 篇残留 = 0**;pg 111/634 → 109/592
5. 收敛观察(3 轮):568/592(refill 10 篇/152 chunks)→ 605/592(refill 3 篇/83)→ **639/592(refill 清单空)**;pg 侧核查 109 行/无重复/592 干净
6. **prune 首实战:零触发**(如实记录)——重灌均为新路径新对象,prune 按文档触达不到旧路径残留;契约预设的人工点名清即为此设计

**仍 partial 的原因(契约 T2-1 预留分支,如实报告)**:
- **新发现疑似产品缺陷(D4)**:ingest 写入成功计数依赖已废弃的 `all_responses` 属性(Dep020 告警在案),失败计数疑失效 → "N/N chunk 成功"可能为假成功(实证:`README.md` 日志 `7/7 chunk 成功`,随后 uuid5 探针 #3..#6 缺失、#0..#2 为旧版本;同模式 10 篇)→ pg 与 wv 漂移、refill 反复触发震荡(重灌写入 wv 但 pg upsert 疑未落地,expected 冻结 592)
- **两口径差(既有已知局限)**:聚合(like 分词)vs 迭代器口径存在不可见对象,639 vs 迭代器侧数值无法对齐
- 两者均需代码修复,**超出本契约范围**(Non-goal:仅 Task 1 动代码)→ 建议另立任务:`fix(ingest): 写入成功记账改用 result.errors/uuids(Dep020)`

## 6. Task 3:backup 分支清理 —— **PASS**

```
before: backup/sync-consistency-pre-rebase
Deleted branch backup/sync-consistency-pre-rebase (was d2efc7f).
after: [](git branch --list 'backup/*')
```

## 7. Task 4:残留源孤儿清单(只读,零删除)—— **PASS**

迭代器口径单次全扫;脚本无任何删除调用。

| 源 | pg行/sum | wv文档/chunks | 孤儿文档/chunks | 缺口方向 | 性质推断 |
|---|---|---|---|---|---|
| lowpower-camera-local | 2421/36841 | 2431/37001 | **10/160** | 纯 orphan | hw-v1.2 分支旧版 .c/.h |
| ne301-local | 5475/67411 | 5998/70233 | **523/2822** | 纯 orphan | main 分支旧版头文件批量残留 |
| neomind-dashboard-local | 17/231 | 17/231 | **0/0** | **一致** | **假阳性**(见 D5) |
| neomind-devicetypes-local | 132/826 | 134/832 | 2/6 | 纯 orphan | types/*.json |
| neomind-extensions-local | 489/3665 | 527/3703 | 38/38 | 纯 orphan | tsconfig.json(1 chunk/篇) |
| neomind-local | 873/10953 | 873/10953 | **0/0** | **一致** | **假阳性**(见 D5) |
| wiki-documents-local | 467/3892 | 509/3991 | 42/99 | 纯 orphan | docusaurus `_category_.json` |

**合计真孤儿:615 篇 / 3125 chunks**(零删除佐证:本脚本无删除调用,前后计数由脚本同轮输出)。

**Discrepancy D5(改写决策基础)**:契约写"8 源";实测口径为 7 源(ne503-sdk 已由 Task 2 处理)。其中 **dashboard 与 neomind-local 迭代器口径完全一致(231/231、10953/10953)**——其 sync_log partial(359/231、16983/10953)系**聚合 vs 迭代器两口径差的假阳性**,无需任何清理;真孤儿集中于 5 源 615 篇,与契约 [INFERENCE](产品负责人本地测试裁剪 pg 的残留)吻合。**产品拍板建议:dashboard/neomind-local 无需动作;5 源孤儿按"孤儿人工评估"逐源拍板(另立任务)。**

**Discrepancy D3(更正)**:此前 D-11 汇报称"10 partial"为算术口误,实为 **9 partial**(14 源 - 5 success)。

## 8. Acceptance Self-assessment

| # | 验收 | 自评 | 证据 |
|---|---|---|---|
| T1-1 | admin 命中默认/显式 widget 源 | **PASS** | 8 测试绿;映射断言 |
| T1-2 | 其他渠道与基线等价 | **PASS** | 4 渠道 × 3 过滤点断言 |
| T1-3 | 全量绿 + ruff 零新增 | **PASS** | 507 passed 3 skipped;ruff 78=78 |
| T2-1 | items>0 且源 success(或如实报因) | **PARTIAL** | items=470 ✅;终态 partial,原因=缺陷 D4+口径差(如实在上) |
| T2-2 | 2+13 逐篇对照 + 残留点名清 | **PASS** | 对照表 + 清理后残留 0 + 前后计数 |
| T3-1 | backup 分支删除 | **PASS** | was d2efc7f,branch list 无 |
| T4-1 | 清单交付 + 零删除 | **PASS** | 7 源表 + 615/3125;只读脚本 |

**Overall: PARTIAL** —— Task 1/3/4 全过;Task 2 完成契约动作但源终态 partial,根因(疑似 ingest 假成功记账 + 两口径差)已钉死并上报,修复需另立代码任务。

## 9. Deviations

1. **D1** 第三处过滤点(`search_bucket:291`)一并修复(契约仅点名两处;不改则 Objective 不成立)
2. **D2** 窗口重置需配对 clone 回退(SHA 短路);host clone 误操作已用 sudo 恢复至原 HEAD(74cd847,git status 干净)
3. **D3** 更正 D-11 报告的"10 partial"口误(实为 9)
4. **D5** "8 源"实为 7 源 + 2 源假阳性
5. Task 1 按"回报等放行"暂停 push;Task 2/3/4 与其无依赖,继续执行以缩短交付周期

## 10. Remaining Risks

1. **admin 内嵌聊天检索在生产仍不可用**——Task 1 代码未合入未部署(契约 Non-goal:不部署);合入后随下次常规发布生效
2. **ingest 假成功记账缺陷(D4)**:现网所有 github 源的 replace 场景均可能 pg/wv 漂移;建议高优另立 `fix(ingest)` 任务(改用 `result.errors`/`uuids`,Dep020 本就要求迁移)
3. **ne503-sdk-local 终态 partial** 待 D4 修复后由自愈循环收敛(重灌清单会自动命中假成功文档)
4. **5 源 615 篇孤儿**待产品逐源拍板(本任务零删除)
5. **两口径差**(聚合 like 分词 vs 迭代器)为校验器已知局限,产生假阳性 partial(dashboard/neomind-local 实证);候选改进:校验器精确级遇"聚合差但迭代器一致"时输出专门标记
