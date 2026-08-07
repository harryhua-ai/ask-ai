# ask-ai 开发部署(backend + DB on tesla-t4,前端在 mac)

## 架构

```
开发阶段:
  tesla-t4(project=ask-ai-dev,共享 prod 的 external 数据卷):
    ├── postgres    (tesla-t4_pgdata,与 prod 共享)
    ├── weaviate   (tesla-t4_weaviate_data,与 prod 共享)
    ├── backend    GPU uvicorn(18000:8000)
    └── sync       GPU 一次性(手动,不常驻)
  mac:
    └── 前端 admin/widget(npm run dev,Vite 代理 /api → tesla-t4:18000)
```

与 `prod` 的差异:① **无 sync-cron**(前端 dev 期间不让每小时同步抢 GPU);② project 名 `ask-ai-dev`(容器名与 prod 隔离,但**共享 external 数据卷**)。

## 数据保留

- 与 `prod` 共享 `tesla-t4_pgdata` / `tesla-t4_weaviate_data`(external 卷)+ 同一个仓库根 `.env`。
- dev↔prod 切换:数据/配置不丢(卷 external,`down` 不删卷)。

## 用法

### 1. tesla-t4 起后端(ssh)

```bash
# 首次:确保 prod .env 已配好(见 prod/README.md);若 prod 在跑,先停 prod
docker compose -f ~/ask-ai/deploy/prod/docker-compose.yml down    # 停 prod(卷保留)
# 起 dev
docker compose -f ~/ask-ai/deploy/dev/docker-compose.yml up -d
# 健康检查
curl http://tesla-t4:18000/health
```

⚠️ dev/prod 的 backend 都绑 18000,**不能同时跑**(端口冲突)。切换前 `down` 另一个。

### 2. mac 起前端

```bash
# admin(http://localhost:5174)
cd admin && npm install && npm run dev

# widget(http://localhost:5173)
cd widget && npm install && npm run dev
```

Vite 代理 `/api` → tesla-t4:18000(见 `admin/vite.config.ts` / `widget/vite.config.ts` 的 `VITE_API_TARGET`)。
若 .env / 代理目标不对,设 `VITE_API_TARGET=http://tesla-t4:18000` 后 `npm run dev`。

### 3. dev 期间手动同步 / reindex(按需)

```bash
# 增量同步(dev 改了数据源配置后)
docker compose -f ~/ask-ai/deploy/dev/docker-compose.yml run --rm sync python scripts/sync.py

# 全量 reindex(schema 变更/符号回填)
docker compose -f ~/ask-ai/deploy/dev/docker-compose.yml run --rm sync python scripts/sync.py --reindex
```

## dev → prod 切换(部署)

```bash
# 停 dev(卷保留)
docker compose -f ~/ask-ai/deploy/dev/docker-compose.yml down
# 部署 prod(数据/配置延续)
ssh tesla-t4 'cd ~/ask-ai && ./deploy/prod/update.sh'
```

## GPU 共享约束

同 `prod/README.md` — tesla-t4 共享 GPU,`EMBEDDER_BATCH_SIZE=16`,reindex 时盯 `nvidia-smi >15.8GB`。
dev 期间无 sync-cron 抢 GPU,但手动 sync/reindex 仍占 GPU。
