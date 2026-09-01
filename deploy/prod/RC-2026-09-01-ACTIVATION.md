# CAMTHINK_V1_RELEASE_CANDIDATE — 生产激活清单(RC-2026-09-01)

> **本文件是下一个门(Production Activation)的执行清单,本门未执行任何一步。**
> 基线:`release/camthink-v1-rc-2026-09-01`(RC commit 见 git log)。
> 完整论证见 docs 仓 `docs/implementation/CAMTHINK_V1_RELEASE_CANDIDATE_GATE_2026-09-01.md`。

## 阶段依赖(严格按序;前一步未验证通过不得进入下一步)

```
DB 迁移/启动 → Trust Boundary/channel_visibility → runtime/config/secrets
→ WEB 语料同步/修复 → Multi-Site Origin/CORS/站点配置 → Widget 嵌入 → 生产验证
```

### 阶段 0 — 制品与前置

- [ ] CI `build-image.yml` 从本 RC SHA 构建并推送 `ghcr.io/harryhua-ai/ask-ai:<sha>`(workflow 先 build admin/widget SPA 再 docker build;`uv sync --frozen` 校验锁一致)
- [ ] **镜像架构核验**:`docker image inspect ghcr.io/harryhua-ai/ask-ai:<sha> --format '{{.Architecture}}/{{.Os}}'` 必须为 `amd64/linux`(生产构建 = GHA `ubuntu-latest` 原生 amd64,无 platform 覆盖;RC 门已从仓库证据裁决生产架构 = linux/amd64)
- [ ] **NVIDIA 运行时验证(T4 上执行,macOS 无法代替)**:
  - `nvidia-smi` 正常且 driver ≥ 575 / CUDA 12.9(Dockerfile 契约:torch cu128 wheel 自带全套 nvidia 用户态库,driver 侧 libcuda 由 nvidia container runtime 注入)
  - `docker compose run --rm backend python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"` → `True` + GPU 名
  - GPU 冒烟:backend 启动后一次真实 /api/ask(BGE embed + rerank + generate 全链走 GPU,无 CUDA unavailable/OOM)
  - 若 OOM:update.sh 预检提示降 `EMBEDDER_BATCH_SIZE=8`
- [ ] T4 仓库根 `.env` 对照 `deploy/prod/.env.example` 全量核对;**变量名必须精确**(RC 修正:`CORS_ALLOW_ORIGINS`(旧模板 `CORS_ORIGINS` 是死变量)、`ASKAI_API_HOST/ASKAI_API_PORT`(旧 `API_HOST/PORT` 同))、`DEEPSEEK_MODEL=deepseek-v4-flash`(08-31 拍板)
- [ ] **沿用既有 `ENCRYPTION_KEY`**(更换会导致 llm_providers 已加密 api_key 不可解密);JWT_SECRET 非默认值(prod 启动强校验,缺失直接拒绝启动)
- [ ] `models/`、`ask-ai-corpus/`、`knowledge-support/` 挂载路径在位(compose 卷映射不变)

### 阶段 1 — DB 迁移/启动(隔离已验证:bbfaa6a 形态库 → RC 全链通过,幂等)

- [ ] `./deploy/prod/update.sh <tag>`(backend 先行,health 门禁;sync-cron 随后)
- [ ] 启动即自动:`init_db` create_all(新表 `site_experiences`/`llm_allowed_hosts`)+ 站点 YAML 幂等 upsert(3 站);如需停机窗口显式控制,可先在容器内跑 `python scripts/migrate_add_site_experiences.py`(幂等,与启动等价)
- [ ] 若 `llm_providers` 存在旧链格式:`python scripts/migrate_llm_chain_format.py`(幂等归一化;先 DB 备份)
- [ ] 验证:`/health` 200;admin 登录;遗留对话/数据源/技术洞察可读(升级兼容性已由 RC 门在 bbfaa6a 形态库上实证)

### 阶段 2 — Trust Boundary / channel_visibility(P0 红线:必须先于任何新的公开暴露)

- [ ] 盘点内部源(如 `knowledge-support`):管理端 PATCH `/api/admin/data-sources/{id}` 将 `config.channel_visibility` 设为 `["internal"]`
- [ ] `python scripts/migrate_channel_visibility.py`(dry-run,审阅计划;幽灵 chunk 单列上报,不自动处理)
- [ ] `python scripts/migrate_channel_visibility.py --apply`(幂等,只写属性不重嵌入)
- [ ] 验证:公共 widget 渠道检索不到内部源内容(内部案例 ICCID/报价等不再出现在公开回答)

### 阶段 3 — runtime/config/secrets

- [ ] admin 默认口令处置(生产 admin 若仍为种子口令,立即改密;`scripts/create_admin_user.py` 可建独立管理员)
- [ ] `GITHUB_TOKEN` 只读最小权限(启动时严格模式自动校验,过宽会阻断启动 —— 属预期 fail-fast)
- [ ] 预算默认值(BUDGET_DAILY_REQUESTS/TOKENS)按需调整

### 阶段 4 — WEB 语料同步/修复(WEB-01)

- [ ] 选维护窗口手动首跑:`docker compose -f deploy/prod/docker-compose.yml run --rm sync python scripts/sync.py`
- [ ] **预期首跑自愈浪涌**:生产账本存在旧漂移(821 chunks vs 2 行时代),一致性校验将触发全量重灌(约 100+ 页重嵌入,GPU 数十分钟级),SyncLog 记 `partial`(附 coverage 行)→ 下轮复核转 `success`;这不是故障
- [ ] 已知盲区如实上报:20 个 JS 渲染页 low_content(headless 渲染 = F-6 跟进项),勿当事故
- [ ] `--reindex` 仅限 schema 变更需要(删 collection 全量重灌,期间服务不可用)

### 阶段 5 — Multi-Site Origin/CORS/站点配置

- [ ] `CORS_ALLOW_ORIGINS` 含三站:`https://www.camthink.ai,https://wiki.camthink.ai,https://store.camthink.ai`
- [ ] 核对 `config/sites.yaml` 三站域名与真实域名一致(seed 幂等,改 YAML 重启生效)
- [ ] 逐站验证 `GET /api/widget/site-config?site_id=<id>`:合法 Origin 200 / 错误 Origin 403 / 未知站 403(fail-closed 已由测试锚定)

### 阶段 6 — Widget 嵌入(真实三站)

- [ ] website/wiki/store 按站嵌入(`data-api-url` + `data-site-id`);legacy(无 site-id)路径保持兼容
- [ ] 每站冒烟:启动、starters/welcome 生效、一次真实问答、一次越权路径 403

### 阶段 7 — 生产验证

- [ ] 三站 Natural Acceptance + 生产验收(独立门,不在本清单内展开)

## 回滚 / 失效边界

- **镜像回滚**:`./deploy/prod/update.sh <旧 tag>`(脚本内置 backend health 门禁,失败即退出,不盲推进 sync-cron)
- **DB 兼容**:本 RC 全部 schema 变更为**纯增量**(新表 site_experiences/llm_allowed_hosts + conversations 可空列 site_id),旧代码在新库上照常运行 → 镜像回滚不需要回滚 DB
- **启动失效安全**:APP_MODE=prod 下 ENCRYPTION_KEY 缺失/JWT_SECRET 默认值 → 拒绝启动(RuntimeError);GPU 预检在 update.sh;BGE 首载 ~45s 内 health 未就绪属预期,非故障
- **同步失效安全**:单源失败不中断批次;partial 不推进增量窗口;删除生命周期向量清理失败 → 502 且配置/账本保留可重试
- **站点失效安全**:未知站/禁用站/Origin 不匹配/无 Origin → 一律 403 统一文案(fail-closed);site-config 拉取失败 Widget 回退默认体验且 site_id 仍由服务端裁决
