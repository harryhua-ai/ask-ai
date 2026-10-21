#!/usr/bin/env bash
# 正式受控恢复流程:历史备份 → 隔离/DR 目标 → G3 门禁 → (且仅当 ALLOW)开放入口。
#
# 强制语义:
#   1. 恢复目标默认视为隔离实例;目标为生产集群(SID=生产钉值)时必须显式
#      --target-is-production-dr,否则 DENY identity-target(防误指生产)。
#   2. 入口默认关闭:本流程在门禁 ALLOW 前不启动、不重建任何应用容器;
#      门禁 DENY 时主动停止 --app-service(若在运行),保证对外入口关闭。
#   3. --start-app-cmd 给出环境正确的启动命令;流程在 ALLOW 后重跑一次门禁
#      (防 TOCTOU),仍 ALLOW 才执行启动命令;启动后探测 /health。
#   4. 任何失败/超时/身份不符/证据缺失 => 非零退出且入口保持关闭。
#   5. dump 原件只读:先记录 sha256,恢复用副本语义读取,不写回原路径。
#
# 用法:
#   scripts/controlled_restore.sh --pg-container <c> --dump <file> \
#     --weaviate-url <url> --app-service <name> --start-app-cmd <cmd> \
#     [--app-compose-file <f>] [--pg-user <u>] [--pg-db <d>] [--expect-sid <sid>]
#     [--drop-schema] [--target-is-production-dr] [--receipt <file>] [--health-url <url>]
#   不给 --start-app-cmd 时,ALLOW 后保持入口关闭(仅打印状态),供继续离线核验。
set -euo pipefail

PG_CONTAINER="" PG_USER="ask_ai" PG_DB="ask_ai" DUMP="" WV_URL=""
APP_SERVICE="" APP_COMPOSE="" APP_COMPOSE_SERVICE="" START_CMD="" EXPECT_SID="" RECEIPT="" HEALTH_URL=""
DROP_SCHEMA="no" PROD_DR="no"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROD_SID_PIN="7670132346517975075"
while [ $# -gt 0 ]; do
  case "$1" in
    --pg-container) PG_CONTAINER="$2"; shift 2 ;;
    --pg-user) PG_USER="$2"; shift 2 ;;
    --pg-db) PG_DB="$2"; shift 2 ;;
    --dump) DUMP="$2"; shift 2 ;;
    --weaviate-url) WV_URL="$2"; shift 2 ;;
    --app-service) APP_SERVICE="$2"; shift 2 ;;
    --app-compose-service) APP_COMPOSE_SERVICE="$2"; shift 2 ;;
    --app-compose-file) APP_COMPOSE="$2"; shift 2 ;;
    --start-app-cmd) START_CMD="$2"; shift 2 ;;
    --expect-sid) EXPECT_SID="$2"; shift 2 ;;
    --receipt) RECEIPT="$2"; shift 2 ;;
    --health-url) HEALTH_URL="$2"; shift 2 ;;
    --drop-schema) DROP_SCHEMA="yes"; shift ;;
    --target-is-production-dr) PROD_DR="yes"; shift ;;
    *) echo "UNKNOWN_ARG: $1" >&2; exit 2 ;;
  esac
done
[ -n "$PG_CONTAINER" ] && [ -n "$DUMP" ] && [ -n "$WV_URL" ] && [ -n "$APP_SERVICE" ] || \
  { echo "usage: --pg-container/--dump/--weaviate-url/--app-service 必填" >&2; exit 2; }
[ -f "$DUMP" ] || { echo "ABORT: dump 不存在: $DUMP" >&2; exit 2; }

log(){ echo "[restore] $*"; }
stop_entrance(){
  if [ -n "$APP_COMPOSE" ]; then
    docker compose -f "$APP_COMPOSE" stop "${APP_COMPOSE_SERVICE:-$APP_SERVICE}" >/dev/null 2>&1 || true
  fi
  docker stop "$APP_SERVICE" >/dev/null 2>&1 || true
}
compose_up(){
  if [ -n "$APP_COMPOSE" ]; then
    docker compose -f "$APP_COMPOSE" up -d "${APP_COMPOSE_SERVICE:-$APP_SERVICE}"
  else
    docker start "$APP_SERVICE" >/dev/null
  fi
}
gate(){ # 复用正式门禁;任何 DENY => 停入口 + 回执 + 退出 1
  local args=(--pg-container "$PG_CONTAINER" --pg-user "$PG_USER" --pg-db "$PG_DB" --weaviate-url "$WV_URL")
  [ -n "$EXPECT_SID" ] && args+=(--expect-sid "$EXPECT_SID")
  [ -n "$RECEIPT" ] && args+=(--receipt "$RECEIPT")
  if ! "$REPO_ROOT/scripts/restore_ingress_gate.sh" "${args[@]}"; then
    log "GATE=DENY -> 强制关闭入口($APP_SERVICE)并停止;不进入开放流程"
    stop_entrance
    exit 1
  fi
  log "GATE=ALLOW"
}

# S0 目标身份:防误指生产
ACT_SID=$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -tA -c "SELECT system_identifier FROM pg_control_system();" 2>/dev/null || echo "")
if [ "$ACT_SID" = "$PROD_SID_PIN" ] && [ "$PROD_DR" != "yes" ]; then
  log "GATE=DENY identity-target: 目标是生产集群 SID=$ACT_SID 但未显式 --target-is-production-dr"
  stop_entrance
  exit 1
fi
log "S0 target identity: SID=$ACT_SID prod_dr=$PROD_DR"

# S1 原件只读记录 + 恢复(dump sha256 先落日志,再恢复)
log "S1 dump sha256: $(shasum -a 256 "$DUMP" | awk '{print $1}')"
docker cp "$DUMP" "$PG_CONTAINER:/tmp/restore-in.dump" >/dev/null
if [ "$DROP_SCHEMA" = "yes" ]; then
  docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" >/dev/null
fi
docker exec "$PG_CONTAINER" sh -c "pg_restore -U $PG_USER -d $PG_DB --no-owner --role=$PG_USER /tmp/restore-in.dump 2>&1 | tail -2; rm -f /tmp/restore-in.dump"
log "S1 restore done"

# S2 门禁(恢复后立刻;DENY => 入口强制关闭)
gate

# S3 ALLOW 后才可能开放入口;启动前再跑一次门禁(防 TOCTOU)
if [ -n "$START_CMD" ]; then
  gate
  log "S3 opening entrance via start command"
  if [ -n "$APP_COMPOSE" ]; then
    compose_up
  else
    bash -c "$START_CMD" >/dev/null 2>&1 || docker start "$APP_SERVICE" >/dev/null
  fi
  if [ -n "$HEALTH_URL" ]; then
    OK=""
    for i in $(seq 1 30); do
      if curl -fsS -m 5 "$HEALTH_URL" >/dev/null 2>&1; then OK=yes; log "S3 /health OK after ${i}x5s"; break; fi
      sleep 5
    done
    [ -n "$OK" ] || { log "S3 /health 未就绪 => 关闭入口"; stop_entrance; exit 1; }
  fi
  log "DONE: entrance OPEN (gated)"
else
  log "DONE: ALLOW, entrance KEPT CLOSED (未给 --start-app-cmd)"
fi
