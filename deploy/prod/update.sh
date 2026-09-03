#!/usr/bin/env bash
# ask-ai 生产部署/更新脚本(tesla-t4)—— #10 版本与发布治理契约
#
# 用法(自 v1.0.0 起强制版本化):
#   ssh tesla-t4 'cd ~/ask-ai && ./deploy/prod/update.sh <version-tag>'   # 如 v1.0.0
#   回滚 = 同一命令 + 上一个不可变版本 tag(如 ./deploy/prod/update.sh v0.9.0)
#
# 契约(#10 冻结):
#   - 缺少 tag 参数 → 失败(禁止隐式升级);
#   - latest → 拒绝(生产部署/回滚必须显式不可变版本 tag);
#   - backend / sync-cron / sync-executor 三应用服务**同批**更新到同一 tag,
#     不允许任何服务停留在不同 ASK-AI release tag;
#   - 切换前校验镜像内 RELEASE.json(version/git_sha)与请求 tag 一致(fail-closed);
#   - 切换后核验 /health 上报 version 与请求 tag 一致(运行时身份 = 镜像身份);
#   - 基础设施服务(postgres/weaviate 等)不受影响。
#
# 前置(一次性):
#   1. docker login ghcr.io -u harryhua-ai -p <GHCR token>(首次)
#   2. cp deploy/prod/.env.example .env,填生产凭证(仓库根 .env)
#   3. corpus 在 /home/ubuntu/ask-ai-corpus;models 在 /home/ubuntu/ask-ai/models
#
# ⚠️ 本脚本只适用于内嵌 RELEASE.json 的镜像(#10 之后由 CI 构建的 tag 镜像);
#    旧镜像(无清单)会被步骤 [3/6] 显式拒绝,不会静默部署。

set -euo pipefail

IMAGE="ghcr.io/harryhua-ai/ask-ai"
TAG="${1:-}"

# ---------- [1/6] 版本化契约守卫 ----------
if [ -z "$TAG" ]; then
    echo "❌ 缺少版本 tag 参数。用法: $0 <version-tag>(如 v1.0.0;回滚传上一个不可变 tag)"
    exit 2
fi
if [ "$TAG" = "latest" ]; then
    echo "❌ 生产部署/回滚禁止 latest(#10 契约):必须显式不可变版本 tag(如 v1.0.0)"
    exit 2
fi
export ASKAI_IMAGE_TAG="$TAG"
# compose 文件相对脚本位置;脚本从仓库根运行(cd ~/ask-ai)
COMPOSE_FILE="$(dirname "$0")/docker-compose.yml"
BACKEND_PORT="${BACKEND_PORT:-18000}"
EXPECTED_VERSION="${TAG#v}"   # RELEASE.json 内为无前缀 SemVer

echo "=== ask-ai 部署:$IMAGE:$TAG(期望 version=$EXPECTED_VERSION)==="

# ---------- [2/6] 拉取镜像 ----------
echo "[2/6] 拉取镜像 $IMAGE:$TAG ..."
docker compose -f "$COMPOSE_FILE" pull

# ---------- [3/6] 镜像内 RELEASE.json 断言(fail-closed) ----------
echo "[3/6] 校验镜像内发布清单 ..."
CID=$(docker create "$IMAGE:$TAG")
RELEASE_TMP="$(mktemp /tmp/askai-release.XXXXXX.json)"
docker cp "$CID:/app/RELEASE.json" "$RELEASE_TMP" || {
    docker rm "$CID" >/dev/null 2>&1 || true
    echo "❌ 镜像内无 RELEASE.json:$TAG 不是 #10 契约的版本化镜像,拒绝部署"
    exit 1
}
docker rm "$CID" >/dev/null
ACTUAL_VERSION=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['version'])" "$RELEASE_TMP")
ACTUAL_SHA=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['git_sha'])" "$RELEASE_TMP")
rm -f "$RELEASE_TMP"
if [ "$ACTUAL_VERSION" != "$EXPECTED_VERSION" ]; then
    echo "❌ 镜像内 version=$ACTUAL_VERSION ≠ 请求 $EXPECTED_VERSION,拒绝部署"
    exit 1
fi
if [ -z "$ACTUAL_SHA" ]; then
    echo "❌ 镜像内 git_sha 为空,拒绝部署"
    exit 1
fi
echo "  ✅ 镜像身份: version=$ACTUAL_VERSION git_sha=$ACTUAL_SHA"

# ---------- [4/6] GPU 预检(基础设施不受影响,仅提示) ----------
echo "[4/6] GPU 预检..."
GPU_USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
echo "  GPU 已用: ${GPU_USED} MiB / 16384 MiB"
if [ "$GPU_USED" -gt 15000 ]; then
    echo "  ⚠️ GPU 显存 >15GB(共享服务占用高),继续但 sync 可能 OOM"
    echo "  若 OOM,降 EMBEDDER_BATCH_SIZE=8"
fi

# ---------- [5/6] 更新 backend(健康轮询 + 运行时版本核验) ----------
echo "[5/6] 更新 backend ..."
docker compose -f "$COMPOSE_FILE" up -d backend
# BGE 模型加载 ~45s+(有界轮询,最长 180s);就绪后核验 /health 上报版本
HEALTH_OK=0
HEALTH_JSON=""
for _ in $(seq 1 36); do
    sleep 5
    HEALTH_JSON=$(curl -sf "http://localhost:${BACKEND_PORT}/health" 2>/dev/null || true)
    if [ -n "$HEALTH_JSON" ]; then
        HEALTH_OK=1
        break
    fi
done
if [ "$HEALTH_OK" -ne 1 ]; then
    echo "  ❌ backend 健康检查失败(localhost:${BACKEND_PORT}/health,等待 180s)"
    echo "  查日志:docker compose -f $COMPOSE_FILE logs backend"
    exit 1
fi
RUNTIME_VERSION=$(printf '%s' "$HEALTH_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin).get('version',''))")
if [ "$RUNTIME_VERSION" != "$EXPECTED_VERSION" ]; then
    echo "  ❌ 运行时 /health version=$RUNTIME_VERSION ≠ 镜像 $EXPECTED_VERSION(身份不一致,拒绝完成部署)"
    exit 1
fi
echo "  ✅ backend 健康,运行时 version=$RUNTIME_VERSION(与镜像一致)"

# ---------- [6/6] 更新 sync-cron + sync-executor(三服务同 tag)并一致性核验 ----------
echo "[6/6] 更新 sync-cron + sync-executor ..."
docker compose -f "$COMPOSE_FILE" up -d sync-cron sync-executor
for SVC in backend sync-cron sync-executor; do
    SVC_CID=$(docker compose -f "$COMPOSE_FILE" ps -q "$SVC")
    SVC_IMG=$(docker inspect --format '{{.Config.Image}}' "$SVC_CID")
    if [[ "$SVC_IMG" != *":$TAG" ]]; then
        echo "  ❌ $SVC 镜像 $SVC_IMG ≠ $TAG(发布身份不一致)"
        exit 1
    fi
    echo "  ✅ $SVC @ $SVC_IMG"
done

echo ""
echo "=== 部署完成:$TAG(version=$EXPECTED_VERSION,git_sha=$ACTUAL_SHA)==="
docker compose -f "$COMPOSE_FILE" ps
echo ""
echo "回滚:./deploy/prod/update.sh <上一个不可变版本 tag>(同一契约)"
echo "手动同步 / reindex(按需):"
echo "  docker compose -f $COMPOSE_FILE run --rm sync python scripts/sync.py            # 增量同步"
echo "  docker compose -f $COMPOSE_FILE run --rm sync python scripts/sync.py --reindex  # ⚠️ 删 collection 全量重灌"
echo ""
echo "查看日志:docker compose -f $COMPOSE_FILE logs -f backend"
