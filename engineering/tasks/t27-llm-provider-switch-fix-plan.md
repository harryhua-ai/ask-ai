# T27-LLM-PROVIDER-SWITCH-FIX Execution Contract(换供应商:拉模型用旧凭证 + 保存静默失败)

- **Task ID**:t27-llm-provider-switch-fix | **Parent Initiative**:模型配置系统(LLM 供应商管理)
- **Baseline Commit**:`bbfaa6a`(main = origin/main)
- **Risk Level**:**L2**(后端端点签名扩展 + 前端弹窗,安全边界邻接但语义不变)
- **Contract Authorization**:**AUTHORIZED**(2026-08-31,Role A 签发)——用户本地自测报告两个缺陷,经代码+库实证均为真实产品缺陷(非环境问题);修复不改变 SSRF 安全边界语义。

## 1. Objective

管理员把默认 deepseek 供应商换成其他 OpenAI 兼容供应商时:①「从 API 拉取」用表单当前值而非库中旧凭证;②保存失败必须显式报错(含 allowlist 指引),不得静默关闭弹窗造成"保存后恢复原值"的假象;③手动添加的模型可设为默认。

## 2. Current State / Evidence(Inspect @ bbfaa6a,已实证)

| # | 事实 | 级别 |
|---|---|---|
| E1 | `fetch-models` 端点(`llm_providers.py:333`)无请求体,只读 DB 已保存 config → 编辑弹窗里刚输入未保存的 api_base/api_key 不生效,拉到的是旧供应商(deepseek)的模型 | FACT |
| E2 | `validate_llm_api_base`(`schemas.py:169`):host 白名单 = `_DEFAULT_LLM_HOSTS`(api.deepseek.com / api.openai.com / api.anthropic.com)+ env `LLM_ALLOWED_HOSTS`;换任何其他供应商 → PATCH 422。已本地实证:`https://api.siliconflow.cn/v1` → `REJECTED: 不在 allowlist` | FACT |
| E3 | 前端保存链路无错误呈现:`handleSaveProvider`(`LLMProviders.tsx:103`)fire-and-forget `mutate()` 即 `setEditId(null)` 关弹窗;`useUpdateProvider` 无 onError → 422 静默,DB 未变,列表回显旧值 = 用户所见"恢复回原来的 deepseek" | FACT |
| E4 | 422 时 FastAPI `detail` 是数组(`[{loc, msg: "Value error, api_base 主机 X 不在 allowlist…"}]`),`apiFetch` 原样透传(`api.ts:44-52`),前端即使显示也是对象不可读 | FACT |
| E5 | 本地库实证:用户编辑后 `llm_providers` 仍为纯种子态(api_base=deepseek 官方、model=deepseek-v4-pro)→ 用户的链接/token/模型从未落库 | FACT |
| E6 | 编辑弹窗模型列表(`ProviderEditDialog.tsx:102-150`)只有追加/删除,无排序/设默认;`handleSave` 取 `models[0]` 为默认 → 手动添加的模型排尾,保存后默认模型仍是旧的 | FACT |
| E7 | 启动种子(`main.py:263-275`)仅行不存在时插入,不覆盖用户编辑;"恢复"非后端重写 | FACT |

## 3. Scope

1. **fetch-models 支持表单值**:端点接受可选请求体 `{api_base?: str, api_key?: str}`;生效值 = body.api_base(非空)否则 DB 值,body.api_key(非空)否则 DB 解密值;对生效 api_base 复用 `validate_llm_api_base`(SSRF 边界不放宽);校验失败/拉取失败仍返回脱敏 error。前端「从 API 拉取」传表单当前 api_base(api_key 留空则不传,后端用旧 key)。
2. **保存失败显式报错**:保存 mutation 失败 → 红色 toast 展示可读原因(422 detail 数组扁平化为 msg 文本拼接),编辑弹窗保持打开、表单态保留;成功才关弹窗。
3. **api_base 输入提示**:编辑弹窗 api_base 下加一行 muted 说明(默认三家直连;其他供应商需服务端 `LLM_ALLOWED_HOSTS` 放行后才能保存)。
4. **模型设默认**:模型列表项支持"设为默认"(置顶/星标切换 HOW 自定),保存后 `model` = 所设默认项。

## 4. Non-goals

SSRF/allowlist 判定语义与 `_DEFAULT_LLM_HOSTS` 不动(不加 host、不改 prod/dev 分支);routing/chain、reload、provider type 体系不动;本地 models 卡片不动;不做保存前连通性预检。

## 5. Change Boundary

**Product**:允许 = 拉模型可用表单值、保存失败可见、模型可设默认;必须不变 = allowlist 安全边界、api_key 加密/脱敏/`********` 占位语义、reload 行为。
**Code EXPECTED**:`backend/api/admin/llm_providers.py`、`backend/api/admin/schemas.py`(请求 schema)、`admin/src/components/ProviderEditDialog.tsx`、`admin/src/pages/LLMProviders.tsx`、`admin/src/hooks/useLLMProviders.ts`、`tests/api/admin/test_llm_providers.py`。
**CONDITIONAL**:`admin/src/lib/api.ts`(若需 422 detail 扁平化 helper)、admin 侧新增/调整测试文件。
**FORBIDDEN**:`validate_llm_api_base` 判定逻辑与 `_DEFAULT_LLM_HOSTS`、`backend/llm/*`、reload/_build_llm_state、其他 admin 页面、widget。
**Regression**:CI 口径 pytest(443+)全绿 + tests/api/admin(需 ENCRYPTION_KEY)全绿 + admin vitest 全量 + tsc --noEmit。

## 6. Frozen Contract

1. 「从 API 拉取」在表单有未保存 api_base/api_key 时使用表单值(空 key 回退 DB 旧密钥),拉取结果为新供应商列表或可读错误;
2. 保存被 allowlist(或其他校验)拒绝时:红色 toast 含后端 msg 文本、弹窗不关、DB 不变;成功时弹窗关闭且 DB config 更新;
3. 模型列表可设默认,保存后 `model` 字段 = 默认项;
4. SSRF 校验对 body 传入 api_base 同样生效;错误响应不外泄 key/内部堆栈(现有脱敏策略不变)。

## 7. Acceptance Criteria

- **AC1**(换供应商全流程,真实浏览器):allowlist 外 host 保存 → 明确报错+弹窗保留+DB 未变(截图/断言);本地 `.env` 加 `LLM_ALLOWED_HOSTS=<该host>` 重启后端 → 保存成功 → 库中 api_base/model/api_key(密文长度变化)更新 → 「应用变更」toast N 个供应商生效;
- **AC2**(拉模型):表单输入新 api_base+key(未保存)点「从 API 拉取」→ 请求携带表单值(网络面板/后端日志判别);key 留空时用旧 key;返回模型可点选加入;
- **AC3**(设默认):手动添加模型 → 设为默认 → 保存 → 重新打开弹窗默认项正确、DB `config.model` 一致;
- **AC4**:回归全绿(CI 口径 + tests/api/admin + admin vitest + tsc);api_key 脱敏/加密既有用例不削弱;
- **AC5**:报告落 `docs/engineering/tasks/t27-llm-provider-switch-fix-execution.md`,CANDIDATE READY,不 push 不部署。

## 8. Verification 口径

本地:后端 pytest(两口径)+ admin vitest + tsc;真实浏览器走 AC1-AC3(mac 本地后端 :8000 + admin dev server,注意本地后端无热重载需重启)。

## 9. Parallel / 依赖

与 C8B(DataSources.tsx)/ T25A(Analytics+DataSources)/ T26(Conversations.tsx)文件域互斥,基线同为 `bbfaa6a`,可并行。

---

## 10. Executor Prompt(可拷贝)

```markdown
# Role B 执行任务:T27-LLM-PROVIDER-SWITCH-FIX(换供应商:拉模型用旧凭证 + 保存静默失败)

先完整阅读:
1. /Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/DUAL_AGENT_PROTOCOL.md
2. /Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/role-B.md
3. 契约:/Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/tasks/t27-llm-provider-switch-fix-plan.md

## 任务
按契约修复模型配置页换供应商链路的三个缺陷:
① fetch-models 端点只读 DB 旧凭证 → 扩展为可选 body {api_base?, api_key?},表单值优先生效,api_base 复用 validate_llm_api_base(SSRF 边界不放宽);
② 保存失败静默关弹窗 → 失败时红色 toast 显示可读原因(422 detail 数组扁平化为 msg 文本)、弹窗保持打开表单态保留,成功才关;
③ 编辑弹窗模型列表加"设为默认",保存后 config.model = 默认项;api_base 输入框下加一行 LLM_ALLOWED_HOSTS 指引说明。

## 环境与边界
- 主仓:/Users/harryhua/Documents/GitHub/ask-ai(baseline = main = origin/main = bbfaa6a,开工前自行核实)
- worktree:/Users/harryhua/Documents/GitHub/ask-ai-t27-llm-fix,分支 worktree-exec/t27-llm-provider-switch-fix
- Change Boundary 以契约 §5 为准;FORBIDDEN 含 validate_llm_api_base 判定逻辑与 _DEFAULT_LLM_HOSTS、backend/llm/*、reload、其他 admin 页面
- 测试红线:后端测试必须 export TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test;tests/api/admin 需要 ENCRYPTION_KEY 注入(参考既有注释)
- 不 push、不部署、不碰生产

## 实施要点(证据锚点)
- llm_providers.py:333 fetch-models(现无 body)、:142 update_provider、schemas.py:169 validate_llm_api_base / :220 ProviderConfig(extra=forbid)
- ProviderEditDialog.tsx:38 handleFetch(现只传 provider.id)、:51 handleSave(model=models[0]);LLMProviders.tsx:103 handleSaveProvider(现 fire-and-forget 即关弹窗);api.ts:44 detail 透传(422 时是数组)
- worktree 起本地后端须复制 .env + 软链 models + HF_HUB_OFFLINE=1,用 ASKAI_API_PORT 独立端口;本地后端无热重载,改码必重启
- 演示 AC1 需在本地 .env 临时加 LLM_ALLOWED_HOSTS(用完还原,勿提交 .env)

## 验证(全部实际执行,给证据)
1. 后端:CI 口径 pytest + tests/api/admin 全绿;新增用例:body 传入 api_base 生效 / 空 key 回退 DB / api_base 校验失败返回脱敏 error / PATCH 422 语义不回归
2. admin:npx vitest run 全量 + tsc --noEmit;新增用例:保存失败不关弹窗+toast 文本 / 422 detail 数组扁平化 / 设默认后保存 payload.model 正确
3. 真实浏览器 AC1-AC3 全流程截图(错误路径 + allowlist 放行后成功路径)

## 交付
- 报告:docs/engineering/tasks/t27-llm-provider-switch-fix-execution.md(协议模板:Worktree/Branch、Baseline/Final Commit、Files Changed、Implementation、Verification actually executed、Runtime/Self-Check、Deviations/Risks、Status)
- 最终回复必须含:报告路径 + final commit + 状态(仅 CANDIDATE READY / PARTIAL / FAIL / BLOCKED)
- Gate 停等:本任务不 push,等 A Review 放行
```
