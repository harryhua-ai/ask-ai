# T30-TEST-DB-SAFETY Execution Contract(测试库安全防呆)

- **Task ID**:t30-test-db-safety | **Parent Initiative**:测试基础设施卫生
- **Baseline Commit**:发布批次(C8B+T28+T26+T27)合入后的 main(开工前自行核实)
- **Risk Level**:**L1**(仅测试基建,零产品代码)
- **Contract Authorization**:**AUTHORIZED**(2026-08-31,Role A 签发)——当日两起真实事故定性:①A 侧审查复跑漏带 `TEST_DATABASE_URL`,conftest 回退主 .env 开发库 DSN 且 fixture `drop_all`,**本地开发库 ask_ai 全表被清**(已恢复);②执行端上报 `test_lifespan_smoke` 毒化共享 ask_ai_test 的 deepseek 行(历史 mask flaky 根因)。

## 1. Objective

测试进程在未显式指定测试库时**硬失败**,杜绝任何路径连到开发/生产库执行 drop_all/写入;隔离 smoke 测试对共享测试库的跨口径毒化。

## 2. Evidence(均已实证)

| # | 事实 | 来源 |
|---|---|---|
| E1 | `tests/conftest.py:34-44`:env 缺 `TEST_DATABASE_URL` 时回退 `load_settings(...).postgres_dsn`(= 主 .env 开发库 ask_ai),且 fixture 内 `Base.metadata.drop_all` | 代码 + 事故复盘 |
| E2 | 2026-08-31 A 侧复跑 CI 口径未带该变量 → 443/447 用例对 ask_ai drop_all → 15 表全清(执行端收尾时库完好,责任在 A) | pg_tables 复核 |
| E3 | `tests/scripts/test_migrate_llm_chain_format.py:32` 已有同类防呆("必须在 ask_ai_test 库上运行")——证明风险已知但仅单点覆盖 | 代码 |
| E4 | `test_lifespan_smoke` 跑真 lifespan,YAML `${DEEPSEEK_API_KEY}` 空时种出空 api_base/api_key 的 deepseek 行,毒化共享 ask_ai_test;admin conftest 种子仅缺行时插入,后续 admin 口径踩脏行 → mask 用例假失败 | 执行端 T27 Deviations + 复现 |

## 3. Scope

1. `tests/conftest.py`(及 `tests/api/admin/conftest.py` 同类回退点):`TEST_DATABASE_URL` 缺失或 DSN 库名非 `*_test` 时 `pytest.fail`/`pytest.exit`,**移除对开发库 DSN 的回退**;CI 已显式注入,行为不变;
2. `test_lifespan_smoke`:测试自建/自清其 deepseek 行(或用独立 schema/事务回滚),消除跨口径毒化;毒化-修复回归用例(先毒后跑 admin mask 用例应绿);
3. 附注级(不强制修):`test_analytics_business` 顺序敏感两用例定位根因,能低成本隔离则一并修,否则报告记录。

## 4. Non-goals

产品代码;CI workflow 结构;测试库拆分多实例;性能优化。

## 5. Change Boundary

**Code EXPECTED**:`tests/conftest.py`、`tests/api/admin/conftest.py`、`tests/test_lifespan_smoke.py`、相关测试。
**CONDITIONAL**:`test_analytics_business` 隔离修复。
**FORBIDDEN**:`backend/**`、`admin/**`、`widget/**`、`.github/**`。

## 6. Frozen Contract

1. 无 `TEST_DATABASE_URL` 跑任何后端测试 → 立即失败并输出指引,**任何情况下不触碰 ask_ai 库**;
2. DSN 指向非 `*_test` 库名 → 同样硬失败;
3. CI(显式注入)与本地(带环境)行为不回归,两口径全绿;
4. smoke 不再毒化共享测试库(毒化-修复用例锁定)。

## 7. Acceptance Criteria

- **AC1**:不带走 env 直接 `pytest tests/` → 秒级失败,错误信息含设置指引(截图/输出);
- **AC2**:带 `TEST_DATABASE_URL=…ask_ai_test` 两口径全绿(基线口径无回归);
- **AC3**:CI 口径后紧接 admin 口径连跑两遍,deepseek mask 用例稳定绿(毒化消除);
- **AC4**:报告 `t30-test-db-safety-execution.md`,CANDIDATE READY,不 push。

## 8. Executor Prompt(可拷贝)

```markdown
# Role B 执行任务:T30-TEST-DB-SAFETY(测试库安全防呆)

先完整阅读:
1. /Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/DUAL_AGENT_PROTOCOL.md
2. /Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/role-B.md
3. 契约:/Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/tasks/t30-test-db-safety-plan.md

## 任务(背景:今天 conftest 回退开发库 + drop_all 真实清掉了本地 ask_ai, smoke 毒化共享测试库)
① tests/conftest.py 与 tests/api/admin/conftest.py:TEST_DATABASE_URL 缺失或库 名非 *_test → 硬失败
   (pytest.fail/exit + 设置指引),移除对开发库 DSN 的回退;
② test_lifespan_smoke 自建/自清 deepseek 行(或等效隔离),加"毒化-修复"回归用例;
③ CONDITIONAL:test_analytics_business 两用例顺序敏感,低成本隔离则修,否则报告记录根因。

## 环境与边界
- 主仓 baseline = 发布批次合入后 main(开工前核实);worktree:/Users/harryhua/Documents/GitHub/ask-ai-t30-test-db,分支 worktree-exec/t30-test-db-safety
- FORBIDDEN:backend/**、admin/**、widget/**、.github/**
- 验证红线:AC1 必须"不带 env 裸跑"实证失败;绝不可在无 TEST_DATABASE_URL 状态下让任何用例连库
- 测试环境:export TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test(+ENCRYPTION_KEY)

## 验证(全部实际执行,给证据)
1. 裸跑 pytest(无 env)→ 秒败 + 指引输出
2. 带环境两口径全绿;CI 口径→admin 口径连跑两遍,mask 用例稳定绿
3. 报告 docs/engineering/tasks/t30-test-db-safety-execution.md;状态 CANDIDATE READY,不 push
```
