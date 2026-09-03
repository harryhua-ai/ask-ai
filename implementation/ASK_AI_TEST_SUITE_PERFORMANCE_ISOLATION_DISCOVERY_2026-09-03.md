# ASK-AI 测试套件性能与隔离 Discovery 报告(2026-09-03)

- 任务类型:ENGINEERING PRODUCTIVITY DISCOVERY(Window C,并行发现)
- 基线 commit:**1b8572abd74145bac5727688a957a2c37370c7ec**(= origin/worktree-exec/sync-isolation-20260902,检出于主仓 worktree `.worktrees/ingest-safety`;非 main 祖先,与 main=ebe10b8 有 27 文件差异,故所有 profile 严格在该 worktree 执行)
- CODE_MUTATION:NONE(零实现改动;主仓工作树零接触,只读)
- PRODUCTION_ACCESS:NONE
- 证据归档:`docs/implementation/evidence/test-suite-perf-2026-09-03/`(6 个原始日志)

---

## 0. 一句话结论(TL;DR)

**36:45 不是"测试慢",是"每次全量都在重新下载 ~5.5GB 模型"。** 在隔离干净的环境下,同一棵树、同一命令、同样 1058 passed / 6 skipped / 0 failed 的全量套件实测只要 **83.5~84.1 秒(两轮复现,差 0.6s)**。36 分钟与 84 秒之间 26 倍差值的成因已用运行时证据钉死:`tests/embedder/test_bge.py` 的一个单元测试把进程级 HF 缓存环境变量泄漏到一次性 tmp 目录,导致其后的 BGE 集成测试现场从 HuggingFace 下载模型(实测挂死 17+ 分钟仅下载 2.2GB)。**先修隔离,再谈门禁**;在干净环境下,优化空间主要剩 per-test bcrypt(≈40s,占 48%)与少数真实 sleep/模型加载(高度集中在 10 个用例)。

---

## 1. Baseline:声称 36:45

任务输入的最终套件水位(阶段⑩交付时两轮实测):

| 指标 | 值 |
|---|---|
| passed | 1058 |
| skipped | 6 |
| failed | 0 |
| wall time | 36:45 |

本轮在基线树上的收集期核对:**1064 collected = 1058 + 6**,与声称完全一致(用例集合同一)。

## 2. Profiling Method(三轮运行 + 两轮分片)

### 2.1 运行矩阵

| Run | 环境 | TEST_DATABASE_URL | 命令 | 结果 |
|---|---|---|---|---|
| **A** | 裸环境(shell 无 HF 变量、无 offline) | 隔离库 `ask_ai_profile_c`(专用,避免并行窗口互踩) | `pytest tests -q --durations=2000` | **~40% 处挂死 ≥18 分钟,killed**;主线程阻塞在 hf_xet(HuggingFace 下载器),正把 BGE-m3 权重下载进单测泄漏出的 tmp 缓存(kill 时 2.2GB 仍不完整,reranker 未开始) |
| **B** | 暖缓存+offline,自定义库名 | `ask_ai_profile_c` | 同 A | 84.75s;1055 passed + **3 errors** |
| **C** | 暖缓存+offline,**标准库** | `ask_ai_test`(仓库约定) | `pytest tests -q --durations=2000 --durations-min=0` | **83.54s;1058 passed / 6 skipped / 0 failed** ✅ 与基线对齐 |
| **D** | 同 C | `ask_ai_test` | `pytest tests -q -rs --durations=25` | **84.12s;1058/6/0**(复现,差 0.6s) |
| E | 同 C | 同 | `-m unit` | **9.04s**,556 passed |
| F | 同 C | 同 | `-m integration` | **17.91s**,64 passed / 3 skipped |
| G | 同 C | 同 | CI 同款选择(CI 的 `--ignore` 列表,见 §8.4) | **31.17s**,853 passed |

- Run B 的 3 errors 是**发现而非噪声**:`tests/scripts/test_migrate_llm_chain_format.py:32` 的 fixture 硬断言 DSN 必须包含字面量 `ask_ai_test`,换任何隔离库名即 ERROR(详见 §7)。
- Run A/B 用了自定义隔离库,是为规避已知风险(并行窗口会重建共享 `ask_ai_test`,历史上多次互踩);Run C/D 改回标准库前确认了 `pg_stat_activity` 无其他连接。

### 2.2 环境 Notation(可复现性关键)

- 机器:Apple Silicon(darwin 24.6.0 arm64),本地 Docker(Postgres 16.11 @5432、weaviate @8080、p1b-weaviate @21100)。
- "暖缓存+offline" = `HF_HOME=<主仓>/models`、`HF_HUB_CACHE=<主仓>/models/hub`、`TRANSFORMERS_CACHE` 同前、`HF_HUB_OFFLINE=1`。主仓缓存双模型齐全(bge-m3、bge-reranker-v2-m3);**worktree 自己的 `models/` 缺 reranker**。预置这些变量后,§6.1 的泄漏 setdefault 变 no-op,即为"干净基线"。
- pytest 9.1.1,`asyncio_mode=auto`,pyproject 无 addopts(无 coverage 隐性开销)。
- venv 为主仓 editable 安装;已在 worktree 内实测 `import backend` 解析到基线树(`.worktrees/ingest-safety/backend/__init__.py`),未跑错代码。

### 2.3 为什么声称的 36:45 会发生(归因链,证据齐全)

1. `test_ensure_hf_cache_sets_env_vars`(tests/embedder/test_bge.py:147)先 `monkeypatch.delenv("HF_HOME"/"HF_HUB_CACHE"/"TRANSFORMERS_CACHE", raising=False)`——**这些变量本来不存在,monkeypatch 不记录任何恢复动作**;
2. 测试体调用 `_ensure_hf_cache(tmp/models)`,其内部 `os.environ.setdefault(...)`(backend/embedder/bge.py:34-36)**把三个进程级变量设成该测试的一次性 tmp_path**;
3. teardown 无法恢复(步骤 1 未记录),**泄漏持续整个进程**;
4. 其后的 4 个 `@pytest.mark.integration` 真模型测试(test_bge.py:248-291)实例化 `BGEEmbedder/BGEReranker` → 经泄漏变量把 hub 缓存解析到一次性 tmp 目录 → 权重必然缺失 → **现场联网下载**(bge-m3 ≈3.3GB + reranker ≈2.2GB);
5. 本机到 HF 的实际带宽为突发 ~2MB/s 且多次分钟级停滞(Run A 实测:17 分钟 2.2GB;采样栈 390 帧 hf_xet、`_pthread_cond_wait`)。

**结论(证据充分的外推):任何"裸环境"全量运行都要为该泄漏支付 25~50 分钟下载时间——这是 36:45 的主体构成。** 历史运行的 shell 环境无法回溯观测,故标注为"强证据外推"而非直证;但"干净环境 ≤85s"是两轮直证,不可辩驳。另注意:**tmp_path 每次运行都是新目录,所以该下载每个全量运行都重付,无缓存摊销。**

## 3. Top 50(Run C,`--durations=2000 --durations-min=0`,全量捕获 1999 条相位记录)

前 20(完整 50 条见证据文件 askai_profile_runC.log):

| # | 总耗时 | setup/call/teardown | 用例 |
|---|---|---|---|
| 1 | 6.01s | 0 / 6.01 / 0 | connectors/test_web_crawl.py::test_run_stats_reports_failures_without_breaking_crawl |
| 2 | 4.39s | 0.03 / 4.36 / 0 | services/test_504_golden_regression.py::test_new_execution_plane_keeps_real_backend_responsive |
| 3 | 3.67s | 0 / 3.67 / 0 | embedder/test_bge.py::test_embedder_produces_vectors |
| 4 | 3.30s | 0.07 / 3.03 / 0.20 | services/test_504_golden_regression.py::test_old_inline_pattern_starves_event_loop |
| 5 | 2.21s | 0 / 2.21 / 0 | connectors/test_filesystem.py::test_filesystem_fetch_changes_mtime_filter |
| 6 | 1.48s | 0 / 1.48 / 0 | api/admin/test_data_source_delete_document_local.py::test_real_weaviate_delete_document_local |
| 7 | 1.08s | 0 / 1.08 / 0 | embedder/test_bge.py::test_reranker_scores_pairs |
| 8 | 1.02s | 0 / 1.02 / 0 | embedder/test_bge.py::test_reranker_single_document_returns_list |
| 9 | 0.88s | 0 / 0.88 / 0 | test_lifespan_smoke.py::test_lifespan_starts_and_wires_llm_state |
| 10 | 0.72s | 0 / 0.72 / 0 | embedder/test_bge.py::test_embedder_dimension_property |
| 11-26 | 各 0.65-0.67s | **setup 0.65 / call 0.01** | api/admin/test_llm_allowed_hosts.py(10)+ test_leads.py(8)等 |
| 27 | 0.64s | 0 / 0.64 / 0 | auth/test_jwt.py::test_hash_and_verify_password(bcrypt 实测位) |
| 28-32 | 各 0.51-0.57s | setup 0.5 左右 | pipeline/test_ingest_prune_document_local.py 真 Weaviate 4 例 |
| 33-50 | 各 0.25-0.45s | — | admin auth/users/analytics、local_git、sync_executor 等 |

**集中度:call 相位全 suite 共 32.1s,Top10 用例合计 24.8s(77%)。**

## 4. Time Distribution

### 4.1 相位(Run C,捕获 81.3s / 实际 83.54s)

| 相位 | 耗时 | 占比 |
|---|---|---|
| **setup** | **48.06s** | **59%** |
| call | 32.06s | 39% |
| teardown | 1.15s | 1% |
| (解释器/收集启动) | ≈2.3s | — |

**大头是 fixture 机器,不是测试体。** setup≥0.1s 的用例 182 个,合计 46.3s(占全部 setup 的 96%)。

### 4.2 目录

| 目录 | 耗时 | 用例数 | 备注 |
|---|---|---|---|
| tests/api/admin | **46.07s** | 176 | 其中 **setup 42.0s vs call 4.0s(91% 是 fixture)** |
| tests/connectors | 11.21s | 75 | 最大单例是 web_crawl 限速 sleep(6.01s) |
| tests/services | 9.63s | 66 | 504 黄金回归两例占 7.7s |
| tests/embedder | 6.49s | 11 | 4 次真模型加载 |
| tests/pipeline | 3.29s | **282** | 用例最多的目录反而最便宜(MagicMock embedder) |
| 其余合计 | ~6s | ~155 | retrieval 47 例 ≈0s,llm 24 例 0.07s |

### 4.3 模块 Top10

test_504_golden_regression 7.69s(n=2)> test_bge 6.49s(n=11)> test_web_crawl 6.01s(n=14)> test_llm_providers 5.87s(n=27)≈ test_analytics 5.69s(n=25)≈ test_llm_allowed_hosts 5.33s(n=10)≈ test_leads 5.28s(n=8)。

### 4.4 skips(Run D `-rs` 权威清单,共 6)

1. `api/admin/test_sync_trigger_isolation.py:320` — 条件跳过(库内存在其他启用源)
2-3. `e2e/test_symbol_recall.py:27,43` ×2 — 环境门控(`RUN_SYMBOL_E2E=1`)
4-6. `scripts/test_sync_db.py:59,174,247` ×3 — local_git 已移除 registry 注册(决策 2A)

注意:真 Weaviate 集成测试(prune/ghost/delete_document_local)**在本机都跑了**(21100 容器在线);它们不可达时会静默转 skip——**skip 集合随环境漂移,门禁脚本必须断言 skip≤6 而非忽略 skip**。

## 5. Marker Inventory

| marker | 注册 | 用例数 | 占比 | 实测 wall |
|---|---|---|---|---|
| unit | pyproject 已注册 | 556 | 52.3% | **9.04s**(Run E) |
| integration | 已注册 | 67 | 6.3% | **17.91s**(Run F,64+3skip) |
| slow | 已注册 | **0** | 0% | — **注册后从未使用,确证** |
| **无标记** | — | **442** | **41.5%** | ≈55s(由 83.5−9−18−启动 推得) |

- unit/integration 重叠仅 1 例;无标记 442 例。
- **捕获耗时归因(Run C,≥5ms 用例):unmarked 59.6s(73%)/ integration 16.6s / unit 5.1s。**
- 语义一致性抽查:admin 套件(176 例,DB+HTTP 栈)几乎全无标记;embedder 真模型测试正确标了 integration;少量历史文件用 `pytestmark = integration` 整文件标注。**结论:marker 已注册但体系未建成——slowl 是死条目;41.5% 用例游离在外;不能直接拿 marker 当门禁分片依据,但 unit(9s)与 integration(18s)两片的实测数字已天然可用(见 §8)。**

## 6. Root Cause Classification(Top offenders 逐个读源码定案)

| 类别 | 证据 | 耗时/暴露面 |
|---|---|---|
| **隔离缺陷→网络下载(P0,本次新发现)** | §2.3 归因链;Run A 留证(采样栈 + .incomplete blob 增长曲线) | 裸环境每次全量 +25~50min |
| **per-test bcrypt(fixture 固定成本)** | `hash_password` 实测 0.224s/次、verify 0.203s;`role_headers` 每测试 3 次哈希(test_llm_allowed_hosts.py:43-66)= 0.67s,与观测 setup 0.65-0.66s 吻合;27 处调用分布 15 个测试文件;admin 161 例 setup≥0.15s 合计 42.0s | **≈42s(全 suite 的 50%)** |
| **真实 sleep(生产代码限速路径)** | web_crawl.py:485,553 `time.sleep(crawl_delay_ms=500)`;Top1 用例 6.01s≈12 次×0.5s(mock 网络但真 sleep) | ≈6-8s |
| **真实 sleep(测试代码)** | test_filesystem.py:119,121 两次 `time.sleep(1.1)` | 2.21s |
| **模型加载(无复用)** | test_bge.py:248-291 四个集成测试各自构造模型(2×bge-m3 + 2×reranker);backend/embedder 无 singleton/缓存;`test_embedder_dimension_property` 只为读一个属性就完整加载一次 bge-m3(0.72s) | ≈6.5s(暖缓存;冷缓存放大数倍) |
| **e2e 类(有意为之,不建议动)** | test_504_golden_regression 起真 uvicorn+事件循环饿死实验,时间预算写死(1s 超时断言、8s 恢复轮询) | 7.7s |
| **Docker 服务集成(真 Weaviate)** | 6 例连 localhost:21100(p0a/p1 双门控常量同端口);集合名 uuid 随机(`DelSafety{uuid}`)仅 ProbeP1 固定 | ≈4s |
| **app 启动** | test_lifespan_smoke 单例 0.88s(模型已 mock);FastAPI TestClient/ASGITransport 每测试建连属毫秒级 | <1.5s |
| **DB create/drop** | 函数级 `db_engine` 每测试 create_all+drop_all(19 表),但直接依赖仅 6 个 fixture 点/约 20-30 例;pipeline 282 例总共 3.29s | **<4s,不是瓶颈(反直觉,实测推翻预设)** |
| 网络(live) | 无。llm/deepseek、retrieval、web_crawl 全部 mock 断网验证 | 0 |

## 7. DB Isolation Findings

**现状架构**(tests/conftest.py + tests/api/admin/conftest.py):

1. 全局 `db_engine`:函数级,每用例 `init_db`(create_all 19 表)→ 测试 → `drop_all` → `dispose`。DSN 优先 `TEST_DATABASE_URL`,回退 `.env`。
2. admin 套件:session 级 `_setup_app_state`(autouse)手动 init app.state + seed LLM 供应商/路由/默认定制;用例经 `app.state.session_factory` 直写 DB,各自负责清理(显式 DELETE)。session 级事件循环(`loop_scope="session"`,31 个文件)。
3. `TEST_DATABASE_URL` 约定指向共享 `ask_ai_test`;并行窗口各自全量跑会互踩(历史已知:种子/用户行丢失→401)。本轮为此建专用库 `ask_ai_profile_c` 跑 A/B。

**为什么当前不能安全 xdist(静态证据):**

- **B1 共享单库 + 每测试 DDL**:`db_engine` 的 `drop_all` 会砸掉其他 worker 正在用的表;admin session 级 seed 与各测试的数据清理也会跨 worker 冲突。
- **B2 库名守卫**:`test_migrate_llm_chain_format.py:32` `assert "ask_ai_test" in dsn` ——任何 per-worker 库改名即 ERROR(Run B 直证 3 errors)。
- **B3 进程级环境突变**:admin conftest session 起手写 `LLM_ALLOWED_HOSTS`;§2.3 的 HF 泄漏就是该风险类的现行案例。
- **B4 共享 Weaviate**:6 例真集成共享 21100 单容器;ProbeP1 固定集合名是唯一硬撞点(其余用 uuid 名)。
- 中性:session 级 event loop 在 xdist 下按 worker 隔离(每 worker 独立进程),504 回归用临时端口,tmp_path 天然隔离。

**评估(本轮只评估不实现):**

| 方案 | 结论 |
|---|---|
| **per-worker database(template 克隆)** | 推荐:模板库建好 19 表,每 worker `CREATE DATABASE ... TEMPLATE` 毫秒级;`TEST_DATABASE_URL` 由 xdist worker 注入;需同时拆掉 B2 守卫 |
| schema-per-worker | 不推荐:19 表 create_all 语义、跨 schema 搜索路径易埋雷 |
| transaction rollback | 理论最优但要求重写 fixture 语义(现架构直接 commit + 跨 fixture 读 app.state.session_factory),改动面大 |
| container-per-worker | Postgres 不值(本机 DDL 实测便宜);Weaviate 若将来并行化再考虑 |

## 8. Recommended Gate Model(数字全部实测,非硬凑)

| Gate | 选择 | 实测 | 何时跑 | 依赖 |
|---|---|---|---|---|
| **FAST** | `-m unit` | **9.0s / 556 例** | 每次 ide save 后/提交前;Executor 自检 | 无 DB/无模型/无网络(hermetic) |
| **INTEGRATION** | `-m integration` | **17.9s / 64+3skip** | PR/合并前 | Postgres + Weaviate + 暖模型缓存(offline) |
| **FULL** | `pytest tests`(全量) | **84s / 1058+6** | 发版前、集成门、双窗口协议验收点 | 同上;必须 1058/6/0 |
| (现状 CI) | build.yml 的 `--ignore` 子集 | 31.2s / 853 | 每次 push | 无模型(绕开 embedder) |

- 三个门全部落在 FAST≤2min / INTEGRATION≤5-10min 的建议线内,**无需新增 slow marker、无需重标任何测试**。
- **绝不能被跳过的**:FULL 必须包含 admin 全套(178)、BGE 集成 4 例、真 Weaviate 6 例;skip 集合恒等 §4.4 的 6 例(建议门禁脚本断言 `skipped<=6` 并打印名单)。
- §8.4 现状风险:CI 用 `--ignore` 列表做隐式分层,admin 176 例**从未进过 CI 门禁**;建议后续把 CI 切到 marker 驱动(依赖 §9-B6 回填),本轮不改。

## 9. Optimization Backlog(Impact/Effort/Risk,含基线对比方案)

| # | 项 | Impact | Effort | Risk | 验证方案(每项通用:同一命令跑 Run C 基线对比) |
|---|---|---|---|---|---|
| B1 | **HF env 泄漏修复**:conftest 加 autouse fixture 对 HF_HOME/HF_HUB_CACHE/TRANSFORMERS_CACHE 做快照/恢复(或两个测试改 monkeypatch.setenv) | 裸环境全量 36min→≤3min | XS | 低 | 裸环境全量复跑 ≤180s;断言 HF 变量逐用例不变;用例数 1058/6/0 不变 |
| B2 | **bcrypt 常量化**:测试内 `hash_password("pass123")` → 模块级预计算哈希常量(保留 test_jwt 1 例测真哈希);或 per-test 用户改 session 级 | 全量 84s→≈45s;admin 46s→≈8s | S | 低 | setup 总量 48→<10s;Top50 不再见 0.65s 平台 |
| B3 | **crawl_delay 注入**:web_crawl 测试传 `crawl_delay_ms: 0` | −6~8s | XS | 低 | Top1 用例 6.0s→<0.5s |
| B4 | **BGE session 级共享 fixture**:4 次加载→1 次 | −4~5s(冷缓存收益放大) | S | 中低 | test_bge 模块 6.5s→≈3s;device/fp16 断言不弱化 |
| B5 | filesystem mtime sleep → `os.utime`/注入时钟 | −2.2s | S | 低 | 该用例 2.2s→<0.1s |
| B6 | **marker 回填**(442 unmarked→按文件审阅归类)+ 默认加 `-ra` | 门禁分片可靠性;skip 可见性 | M | 中(须逐文件审,防语义漂移) | unit/integration 两片用例数之和=1064;slow 只标有据可查者 |
| B7 | **xdist 前置**(§7 方案:template per-worker + 拆 B2 守卫 + ProbeP1 加 worker 后缀) | FULL 再÷N | L | 中高 | 双 worker FULL 与单 worker 用例数/flaky 率一致 |
| ✗ | 不做:批量重标 slow、删慢测试、隐藏 E2E、直接上 xdist | — | — | — | 硬边界 1-5 |

## 10. xdist Decision:**LATER**(现阶段 NOT_WORTH_IT)

干净环境 FULL=84s,FAST=9s——当前瓶颈量级下引入 xdist 属于负收益:需要先完成 B1/B2/B7 与 §7 四个阻塞项,还要承担 flaky 面扩大与双窗口协议复杂度。**触发重估条件:干净 FULL>5min,或 CI 需要并行压缩 build 时间。**

## 11. Estimated Benefit

| 状态 | 现状 | B1 后 | B1+B2+B3+B4+B5 后 |
|---|---|---|---|
| 裸环境全量(现状默认) | **36:45** | **≤3min** | ≤2.5min |
| 干净环境全量 | 84s | 84s | **≈38-42s** |
| FAST(-m unit) | 9s | 9s | ≈7s |
| INTEGRATION(-m integration) | 18s | 18s | ≈14s |

## 12. Risks

1. **覆盖红线**:所有优化必须以"1058 passed / 6 skipped / 0 failed"逐字不变为验收硬条件;门禁脚本应内置该断言。
2. 36:45→下载的归因是强证据外推(历史 shell 环境不可回溯),但"干净环境 84s×2 轮"是直证,结论不受影响。
3. **skip 集合随环境漂移**:真 Weaviate 测试不可达时静默 skip;CI(无模型/无容器)现状直接 --ignore 掉 embedder/admin——分层语义目前只在本地成立,CI 门禁等价性未经验证。
4. 共享 `ask_ai_test` 的并行窗口互踩风险依旧存在(本轮用专用库+连接检查规避);协议上全量验证建议错峰或 per-window 库(依赖 B7)。
5. CI 若有一天把 embedder 纳入门禁而无暖缓存,会遇到与本轮 Run A 同构的下载问题(B1 修的泄漏在 CI 同样致命)。
6. 本轮零实现;上述 backlog 均未实施,数字为测量+机制推算,落地后须按 §9 验证方案逐项对账。

## 13. Recommended Next Task

**单个小步实现任务:「测试隔离与 fixture 性能修复包」= B1(HF env 泄漏)+ B2(bcrypt 常量化)+ B3(crawl_delay 注入)+ 默认 `-ra`**,验收=§9 对应验证方案 + 全量 1058/6/0 不变 + 干净环境全量 ≤45s + 裸环境全量 ≤3min。B4/B5 并入同任务可选;**B6 marker 回填单独立项;B7 xdist 明确延期**。该修复包不在 CamThink V1 Critical Path 上,属工程生产力轨道。

---

### 附:证据文件(docs 仓 `implementation/evidence/test-suite-perf-2026-09-03/`)

| 文件 | 内容 |
|---|---|
| askai_profile_runC.log | Run C 全量 durations(--durations-min=0,权威性能画像) |
| askai_profile_runD.log | Run D `-rs`(skip 身份 + 复现计时) |
| askai_runE_unit.log / askai_runF_integration.log | marker 分片计时 |
| askai_runG_ci_subset.log | CI 同款子集计时 |
| profile_runA_evidence.txt | Run A 挂死证据(hf_xet 栈帧计数 + .incomplete blob 尺寸/时刻) |
