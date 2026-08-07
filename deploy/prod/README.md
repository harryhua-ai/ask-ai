# ask-ai 生产部署(tesla-t4 全栈 GPU docker)

## 架构

```
tesla-t4(NVIDIA T4 16GB)docker compose(project=tesla-t4):
  ├── postgres:16-alpine     (external 卷 tesla-t4_pgdata)
  ├── weaviate:1.28.0        (external 卷 tesla-t4_weaviate_data)
  ├── backend   GPU uvicorn  (18000:8000,服务 /api + /admin 前端)
  ├── sync      GPU 一次性    (手动 sync/reindex,不常驻)
  └── sync-cron GPU 每小时增量
```

**同一 GPU 镜像**(`ghcr.io/harryhua-ai/ask-ai:latest`)服务 backend + sync + sync-cron,compose 用 `command` 覆盖入口。DRY via YAML anchor(`x-backend-base`)。

## 数据保留(name + external 卷)

- `name: tesla-t4` + external 命名卷(`tesla-t4_pgdata` / `tesla-t4_weaviate_data`)。
- 目录从旧 `deploy/tesla-t4/` 改名到 `deploy/prod/` **不改 project 名/卷名**,现有数据不丢。
- `dev` compose(`ask-ai-dev`)引用**同一 external 卷**,dev↔prod 切换数据保留。
- `docker compose down` **不删 external 卷**(只删容器);`down -v` 才删卷(慎用)。

## 挂载(决策 2/3,不打进镜像)

| host 路径 | 容器路径 | 权限 | 用途 |
|---|---|---|---|
| `/home/ubuntu/ask-ai-corpus` | `/home/ubuntu/ask-ai-corpus` | rw | 代码仓库 clone(sync git checkout 需写权限) |
| `/home/ubuntu/knowledge-support` | `/home/ubuntu/knowledge-support` | ro | filesystem 源(knowledge-support-cases)读取 |
| `/home/ubuntu/ask-ai/models` | `/models` | ro | BGE-m3 + reranker 权重(`HF_HOME=/models`) |

## 镜像构建(GitHub Actions)

- **触发**:push to main / tag `v*.*.*` / manual
- **流程**:test job(单测,失败不出镜像)→ build GPU image → push GHCR
- **tag**:`latest` + git SHA + semver
- **GPU 镜像**:CUDA 12.8 + uv(锁 uv.lock)+ 多阶段(builder 装依赖 → runtime 精简)

## 一次性前置准备(tesla-t4)

```bash
# 1. GHCR 登录(首次,需 GitHub PAT,read:packages 权限)
docker login ghcr.io -u harryhua-ai -p <GHCR_TOKEN>

# 2. 生产 .env(仓库根)
cd ~/ask-ai
cp deploy/prod/.env.example .env
# 填:POSTGRES_PASSWORD / JWT_SECRET / ENCRYPTION_KEY / DEEPSEEK_API_KEY / WOOCOMMERCE_* / GITHUB_TOKEN / ADMIN_PASSWORD
# JWT_SECRET/ENCRYPTION_KEY 用:openssl rand -hex 32

# 3. 确认挂载路径
ls -d /home/ubuntu/ask-ai-corpus /home/ubuntu/ask-ai/models /home/ubuntu/knowledge-support
```

## 部署/更新

```bash
# 首次部署 / 更新到 latest(Actions 构建后)
ssh tesla-t4 'cd ~/ask-ai && ./deploy/prod/update.sh'

# 回滚到指定 tag
ssh tesla-t4 'cd ~/ask-ai && ./deploy/prod/update.sh <git-sha 或 v0.1.0>'

# 查看日志
docker compose -f ~/ask-ai/deploy/prod/docker-compose.yml logs -f backend
```

`update.sh` 流程:pull 镜像 → GPU 预检 → `up -d backend` + 健康检查(`localhost:18000/health`)→ `up -d sync-cron`。
**sync 不 `up -d`**(一次性,会循环重启),手动按需触发(见下)。

## 手动同步 / reindex

```bash
# 增量同步(24h 窗口 + documents 表比对,无变更跳过)
docker compose -f ~/ask-ai/deploy/prod/docker-compose.yml run --rm sync python scripts/sync.py

# 全量 reindex(⚠️ 删整个 collection 后重灌所有 enabled 源;schema 变更/符号回填时用)
docker compose -f ~/ask-ai/deploy/prod/docker-compose.yml run --rm sync python scripts/sync.py --reindex
```

⚠️ **`--reindex` 无 `--source` = 全量重灌**(删 collection + 重灌所有源);**`--source X --reindex` = 灾难性误操作**(删全库只灌 X,曾误删 560k chunk)。单源增量绝不用 `--reindex`。

## sync 策略

- `sync-cron`:每小时增量(`fetch_changes(24h)` + documents 表比对,无变更跳过)。
- `sync`(手动):全量初始化 / `--reindex` schema 变更时触发。
- WooCommerce 源:每小时刷新(40 产品,价格/库存动态)。

## GPU 共享约束(关键)

tesla-t4 是生产服务器,共享 `locate-anything`(~3.8GB)/ `llama-server`(~4.8GB)/ `neomind-extension-runner`(~2.7GB),基线 ~11.3GB。
- `EMBEDDER_BATCH_SIZE=16`(显存保护,剩 ~4.5GB;实测 reindex 峰值 ~13.4GB)。
- 若 sync OOM:降 `EMBEDDER_BATCH_SIZE=8`。
- **绝不停生产服务**;盯 `nvidia-smi >15.8GB` → kill sync 降 batch。

## 已知细节

- `sync` / `sync-cron` 的 `healthcheck: disable: true` — 镜像内置 HEALTHCHECK(`curl :8000/health`)为 backend(uvicorn)设计,sync 不跑 web 服务,不关会永远 unhealthy。
- `backend` 健康检查走镜像内置 HEALTHCHECK(host 端口 18000 → 容器 8000)。
