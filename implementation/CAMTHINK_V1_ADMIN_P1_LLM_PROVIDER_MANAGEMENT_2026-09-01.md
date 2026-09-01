# CAMTHINK V1 — Admin P1: LLM Provider Management Closure

- TASK_ID: CAMTHINK_V1_ADMIN_P1_LLM_PROVIDER_MANAGEMENT
- 执行端: PARALLEL CODEX B(独立 worktree,不触碰 P0+P1 集成门 / Data Source Health / Citation Integrity 域)
- 日期: 2026-09-01
- STATUS: **PASS**
- BASELINE_COMMIT: 76b2199ff334194a4e145c80ab844726d7e50293 (main)
- FINAL_COMMIT: 4544a42e1e45efb1efcb5ba220f904aefb56d90a
- REMOTE_BRANCH: worktree-exec/admin-p1-llm-provider (origin,本地与远程 HEAD 核验一致)
- WORKTREE: /Users/harryhua/Documents/GitHub/ask-ai-llm-provider / branch worktree-exec/admin-p1-llm-provider
- BACKEND_PORT: 8023(8021 被并行任务间歇占用,health 实测 200;未动 :8000 主后端)
- PRODUCTION_DEPLOYED: **NO**

---

## 1. Baseline 与环境

- worktree 自 76b2199 精确建立;`.env` 自主仓复制(仅本地测试库使用);models 软链共享只读 + HF_HUB_OFFLINE=1,未重新下载权重。
- Postgres 写操作仅发生在 `ask_ai_test` 测试库;共享 weaviate(localhost:8080)只读(启动 meta 检查);未修改任何生产/开发凭证。
- 本地开发库 ask_ai 仅做过一次只读 SELECT 取证(llm_providers 行)。

## 2. LLM-01 根因(systematic-debugging 实证)

**根因**:`backend/api/admin/schemas.py` 的 `ProviderConfig` 上有 pydantic 字段级校验器 `_check_api_base`,对**每一次** create/PATCH 请求中的 api_base 做 allowlist 校验。任何携带未授权 api_base 的保存请求**整包 422**——同一请求里的 model、available_models 等非密钥修改一并被丢弃。

**用户观察还原**:用户把 DeepSeek 供应商指向自建网关 `http://100.124.85.19:13000/v1`(Tailscale/CGNAT 地址)→ 整包 422 → "编辑了但不保存"。与 LLM-02 是**同一次事故**的两面。

**排除项(取证证据)**:
- 纯非密钥编辑持久化本身是好的:活体后端 PATCH model → 重读留存(curl 实证);既有 21 个 provider 测试(部分更新/密文保留/占位符/空 key)基线全绿。
- `extra="forbid"` 假说排除:本地开发库 deepseek 行的 config 键全部在 schema 六键内。

**`.env` 提示是死路(铁证)**:`validate_llm_api_base` 的字面内网 IP 检查在 allowlist 之前——即使把 127.0.0.1/10.x 加进 `LLM_ALLOWED_HOSTS` 也被 "禁止 api_base 指向内网地址" 拒绝(env 运行时实证)。即产品提示的正常工作流对私有端点**根本不可达**。UI 提示原文(ProviderEditDialog):"其他供应商需在服务端 .env 配置 LLM_ALLOWED_HOSTS 放行"——即 LLM-02 观察到的问题原文。

## 3. 授权架构(AUTHORIZATION_DESIGN)

**在现有架构内的最小显式授权模型**(非新安全架构,无 CONTRACT CONFLICT):

信任存储 = 新表 `llm_allowed_hosts`(backend/db/models.py):
- `host`(PK,小写主机名/IP 字面量,精确匹配,**无通配符**)
- `allow_private`(bool,由主机形态自动判定,不可手改):非全局 IP 字面量(`is_global=False`,覆盖 RFC1918/loopback/link-local/reserved/**CGNAT 100.64/10**)→ 内网级
- `note` / `created_by` / `created_at`:可审查、可追溯

信任层级(`validate_llm_api_base` 扩展 `authorized_public`/`authorized_private` 集合参数):
1. 内置三家主机(api.deepseek.com/openai.com/anthropic.com):预授权,语义不变
2. env `LLM_ALLOWED_HOSTS`:部署级预授权,保留兼容(CI 依赖),产品工作流**不再依赖**它
3. DB 显式授权:public 级(公网主机)/ private 级(内网端点)两级

不变式(SSRF 边界不放宽):
- 协议仅 http/https,任何授权下都不放宽;畸形输入(缺协议/缺主机/危险协议)一律拒绝
- private 级授权**仅**解锁:私有 IP 字面量 + 内网 http(prod)+ 免公网 DNS 检查——均为管理员显式记录在案的决定
- public 级授权**不能**放行私有 IP 字面量(两级不混淆,测试锁定)
- prod 的 https 要求与 DNS 解析内网检查对 public 级授权主机完整保留

校验路径统一:api_base 校验从 pydantic 字段验证器**移至端点层**(授权需查 DB)。create / update / test / fetch-models / `_build_llm_state`(启动 + reload)全部走同一条 `load_endpoint_authorization → validate_llm_api_base` 路径。**撤销授权后 reload 会把对应供应商记入 skipped**(运行时与保存路径同一信任存储,授权可回收)。

角色边界:授权写操作(POST/DELETE)仅 admin;读取 viewer+(与其它 LLM 配置一致)。供应商 CRUD 维持 admin/editor 不变。

## 4. API / UI 实现

- `GET/POST/DELETE /api/admin/llm-allowed-hosts(/{host})`:201/409/404/403 齐全;输入归一化(剥 scheme/port/path/userinfo,IPv6 剥方括号,转小写);通配符/空值 422
- 错误文案产品化(LLM-02):"API 地址主机 {host} 尚未授权:请由管理员在「模型配置 → 端点授权」中添加后重试" / "内网/私有地址 {ip} 默认拒绝:…显式授权后使用"——**不再含 LLM_ALLOWED_HOSTS/.env 实现指令**(测试锁定)
- UI:LLMProviders 页新增「端点授权」入口(与「供应商凭证」并列,配置/信任分离);`EndpointAuthDialog` 支持授权列表(公网/内网徽标+备注)、新增、撤销,非 admin 只读+提示;ProviderEditDialog 移除 .env 指引,改为端点授权工作流提示

## 5. RED/GREEN 证据(TDD)

RED(实现前观察失败):
- `test_llm_allowed_hosts.py`:端点 ERROR(404 不存在)+ 纯函数 TypeError(无 authorized_public 参数)+ 文案不匹配("allowlist" vs "尚未授权")
- `test_llm_providers.py` P1 子集:6 failed(文案/授权流/撤销跳过)
- 前端:hint 测试 fail(旧 .env 提示)+ EndpointAuthDialog 模块不存在

GREEN(实现后):
- 后端 focused:allowed-hosts 18 passed;providers 27 passed;lifespan_smoke 8 passed
- 后端回归子集(tests/api + test_main + llm + lifespan_smoke + models_trace):**178 passed, 0 failed**
- 前端 vitest 全量:**136 passed**;`tsc -b` 0 错误;`vite build` 成功(chunk>500kB 警告为既有)

契约演进的既有测试更新(均有注释说明):
- `test_update_provider_allowlist_422_regression`:仍锁 422+DB 不变,文案断言改为产品级(无 .env/LLM_ALLOWED_HOSTS)
- `test_fetch_models_body_api_base_outside_allowlist_rejected`:error 断言改为含"尚未授权"(仍不泄露 key)
- lifespan_smoke 3 处文案正则 "禁止 api_base 指向内网地址" → "默认拒绝"(拒绝行为本身未变,169.254.169.254 元数据端点仍拒);2 处补 `load_endpoint_authorization` patch(MagicMock factory 下新依赖)
- ProviderEditDialog 旧 hint 用例改为断言端点授权指引

## 6. Golden Scenarios(活体证据,:8023 真实后端 + Playwright 真实浏览器)

| 场景 | 结果 | 证据 |
|---|---|---|
| G001 非密钥编辑保存→刷新留存 | PASS | curl PATCH model→200;重读留存;**UI:保存 toast→页面刷新→重开弹窗值留存**(Playwright 实测) |
| G002 空 API key 保留密钥 | PASS | 空白 key 保存后 DB 密文长度 140 不变;响应恒为 "********" |
| G003 未授权自定义端点→明确失败 | PASS | api.together.xyz → 422 "尚未授权…端点授权"(无 .env 字样);UI 红 toast+弹窗保持 |
| G004 显式授权后保存成功 | PASS | POST 授权(输入完整 URL 自动归一化 api.together.xyz,公网级)→ 同一 PATCH 200;UI 授权→保存→成功 toast |
| G005 私有端点默认拒→显式放行 | PASS | `http://100.124.85.19:13000/v1`(用户原始端点)默认 422;授权后自动内网级(allow_private=true)→ http 保存 200 |
| G006 畸形端点一律拒绝 | PASS | ftp://、file:///etc/passwd、https://(缺主机)、缺协议 → 全 422 |
| G007 内置工作流无回归 | PASS | deepseek 内置主机创建/更新/连通性路径测试全绿;单测+活体双验证 |

附加活体证据:editor 角色 POST 授权 → 403、GET 列表 → 200;撤销授权链路 reload:授权内 `providers_count=2, skipped=[]` → 撤销后 `providers_count=1, skipped=['deepseek']`。UI 全程截图/快照在 .playwright-cli(会话内)。

E2E 后清理:deepseek api_base/model 回退、临时 provider 删除、授权清单清空(已核验 `[]`)。

## 7. Security Analysis

- 默认拒绝面**扩大**:CGNAT/Tailscale(100.64/10,`is_global=False`)此前可经 env allowlist 直通,现归入私有族默认拒绝——收紧,符合 LLM-03 "custom/private hosts default deny"
- 无通配符、无"记录存在即信任"、无 SSRF 关闭;授权精确到主机、逐条可撤销
- private 级授权=管理员显式信任内网通道:允许内网 http 与免公网 DNS 检查。残余风险:若管理员授权恶意/被劫持主机,凭证可能发往该主机——这是显式、留痕(admin email)、可撤销的决定,与契约"explicit and reviewable"一致;169.254.169.254 等元数据端点同样只能经显式授权到达(默认拒绝已在测试锁定)
- 密钥零回显:响应恒脱敏;fetch-models/test 错误文案不含 key
- 兼容性:env LLM_ALLOWED_HOSTS 保留为部署级通道(部署方 bootstrap 可用),但产品 UI/文案不再指向它

## 8. Changed Files(13)

新增:`admin/src/components/EndpointAuthDialog.tsx`、`admin/tests/EndpointAuthDialog.test.tsx`、`tests/api/admin/test_llm_allowed_hosts.py`
修改:`backend/api/admin/schemas.py`(validate 重构+schema)、`backend/api/admin/llm_providers.py`(授权 CRUD+端点级校验)、`backend/db/models.py`(LLMAllowedHost)、`backend/main.py`(_build_llm_state 授权集)、`admin/src/components/ProviderEditDialog.tsx`、`admin/src/hooks/useLLMProviders.ts`、`admin/src/pages/LLMProviders.tsx`、`admin/tests/ProviderEditDialog.test.tsx`、`tests/api/admin/test_llm_providers.py`、`tests/test_lifespan_smoke.py`

未触碰(契约禁区):backend/pipeline/rag.py、SourceVisibilityGuard、生成可靠性、citation、检索排序、知识可见性、Data Source Health、Technical Insights——零改动。

## 9. Residual Risks / 部署注意

1. **新表 `llm_allowed_hosts`** 由 init_db create_all 自动建(dev/test/T4 现行机制);无 alembic 目录,若未来引入 alembic 需补迁移脚本
2. 测试库 seed 用 .env 的 DEEPSEEK_* 值(仅本地 ask_ai_test,一次性);T4 生产库不受影响;admin123 改密事项与本任务无关、维持挂起
3. 授权粒度为主机级(不含端口/路径);BGE/嵌入与 reranker 路径未动
4. 8021 端口被并行任务间歇占用(证据:bind 两次失败),本次改用 8023;建议并行任务协调端口表
5. UI 编辑弹窗对"已授权主机"不做实时预检(保存时后端 422 即时反馈,文案可操作)——如需输入即校验可作后续增强

## 10. 验证命令复现

```bash
cd /Users/harryhua/Documents/GitHub/ask-ai-llm-provider
export TEST_DATABASE_URL="postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test"
export PYTHONPATH=$PWD
.venv 主仓共享: /Users/harryhua/Documents/GitHub/ask-ai/.venv/bin/python -m pytest tests/api tests/test_main.py tests/llm tests/test_lifespan_smoke.py tests/test_models_trace.py -q   # 178 passed
cd admin && npx vitest run   # 136 passed; npx tsc -b; npx vite build
```

---

## 11. 追加修复(用户实测反馈,09-01)

### 11.1 现象与定性

用户报告「新增供应商 + http://100.124.85.19:13000/v1 → 从 API 拉取」提示 "api_base 校验失败"。取证:
- 该文案**只存在于旧代码**(主仓 :8000/:5174);新栈(4544a42)对同一操作返回产品级文案
  「内网/私有地址 100.124.85.19 默认拒绝:请由管理员在「模型配置 → 端点授权」中显式授权后使用」(活体复现)。
  → 用户测试的是旧栈;新栈行为符合契约。
- 但顺着复现发现**新栈真 bug**:授权后拉取仍失败,服务端日志为
  `httpcore.LocalProtocolError: Illegal header value b'Bearer '`。

### 11.2 根因与修复(9ff68d5)

deepseek.py 三处(generate/stream/list_models)无条件构造 `Authorization: Bearer {key}`,
key 为空时 httpx 拒绝空值头 → 协议层崩溃。修复:`_auth_headers()` 助手,空 key 返回 `{}`。
TDD RED(2 断言)→ GREEN;llm 19/19,providers+allowed-hosts 64 passed。活体:授权后未填
token 拉取 → 请求真实到达网关(401 Unauthorized),Illegal header 0 次。

语义收益:generate 对空 key 从「协议层崩溃」变为「发出无鉴权请求」,免鉴权自建网关
(本地 vLLM/ollama 类)成为一等公民。

### 11.3 测试环境事故记录

ask_ai_test 库 users 表被并行测试进程清空(:8023 登录 500,UndefinedTableError),
重启 worktree 后端由 lifespan 重建+seed 恢复。共享测试库的并行任务需协调(与 §9.4 端口冲突同源)。
