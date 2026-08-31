# T27-LLM-PROVIDER-SWITCH-FIX Review(Final Acceptance)

- **Reviewer**:Role A | **日期**:2026-08-31 | **Verdict**:**FINAL PASS**
- **Execution**:`37d7501`(worktree ask-ai-t27-llm-fix,bbfaa6a → 37d7501,单提交)

## 五 Gate 审查记录

| Gate | 结果 | 证据 |
|---|---|---|
| 1 契约↔报告 | ✓ | 报告 55 行;AC1-5 覆盖;两条环境上报已分流 |
| 2 Diff 审计 | ✓ | EXPECTED 全内(llm_providers.py/schemas.py/前端四件/后端+前端测试);`api.ts` 属契约声明 CONDITIONAL;FORBIDDEN(validate_llm_api_base 判定逻辑/_DEFAULT_LLM_HOSTS/backend/llm/reload)零触碰 |
| 3 独立复跑 | ✓ | A 侧:pytest `test_llm_providers.py` **21 passed** + tests/api/admin **92 passed** + CI 口径 **447 passed**;admin vitest **123/123** + `tsc` exit 0 |
| 4 真实运行 | ✓ | A 侧后端 curl 直验(t27 build @8010):① 建临时供应商 201(api_key 脱敏 `********`);② PATCH 未放行 host → **422 且 detail 数组含可读中文 msg**("api_base 主机 … 不在 allowlist(通过 LLM_ALLOWED_HOSTS 配置)");③ fetch-models body 带未放行 api_base → 脱敏 `{"models":[],"error":"api_base 校验失败"}`;④ body 带合法 api_base+假 key → 真实出站(服务端日志实证命中 `api.deepseek.com/v1/models` 401)且响应不含 key;⑤ 临时行 DELETE 204、库零残留 |
| 5 真实场景 | ✓ | 执行端浏览器 E2E:错误路径红 toast + 弹窗保持(截图)、mock 服务端日志实证"表单 api_base + DB 解密 key 回退"、设默认落库 `model=t27-e2e-model` 重开一致、应用变更 toast 生效;deepseek 快照还原 |

## 环境上报分流(执行端 Deviations)

1. `test_lifespan_smoke` 毒化共享 ask_ai_test 的 deepseek 行(历史 mask flaky 根因)→ **并入 T30 立项**(见 t30-test-db-safety-plan.md)。
2. `test_analytics_business` 两用例合并口径顺序敏感(基线 fresh 全绿,非本批引入)→ 记入测试卫生 backlog。

## 裁决

安全边界(SSRF/脱敏)不放宽前提下三个产品缺陷全关,前后端行为均独立可复现。**FINAL PASS,授权进入发布批次。**
