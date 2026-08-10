#!/usr/bin/env bash
# 在 tesla-t4(GPU)上执行 reindex,完成后同步数据回 mac 本地
#
# 用法:
#   ./scripts/reindex_remote.sh                      # 全量 reindex + 同步回本地
#   ./scripts/reindex_remote.sh --sync-only          # 仅 reindex,不同步
#   ./scripts/reindex_remote.sh --source github-ne301  # 单源「增量」(不带 --reindex)
#
# ⚠️ 全量 reindex(无 --source)会删除整个 Weaviate collection 后全量重灌!
#    期间服务不可用;仅 schema 变更/符号字段回填时手动触发。
#    单源增量(--source X)绝不动 --reindex(曾误删 560k chunk,见 CLAUDE.md 约束)。
#
# 流程:
#   1. tesla-t4 上 docker compose run --rm sync python scripts/sync.py [args]
#   2. (可选)mac 本地补灌 filesystem 源(mac 有 Knowledge 仓库)
#   3. sync_local_data.sh 把 tesla-t4 数据同步回 mac

set -euo pipefail

SSH_HOST="tesla-t4"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SYNC_SCRIPT="$REPO_ROOT/scripts/sync_local_data.sh"
# 纯镜像部署:用 ~/ask-ai/deploy/prod/ 的 sync 服务(镜像内最新 sync.py)
REMOTE_SYNC_CMD="cd ~/ask-ai/deploy/prod && docker compose run --rm sync python scripts/sync.py"

DO_SYNC=true
SYNC_ARGS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sync-only) DO_SYNC=false ;;
    --source)
      # 单源增量:只传 --source X,绝不带 --reindex(防误删整个 collection)
      shift
      SYNC_ARGS="--source $1"
      ;;
    --reindex)
      # 显式全量 reindex:删整个 collection 重灌(高危,需用户确认)
      SYNC_ARGS="--reindex"
      ;;
    *) echo "用法: $0 [--sync-only | --source <源名> | --reindex]"; exit 1 ;;
  esac
  shift
done

# 安全提示:仅当真正走 --reindex 时才警告删库
if [[ "$SYNC_ARGS" == *"--reindex"* ]]; then
  echo "=== ask-ai 远程全量 reindex(tesla-t4 GPU) ==="
  echo ""
  echo "⚠️  这将删除 tesla-t4 上的整个 Weaviate collection 并重新索引!"
  echo "   reindex 参数: python scripts/sync.py $SYNC_ARGS"
  echo ""
  read -p "确认继续? (yes/no): " confirm
  if [ "$confirm" != "yes" ]; then
    echo "已取消"
    exit 0
  fi
else
  echo "=== ask-ai 远程同步(tesla-t4 GPU) ==="
  echo "   参数: python scripts/sync.py $SYNC_ARGS(增量,不动 collection)"
  echo ""
fi

echo "[1/2] tesla-t4 执行($SYNC_ARGS)..."
ssh "$SSH_HOST" "$REMOTE_SYNC_CMD $SYNC_ARGS"

echo ""
echo "  同步完成 ✓"

# 提示 filesystem 源补灌
echo ""
echo "提示:filesystem 源(knowledge-support)需在 mac 上补灌:"
echo "  uv run python scripts/sync.py --source knowledge-support-cases"
echo ""

# 同步回本地
if [ "$DO_SYNC" = true ]; then
  echo "[2/2] 同步数据到 mac 本地..."
  exec "$SYNC_SCRIPT"
else
  echo "[2/2] 跳过同步(--sync-only)"
  echo "  手动同步: ./scripts/sync_local_data.sh"
fi