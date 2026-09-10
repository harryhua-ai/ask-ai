# Bug Fix Sprint — 2026-09 · Role A 评审清单(Review Manifest)

- 生成:2026-09-10(sprint 编排执行完成时点)
- Sprint 基线:main = `03e6c5787fc28e0625ce35cbe1be59690f2de0dd`(#21 ff-only 集成后)
- 状态:全部候选 **CANDIDATE READY / 未合并 / 未部署**;等待独立 Role A 评审
- 建议评审顺序:#45 → #34 → #26-31 共享矫正(#32 基线工件为其验收附件,随批补齐)

---

## 1. #21 — Admin 当前健康 vs 历史可靠性

| 项 | 值 |
| --- | --- |
| Base → Candidate | `b5e27a1` → `03e6c57`(ff-only 已集成 **DONE**,main=03e6c57) |
| Role A | FINAL PASS(隔离栈五场景浏览器验收) |
| 证据 | `~/Documents/ask-ai-acceptance/issue21-review-20260910/` |

## 2. #45 — 同步灌入文档级失败诊断 + 字符契约对齐

| 项 | 值 |
| --- | --- |
| 分支 / Candidate | `fix/45-ingest-char-contract` @ `ebc45c2` |
| Base | main `03e6c57`(零漂移切出) |
| RCA | CONFIRMED(生产只读 + 代码 + 本地复现;issue #45 评论 2026-09-10):部署 `EMBEDDER_MAX_LENGTH=1024`(字符)413 显式拒绝 vs 分块器按 token(600)封顶;两页面全部 chunk 超限(2437/2841/1514 与 2697/1162 本地实测);09-03 起小时级 cron 无效重试 |
| 契约 | ①灌入边界按 embedder 字符契约预切超限 chunk(uuid5/幂等/prune 不变)②DocFailure 结构化(source_id/stage/分类/可重试)经 IngestFailures.failures 落 SyncLog+SyncRun.counters(零迁移)③413/422=permanent、transport/write=retryable ④零成功写不覆写/不留 0 行账本(自愈解锁) |
| 变更文件 | `backend/pipeline/ingest.py`、`scripts/sync.py`、`tests/pipeline/test_ingest_char_contract.py`(12 条)、执行报告 |
| 测试 | 后端全量 **2202 绿 / 8 skip**(基线 2190+12) |
| 执行报告 | `docs/engineering/tasks/issue45-ingest-char-contract-execution.md` |
| 残留风险 | 修复合入后依赖下一轮 cron 自动恢复 website-camthink 源(窗口 lastmod);无需人工干预的重灌路径 = 常规同步 |

## 3. #34 — GitHub 源传输失败证据化 + 有界恢复

| 项 | 值 |
| --- | --- |
| 分支 / Candidate | `fix/34-git-transport-recovery` @ `8d0350b` |
| Base | main `03e6c57` |
| RCA | CONFIRMED(issue #34 评论):09-07 05:35–08:57Z 间歇性 github.com:443 连接失败(~130s=OS SYN 耗尽);同分钟对照他源成功 → 非主机出口/非 GitHub 全网;10:00 起经 cron 自愈;`_run_git` 无超时无重试;业务失败被吞 → runner 恒 0 退出 → §14 恢复面永不触发 |
| 契约 | ①subprocess 显式超时(`GITHUB_GIT_TIMEOUT_SECONDS`,默认 900s,≤0 关闭)②stderr 证据模式 → `GitTransportError`(连接/DNS/超时/SSL/gnutls/TLS/reset;ref 不存在/鉴权=非传输)③main 退出码 2 → executor 既有 runner_failed 有界重试(4 次/30/120/600s,零 executor 改动);纯业务失败恒 0(§14 不变)④`[transport][retryable]` 前缀 + counters.transport_failures;token 脱敏保留 |
| 变更文件 | `backend/connectors/github.py`、`scripts/sync.py`、`tests/connectors/test_github_transport.py`(17 条)、执行报告 |
| 测试 | 后端全量 **2207 绿 / 8 skip**(基线 2190+17) |
| 执行报告 | `docs/engineering/tasks/issue34-git-transport-recovery-execution.md` |
| 残留风险 | 与 #45 候选在 `scripts/sync.py::_sync_one` except 块相邻(语义正交:IngestFailures counters vs 传输返回值/前缀),后合并方需一次小 rebase |

## 4. #26–#31 — 答案智能共享矫正(一个候选,五 issue 可独立追溯)

| 项 | 值 |
| --- | --- |
| 分支 / Candidate | `fix/26-31-answer-intel-shared` @ `90fac46` |
| Base | main `03e6c57` |
| 归因(共享层) | #26/#27:INC-3 已修(零改动,基准验收,种子 cg-r03/r04/s01);#28:store 证据类被资格闸整体排除(生产实证 38 chunk 不可达);#29:/tools/ 页无推导规则=unknown 被拦截;#31:推荐计划缺案例槽+信号词表过窄+帧指令无组合语义 |
| 契约 | #28:store kind 入资格展开(SHARABLE_KINDS+applies_to 全线;单一权威缝贯通检索闸/防御过滤/引用资格/比较管线;sibling 边界与 is_targetable 不松动);#29:`tools` 共享桶 + `/tools/` 推导规则(特异性优先);#31:推荐计划 +CASE_EVIDENCE 可选槽、_SOLUTION_SIGNALS 扩充、推荐帧指令跨证据类组合(coverage 真值驱动,NEW_LLM_CALLS=0) |
| 变更文件 | `config/product_taxonomy.yaml`、`backend/product_taxonomy.py`、`backend/pipeline/{evidence_planning,evidence_selection,response_strategy}.py`、测试 4 文件、`scripts/benchmark_v1/run_benchmark.py`(runner 入库)、执行报告 |
| 测试 | 后端全量 **2198 绿 / 8 skip**(基线 2190+8) |
| 执行报告 | `docs/engineering/tasks/issue26-31-answer-intel-shared-execution.md` |
| 依赖 | 验收以 #32 基线种子判分为对照(§6);#29 生产端到端生效需 website 源重灌(依赖 #45 修复后的 cron 恢复;一次性 reindex 属生产变更,延至发布门) |
| 残留风险 | 生产语料中 calculator 页现标 unknown,重灌前其证据不可达(如实声明);store 入围扩大了 commercial 噪声面(38 chunk,量级极小,INC-5/INC-6 约束照常) |

## 5. #32 — Answer Intelligence Benchmark v1(支撑前置)

| 项 | 值 |
| --- | --- |
| 已有资产 | 冻结 121 案例(contracts/corpus/evaluator/scoring 四件套,2026-09-07 冻结)+ 基线(v1.1.2 cdbcad3)+ 复测(v1.2.1 26de2b6)+ taxonomy —— `docs/evaluation/benchmark_v1/` |
| 本次新增 | **可执行 runner 入库**:`scripts/benchmark_v1/run_benchmark.py`;**基线已测完成**:prod v1.4.0(`41278f07`)121×3=363 runs / 0 传输错,工件 `docs/evaluation/baseline_v1_2026-09-10/`→`benchmark_v1/baseline_v1_2026-09-10/`(raw jsonl + run manifest + 种子判分 sq/cg + BASELINE_V1_SUMMARY.md) |
| 基线结论 | 种子 9/21 PASS:#26(3/3)#27(6/6)INC-3 已修;#28/#29/#31 全败,失败模式(false_absence/no_composition/cg-r07 误路由)与候选矫正逐一对位;追加 1 处 prompt guard(场景充分性),回归红线 cg-r03/r04/s01=9/9 |
| 种子映射 | #26=cg-r03;#27=cg-r04+cg-s01;#28=cg-r05+sq-026/045/080;#29=cg-r06+sq-073;#31=cg-r07+cg-r09+sq-034/040 |
| 判分 | EVAL_V1 LLM-assisted judge(先例:v1 复测 judge=executor session subagents);本 sprint 判种子案例 + 抽样对照,全量机械结果先落库 |

## 6. 基线工件(已完成)

`docs/evaluation/benchmark_v1/baseline_v1_2026-09-10/`:
`baseline_results_raw.jsonl`(363 runs)| `run_manifest_v1.json` | `seed_judging_sq.md` |
`seed_judging_cg.md` | `BASELINE_V1_SUMMARY.md`(基线通过率/失败模式/对候选的验收预测)

---

## 评审守则(全候选通用)

1. 不接受报告数字,独立重跑:后端 `uv run pytest -q`;admin `cd admin && npm test && npm run build`;
2. 越界审计:各候选 changed-file surface 不得出现禁区(engine 重设计/schema/生产/发布/无关 issue);
3. 运行时验收在隔离栈(一次性 DB + 本地 uvicorn/vite)执行;#26–#31 的真实答案流验收
   以 #32 基线种子做只读生产对照(不触生产知识状态);
4. 合并顺序建议:#45 → #34(`scripts/sync.py` 相邻,第二家 rebase)→ #26-31(独立区);
   合并后跑全量回归 + `#32 runner` 对集成树做种子复测(Phase 5 要求,部署仍禁止)。
