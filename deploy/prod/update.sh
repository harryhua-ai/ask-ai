#!/usr/bin/env bash
# ask-ai 生产部署/更新脚本(tesla-t4)
#
# 用法:
#   ssh tesla-t4 'cd ~/ask-ai && ./deploy/prod/update.sh'        # 更新到 latest
#   ssh tesla-t4 'cd ~/ask-ai && ./deploy/prod/update.sh <tag>'  # 更新到指定 tag(回滚)
#
# 前置(一次性):
#   1. docker login ghcr.io -u harryhua-ai -p <GHCR token>(首次)
#   2. cp deploy/prod/.env.example .env,填生产凭证(仓库根 .env)
#   3. corpus 在 /home/ubuntu/ask-ai-corpus(decision 2)
#   4. models 在 /home/ubuntu/ask-ai/models(decision 3)
#
# 回滚:./update.sh <旧 tag>(如 v0.1.0 或某 git sha)

set -euo pipefail

TAG="${1:-latest}"
# compose 文件相对脚本位置;脚本从仓库根运行(cd ~/ask-ai)
COMPOSE_FILE="$(dirname "$0")/docker-compose.yml"
# backend host 端口(与 compose 的 ports 映射一致:18000:8000)
BACKEND_PORT="${BACKEND_PORT:-18000}"

echo "=== ask-ai 部署:tag=${TAG} ==="

# 1. 拉最新镜像
echo "[1/4] 拉取镜像 ghcr.io/harryhua-ai/ask-ai:${TAG}..."
docker compose -f "$COMPOSE_FILE" pull

# 2. 健康预检:GPU 可用 + 显存
echo "[2/4] GPU 预检..."
GPU_USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
echo "  GPU 已用: ${GPU_USED} MiB / 16384 MiB"
if [ "$GPU_USED" -gt 15000 ]; then
    echo "  ⚠️ GPU 显存 >15GB(共享服务占用高),继续但 sync 可能 OOM"
    echo "  若 OOM,降 EMBEDDER_BATCH_SIZE=8"
fi

# 3. 滚动更新 backend(先 backend,sync 后,避免拉新数据时旧 backend 读)
echo "[3/4] 更新 backend..."
docker compose -f "$COMPOSE_FILE" up -d backend
sleep 5
# backend 健康检查(host 端口 18000,非容器内 8000)
if curl -sf "http://localhost:${BACKEND_PORT}/health" > /dev/null; then
    echo "  ✅ backend 健康(localhost:${BACKEND_PORT}/health)"
else
    echo "  ❌ backend 健康检查失败(localhost:${BACKEND_PORT}/health)"
    echo "  查日志:docker compose -f $COMPOSE_FILE logs backend"
    exit 1
fi

# 4. 更新 sync-cron(sync 是一次性手动,不 up -d;见下方说明)
echo "[4/4] 更新 sync-cron..."
docker compose -f "$COMPOSE_FILE" up -d sync-cron

echo ""
echo "=== 部署完成 ==="
docker compose -f "$COMPOSE_FILE" ps
echo ""
echo "手动同步 / reindex(按需):"
echo "  docker compose -f $COMPOSE_FILE run --rm sync python scripts/sync.py            # 增量同步"
echo "  docker compose -f $COMPOSE_FILE run --rm sync python scripts/sync.py --reindex  # ⚠️ 删 collection 全量重灌"
echo ""
echo "查看日志:docker compose -f $COMPOSE_FILE logs -f backend"
