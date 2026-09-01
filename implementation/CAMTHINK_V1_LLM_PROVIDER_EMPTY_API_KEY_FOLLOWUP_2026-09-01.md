# CAMTHINK V1 — LLM Provider Empty API Key Follow-up Acceptance Closure

- TASK: FOLLOW-UP FIX ACCEPTANCE CLOSURE(证据收口,非新实现)
- 日期: 2026-09-01
- STATUS: **PASS**(本收口自评;Final Acceptance 归 Planner)
- BASELINE_COMMIT: 4544a42e1e45efb1efcb5ba220f904aefb56d90a(已独立验收的 LLM Provider 实现)
- IMPLEMENTATION_COMMIT: 9ff68d57b87b16459182aeb38d3fa5192500fcaf(冻结,零改动)
- EVIDENCE_TEST_COMMITS: 6c03c80(G005 stream 回归测试)、2dd9113(G004 generate 头锁定)——均为 **test-only**,无实现改动,分支头 = origin = 2dd9113
- REPORT_COMMIT: 见 docs 仓本文件提交
- REPORT_PATH: docs/implementation/CAMTHINK_V1_LLM_PROVIDER_EMPTY_API_KEY_FOLLOWUP_2026-09-01.md
- BRANCH: worktree-exec/admin-p1-llm-provider(origin,本地=远程核验一致)
- PRODUCTION_DEPLOYED: **NO**

---

## 1. Executive Result

用户真实测试发现:已通过端点显式授权的自建网关(`http://100.124.85.19:13000/v1`,内网级)在**未填 API key** 时,「从 API 拉取」仍失败。根因不是授权层,而是客户端 `DeepseekProvider` 三处无条件构造 `Authorization: Bearer ` 空值头,httpx 在**请求发出前**于本地抛 `LocalProtocolError: Illegal header value`。修复 `9ff68d5` 引入 `_auth_headers()`:空 key 返回空头部字典,有 key 行为不变。本收口独立重建了 Git 关系、根因路径、七场景证据与回归,结论:**修复成立、边界未弱化、范围紧贴缺陷**。

## 2. Product-Origin Context

- 产品负责人手工实测 LLM Provider Management(4544a42 已验收特性)时发现上述真实缺陷,明确授权执行端修复。
- 端点 `100.124.85.19` 已通过新工作流授权(内网级,allow_private=true),失败发生在**授权之后**。
- AUTHORIZATION_STATUS = USER_AUTHORIZED_FOLLOW_UP_FIX。

## 3. Authorization Status

USER_AUTHORIZED_FOLLOW_UP_FIX。本 Gate 仅做证据闭环,不做追溯性范围否决。

## 4. Baseline / Final Commit(Git 核验,非假设)

- `git log --format="%h %p" -1 9ff68d5` → `9ff68d5 4544a42`:**直接父子关系**,区间 `4544a42..9ff68d5` 仅 1 个提交。
- Diff 审计(`git diff --stat 4544a42 9ff68d5`):**恰好 2 个文件** — `backend/llm/deepseek.py`(+24/-10 上下文内)与 `tests/llm/test_deepseek.py`;无任何额外生产文件。

## 5. Root Cause

`backend/llm/deepseek.py`(4544a42 版)在 L75(generate)、L129(stream)、L183(list_models)三处均硬编码:

```python
headers={"Authorization": f"Bearer {self._api_key}"}
```

当 `api_key=""` 时产生 `Authorization: Bearer `(空 token)。httpx 在客户端头部校验阶段即拒绝非法头值,抛 `httpcore.LocalProtocolError: Illegal header value b'Bearer '`——这是**本地协议层失败**,与远端网关的鉴权策略无关。

## 6. Failure Path(逐跳)

`POST /api/admin/llm-providers/{id}/fetch-models`(表单带 api_base,无 key)
→ `load_endpoint_authorization` + `validate_llm_api_base`(**通过**,端点已授权)
→ `LLMRegistry.create("openai_compatible", api_key="")`
→ `DeepseekProvider.list_models()` → `httpx.AsyncClient.get(f"{api_base}/models", headers={"Authorization": "Bearer "})`
→ **本地抛 LocalProtocolError,零字节上线**
→ 被端点兜底为脱敏通用文案「拉取模型失败(详见服务端日志)」。

日志证据(4544a42 运行期实测):traceback 终点 `httpcore.LocalProtocolError: Illegal header value b'Bearer '`。

## 7. Frozen Product Behavior(核验通过)

- 有 key:三处调用点在 `9ff68d5` 后仍产生 `Authorization: Bearer <key>`(G002/G004 测试锁定精确头字典)。
- 无 key:不发 Authorization 头,请求正常发出,远端决定结果(免鉴权网关可接受;要鉴权网关 401/403)。
- 空 key ≠ 绕过远端鉴权;仅 = 不发非法头。

## 8. Security Boundary(未弱化,证据)

`9ff68d5` 的 diff **只触碰** `deepseek.py` 头部构造 + 其测试;不涉及 schemas / llm_providers / main / allowed-hosts 任何一行。授权层调用序列不变:端点授权 → 请求放行 → 有 key?Bearer : 无头 → 远端裁决。活体复核:
- 未授权端点 + 空 key 创建供应商 → **422「尚未授权」**(空 key 不构成绕过);
- 已授权端点 + 空 key 拉取 → 请求上线,**远端返回 401**(服务端日志 `HTTPStatusError: Client error '401 Unauthorized' for url 'http://100.124.85.19:13000/v1/models'`,当日新鲜复现;`Illegal header` 计数 0)。
- 凭证零泄漏:空 key 下无凭证可泄;有 key 路径头仅存在于出站请求,响应/日志不含 key。

## 9. Changed Files / Diff Audit

| 提交 | 文件 | 性质 |
|---|---|---|
| 9ff68d5 | backend/llm/deepseek.py | 实现:`_auth_headers()` 助手 + 三处调用点替换(另含 black 格式化的 logger 参数换行,无语义) |
| 9ff68d5 | tests/llm/test_deepseek.py | 测试:G001/G002/G003 场景 |
| 6c03c80 | tests/llm/test_deepseek.py | test-only:G005 stream 回归 |
| 2dd9113 | tests/llm/test_deepseek.py | test-only:G004 generate 头锁定 |

无未解释的额外生产变更。

## 10. FOLLOW-G001..G007

| 场景 | 结果 | 证据(确定性) |
|---|---|---|
| G001 空 key / list_models | PASS | `test_list_models_empty_api_key_omits_authorization_header`:断言发出的 headers 无 `Authorization`;历史 RED 已观察(见 §11) |
| G002 有 key / list_models | PASS | `test_list_models_with_api_key_sends_bearer_header`:精确断言 `{"Authorization": "Bearer sk-x"}` |
| G003 空 key / generate | PASS | `test_generate_empty_api_key_omits_authorization_header`:fake_post 捕获 headers,断言无 `Authorization` |
| G004 有 key / generate | PASS | `test_generate_with_api_key_sends_bearer_header`(2dd9113 新增):精确断言 `{"Authorization": "Bearer sk-live"}` |
| G005 空 key / stream | PASS | `test_stream_empty_api_key_omits_authorization_header`(6c03c80 新增);**revert 验证**:临时还原 stream 处旧无条件头 → 该测试 FAIL(复现缺陷类),恢复 `_auth_headers()` → PASS(当日实测) |
| G006 远端鉴权权威 | PASS | 活体:已授权 `100.124.85.19` + 空 key 拉取 → 网关真实 `401 Unauthorized`(服务端日志),客户端未造凭证、未绕过;`Illegal header` 0 次 |
| G007 端点授权仍必需 | PASS | 活体:未授权 `api.together.xyz` + 空 key 创建供应商 → 422「尚未授权」;回归套件 tests/api/admin/test_llm_allowed_hosts.py(18)+ test_llm_providers.py(27)全绿 |

## 11. RED → GREEN Historical Evidence

- **HISTORICAL_RED = DOCUMENTED(9ff68d5 作者会话内直接观察,非补造)**:实现前运行 5 个新测试,输出 `2 failed, 12 passed` —— `test_list_models_empty_api_key_omits_authorization_header` 与 `test_generate_empty_api_key_omits_authorization_header` 因"空 key 仍发 Authorization 头"而失败;应用 `_auth_headers()` 后同套件 `19 passed`。
- **G005 RED = RE-RUN(本收口当日)**:revert 验证(还原 stream 调用点 → FAIL;恢复 → PASS),证明该回归测试具备缺陷捕获能力。
- G002/G004 为既有行为的正向锁定(post-fix 编写,不需要 RED)。

## 12. Direct Focused Test Evidence(分支头 2dd9113,当日新鲜运行)

`pytest tests/llm tests/api/admin/test_llm_providers.py tests/api/admin/test_llm_allowed_hosts.py tests/test_lifespan_smoke.py tests/test_main.py -q`
→ **76 passed, 0 failed**(llm 16 + providers 27 + allowed-hosts 18 + lifespan_smoke 8 + main 7)。
指定头行为测试点名运行:`-k "empty_api_key or with_api_key"` → 4 passed(后 G004 补测后全套 16 passed)。

## 13. Later Integration Regression Evidence(引用,非本提交历史证据)

集成分支 `integration/camthink-v1-p0-p1` 候选提交 `e945f59` 已包含本修复的 **cherry-pick 等价提交 `f496efc`**(patch-id `5c2e65ed…` 与 `9ff68d5` **完全一致**,已核验;同法核验 c016e27 ↔ 4544a42 亦等价)。e945f59 报告:后端全量 656 passed + 3 skipped、组合契约 165 passed、widget 39/39、admin 145/145。**该证据属于集成分支的组合树,不是 9ff68d5 当时点的历史证据**,二者在此明确区分。
注:6c03c80 / 2dd9113 两个 test-only 提交晚于 f496efc,不在 e945f59 内;它们不改实现语义,集成检查点如需对齐可原样纳入(由 Planner/集成负责人决定,本收口不执行 cherry-pick)。

## 14. Acceptance Criteria

AC-01 ✅(§5/§6)AC-02 ✅(G001/G003/G005)AC-03 ✅(G002/G004)AC-04 ✅(G001-G004)
AC-05 ✅(G005 专项测试 + revert 验证;stream 与 generate/list_models 共用 `_auth_headers()` 单点实现)
AC-06 ✅(G006 远端 401)AC-07 ✅(§8 diff 范围 + G007)AC-08 ✅(§8)
AC-09 ✅(76 passed)AC-10 ✅(§4/§9:实现 diff 仅 deepseek.py 一个生产文件)
AC-11 ✅(未触碰 T4/生产;本地栈 :8023 为测试实例)AC-12 ✅(本报告)

## 15. Residual Risks

1. 空 key + 免鉴权网关现为受支持形态;若运维误将免鉴权网关暴露于内网,授权后即可被调用——授权审查(note/created_by)仍是唯一人控闸门(与主报告 §7 一致,非新增风险)。
2. `generate` 空 key 语义从「本地崩溃」变为「发出无鉴权请求」:运行期启用一个空 key 供应商时,失败模式由 LocalProtocolError(不可重试)变为网关 401(HTTPStatusError,同样不可重试)——两者最终都会走故障切换,行为收敛更合理,但日志形态不同。
3. 共享 ask_ai_test 库的并行清库干扰(见 §16.1)可能造成验收复现时的环境性 500/数据缺失,需按 §16.1 处置。

## 16. FOLLOW_UP_FINDINGS(仅记录,本收口不修)

1. **共享测试库互踩(环境)**:本收口期间 ask_ai_test 的 users 表、llm_allowed_hosts 行、自定义供应商行两次被并行任务清空(8023 登录 500 UndefinedTableError;授权清单莫名变空)。建议:并行执行期每任务用一次性隔离库(与既有规约一致),或为 ask_ai_test 建立清库协调约定。
2. **test_provider 对空 key 供应商的连通性语义(产品级,独立缺陷候选)**:`DeepseekProvider.health_check()` 返回 `bool(api_key)`——免鉴权网关即使可达,「连通性测试」按钮也会报不可用(success=False,不发起请求)。修复方向:health_check 空 key 时发一次轻量 GET /models。**未修**(超出冻结行为,留 Planner 裁决)。

## 17. Production Status

PRODUCTION_DEPLOYED = **NO**。T4 生产未部署、未变更;本地 :8023/:5175 为测试实例(test 库)。

## 18. Final Commit / Branch / Report Path

- IMPLEMENTATION_COMMIT = 9ff68d57b87b16459182aeb38d3fa5192500fcaf(冻结)
- EVIDENCE_TEST_COMMITS = 6c03c80、2dd9113(test-only)
- BRANCH = worktree-exec/admin-p1-llm-provider(origin 同步)
- REPORT_PATH = docs/implementation/CAMTHINK_V1_LLM_PROVIDER_EMPTY_API_KEY_FOLLOWUP_2026-09-01.md
- REPORT_COMMIT = 见本文件在 docs 仓的提交 SHA

---

*本收口不构成 FINAL ACCEPTANCE;Planner 拥有最终独立验收权。*
