# ASK-AI — Test Isolation & Fixture Performance Closure 报告

- 日期:2026-09-03
- 窗口:WINDOW C(并行执行)
- 仓库:harryhua-ai/ask-ai
- BASELINE_COMMIT:`269cadb0ce6a3ce47059e0f4b074f356e41612eb`(origin/main 核验一致)
- 分支:`worktree-exec/test-isolation-performance-20260903`
- worktree:`.worktrees/test-isolation-performance`
- IMPLEMENTATION_COMMIT:`edcf98d`(已推 origin)
- CODE_MUTATION 面:**仅 4 个测试文件(+174/−27),生产代码零改动**

## 1. 前置核验

- `git fetch origin` 后 `origin/main == 269cadb0…` == 指定基线 ✅(否则已 STOP);
- 独立 worktree/分支自基线精确创建 ✅;
- 环境遵守:env/DSN 以 shell 变量注入;模型权重用**既有本地物理路径**(`MODEL_CACHE_DIR=<主仓>/models`,无软链、无拷贝、无提交);无密钥/env 入库。

## 2. 缺陷与成本根因(实测定位)

### 2.1 B1 HF env 泄漏(正确性缺陷,首要)

- 生产函数 `backend/embedder/bge.py::_ensure_hf_cache` L34-36 以 `os.environ.setdefault` 写 `HF_HOME/HF_HUB_CACHE/TRANSFORMERS_CACHE`(进程级,生产语义);
- 泄漏源 = `tests/embedder/test_bge.py` 中 4 个 fake-FlagEmbedding 构造器测试(`BGEEmbedder/BGEReranker(device=…, cache_dir=tmp_path)`):它们走**真实构造器**→触发 `_ensure_hf_cache(tmp_path)`,在 HF 变量缺失的裸环境下把进程 env 永久指向**测试后即销毁的 tmp 目录**(无任何恢复);
- 后续真实 BGE 集成测试(`cache_dir=None`)的 setdefault 被 tmp 值短路 → huggingface_hub 在死缓存中 miss → 触发 hf_xet 下载数 GB(Discovery Run A 实证);
- 顺带确证:`test_ensure_hf_cache_sets_env_vars` 本身因 monkeypatch.delenv 的 teardown 语义**不是**泄漏源;真凶是上述无保护的构造器测试。

### 2.2 其他成本(Discovery 数据,本轮逐一处理)

| 项 | 实测 | 处置 |
|---|---|---|
| admin per-test bcrypt(~42s) | 27 调用点/fixture 每测试实例化,~170 次 bcrypt(cost 12) | B2:进程内 lru_cache 真实哈希 |
| web crawl 失败重试真实退避 | `_http_get` L431 `time.sleep(1+attempt)`,ConnectionError 路径 1+2+3s/URL | B3:测试注入模块级 fake time + 退避值显式断言 |
| BGE 重复热加载(~6.5s) | 4 个集成测试各构造一次 | B5:module 级实例共享(2 次加载) |
| filesystem timing(~2.2s) | `test_filesystem_fetch_changes_mtime_filter` 2×1.1s sleep 拉开 mtime | B4:`os.utime` 确定性回拨 |
| 504 Golden Regression | 有意成本 | **KEEP,零触碰**(单独跑 2 passed/8.29s) |

## 3. 实现明细(全部测试侧)

### B1 HF 隔离(HARD CONTRACT 落地)

`tests/conftest.py`:新增 **autouse 守卫** `_hf_env_isolation`(function 级,全局生效):
- 测试前快照三个变量;teardown **精确恢复**——原本缺失→恢复缺失,原本存在→恢复原值;
- 生产 `bge.py` **零改动**(AC3:生产 BGE cache 行为不变;无 production bug,无 scope expansion);
- `tests/embedder/test_bge.py` 新增 3 个回归测试:
  - `test_hf_env_leak_step1_pollutes_via_ensure_hf_cache`:复刻旧缺陷路径(裸环境→tmp 污染);
  - `test_hf_env_leak_step2_next_test_sees_exact_restoration`:**跨测试哨兵**(AC2)——下一测试断言 env==模块会话基线;守卫缺失/恢复不精确即失败;
  - `test_hf_env_present_values_survive_ensure_hf_cache`:存在情形逐字节保留。

### B2 bcrypt(认证 coverage 不降)

`tests/conftest.py` 导入期(早于全部测试模块的 from-import 绑定)把 `backend.auth.jwt.hash_password` 替换为 `lru_cache` 包装:同一明文每 pytest 会话仅做一次**真实 bcrypt** 计算;`verify_password`/登录/失败路径零改动,未 mock authentication layer。
- 直证:`hash_password('probe123')` 两次调用同值、合法 bcrypt 格式、`verify_password` 对/错密码 = True/False;
- 真实 hash+verify 回归保留于 `tests/auth/test_jwt.py`(经同一包装仍是真实 bcrypt 算法);`test_auth.py`/`test_users.py` 登录与角色用例全绿;
- `tests/services/test_504_golden_regression.py` **整体未触碰**。

### B3 web crawl(生产语义保持)

`tests/connectors/test_web_crawl.py`:新增 `_fake_crawl_time`(monkeypatch 替换 `wc.time` 模块引用为记录型 no-op 时钟);`test_run_stats_reports_failures_without_breaking_crawl` 注入后**显式断言** `[s for s in sleeps if s>0] == [1.0, 2.0, 3.0]`——生产代码必须请求正确的退避延迟(3 次尝试),只是不再真实等待。生产 `web_crawl.py` 零改动;`crawl_delay_ms`/限速逻辑原样。
- 更正 Discovery 一处归因:第二个失败测试(`authoritative_source_ids…`)抛的是裸 `RuntimeError`,不走重试退避,原本就无 sleep;真实等待来自 run_stats 测试的 ConnectionError 路径(3s)。

### B4 filesystem(确定性替代,验收等价)

`tests/connectors/test_filesystem.py`:mtime 测试改写两文件后用 `os.utime(old, since-1h)` 确定性回拨;被测 `fetch_changes` 的 mtime 过滤语义零改动;2.2s 真实 sleep 归零(模块 14 passed/0.04s)。

### B5 BGE fixture 复用(隔离/语义有效才做——成立)

`real_embedder`/`real_reranker` module 级共享:encode/compute_score 无状态推理,生产同为单实例常驻(app.state.rag);4 个集成测试改用 fixture,断言逐字未动;模型加载 4 次→2 次。

## 4. 验证矩阵(任务要求逐项)

| 要求 | 结果 |
|---|---|
| HF env absent → restored absent | `test_hf_env_leak_step1/2` 哨兵对 ✅(裸环境基线=缺失) |
| HF env present → restored exact value | `test_hf_env_present_values_survive_ensure_hf_cache` + 守卫快照语义 ✅ |
| test ordering isolation | 守卫为 suite 级 autouse;step1→step2 文件内保序哨兵;fake-constructor 测试先于集成测试的真实文件序亦覆盖 ✅ |
| no accidental model download from leaked tmp cache | 裸环境哨兵:`env -u HF_HOME -u HF_HUB_CACHE -u TRANSFORMERS_CACHE` + `HF_HUB_OFFLINE=1`(范围限定的 tripwire:解析错缓存=快速失败而非下载)下 `pytest tests/embedder` **22 passed / 5.61s** ✅;未消耗任何 GB 级下载 |
| real cached model integration | `tests/embedder` 全模块 22 passed(真实加载+推理,warm cache)✅ |
| bcrypt auth regressions | `tests/auth/ + test_auth + test_users + test_conversations` 20 passed;包装语义直证(§B2)✅ |
| web crawl delay behavior | 退避 [1,2,3]s 显式断言 + 24 crawl tests passed ✅ |
| filesystem timing behavior | 等价 mtime 验收,14 passed ✅ |
| 504 Golden Regression retained | 全套内通过 + 单独 `2 passed / 8.29s`;零修改零跳过 ✅ |

## 5. 性能证据

命令(worktree 内):

```
export TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:ask_ai@localhost:5432/ask_ai_test \
       MODEL_CACHE_DIR=/Users/harryhua/Documents/GitHub/ask-ai/models \
       HF_HOME=<主仓>/models HF_HUB_CACHE=<主仓>/models/hub TRANSFORMERS_CACHE=<主仓>/models/hub \
       PYTHONPATH=$PWD
/usr/bin/time -p <主仓>/.venv/bin/pytest -q
```

环境假设:本地 Postgres 5432(ask_ai_test,asyncpg DSN);模型权重 warm cache=主仓 `models/hub`(BAAI/bge-m3 + bge-reranker-v2-m3 物理存在);HF 在线(无 OFFLINE 掩盖);macOS arm64 本机(有并行负载波动)。

| 轮次 | 结果 | wall time |
|---|---|---|
| 基线确认(269cadb,修复前) | 1066 passed + 6 skipped + 0 failed | **99.05s**(pytest 97.95s) |
| **FULL RUN 1(修复后)** | **1069 passed + 6 skipped + 0 failed** | **42.05s(pytest 40.21s)** |
| **FULL RUN 2(修复后)** | **1069 passed + 6 skipped + 0 failed** | **41.59s(pytest 39.74s)** |

- PERFORMANCE_DELTA:99.05s → 40.21/39.74s,**−59.6%**;两轮稳定(Δ0.5s);
- 目标 ≤60s:**达成**;hard ceiling ≤75s:余量 35s;
- 参照系说明:Discovery 的 84s×2 基于 1b8572a;本基线确认在 269cadb(+8 测试)实测 99.05s(当日机器偏慢),delta 以同日同环境同树前后对比为准。

## 6. Test Count / Coverage Invariant

- 基线 269cadb:1072 collected(1066P+6S);最终:1075 collected(**1069P+6S+0F**);
- 增量 = +3(全部为 B1 隔离回归测试);**零删除、零新增 skip、零 xfail、零 ignore、FULL 定义未变**;
- 6 skipped 与基线相同(既有用例,未新增)。

## 7. CI 影响

- CI 选择(build-image.yml test job:`pytest tests/ -q --ignore=tests/api/admin --ignore=tests/scripts/test_sync_db.py --ignore=tests/embedder --ignore=tests/e2e`)**未做任何改动**(不缩减、不扩);
- 本轮改动对 CI 子集为纯收益且零风险:conftest 守卫/哈希缓存自动生效,web_crawl/filesystem 修复均在 CI 路径内;CI 无 HF 缓存故 embedder 本就被 ignore,维持现状;
- CI Gate redesign 不在范围,未触碰。

## 8. 边界遵守

- 无 xdist(AC7)✅;无 marker 重写(AC8)✅;无测试数量/coverage 减少(AC9)✅;
- 未 merge main、未部署、未触生产(PRODUCTION_ACCESS: NONE);
- xdist 重新评估阈值:遵循任务给定(stable FULL > 5 分钟再评估)。

## 9. Known Limitations

1. `_ensure_hf_cache` 的进程级 setdefault 生产语义保留(AC3 要求);测试内触发的瞬时 env 变更由守卫在 teardown 恢复——若未来有人在**同一测试内**于 `_ensure_hf_cache` 调用前捕获 env 并在调用后断言 env 不变,会看到 setdefault 生效(那是生产语义,不是缺陷);
2. B2 的 conftest 导入期替换对测试会话内所有 `backend.auth.jwt.hash_password` 调用者生效(含生产代码路径的测试调用);均为真实 bcrypt,仅去重;若未来测试断言「两次注册同一明文产生不同盐哈希」将不成立(现无此类断言);
3. 裸环境哨兵使用范围限定 `HF_HUB_OFFLINE=1` 仅作为**失败加速 tripwire**(禁止全局 OFFLINE 掩盖的原则未被违反:全套件运行不带 OFFLINE);
4. 40s 结果含机器负载变量;两轮 Δ0.5s 且 user 时间稳定(~21s),复现置信度高;若他机 >75s 应按任务约定报 PARTIAL+profiling,而非篡改测试;
5. Discovery 所列「Admin bcrypt fixture ~42s」为 1b8572a 估算口径;本轮在 269cadb 以整轮前后差实测收敛(99→40s),未单独拆账 bcrypt 贡献。

## 10. Changed Files

| 文件 | 变更 |
|---|---|
| `tests/conftest.py` | +49:B1 autouse HF 守卫;B2 lru_cache 哈希包装(导入期生效) |
| `tests/embedder/test_bge.py` | +121/−27:B1 三个回归测试+基线捕获 fixture;B5 module 级 real_embedder/real_reranker |
| `tests/connectors/test_web_crawl.py` | +17:B3 `_fake_crawl_time` + run_stats 测试注入与退避断言 |
| `tests/connectors/test_filesystem.py` | +8/−6:B4 os.utime 确定性 mtime |
| 生产代码(backend/scripts/config) | **零改动** |

## 11. Final State

**CANDIDATE READY**

- AC1 ✅ HF 泄漏消除(哨兵对+裸环境 OFFLINE tripwire)
- AC2 ✅ 顺序不可再重定向死缓存
- AC3 ✅ 生产 BGE 零改动
- AC4 ✅ 认证 coverage 保留(真实 verify/错误密码/角色全绿)
- AC5 ✅ crawl 限速语义保留且被显式断言
- AC6 ✅ 504 Golden Regression 保留
- AC7 ✅ 无 xdist;AC8 ✅ 无 marker 重写;AC9 ✅ 数量/coverage 只增不减
- AC10 ✅ Full Suite 全绿 ×2;AC11 ✅ 40.21/39.74s ≤ 60s
