# Execution Contract: p1-admin-visibility-and-data-residuals

> **任务代号**:P1-RES
> **签发**:产品规划/审查窗口(Planner / Reviewer Authority,依 `docs/planner-reviewer-protocol.md`)
> **签发日期**:2026-08-30
> **本契约自包含,Executor 无需读取规划会话历史**

## 1. BASELINE_COMMIT

`88a4c9f`(main = origin/main)。Task 1(代码)在此基线上开 worktree;Task 2/4(T4 数据)基线为「生产运行版本 `88a4c9f` + 当时数据状态」。

## 2. Objective

1. **修复 P1**(生产缺陷):admin 内嵌聊天的检索被 `channel_visibility` 过滤排除,管理后台测试环境不可用——使其恢复可用,且语义为"管理员所见 = 访客所见"。
2. **修复 ne503-sdk-local 数据缺口**(rename 窗口盲区),并取得 prune 首个生产实战证据。
3. **清理已放行的 backup 分支**;产出 8 源孤儿清单(供产品负责人拍板,本任务不删)。

## 3. Current State / Evidence

**[FACT]** `backend/retrieval/search.py:164`(hybrid 检索)与 `:208`(符号检索)均以 `Filter.by_property("channel_visibility").contains_any([channel])` 过滤;`:64` 默认可见性 `("widget","api")`;各生产源 `channel_visibility` 未配置。
**[FACT]** 生产 A/B 实证(D-11):同一问题 `channel=widget` 正常出 sources + 回答;`channel=admin` 拒答(零命中);conversations 已有 3 条 `channel=admin` 落库(数据隔离本身正常)。
**[FACT]** ne503-sdk-local:repo 已将包改名 `hailo_ipc_sdk → neoruntime_ipc_sdk`,增量窗口滑过 rename;`refill_set ∩ fetch_all = []`(fetch_all 实测 101 docs 全为新路径)→ refill 永久空集、items_updated 恒 0。2 篇计数不一致(`hailo_ipc_sdk/inference.py` pg21/wv0..24 多余 5;`proto/camera_pb2.py` pg21/wv0..18 缺 2)+ 13 篇孤儿(pg 无 wv 有)。
**[FACT]** `channel="admin"` 已在生产生效(`c8117f4`,镜像 `88a4c9f` 已部署)。
**[INFERENCE]** 其余 8 个 partial 源的孤儿(每源 2~523)系产品负责人本地测试裁剪 pg 后的 Weaviate 残留(与用户自述及数据时间线吻合)。
**[UNKNOWN]** Task 2 重置窗口后旧路径的自动清理实效(prune 首个生产样本,不可预知)——因此验收要求实测核对,不允许假设。

## 4. Product / Architecture Contract(冻结 WHAT)

**Task 1|代码(worktree)**:检索层将 `channel == "admin"` 的过滤语义**映射为 `"widget"` 视角**(admin 测试环境所见即访客所见)。两处过滤点(`search.py:164` hybrid、`:208` symbols)**行为必须一致**。实现方式(HOW)不规定。已否决方案不得采用:①逐源在数据侧加 admin;②默认可见集合加 admin(对显式配置源行为不一致)。

**Task 2|T4 数据**:重置 ne503-sdk-local 的 `_last_success_at` 使增量窗口覆盖 rename → 单源同步 → 新路径灌入;**硬要求**:逐篇核对旧路径 2+13 篇在 wv/pg 的清理实效并出对照表;残留则用迭代器/UUID 口径人工点名清(Weaviate TEXT 分词陷阱:like/Equal 不可用于点名)。

**Task 3|主工作区 git**:`git branch -D backup/sync-consistency-pre-rebase`(已放行)。

**Task 4|T4 只读**:8 个 partial 源逐源清单:源名 / orphan 数 / 缺口方向(missing/orphan/计数差)/ 性质推断。**零删除**。

## 5. Non-goals

- 不改 `channel_visibility` 默认值;不做数据侧逐源配置
- 不做 API key / 集成方体系(D-4 预留)
- 不批量清理 8 源孤儿(待用户拍板后另立任务)
- 不修"源里消失文档"功能盲区(候选池项,另立)
- 不动 discord/whatsapp/mcp 渠道行为
- 不部署(Task 1 代码合入后随下次常规发布)

## 6. Acceptance Criteria

| # | 验收 |
|---|---|
| T1-1 | 新测试(TDD 先红后绿)证明:`channel="admin"` 可命中默认可见性源**和**显式 `(widget)` 配置源 |
| T1-2 | 回归:`widget`/`api`/`discord` 渠道下构造的过滤条件与基线**等价**(断言过滤器或行为) |
| T1-3 | 全量 pytest(排除 embedder/e2e,CI 口径)全绿;ruff 与 main 同集合零新增 |
| T2-1 | ne503 单源同步后新路径文档 items 计数 > 0,源转 `success`(或如实报告仍 partial 的原因) |
| T2-2 | 旧路径 2+13 篇 wv/pg 清理实效**逐篇对照表**(含 prune 首实战日志摘录);残留点名清附前后计数 |
| T3-1 | `git branch` 无 backup 分支 |
| T4-1 | 8 源清单表交付,零删除佐证(前后计数不变) |

## 7. Required Verification

- Task 1:worktree(`worktree-exec/admin-visibility`,基线 `88a4c9f`)内 TDD;`TEST_DATABASE_URL` 必设;**push 前必须回报,经 Review 放行**
- Task 2/4:T4 操作,所有删除仅限本契约点名范围;盘点一律迭代器/UUID 口径
- 汇报:按 D-11 先例格式写 execution report 至 `docs/engineering/tasks/p1-res-execution.md`,**给证据不给形容词**;状态自评用 PASS/PARTIAL/FAIL/BLOCKED

## 8. Regression Constraints

- `widget`/`api`/`discord`/`mcp` 渠道检索行为零变化
- 绝不 `--reindex` / 不删 Weaviate collection
- 测试必设 `TEST_DATABASE_URL`(conftest drop_all 红线)
- 提交不含 `docs/`(文档仅本地);ruff/black/isort(line-length=100);中文提交信息
- Task 1 合入方式:worktree 分支 → 回报 → Review PASS → 放行 push origin main

*契约冻结。变更须由 Reviewer 显式 RE-PLAN,不静默修改。*
