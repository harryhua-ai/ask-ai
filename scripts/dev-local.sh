#!/usr/bin/env bash
# ask-ai 本地一键启动(mac)
#
# 用法:
#   ./scripts/dev-local.sh          # 启动数据层 + 后端
#   ./scripts/dev-local.sh --data   # 仅启动数据层(postgres + weaviate)
#   ./scripts/dev-local.sh --reset  # 重启数据层(保留数据)
#
# 前置:
#   - .env 已配置(DEEPSEEK_API_KEY 等)
#   - 首次运行需先 ./scripts/sync_local_data.sh 拉取数据
#   - BGE 模型权重在 models/ 目录(首次从 HF 下载或从 tesla-t4 拷贝)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/deploy/local/docker-compose.yml"

START_DATA=true
START_BACKEND=true

case "${1:-}" in
  --data)  START_BACKEND=false ;;
  --reset) START_BACKEND=false; docker compose -f "$COMPOSE_FILE" down ;;
  "")      ;;
  *) echo "用法: $0 [--data | --reset]"; exit 1 ;;
esac

echo "=== ask-ai 本地启动 ==="
echo ""

# 1. 数据层
echo "[1/2] 启动数据层(postgres + weaviate)..."
docker compose -f "$COMPOSE_FILE" up -d

echo "  等待 postgres 就绪..."
until docker compose -f "$COMPOSE_FILE" exec -T postgres pg_isready -U ask_ai >/dev/null 2>&1; do
  sleep 1
done

echo "  等待 weaviate 就绪..."
until curl -sf http://localhost:8080/v1/.well-known/ready >/dev/null 2>&1; do
  sleep 2
done

echo "  数据层就绪 ✓"
echo ""

# 2. 后端
if [ "$START_BACKEND" = true ]; then
  echo "[2/2] 启动后端(CPU 模式)..."
  echo "  EMBEDDER_DEVICE=auto (CPU)"
  echo "  API: http://localhost:8000"
  echo "  Docs: http://localhost:8000/docs (dev 模式)"
  echo ""
  echo "  Ctrl+C 停止后端"
  echo ""

  cd "$REPO_ROOT"
  EMBEDDER_DEVICE=auto \
  TRANSFORMERS_OFFLINE=0 \
  exec uv run python -m backend.main
fi
