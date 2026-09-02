# CAMTHINK_V1_CUSTOMIZATION_PROMPT_HOT_RELOAD_CLOSURE_2026-09-02

- Gate: Customization Prompt Runtime Hot Reload Closure(小切口闭环)
- 分支:`task/customization-hot-reload`;worktree:`.worktrees/custom-hot-reload`(基于 origin/main 新建,未触碰其他活动 worktree)
- 结论: **PASS**(保存即生效;原子快照;失败语义显式;相关回归全绿)

## 1. Baseline

- `git fetch origin` 后 `origin/main = 4d692e9a3e5597fd5730c81b6e91d091e6ff2aed` —— 与任务预期 baseline **完全一致**(origin/main==baseline,无漂移),未触发 BLOCKED。
- worktree 拓扑:5 个既有 worktree 全部保留未动;本任务新建 `.worktrees/custom-hot-reload`(branch `task/customization-hot-reload` @ 4d692e9)。`.env` 未链接/未提交;无模型资产需求(源级实现 + mock 边界测试)。
- **Sales Lead 在场确认**(修订旧 Discovery 的过期结论):当前 main 的 `backend/pipeline/rag.py` 含已验收 Sales Lead 实现(68 处引用)+ `tests/pipeline/test_rag_lead.py`(61 处)/`tests/api/admin/test_ask_lead_flow.py`,本 Gate 未触碰其行为。

## 2. Root Cause(当前 main 复核,与 Discovery 一致)

- `load_customizations_from_db`(`config_loader.py:53`)**仅在 lifespan** 执行(`main.py:338`),结果经 `main.py:344` 投影为 `{channel: 合并后 system_prompt}` 注入 `RAGOrchestrator._channel_customizations`;
- Admin 四个变更端点(create/update/delete/binding,`admin/customizations.py`)**只写 DB**,无任何运行时刷新;
- `RAGOrchestrator._build_messages`(rag.py:508)每请求读 `self._channel_customizations.get(channel, self._system_prompt)` → 进程内快照永不过期 ⇒ **保存成功 ≠ 运行时生效,必须重启**。

## 3. Implementation(最小,原子快照)

| 文件 | 变更 |
|---|---|
| `backend/pipeline/rag.py` | 新增 `set_customization_snapshot(channel_customizations, default_system_prompt=None)`:**整体引用替换** `_channel_customizations`(先局部构建完整 dict 再一次性赋值)+ 可选同步默认回退 prompt;docstring 冻结并发语义与组合不变性 |
| `backend/services/config_loader.py` | 新增 `refresh_runtime_customizations(state)`:重读 DB 绑定+定制 → 与启动同源的 yaml 回退逻辑 → 调用快照替换;`state.rag` 缺失 → no-op(测试环境);失败向上抛出 |
| `backend/api/admin/customizations.py` | 新增 `_refresh_or_500(request)`:四个变更端点(create/update/delete/`PUT customization-bindings/{channel}`)**持久化 commit 成功后**调用;刷新异常 → `HTTP 500 {"detail":"配置已保存,但运行时刷新失败(新配置尚未生效,请重试保存或重启后端):…"}` —— 显式区分「已持久化」与「已激活」 |

**触发面判定**(合同 §5):create/update/delete/binding 四类均改变 `load_customizations_from_db` 的输出(绑定变更改变渠道→定制映射;delete 经 CASCADE 级联删绑定)→ 四类都需刷新。其他 Admin 操作(users/leads/llm/data-sources/…)不触碰该函数。

**运行时状态转换**:`OLD snapshot ──DB commit──▶ refresh(重读 DB)──▶ 原子 swap ──▶ NEW snapshot`。请求侧只做 dict 读取(Python 引用读原子)→ 并发请求只会看到旧或新完整配置(AC-05)。

**失败语义**:持久化失败 → commit 未发生 → 刷新不会调用 → 运行时保持旧快照(AC-04);持久化成功后刷新失败 → HTTP 500 显式上报 + 运行时保持旧快照(不伪造「已生效」;DB 真相与运行时的差异由 500 与 error 信息暴露,用户可重试保存或重启)。刷新本身为单读单写,无部分状态。

**并发/部署假设**:单 backend 进程为 V1 部署形态(compose 单容器);多 worker/多容器下刷新仅作用于受理请求的 worker —— 若未来改多 worker,需要 config-version 轮询/总线,超出本 V1 闭环,此处仅显式记录,不做分布式失效。

## 4. Tests(G001–G006,真实 app+DB+RAGOrchestrator,仅检索/LLM 外部 mock)

`tests/api/admin/test_customization_hot_reload.py`(6 例,复用 `tests/api/admin` conftest 的 TEST_DATABASE_URL 会话):

| 用例 | 证明 | 结果 |
|---|---|---|
| G001 `test_g001_patch_system_prompt_hot_reloads` | PATCH system_prompt → 无重启,`_channel_customizations["whatsapp"]` 与**真实 `answer()` 生成消息**均含新 prompt | PASS |
| G002 `test_g002_patch_style_and_guardrails_hot_reloads` | style/guardrails PATCH → 新值进入下一条 system 消息且 SYS<STYLE<GUARD | PASS |
| G003 `test_g003_rebind_channel_uses_new_customization` | 绑定 whatsapp:hot-cust → other,渠道映射与组合输出随之切换 | PASS |
| G004 `test_g004_failed_persistence_keeps_previous_snapshot` | 404/409 持久化失败路径 → 快照逐键不变 | PASS |
| G005 `test_g005_refresh_failure_is_explicit_and_snapshot_stale_marked` | 刷新抛错 → HTTP 500「…运行时刷新失败…」+ 快照保持旧值(不伪装已生效) | PASS |
| G006 `test_g006_composition_order_preserved` | ORD_SYS < ORD_STYLE < ORD_GUARD < INTENT_STYLE_TAIL(真实 `_build_messages`) | PASS |

RED 实证:实现前 G001/G002/G003/G006 failed、G005 error(刷新 API 不存在)、G004 passed(持久化失败安全为既有语义)。

## 5. Executed Verification(真实命令与结果)

| 套件/命令 | 结果 |
|---|---|
| `pytest tests/api/admin/test_customization_hot_reload.py` | **6 passed** |
| 合同指定组合(test_customizations + config_loader + test_rag + multilingual×2 + citation + trust_boundary + rag_lead + ask_lead_flow) | **122 passed + 2 teardown errors**(`test_ask_lead_flow` 拆卸协程错误) |
| ↳ 同组合于**未改动 pristine main**(stash 后)复跑 | 同样错误 → **预存在的测试隔离问题,非本 Gate 引入**(已如实标注) |
| `pytest tests/pipeline/test_rag_lead.py` / `tests/api/admin/test_ask_lead_flow.py`(单独) | 11 passed / 3 passed |
| `pytest tests/pipeline tests/services`(broad)+ 热重载套件 | **460 passed** |
| `pytest tests/pipeline tests/scripts tests/services tests/db tests/connectors tests/retrieval tests/utils tests/auth`(P0/P1 线同基组合) | **532 passed / 3 skipped** |
| black(4 个变更文件) | 通过 |

环境:`TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@127.0.0.1:5432/ask_ai_test`(本地 5432 ask_ai_test)。

## 6. AC Matrix

| AC | 结果 | 证据 |
|---|---|---|
| AC-01 更新热重载 | PASS | G001 |
| AC-02 绑定热重载 | PASS | G003 |
| AC-03 删除安全 | PASS | delete 端点刷新;级联删绑定由重读 DB 全量覆盖( orphan 绑定消失即映射消失);G003 同机制 |
| AC-04 失败安全 | PASS | G004 |
| AC-05 原子快照 | PASS | 整体引用替换 + G004/G005 断言 |
| AC-06 组合不变 | PASS | G006(真实 _build_messages) |
| AC-07 流式/非流式 | PASS | 共用 `_build_messages` 未动;G001 用真实 `answer()` 验证 |
| AC-08 渠道回退 | PASS | 回退逻辑(refresh 内 default=widget/yaml)与启动同源;G005 未激活路径保持旧回退 |
| AC-09 回归 | PASS | §5(122+460+532;2 个 teardown 错误为预存在,已复现于 pristine main) |
| AC-10 无范围蔓延 | PASS | 变更仅 3 个后端文件 + 1 个新测试文件 |

## 7. Residual Risks

1. 多 worker/多容器部署下刷新仅覆盖受理 worker(单进程为 V1 假设;需分布式失效时另立 Gate);
2. 刷新失败的 HTTP 500 语义:DB 已保存、激活未完成 —— 前端当前会展示错误,用户重试保存即可收敛(可接受的最小行为);
3. `test_ask_lead_flow` 与 `test_customizations` 同批运行存在预存在隔离问题(main 可复现),建议独立小任务修复(与本 Gate 无关)。

## 8. Production Boundary

PRODUCTION_ACCESS = NO;PRODUCTION_MUTATION = NO(全程本地 worktree + 本地 5432 ask_ai_test)。

## 9. Commits

- IMPLEMENTATION_COMMIT: `e2076e1ec12638ab9af0a3f61f3398a5d218921d`
- REPORT_COMMIT: 见交付(tip)
- FINAL STATUS = PASS
