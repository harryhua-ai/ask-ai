# ask-ai 部署

两套 compose,对应两个阶段:

| 目录 | 阶段 | 内容 | 何时用 |
|---|---|---|---|
| [`dev/`](dev/) | 开发 | backend + DB on tesla-t4(无 sync-cron),前端 mac 代理 | 前端在 mac 迭代,后端跑 tesla-t4 |
| [`prod/`](prod/) | 部署 | 全栈 tesla-t4(backend + sync + sync-cron),docker pull | 正式部署,backend 服务 /admin 前端 |

## 共享:数据 + 配置

两套**共享**:
- **数据卷**:`tesla-t4_pgdata` / `tesla-t4_weaviate_data`(external 命名卷,dev/prod 引用同一份)。
- **配置**:仓库根 `.env`(`../../.env`,同一个)。

→ dev↔prod 切换数据/配置**保留**,不丢。

## dev ↔ prod 切换

两套的 backend 都绑 tesla-t4:18000,**不能同时跑**(端口冲突)。切换:

```bash
# dev → prod(部署)
docker compose -f ~/ask-ai/deploy/dev/docker-compose.yml down      # 停 dev(卷保留)
ssh tesla-t4 'cd ~/ask-ai && ./deploy/prod/update.sh'               # 部署 prod

# prod → dev(回到开发)
docker compose -f ~/ask-ai/deploy/prod/docker-compose.yml down      # 停 prod(卷保留)
docker compose -f ~/ask-ai/deploy/dev/docker-compose.yml up -d      # 起 dev
```

`down` 不删 external 卷(只删容器);`down -v` 才删卷(慎用,会丢数据)。

## 镜像

两套都用 `ghcr.io/harryhua-ai/ask-ai:latest`(GitHub Actions 构建,CUDA 12.8 + uv)。
- 更新镜像:`./deploy/prod/update.sh`(pull + 滚动更新)。
- 镜像构建见 `.github/workflows/build-image.yml`。

## 数据源同步

- `prod` 的 `sync-cron`:每小时增量(常驻)。
- `sync`(dev/prod 都有):手动一次性,`docker compose -f <file> run --rm sync python scripts/sync.py [--reindex]`。
- ⚠️ `--reindex` 无 `--source` = 全量重灌(删 collection + 重灌所有源);`--source X --reindex` = 灾难性误操作(曾误删 560k chunk)。

## 各自详细文档

- 开发:`dev/README.md`
- 生产:`prod/README.md`(含前置准备 / GPU 约束 / 已知细节)
