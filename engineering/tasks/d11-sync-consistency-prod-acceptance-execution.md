# Execution Report: d11-sync-consistency-prod-acceptance

> **任务**:D-11 sync-consistency 生产部署验收(tesla-t4)
> **执行日期**:2026-08-30(任务完成于 Executor 协议引入之前,本报告按协议格式回溯撰写,证据均为当时实际命令输出)
> **性质**:部署 + 运行时验收 + 已裁决数据清理,**零代码改动**

## 1. Baseline Commit

`88a4c9f`(main,= origin/main,部署对象镜像即由该 commit 经 CI run 33304279579 构建)

## 2. Final Commit

`88a4c9f`(不变)。本任务无任何代码提交;唯一文件产物为本报告(docs/ 仅本地策略,不入 git)。

## 3. Files Changed

**代码:无(红线遵守:全程不改代码)。**

非代码变更:
| 对象 | 变更 | 授权 |
|---|---|---|
| tesla-t4 生产 backend 容器 | 镜像滚动更新至 88a4c9f 内容 | D-11 任务本体 |
| tesla-t4 pg `documents` 表 | DELETE 5 行(`source_id ~ '(^|/)\._'` 幽灵行) | 收口指令已裁决("只删文件名 ._ 前缀的对象") |
| tesla-t4 Weaviate | **零删除**(迭代器核验幽灵对象=0,无需删) | — |
| `docs/engineering/tasks/` 本报告 | 新建(仅本地) | Executor 协议 |

## 4. Implementation Summary

按收口指令顺序执行:

1. **前置**:CI 33304279579 success;磁盘 `1.3T 276G 952G(23%)`,余量 77%(红线 20%)。
2. **部署**:`update.sh` 成功;健康检查首验失败,BGE-m3 GPU 模型加载慢所致,45s 后 `{"status":"ok"}`。运行版本容器内直查实锤:`schemas.py:18` 含 `1~8000`(88a4c9f)、`:30` 白名单含 `admin`(c8117f4)——防"运行旧版"。
3. **两轮"同步全部"**:逐字节一致(5 success / 10 partial,计数全同)——自愈循环幂等稳定,success 源零退化。
4. **幽灵行清理(已裁决)**:盘点→pg `._*` 仅 knowledge-support-cases 1 源 5 行;Weaviate 迭代器核验幽灵对象 **0 个**(此前 like/Equal 过滤器命中为 TEXT 分词匹配假象,`*/._*` 误中全库 12.9 万对象——**点名操作改用迭代器口径/确定性 UUID,方法修正已记录**)。执行 `DELETE 5`(事务内 before 5/5 → after 0/0 留证)→ knowledge 单源同步 **partial → success(481/481,items_unchanged=179)**。
5. **根因钉死(报告残留项)**:
   - ne503-sdk 2 篇不一致 = `hailo_ipc_sdk/inference.py`(pg 21 / wv 0..24,多余 5)+ `proto/camera_pb2.py`(pg 21 / wv 0..18,缺失 2);13 篇孤儿(pg 无 wv 有)。**根因:repo 已改名包 `hailo_ipc_sdk → neoruntime_ipc_sdk`,增量窗口 `fetch_changes(since)` 滑过 rename,`refill_set ∩ fetch_all = []`(fetch_all 实测 101 docs 全新路径)→ refill 永久空集**。
   - **P1 发现**:admin 渠道被检索层 `channel_visibility` 过滤排除(各源未配置 → 默认 `(widget,api)`,`contains_any(["admin"])` 零命中)。A/B 实证:同问题 widget 正常出 sources+回答、admin 拒答 → **生产 admin 内嵌聊天检索当前不可用**(数据落库正常,conversations 已有 3 条 channel=admin 实证)。

## 5. Tests Actually Executed and Results

本任务为运行时验收,无代码改动故无单测;以下为实际执行的验证与原始输出要点:

| 验证 | 命令/方法 | 结果 |
|---|---|---|
| CI 镜像 | `gh run view 33304279579` | `completed success` |
| 磁盘前置 | `ssh tesla-t4 df -h /` | `952G avail(23%)`,通过 |
| 健康检查 | `curl localhost:18000/health` | 首验失败→45s 后 `{"status":"ok"}` |
| 运行版本 | 容器内 `grep schemas.py` | `1~8000` + `mcp|admin` 双证据 |
| 一轮同步 | POST `/api/admin/data-sources/sync-all` | 14 源,~82s,5 success/10 partial |
| 二轮同步 | 同上 | 与一轮逐字节一致 |
| 幽灵盘点 | pg regex 查询 + Weaviate 迭代器 | pg 5 行;wv 幽灵对象 0 |
| 幽灵清理 | psql `-f`(事务) | `DELETE 5`,before 5/5→after 0/0 |
| knowledge 复验 | 单源同步 POST + sync_log | **success,481/481,unchanged=179** |
| ne503-sdk 诊断 | fetch_all 探针 + 逐文档集合比对 | 交集为空实锤;2 篇差异方向/计数如上 |
| 检索 A/B | POST `/api/ask` channel=widget vs admin | widget: sources+回答;admin: 拒答 |
| 落库证据 | conversations 按渠道计数 | admin=3 / widget=1 |
| 磁盘终验 | `df -h /` | 952G,无异常增长 |

**未执行**:prune 生产验证——全程零重灌发生,prune 未被触发(如实上报,其行为目前仅测试证据:5 个专测);unit/regression 套件未跑(零代码改动,跑之无的)。

## 6. Acceptance Self-assessment

| 验收项 | 自评 | 依据 |
|---|---|---|
| 部署 + 运行版本验证 | **PASS** | 容器内代码双证据 |
| 幽灵行清理(裁决范围) | **PASS** | DELETE 5 留证;knowledge 转绿 481/481 |
| 验收 a:首次同步+prune 摘录 | **PASS(带保留)** | 同步证据完整;prune 零触发如实上报 |
| 验收 b:检索抽查 | **PASS(产出 P1)** | A/B 完成;admin 侧拒答即为最高价值发现 |
| 验收 c:二次同步全绿 | **NOT MET(已上报,非静默)** | 二次与一轮一致(幂等确认),9 源 partial 为数据侧残留,修复方案已列待决策 |
| 红线(无 --reindex/仅 ._* 点名/不动 backup/不改代码/TEST_DATABASE_URL 规则) | **PASS** | 全程遵守 |

**Overall: CONDITIONAL PASS** —— 可执行部分全部完成且证据齐全;9 源 partial 与 P1 为数据侧/产品侧待决策残留,已在报告中逐项钉死根因并给出修复选项。

## 7. Deviations

1. **执行顺序调整**:收口指令将二次同步提前(不被数据侧卡)——按新指令执行,非自主偏离。
2. **诊断方法修正**:like/Equal 过滤器在 TEXT 属性分词匹配不可靠,改用迭代器/确定性 UUID 口径——已记入报告教训项。
3. **任务执行先于协议**:本任务完成于 Executor 协议引入前,报告为回溯补写;证据为当时真实输出,无事后重跑。
4. 执行中途用户指示"数据源我自己来配置",执行端暂停数据侧操作;后续收口指令重新授权 `._*` 清理与 ne503-sdk 细节诊断后恢复。

## 8. Remaining Risks

1. **P1:生产 admin 内嵌聊天检索不可用**——等修复决策(数据侧各源 vis 加 admin / 代码侧改默认)。**当前最影响用户的一点**。
2. **ne503-sdk 永久 partial + 13 孤儿**——修复选项 A(重置 `_last_success_at` 让窗口覆盖 rename)待裁决;孤儿处置策略待定。
3. **8 源 refill-empty partial**——"仅统计不删"设计盲区,需逐源数据侧策略(长期项)。
4. **prune 无生产样本**——首次真实触发要等 ne503-sdk 走修复选项 A 重灌时观察。
5. **backup 分支未删**——等 §9 审查放行。

## 9. 交付物路径

- 本报告:`docs/engineering/tasks/d11-sync-consistency-prod-acceptance-execution.md`(仅本地)
- 验收记录(产品窗口审查用):`docs/superpowers/handoff/2026-08-30-sync-worktree-triage.md` §9(仅本地)
