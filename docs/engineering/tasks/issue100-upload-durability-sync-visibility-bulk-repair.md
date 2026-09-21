# Issue #100 — Uploaded knowledge durability / sync-plane visibility / bulk repair idempotency

- **Issue**: harryhua-ai/ask-ai#100(P0:Uploaded knowledge is not durable/visible to sync workers; bulk repair fails on long document paths)
- **Execution mode**: implement(claim `harryhua-ai-20260921T062357-53c4799f`)
- **Execution base**: `14735859df9a8c8d379677238d1599f7f4dbb03b`(契约冻结基线,精确)
- **STATUS**: CANDIDATE READY — STOP = Role A exact-SHA Review
- **Production mutations**: 0(全程只读;部署应用属后续授权范畴,见 LIMITATIONS)

## 1. RCA → 修复映射

| 生产事实(RCA 已证) | 根因 | 修复 |
| --- | --- | --- |
| 上传 ~243 文件只在 backend 容器可写层;sync-executor/sync-cron 同路径不存在;容器重建即丢失 | 无持久卷挂载:上传端点写 `/app/data/uploads/...` 于容器可写层,四个 backend 类服务(backend/sync/sync-executor/sync-cron)各自独立文件系统 | AC1:prod compose 新增 `uploads_data` 命名卷统一挂载 `/app/data/uploads`;写侧/读侧路径统一由 `UPLOADS_CORPUS_ROOT` 单一常量派生 |
| sync 日志「政策缺席: … include_dirs」刷屏;actionable-missing 计数是执行面隔离伪影;范围内行两次即遭伪退休 | Python 3.13 `Path.rglob` 对缺失根**静默空集**(已实证:missing root → `rglob` 返回 0 项、不抛错)→ `_sync_one` 走「无变更」路径 → 缺席确认把「根不可见」当权威缺席/范围变化分类 | AC2:`SourceRootUnavailable` fail-closed 异常;`FilesystemConnector` fetch 入口探测根缺失/不可读;`_discover_source_docs`/`_handle_no_change` 对该异常穿透;`_sync_one` 记 `failed` + `[source-unavailable]` 可执行详情;成功窗口不推进 |
| `repair-all` HTTP 500:`StringDataRightTruncationError: varchar(100)` | 幂等键 `bulk-repair-v1:{source_id}:{doc.source_id}` 全量拼接,长嵌套/Unicode 身份首行 INSERT 即溢出,整批中止 | AC5:`_bulk_repair_idempotency_key` —— 短身份保持 v1 键(连续性),超长身份 `bulk-repair-v2:<sha256[:32]>`(47 字符恒有界、确定、128bit 碰撞安全) |
| 单文档修复"成功"但无效;批量原语不可用 | repair-all 循环无逐文档隔离:任一异常传播即整批 500 | AC6:逐文档 try/except 隔离,失败项携带 error 明细,批处理完全部资格集;聚合 counts 与逐项 lineage(doc_source_id/task_id/error/sync_request_id)如实可审计 |

## 2. CHANGED(5 文件 + 5 测试文件,137+/31-)

- `backend/connectors/base.py`:`SourceRootUnavailable(RuntimeError)`(AC2 词表)。
- `backend/connectors/filesystem.py`:`_ensure_root_enumerable()`(缺失/非目录/不可读 → fail-closed,错误携带配置 root_path 与解析绝对路径);`fetch_all`/`fetch_changes` 入口调用。根存在但无匹配文件 = 合法空源,语义不变(AC4 边界)。
- `scripts/sync.py`:`_discover_source_docs` 与 `_handle_no_change` 对 `SourceRootUnavailable` **穿透**(不并入"不完整发现 no-op");`_sync_one` 异常面给 `[source-unavailable]` 前缀;失败轮不推进 `_last_success_at`。
- `backend/api/admin/data_sources.py`:`UPLOADS_CORPUS_ROOT` 单一权威常量(`_upload_root`/upload 响应/create/update 的 `root_path` 三处字面统一);`_bulk_repair_idempotency_key`;repair-all 循环逐文档隔离。
- `deploy/prod/docker-compose.yml`:`uploads_data` 命名卷声明 + x-backend-base 挂载 `/app/data/uploads`(backend/sync/sync-executor/sync-cron 四服务同卷)。

## 3. AC_EVIDENCE(RED → GREEN)

| AC | RED(基线 14735859 复现) | GREEN(候选) |
| --- | --- | --- |
| AC1 | compose 无 uploads 卷(`test_prod_compose_mounts_shared_uploads_volume_on_every_backend_service` FAIL);上传↔connector 枚举桥接无契约锁定 | compose 四服务同卷断言 3/3;`UPLOADS_CORPUS_ROOT` 单一权威 + 记录 root_path 枚举可见 2/2 |
| AC2 | `assert 'success' == 'failed'`(伪成功);账本行落 `policy_reason: 'include_dirs'`(事故日志同款);`_last_success_at` 被伪成功推进(`assert None == datetime(...)`) | `SyncLog.status=failed` + 详情含配置根路径;缺席确认计数 0、零政策分类、两轮零退休;窗口不推进 — 3/3 |
| AC3 | 无桥接契约(字面漂移风险无锁定) | 上传落盘 → 以记录 `root_path` 实例化的 connector 枚举到上传语料(含中文嵌套路径);可读源正常摄取由既有 619 scripts/connectors 契约背书 |
| AC4 | —(护栏) | 根存在但空 = 合法 no-change(不误伤);`policy_absence_reason` 词表与 #82/#91/#94 语义零改动;repair 不复活、不动 lifecycle 门 |
| AC5 | `ImportError: _bulk_repair_idempotency_key` → 实现前接口不存在;既有代码长身份 INSERT 即 `StringDataRightTruncationError`(事故形态,资格集构造见测试) | 有界 ≤100(47/100)、确定(重试同键 → 原任务)、碰撞安全(不同身份不同键)、短身份保持 v1 连续性 — 3/3;API 级长 Unicode 身份 repair-all 200 — 1/1 |
| AC6 | 无隔离:任一单文档异常传播即整批 500 | monkeypatch 首文档执行失败 → 200,eligible=3 全处理,failed≥1 携带 error,聚合守恒 `succeeded+rebuild_requested+failed==eligible` — 1/1 |
| AC7 | —(护栏) | `create_repair_task` 的 #83 退役门/幂等/开放任务语义零改动;repair 仍=持久 chunk 回放,不碰源摄取/权威成员资格 |
| AC8 | — | 新增 18 测试(4+3+2+3+6);回归:connectors+scripts 619P/5S/0F,api+services 1001P/1S/**4F(基线既有**,纯净 14735859 上逐一复现,见 §4) |

## 4. TESTS

**新增(18,全 GREEN)**:

- `tests/connectors/test_filesystem_unavailable_root.py`(4):missing root fetch_all/fetch_changes 抛 `SourceRootUnavailable` 且错误含根路径;existing-empty-root 合法 no-change(AC4);unreadable root(权限不可证环境诚实 skip)。
- `tests/scripts/test_source_unavailable_failclosed.py`(3,真实 PG + 真实 FilesystemConnector + 缺失根):fail-closed 非 pseudo-success;缺席/政策分类/退休零推进;成功窗口零推进。
- `tests/api/admin/test_bulk_repair_bounded_idempotency.py`(6,真实 PG):键有界/确定/碰撞安全/短身份 v1 连续性;长 Unicode 嵌套身份 repair-all 200;重试幂等(同文档不产生第二把键);逐文档失败隔离与聚合守恒。
- `tests/deploy/test_shared_uploads_volume.py`(3):uploads 持久卷声明;四 backend 类服务全部挂载;同卷单一权威。
- `tests/api/admin/test_upload_connector_visibility.py`(2):`_upload_root` ≡ 常量派生;记录 `root_path` 枚举可见上传语料。

**回归(工作树内全量目录覆盖,合计 ≈2945 passed)**:

- `tests/connectors + tests/scripts`:**619 passed / 5 skipped / 0 failed**
- `tests/api + tests/services`:**1001 passed / 1 skipped / 4 failed** — 4 失败(`test_gap_export`×2、`test_gap_observation`、`test_tech_answer_gaps`)经**纯净 execution base 14735859 临时工作树逐一复现**,判定基线既有(pre-existing),与本候选零因果。
- `tests/pipeline + tests/db + tests/auth + tests/retrieval + tests/runtime + tests/llm + tests/project_automation`:**1191 passed / 0 failed**
- `tests/e2e + 根级测试文件`:**70 passed / 2 skipped / 0 failed**
- `tests/benchmark`:passed;`tests/embedder`:**62 passed / 2 errors**(`test_bge.py::test_reranker_*`)—— 环境性:本机 HF 缓存无 BGE-m3/reranker 权重,在线下载挂死(已知 xet 假死),offline 下重模型用例不可证。零 delta 面(embedder 模块零改动);生产验收栈有真实权重。

**环境注记**:本地 venv 为 Python 3.14(`rglob` 静默空集行为与生产 3.13 一致,已用最小脚本实证);测试库为真实 Postgres(`TEST_DATABASE_URL`),`String(100)` 列宽溢出可原生复现。

## 5. LIMITATIONS / KNOWN FAILURES

1. **部署应用未执行(需授权)**:compose 卷变更需经生产部署授权(候选不含任何生产 mutation)。首挂载时 `uploads_data` 为空卷 —— **运营 runbook(部署时一次性)**:
   ```bash
   # 在旧 backend 容器内打包既有上传权威,落到新卷(示例;授权后由操作员执行)
   docker compose run --rm --entrypoint sh backend \
     -c 'mkdir -p /app/data/uploads && cp -a /app/data/uploads/. /tmp/merge/ 2>/dev/null || true'
   ```
   实操口径:先 `docker compose up -d backend`(新卷生效)前,把现容器 `/app/data/uploads` 内容 `docker cp` 出来,`up -d` 后 `docker cp` 进新 backend 容器的 `/app/data/uploads/`。事故源 `knowledge-support-cases` 的 ~243 文件随此步骤恢复可见性。
2. **生产验收(挂载后)**:上传→手动 sync 摄取、`repair-all` 真实批处理、UI actionable-missing 归零,须在部署授权后于真实栈复验(本候选仅覆盖代码契约与静态部署配置验证)。
3. **AC2 语义变化面**:任何"配置 root_path 不存在"的 filesystem 源,同步从伪 `success/无变更` 变为显式 `failed` —— 这是 AC2 要求的 fail-closed;若生产存在长期不可见的 fs 源,部署后会出现新的 failed 轮(可执行详情指向其根路径),属**暴露既有问题而非回归**。
4. 本地回归中 4 个基线失败(gap_export/gap_observation/tech_answer_gaps)未修复:与本 Issue 契约无交集,不属本候选 scope(如需另立任务由 A 裁决)。

## 6. 边界自检

- 零生产触碰(43.132.189.162 只读历史证据来自 Issue 正文,本候选未再触碰生产)。
- 未修改 ght-contract / ready / Issue 状态;未自合并;单 ACTIVE claim。
- scope.forbidden 四项(手工生产库/向量编辑、repair 替代源摄取、弱化生命周期换计数、宽域存储平台重设计)全部未触碰:`uploads_data` 单卷挂载为事故所需的最窄部署变更,非平台重设计。
