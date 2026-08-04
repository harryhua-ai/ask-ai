#!/usr/bin/env bash
# tesla-t4 部署/更新脚本
#
# 用法:
#   ssh tesla-t4 'cd ~/ask-ai/deploy/tesla-t4 && ./update.sh'        # 更新到 latest
#   ssh tesla-t4 'cd ~/ask-ai/deploy/tesla-t4 && ./update.sh <tag>'  # 更新到指定 tag(回滚)
#
# 前置(一次性):
#   1. docker login ghcr.io -u harryhua-ai -p <GHCR token>(首次)
#   2. cp .env.example .env,填生产凭证
#   3. corpus 在 /home/ubuntu/ask-ai-corpus(decision 2)
#   4. models 在 /home/ubuntu/ask-ai/models(decision 3)
#
# 回滚:./update.sh <旧 tag>(如 v0.1.0 或某 git sha)

set -euo pipefail

TAG="${1:-latest}"
COMPOSE_FILE="$(dirname "$0")/docker-compose.yml"

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

# 3. 滚动更新(backend 先,sync 后,避免拉新数据时旧 backend 读)
echo "[3/4] 更新服务..."
docker compose -f "$COMPOSE_FILE" up -d backend
sleep 5
# backend 健康检查
if curl -sf http://localhost:8000/health > /dev/null; then
    echo "  ✅ backend 健康"
else
    echo "  ❌ backend 健康检查失败,查看日志:docker compose logs backend"
    exit 1
fi

# 4. sync worker + cron 更新(最后,避免索引中断)
echo "[4/4] 更新 sync worker..."
docker compose -f "$COMPOSE_FILE" up -d sync sync-cron

echo ""
echo "=== 部署完成 ==="
docker compose -f "$COMPOSE_FILE" ps
echo ""
echo "查看日志:docker compose -f $COMPOSE_FILE logs -f backend"