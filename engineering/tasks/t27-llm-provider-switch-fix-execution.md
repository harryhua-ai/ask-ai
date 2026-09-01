# T27-LLM-PROVIDER-SWITCH-FIX Execution Report

- **Task / Initiative**:t27-llm-provider-switch-fix / 模型配置系统(LLM 供应商管理)
- **Worktree / Branch**:`/Users/harryhua/Documents/GitHub/ask-ai-t27-llm-fix` / `worktree-exec/t27-llm-provider-switch-fix`
- **Baseline → Final Commit**:`bbfaa6a` → `37d7501`
- **Status**:**CANDIDATE READY**(不 push,等 A Review)

## Files Changed

| 文件 | 变更 |
|---|---|
| `backend/api/admin/schemas.py` | 新增 `FetchModelsRequest`(可选 body `{api_base?, api_key?}`);FORBIDDEN 的 `validate_llm_api_base`/`_DEFAULT_LLM_HOSTS` 零改动 |
| `backend/api/admin/llm_providers.py` | `fetch_models` 接受可选 body:非空表单值优先,空 key 回退 DB 解密值;生效 api_base 复用 `validate_llm_api_base`(SSRF 边界不放宽);脱敏错误语义不变 |
| `admin/src/lib/api.ts` | 新增 `formatApiDetail` helper:FastAPI 422 detail 数组扁平化为 msg 文本拼接;`apiFetch` 出错统一走它(CONDITIONAL 项) |
| `admin/src/hooks/useLLMProviders.ts` | `useFetchModels` mutation 入参从 `id` 扩为 `{id, apiBase?, apiKey?}`,非空字段才进 body |
| `admin/src/components/ProviderEditDialog.tsx` | ①拉取传表单当前值(api_base trim 后非空才传,key 同)+ 拉取错误可读展示;②api_base 下加 LLM_ALLOWED_HOSTS 指引行;③模型行加「设为默认」(置顶+★+默认徽标);④保存 pending 态防重复提交 |
| `admin/src/pages/LLMProviders.tsx` | `handleSaveProvider` 改 async:成功 toast+关弹窗;失败红 toast(可读原因)且弹窗保持、表单态保留 |
| `tests/api/admin/test_llm_providers.py` | 新增 4 用例:T27①body 生效/②key 回退/SSRF 拒绝脱敏不外呼/PATCH 422 回归锁 |
| `admin/tests/*` | 新增 `LLMProviders.test.tsx`(页级:保存失败不关弹窗+toast 文本/成功关闭)、`api.test.ts`(422 扁平化);`ProviderEditDialog.test.tsx` +4 用例;`useLLMProviders.test.tsx` 适配新签名 +body 用例 |

11 files,+476/−36。

## Implementation

缺陷①②③按契约 Scope 1-4 修复。生效值语义:`eff_api_base = body.api_base(非空) || DB.api_base`;`eff_api_key = body.api_key(非空) || decrypt(DB.api_key)`;两条路径都过 `validate_llm_api_base`。SSRF/allowlist、加密/脱敏/`********` 占位、reload 行为:零改动(Frozen #4 / Non-goals 满足)。

## Verification actually executed

1. **后端红→绿**:新增用例先行 3 failed(body 被忽略)→ 实现后 `test_llm_providers.py` **21 passed**(17 既有 + 4 新,含 422 回归锁与脱敏断言 `error == "api_base 校验失败"` 且不含 key、`LLMRegistry.create` assert_not_called)。
2. **口径一**(tests/ 全量含 tests/api/admin,TEST_DATABASE_URL + ENCRYPTION_KEY):**539 passed**;**口径二**(CI 确切口径):**447 passed**。
3. **admin vitest 全量**:**123 passed**(113 基线 + 10 新:页级 2 + dialog 4 + hook 2 + api 3 中的格式化 3 与 hook 2 等合计);**tsc -b exit 0**。
4. **AC1 真实浏览器**(worktree admin :5177 → worktree 后端 :8001,worktree .env 临时加 `LLM_ALLOWED_HOSTS=api.siliconflow.cn,localhost`):
   - 错误路径:api_base 改为未放行 host 保存 → 红 toast 实测文本 `保存失败:Value error, api_base 主机 api.evil-blocked.net 不在 allowlist(通过 LLM_ALLOWED_HOSTS 配置)`(422 数组已扁平化),**弹窗保持打开、表单值保留**,DB 逐字节未变(复核 api_base 仍为 siliconflow)。截图 `/tmp/t27-e2e/ac1-error-toast.png`;
   - 成功路径:siliconflow + 新 key 保存 → success toast、弹窗关闭;DB 复核 `api_base=https://api.siliconflow.cn/v1`、`api_key` 密文长度 **140→120**(更新实证);curl 直验 `PATCH evil → 422`(安全边界在后端独立成立);
   - 「应用变更」→ toast `已应用变更:1 个供应商生效`。截图 `/tmp/t27-e2e/ac1-reload-toast.png`;
5. **AC2(拉模型表单值)**:api_base 填 `http://localhost:9990/v1`(本地 mock OpenAI /models)、**key 留空** → 从 API 拉取:mock 服务端日志实测 `GET /v1/models Authorization=Bearer sk-t27-e2e-...` —— 请求携带**表单 api_base** 且 key 为 **DB 解密值(留空回退实证)**;返回模型以 chips 展示并点选加入。截图 `/tmp/t27-e2e/ac2-fetch-models.png`。
6. **AC3(设默认)**:手动添加 `t27-e2e-model` → 设为默认(置顶+★)→ 保存 → 重开弹窗默认标记仍在(截图 `/tmp/t27-e2e/ac3-reopen-default.png`)→ DB `config.model = "t27-e2e-model"`、`available_models` 顺序一致。
7. **black**:3 个后端变更文件 clean(基线不洁区未触碰)。

## Runtime / Real-World Self-Check 与环境清理

- 本地 `llm_providers` 已按测试前快照**精确还原**(api_base=deepseek 官方、model=deepseek-v4-flash、api_key 密文长度 140 复核一致);
- worktree `.env` 的临时 `LLM_ALLOWED_HOSTS` 行与端口改动已还原(重新复制主仓 .env,`grep -c` = 0);`.env` 未进任何提交;
- 临时服务(worktree 后端 :8001、mock :9990、vite :5177)已全部停止;**注意**:清理时 `pkill backend.main` 波及主仓 :8000 后端,已按原方式重启并 health 200 复核,主环境(5174 admin、:8000 后端)恢复正常。

## Deviations / Risks

1. **[既有测试环境问题,根因已定位,上报 A]** 本地"合并口径"(tests/ 全量含 tests/api/admin)下 `tests/test_lifespan_smoke.py` 跑真 lifespan:其 YAML 种子将 `${DEEPSEEK_API_KEY}/${DEEPSEEK_API_BASE}`(env 未设)以空值写入共享测试库的 deepseek 行,毒化**下一轮** admin 运行的 `test_list_providers_includes_deepseek_and_masks_key`(期望 `********` 得 `''`;admin conftest 种子 only-if-absent 不会自愈)。真实 CI 每次全新库且 CI 口径不含 tests/api/admin,故 CI 无此问题;本任务两口径分开验证均全绿。历史记录中的该 flaky 与此同源。建议后续立项:lifespan smoke 的种子隔离(如独立 schema/库)。
2. `test_analytics_business` 两用例在本地合并口径下偶发顺序敏感失败(fresh 库基线复测全绿、单文件全过、我的变更域与其无交集)——既有隔离敏感,非本任务引入;CI 口径与 tests/api/admin 单口径均稳定全绿(连跑 2 遍 92 passed)。
3. `formatApiDetail` 全局作用于 `apiFetch` 错误路径:所有页面错误文案从"对象字面量/不可读"变为"msg 文本",属纯可读性改善;全量 vitest 无一用例依赖旧形态。
4. Playwright CLI 的 snapshot ref 跨 shell 变量复用易陈旧(本次 E2E 中两次点击落空),已改用"即取即点 + eval 验证值"流程;不影响被测代码,仅记录以备后续 E2E。

## Parallel/依赖状态

与 C8B(已完)/T25A/T26(已完)文件域互斥;基线同为 bbfaa6a。
