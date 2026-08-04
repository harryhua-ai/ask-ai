# tesla-t4 生产部署(全栈 GPU docker)

## 架构(决策 1a:全栈 tesla-t4)

```
tesla-t4(NVIDIA T4 16GB)docker compose:
  ├── postgres:16-alpine          (持久卷 pgdata)
  ├── weaviate:1.28.0              (持久卷 weaviate_data)
  ├── backend    GPU 镜像 uvicorn  (端口 8000,挂载 corpus+models)
  ├── sync       GPU 镜像 sync.py   (首次全量 + 手动 reindex)
  └── sync-cron GPU 镜像 每小时增量
```

**同一 GPU 镜像**(ghcr.io/harryhua-ai/ask-ai)服务 backend + sync,compose 用 `command` 覆盖入口。

## 挂载(决策 2/3,不打进镜像)

| host 路径 | 容器路径 | 用途 |
|---|---|---|
| `/home/ubuntu/ask-ai-corpus` | `/corpus:ro` | 代码仓库 clone 1.7G(sync 索引源) |
| `/home/ubuntu/ask-ai/models` | `/models:ro` | BGE-m3 + reranker 4.3G(`HF_HOME=/models`) |

## 镜像构建(GitHub Actions,决策 4)

- **触发**:push to main / tag `v*.*.*` / manual
- **流程**:test job(跑单测,失败不出镜像)→ build GPU image → push GHCR
- **tag**:`latest` + git SHA + semver
- **GPU 镜像**:CUDA 12.8 + uv(锁 uv.lock)+ 多阶段(builder 装依赖 → runtime 精简)
- **缓存**:buildx cache `type=gha`,后续构建加速

## 一次性前置准备(tesla-t4)

```bash
# 1. GHCR 登录(首次,需 GitHub Personal Access Token,read:packages 权限)
docker login ghcr.io -u harryhua-ai -p <GHCR_TOKEN>

# 2. 生产 .env
cd ~/ask-ai/deploy/tesla-t4
cp .env.example .env
# 填:POSTGRES_PASSWORD / JWT_SECRET / ENCRYPTION_KEY / DEEPSEEK_API_KEY / WOOCOMMERCE_* / GITHUB_TOKEN / ADMIN_PASSWORD
# JWT_SECRET/ENCRYPTION_KEY 用:openssl rand -hex 32

# 3. 确认挂载路径(decision 2/3)
ls -d /home/ubuntu/ask-ai-corpus /home/ubuntu/ask-ai/models
```

## 部署/更新

```bash
# 首次部署(全栈起 + sync 全量索引)
ssh tesla-t4 'cd ~/ask-ai/deploy/tesla-t4 && ./update.sh'

# 更新到 latest(Actions 构建后)
ssh tesla-t4 'cd ~/ask-ai/deploy/tesla-t4 && ./update.sh'

# 回滚到指定 tag
ssh tesla-t4 'cd ~/ask-ai/deploy/tesla-t4 && ./update.sh <git-sha 或 v0.1.0>'

# 查看日志
docker compose -f ~/ask-ai/deploy/tesla-t4/docker-compose.yml logs -f backend
```

## GPU 共享约束(关键)

tesla-t4 是生产服务器,共享 `locate-anything` / `llama-server` / `neomind-extension-runner`(~11.8GB)。
- `EMBEDDER_BATCH_SIZE=16`(显存保护,剩 ~4.5GB)
- 若 sync OOM:降 `EMBEDDER_BATCH_SIZE=8`
- **绝不停生产服务**;盯 `nvidia-smi >15.8GB` → kill sync 降 batch

## sync 策略

- `sync` 服务:首次全量(或 `--reindex` schema 变更时手动触发)
- `sync-cron` 服务:每小时增量(`modified_after` / git commit 比对)
- WooCommerce 源:每小时全量刷新(40 产品,价格/库存动态)

## 后续(P0#1/#2 就绪后)

1. P0#1 意图路由 + P1#5 WooCommerce merge 到 main
2. Actions 自动构建 GPU 镜像
3. tesla-t4 `./update.sh` 部署
4. 把 woocommerce data_source 加到 DB(admin 或 SQL)
5. `sync` 跑全量(含 woocommerce + 符号回填后)
6. 跑 e2e 20 问验证(P0#1 Real-Run Gate)
7. 配 admin 账户(`scripts/create_admin_user.py`)