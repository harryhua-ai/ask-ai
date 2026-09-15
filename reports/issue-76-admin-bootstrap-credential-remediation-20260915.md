# Issue #76 — Admin Credential Bootstrap Fail-Closed Remediation Report

执行日期：2026-09-15（Asia/Shanghai）
角色：B — Senior Engineering Executor（IMPLEMENT / TEST / VERIFY / DELIVER）
模式：CANDIDATE DELIVERY —— 不 merge、不 tag、不部署、不触碰生产凭证/生产 DB。

## Verdict

**ISSUE_76_ADMIN_CREDENTIAL_REMEDIATION = CANDIDATE READY**

## Baselines

- `git fetch origin` 已执行；**origin/main = `f4e67515af810840aa10fa800f0203c2ba290df0`**（`f4e6751` "docs(release): cite production acceptance finding"）。
- 候选分支自 origin/main 新建（未沿用任何特性分支，不依赖 #71/#72/#75/#77/#78/#79 候选）：worktree `/Users/harryhua/Documents/GitHub/ask-ai-wt-76`，分支 `remediation/issue76-admin-bootstrap-20260915`。
- 创建后 `git status --porcelain` 为空（clean 证明）。
- Issue #76 全文已核读（state=OPEN，labels `bug`+`schedule:current`，release train v1.6.3 → 下一 tag v1.6.3-r4）。

## Commits / Changed Files

| 项 | 值 |
| --- | --- |
| 基线 SHA | `f4e67515af810840aa10fa800f0203c2ba290df0` |
| 分支 | `remediation/issue76-admin-bootstrap-20260915` |
| RED 提交（机械抽 seam + 缺陷复现测试） | `6c3e78d` |
| 实现提交（fail-closed 语义） | `b4971da` |
| 最终推送 SHA | 见 §Push（`b4971da` + 报告提交） |
| 变更文件（f4e6751..HEAD） | `backend/main.py`（+55/-19 区域内）、`tests/auth/test_admin_bootstrap_failclosed.py`（新增 255 行）、`tests/test_lifespan_smoke.py`（+6/-1） |

## Accepted Root Cause（核实，未放宽）

`backend/main.py` lifespan Admin 引导块（基线 243–256 行）等价于：

```python
admin_email = os.environ.get("ADMIN_EMAIL", "admin@camthink.ai")
if not existing_admin:
    password_hash=hash_password(os.environ.get("ADMIN_PASSWORD", "admin123"))
    create_admin(...)
```

即 **缺失 secret ≠ 配置失败**，而是 **可预测默认凭证**。缺陷确为固定口令回退；仓库证据未与之矛盾，RCA 未放宽。`ADMIN_EMAIL` 默认值行为非本缺陷，未改动（契约 §8）。

## Implementation（最小实现）

`backend/main.py::_ensure_admin_user(session)`（模块级窄 seam，lifespan 原事务位调用）：

- 已存在 Admin（按 `ADMIN_EMAIL` 查 `users`）→ 记录诊断日志、返回 `preserved`，**不触碰 password_hash**；
- 缺失 Admin 且 `ADMIN_PASSWORD` 未配置或为空串 → `raise RuntimeError("ADMIN_PASSWORD 未配置:创建初始 Admin 用户需要该引导密钥…")`（错误契约：指认缺失变量、说明为建初始 Admin 所需、不含任何 secret 值、确定性、不静默继续）；
- 缺失 Admin 且已配置 → 以配置口令 `hash_password` 创建，返回 `created`。

- 错误类型 `RuntimeError` = 仓库既有配置错误惯例（`backend/config.py::_validate_prod_secrets`、`resolve_migration_dsn` 均如此），未发明异常层级。
- `ADMIN_PASSWORD` 未加入 `load_settings()`/`_validate_prod_secrets`：该 secret 仅在 DB 中 Admin 缺失时必需（bootstrap secret），启动期 env 校验无法知道 DB 状态，检查必须在引导决策点。
- 失败传播路径：helper 在 lifespan 种子事务内 raise → `async with session` 退出即回滚（同事务先行 seed 一并回滚）→ 异常穿透 lifespan（无 except，仅 finally 释放资源）→ FastAPI 启动失败。fail-closed 全链成立。

## RED Evidence（缺陷复现，`6c3e78d` 保留缺陷语义的 seam 上运行）

RED 状态 **4 failed / 3 passed**（`pytest tests/auth/test_admin_bootstrap_failclosed.py`）：

| 用例 | 语义 | RED 结果 |
| --- | --- | --- |
| RED-1 | 缺 Admin + 缺 secret → 应 fail-closed | **FAIL：DID NOT RAISE**（静默建号） |
| RED-1b | `ADMIN_PASSWORD=""` → 应视为缺失 | **FAIL：DID NOT RAISE**（空串当可用口令） |
| RED-2 | 缺 Admin + 配置 secret → 以配置口令建号 | PASS（边界需保持） |
| RED-3 | 已存在 Admin + 缺 secret → 保留、hash 逐字节不变 | PASS（边界需保持） |
| RED-4 | 已存在 Admin + 不同 secret → 不隐式重置 | PASS（边界需保持） |
| RED-5 | 静态守卫：`backend/**.py` 无固定凭证字面量 | **FAIL：`['main.py']`**（缺陷字面量在产线源码） |
| RED-6 | fail-closed 无部分提交、无关既有行不受损 | **FAIL：DID NOT RAISE**（部分提交发生） |

**基线正向探针**（独立脚本，一次性隔离库 `ask_ai_issue76_probe`，用毕即删）：
`ADMIN_PASSWORD` 缺失时基线引导持久化 1 个 admin 用户，且
`verify_password('admin123', hash) == True` —— 可预测凭证漏洞端到端实证。

## GREEN Evidence（`b4971da`）

- 契约套件 **7/7 passed**（RED-1/1b/2/3/4/5/6 全绿，测试文本 RED→GREEN 零改动）。
- **固定回退移除证明**：RED-5 静态守卫扫描 `backend/**/*.py` 全部源码，`"admin123"` 出现即失败 —— 实现后 0 命中（含注释/文档串，产线源码零字面量）；行为侧 RED-1/1b/6 的 fail-closed 断言 + RED-2 的 `verify_password` 负断言共同证明该凭证不再可被创建/使用。
- **已存在 Admin 保全证明**：RED-3（缺 secret）/RED-4（不同 secret）均断言 `password_hash` 与种子值逐字节相等、行数恰 1、动作返回 `preserved`；RED-4 另断言原口令 `verify_password` 仍为 True（禁止隐式轮换）。
- **配置 secret 引导证明**：RED-2 断言配置口令验证通过且 `admin123` 验证失败。
- **缺失 secret fail-closed 证明**：RED-1/1b 断言 `RuntimeError`(match `ADMIN_PASSWORD`) + 新会话复查 users 表 0 行。
- **事务安全证明**：RED-6 按真实 lifespan 同序构造（同事务先 seed `website-camthink` DataSource 再引导，引导前已有已提交无关 viewer 行）：失败后 Admin 零写入、同事务先行 seed 整体回滚、引导前无关行原样（email 列表与 hash 逐字节不变）。

## Regression

| 套件 | 结果 |
| --- | --- |
| 契约套件 `tests/auth/test_admin_bootstrap_failclosed.py` | 7/7 passed |
| `tests/auth/ + tests/test_main.py + tests/db/` | 45 passed（一次瞬态 setup error 见下） |
| `tests/test_lifespan_smoke.py` | **8/8 passed**（5.07s，offline-HF env） |
| CI 等价套件 `pytest tests/ -q --ignore=tests/api/admin --ignore=tests/scripts/test_sync_db.py --ignore=tests/embedder --ignore=tests/e2e` | **2188 passed / 2 skipped / 0 failed**（107.09s, EXIT=0） |
| `tests/api/admin/`（含 `test_auth.py` 登录/JWT 链路） | **460 passed / 1 skipped / 0 failed**（22.61s） |
| `tests/embedder`、`tests/e2e` | 未运行 —— CI 同样排除（需 HF 模型缓存 / 运行中 LLM 栈）；以 CI 等价口径为界，符合"practical extent" |

静态检查：`python -m compileall` OK；`git diff --check` OK；`ruff check`（变更文件）All checks passed；`isort --check-only` 通过；`black --check` 不在 CI 门内，安装版（black 25, py314）对**未改动的基线 main.py 同样报 reformat**（仓库级风格漂移，唯一差异点为基线已有的 release identity 日志行），本 delta 未引入新的 black 违例类别。

**Test-env 必要调整（非产物弱化）**：`test_lifespan_starts_and_wires_llm_state` 真实跑 lifespan 连空测试库 —— 基线期该测试静默依赖缺陷回退建号（缺陷被测试基设掩盖的实证）；fix 后该测试在本进程 env 显式 `ADMIN_PASSWORD`（test-scoped）。CI 的空 DB（`ask_ai_test`）同样依赖回退，故此调整为 CI 保持绿的必要条件。

**Baseline A/B 证据（契约 §9）**：
- *Lifespan 冒烟挂起*：`tests/test_lifespan_smoke.py` 在本环境默认 env 下挂起（240s timeout EXIT=124，7 dots 无 summary）。A/B：**未改动的 `f4e6751` detached worktree 相同命令同样 EXIT=124/7 dots** —— 挂起为基线既有（HF 下载路径），非本 delta 引入；补 `MODEL_CACHE_DIR + HF_HUB_OFFLINE=1` 后本分支 8/8 通过。
- *瞬态 setup error*：`tests/db/test_migration_path_identity.py::test_migration_idempotent` 在首次组合运行报 setup error 一次；单跑 3/3 通过，同组合重跑 45/45 通过，未再复现。单次未复现瞬态，未定性为基线 flake，如实记录。

## Scope Audit（授权边界）

- 改动仅触及：Admin 引导 seam（`backend/main.py`）+ 测试（新增契约文件、lifespan 冒烟 env）。无认证架构/JWT/登录 API/密码重置/轮换/Vault/UI 重设计；无 RAG/检索/嵌入/数据源代码改动；无 #71/#72/#75/#77/#78/#79 触碰；无 Wiki/内容变更。
- 未使 `ADMIN_EMAIL` 变为必填（契约 §8：默认 email 行为非本缺陷）。
- DB 隔离：全部新测试跑在同服务器一次性专用库（`ask_ai_issue76_boot`/`_probe`，drop→create→init→drop），不触碰开发/生产库。

## Production Safety Confirmation

- 未查看/打印生产 Admin 口令；未变更生产凭证；未删改生产 Admin；
- 未在生产设置 `ADMIN_PASSWORD`；未部署；未重启生产；未变更生产 DB；
- 未对生产做任何登录尝试（含默认/猜测凭证）。
- 生产 secret 供给与运行时验收归属 r4 发布/运行时门（契约 §10/§11）。

## R4 Integration Contract Confirmation

- **未 merge main**；**未创建/移动 `v1.6.3-r4` tag**；**未独立部署**。
- 生命周期：#76 候选 → Role A 评审 → r4 组合树集成 → 组合回归 → tag → 部署 → 运行时验收（验收仅证：无固定凭证回退、环境 Admin 状态/配置有效、无 Admin 被意外重建/重置）。

## Governance（Issue / Project）

- Issue #76：OPEN（未重写，仅追加候选证据评论）。
- Project 2 membership：存在（item `247353840`，bot 添加）。
- Status 字段 = `open`；**Iteration 字段 = `v1.6.3`（id `4ce642b8`）** —— 与 release train v1.6.3-r4 口径一致，无需治理修正。
- 未为同一缺陷新建 Issue。

## Push / Issue Update

- 分支已推送 origin（SHA 见下）。
- Issue #76 已追加候选证据评论（含本报告要点与 SHA 引用）。
