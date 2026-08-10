#!/usr/bin/env bash
# 从 tesla-t4 同步 Postgres + Weaviate 数据到本地 Docker
#
# 用法:
#   ./scripts/sync_local_data.sh              # 同步 pg + weaviate
#   ./scripts/sync_local_data.sh --pg-only    # 仅 Postgres
#   ./scripts/sync_local_data.sh --weaviate-only  # 仅 Weaviate
#
# 前置:
#   - SSH 别名 tesla-t4 已配置
#   - 本地 Docker 已启动(deploy/local/docker-compose.yml)
#   - 远程 tesla-t4 prod/dev 服务运行中(数据源)
#
# 注意:
#   - Weaviate 数据量较大(可能几 GB),首次同步耗时取决于带宽
#   - 同步期间本地 weaviate/pg 会短暂停止(恢复数据需要独占访问)
#   - 不会影响 tesla-t4 上的服务(只读导出)

set -euo pipefail

SSH_HOST="tesla-t4"
REMOTE_COMPOSE="tesla-t4"  # docker compose project name on remote
LOCAL_COMPOSE_FILE="$(cd "$(dirname "$0")/.." && pwd)/deploy/local/docker-compose.yml"
TMP_DIR="/tmp/ask-ai-data-sync"

SYNC_PG=true
SYNC_WEAVIATE=true

case "${1:-}" in
  --pg-only)       SYNC_WEAVIATE=false ;;
  --weaviate-only) SYNC_PG=false ;;
  ""|--all)        ;;
  *) echo "用法: $0 [--pg-only | --weaviate-only | --all]"; exit 1 ;;
esac

echo "=== ask-ai 数据同步:tesla-t4 → mac 本地 ==="
echo ""

# ── Postgres ──────────────────────────────────────────────────────
if [ "$SYNC_PG" = true ]; then
  echo "[1/2] Postgres 同步"
  echo "  导出远程 pg_dump..."
  mkdir -p "$TMP_DIR"
  ssh "$SSH_HOST" \
    "docker exec tesla-t4-postgres-1 pg_dump -U ask_ai -d ask_ai --no-owner --no-acl" \
    > "$TMP_DIR/ask_ai_dump.sql"

  DUMP_SIZE=$(du -h "$TMP_DIR/ask_ai_dump.sql" | cut -f1)
  echo "  dump 大小: $DUMP_SIZE"

  echo "  恢复到本地 postgres..."
  docker compose -f "$LOCAL_COMPOSE_FILE" stop postgres 2>/dev/null || true

  # 删旧库重建(本地数据不保留,完全替换)
  docker compose -f "$LOCAL_COMPOSE_FILE" up -d postgres
  echo "  等待 postgres 就绪..."
  until docker compose -f "$LOCAL_COMPOSE_FILE" exec -T postgres pg_isready -U ask_ai >/dev/null 2>&1; do
    sleep 1
  done

  # drop & recreate 再灌(避免 OID 冲突)
  docker compose -f "$LOCAL_COMPOSE_FILE" exec -T postgres \
    psql -U ask_ai -d postgres -c "DROP DATABASE IF EXISTS ask_ai;"
  docker compose -f "$LOCAL_COMPOSE_FILE" exec -T postgres \
    psql -U ask_ai -d postgres -c "CREATE DATABASE ask_ai OWNER ask_ai;"

  docker compose -f "$LOCAL_COMPOSE_FILE" exec -T postgres \
    psql -U ask_ai -d ask_ai < "$TMP_DIR/ask_ai_dump.sql"

  echo "  Postgres 同步完成 ✓"
  echo ""
fi

# ── Weaviate ─────────────────────────────────────────────────────
if [ "$SYNC_WEAVIATE" = true ]; then
  echo "[2/2] Weaviate 同步"

  echo "  打包远程 weaviate 数据..."
  mkdir -p "$TMP_DIR"
  ssh "$SSH_HOST" \
    "docker run --rm -v tesla-t4_weaviate_data:/data alpine \
     tar cf - -C /data ." > "$TMP_DIR/weaviate_data.tar"

  TAR_SIZE=$(du -h "$TMP_DIR/weaviate_data.tar" | cut -f1)
  echo "  tar 大小: $TAR_SIZE"

  echo "  停止本地 weaviate..."
  docker compose -f "$LOCAL_COMPOSE_FILE" stop weaviate 2>/dev/null || true

  echo "  清空本地 weaviate 数据卷..."
  docker run --rm -v ask-ai-local_weaviate_data:/data alpine \
    sh -c "find /data -mindepth 1 -delete" 2>/dev/null || true

  echo "  恢复数据到本地卷..."
  docker run --rm -i \
    -v ask-ai-local_weaviate_data:/data \
    alpine tar xf - -C /data < "$TMP_DIR/weaviate_data.tar"

  echo "  启动本地 weaviate..."
  docker compose -f "$LOCAL_COMPOSE_FILE" up -d weaviate
  echo "  等待 weaviate 就绪..."
  until curl -sf http://localhost:8080/v1/.well-known/ready >/dev/null 2>&1; do
    sleep 2
  done

  echo "  Weaviate 同步完成 ✓"
  echo ""
fi

# ── 验证 ─────────────────────────────────────────────────────────
echo "=== 验证 ==="

PG_COUNT=$(docker compose -f "$LOCAL_COMPOSE_FILE" exec -T postgres \
  psql -U ask_ai -d ask_ai -t -c "SELECT count(*) FROM documents;" 2>/dev/null | tr -d '[:space:]')
echo "  Postgres documents: ${PG_COUNT:-N/A}"

WV_READY=$(curl -sf http://localhost:8080/v1/.well-known/ready && echo "OK" || echo "FAIL")
echo "  Weaviate ready: $WV_READY"

echo ""
echo "=== 同步完成 ==="
echo "本地后端启动: uv run python -m backend.main"
echo "本地前端启动: cd admin && npm run dev"
