#!/usr/bin/env bash
# 正式受控恢复流程 v3:历史备份 → 分阶段恢复(attempt 状态屏障)→ G3 门禁 → 仅当 ALLOW+健康才开放入口。
#
# fail-closed 语义(A PR #187 审查要求):
#   F1 每个会修改数据的阶段(stage-restore-*)在首个 mutation 之前强制关闭入口并独立
#      探测确认(容器停止 + 无发布端口);EXIT/ERR/INT/TERM trap 在 ALLOW 确认前的任何
#      退出路径再次关闭;stage-status 为只读观察,不装 trap、不停任何服务。
#   F2 pg_restore 退出码显式捕获,失败即 FATAL,不因目标恰好干净而通过。
#   F3 attempt 状态屏障:stage-restore-pg 初始化 attempt(随机 token);历史状态文件
#      不可复用(非空即拒绝,除非 --new-attempt 显式重置);每个后续阶段记录携带同一
#      attempt id;stage-open 要求 attempt-init + 三阶段按序齐全、身份与存活实例一致。
#   F4 破坏性对象强身份绑定:weaviate 数据目录必须与指定容器的实际挂载源精确一致;
#      uploads manifest 生成失败即 FATAL(不吞错);stage-open 强制校验 uploads。
#   F5 目标=生产集群 SID 而未显式 --target-is-production-dr:任何阶段都拒绝。
#   F6 启动命令原样执行、无回退;--health-url 必填;OPEN 必须 /health 200 + 真实发布端口。
# 备份原件只读;残留清理为独立授权程序;stage-status 纯只读。
set -euo pipefail

STATE_FILE="" PG_CONTAINER="" PG_USER="ask_ai" PG_DB="ask_ai" EXPECT_SID=""
WV_URL="" WV_CONTAINER="" WV_EXPECT_HOSTNAME="" APP_SERVICE="" APP_COMPOSE="" APP_COMPOSE_SERVICE=""
RECEIPT="" PROD_DR="no" NEW_ATTEMPT="no"
DUMP="" DROP_SCHEMA="no" TGZ="" WV_DATA_DIR="" WIPE="no" UROOT="" USRC=""
START_CMD="" HEALTH_URL="" UGUARD=""
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROD_SID_PIN="7670132346517975075"
ENTRANCE_OPENED=0
BAIL_GUARD=0
SUBCMD=""

usage_err(){ echo "usage: $1" >&2; exit 2; }
[ $# -ge 1 ] || usage_err "用法: controlled_restore.sh <stage-restore-pg|stage-restore-weaviate|stage-restore-uploads|stage-open|stage-status> [参数]"
case "$1" in
  stage-restore-pg|stage-restore-weaviate|stage-restore-uploads|stage-open|stage-status) SUBCMD="$1"; shift ;;
  *) usage_err "未知阶段: $1" ;;
esac
while [ $# -gt 0 ]; do
  case "$1" in
    --state-file) STATE_FILE="$2"; shift 2 ;;
    --pg-container) PG_CONTAINER="$2"; shift 2 ;;
    --pg-user) PG_USER="$2"; shift 2 ;;
    --pg-db) PG_DB="$2"; shift 2 ;;
    --expect-sid) EXPECT_SID="$2"; shift 2 ;;
    --weaviate-url) WV_URL="$2"; shift 2 ;;
    --weaviate-container) WV_CONTAINER="$2"; shift 2 ;;
    --weaviate-expect-hostname) WV_EXPECT_HOSTNAME="$2"; shift 2 ;;
    --app-service) APP_SERVICE="$2"; shift 2 ;;
    --app-compose-file) APP_COMPOSE="$2"; shift 2 ;;
    --app-compose-service) APP_COMPOSE_SERVICE="$2"; shift 2 ;;
    --receipt) RECEIPT="$2"; shift 2 ;;
    --target-is-production-dr) PROD_DR="yes"; shift ;;
    --new-attempt) NEW_ATTEMPT="yes"; shift ;;
    --dump) DUMP="$2"; shift 2 ;;
    --drop-schema) DROP_SCHEMA="yes"; shift ;;
    --weaviate-backup) TGZ="$2"; shift 2 ;;
    --weaviate-data-dir) WV_DATA_DIR="$2"; shift 2 ;;
    --i-know-this-wipes-weaviate-volume) WIPE="yes"; shift ;;
    --uploads-root) UROOT="$2"; shift 2 ;;
    --uploads-src) USRC="$2"; shift 2 ;;
    --start-cmd) START_CMD="$2"; shift 2 ;;
    --health-url) HEALTH_URL="$2"; shift 2 ;;
    --uploads-guard) UGUARD="$2"; shift 2 ;;
    *) usage_err "未知参数: $1" ;;
  esac
done
[ -n "$STATE_FILE" ] && [ -n "$PG_CONTAINER" ] && [ -n "$EXPECT_SID" ] && \
[ -n "$WV_URL" ] && [ -n "$WV_CONTAINER" ] && [ -n "$WV_EXPECT_HOSTNAME" ] && [ -n "$APP_SERVICE" ] || \
  usage_err "--state-file/--pg-container/--expect-sid/--weaviate-url/--weaviate-container/--weaviate-expect-hostname/--app-service 必填"

log(){ echo "[restore:$SUBCMD] $*"; }
arm_bail_guard(){ BAIL_GUARD=1; trap on_bail EXIT ERR INT TERM; }
disarm_bail_guard(){ trap - EXIT ERR INT TERM; BAIL_GUARD=0; }
stop_entrance(){
  if [ -n "$APP_COMPOSE" ]; then
    docker compose -f "$APP_COMPOSE" stop "${APP_COMPOSE_SERVICE:-$APP_SERVICE}" >/dev/null 2>&1 || true
  fi
  docker stop "$APP_SERVICE" >/dev/null 2>&1 || true
  local running; running=$(docker inspect -f '{{.State.Running}}' "$APP_SERVICE" 2>/dev/null || echo "absent")
  if [ "$running" = "true" ]; then log "CRITICAL: 入口容器 stop 后仍在运行,需人工处置"; return 1; fi
  log "entrance closed: $APP_SERVICE not running"
  return 0
}
verify_entrance_closed(){ # 独立探测:容器未运行且无发布端口
  local running ports
  running=$(docker inspect -f '{{.State.Running}}' "$APP_SERVICE" 2>/dev/null || echo "absent")
  [ "$running" != "true" ] || { log "DENY: 入口容器仍在运行,无法确认关闭"; return 1; }
  ports=$(docker port "$APP_SERVICE" 2>/dev/null || true)
  [ -z "$ports" ] || { log "DENY: 入口容器仍存在发布端口: $ports"; return 1; }
  log "entrance verified closed (not running, no published ports)"
  return 0
}
close_entrance_for_mutation(){ # 所有数据 mutation 前强制调用
  stop_entrance || return 1
  verify_entrance_closed || return 1
}
on_bail(){
  local rc=$?
  trap - EXIT ERR INT TERM
  if [ "$BAIL_GUARD" = "1" ] && [ "$ENTRANCE_OPENED" != "1" ]; then
    log "bail(rc=$rc): 恢复未完成 => 强制关闭入口"
    stop_entrance || true
    verify_entrance_closed || true
  fi
  exit $rc
}
pg(){ docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -tA -v ON_ERROR_STOP=1 "$@"; }
live_sid(){ pg -c "SELECT system_identifier FROM pg_control_system();" 2>/dev/null || echo "unreachable"; }
wv_host(){ docker exec "$WV_CONTAINER" printenv CLUSTER_HOSTNAME 2>/dev/null || echo "unreadable"; }
identity_check(){ # 每阶段重读存活身份;生产 SID 未显式 DR 一律拒绝
  local s h
  s=$(live_sid)
  [ "$s" = "$EXPECT_SID" ] || { log "ABORT: SID 漂移 live=$s expected=$EXPECT_SID"; return 1; }
  if [ "$s" = "$PROD_SID_PIN" ] && [ "$PROD_DR" != "yes" ]; then
    log "ABORT: 目标是生产集群 SID=$s 而未显式 --target-is-production-dr"; return 1
  fi
  h=$(wv_host)
  [ "$h" = "$WV_EXPECT_HOSTNAME" ] || { log "ABORT: Weaviate 身份漂移 live=$h expected=$WV_EXPECT_HOSTNAME"; return 1; }
  return 0
}
state_put(){ # $1=stage $2=payload(不含花括号);自动携带 attempt id
  local ts; ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  printf '{"stage":"%s","ts":"%s","attempt_id":"%s",%s}\n' "$1" "$ts" "$ATTEMPT_ID" "$2" >> "$STATE_FILE"
  log "state += $1"
}
attempt_id_from_state(){
  sed -n 's/.*"stage":"attempt-init".*"attempt_id":"\([0-9a-f-]*\)".*/\1/p' "$STATE_FILE" | head -1
}
stage_done_in_order(){ # $1=stage:仅统计当前 attempt 的该阶段成功记录
  [ -n "$ATTEMPT_ID" ] && grep -q "\"stage\":\"$1\".*\"attempt_id\":\"$ATTEMPT_ID\"" "$STATE_FILE"
}
compose_up(){ if [ -n "$APP_COMPOSE" ]; then docker compose -f "$APP_COMPOSE" up -d "${APP_COMPOSE_SERVICE:-$APP_SERVICE}"; else docker start "$APP_SERVICE" >/dev/null; fi; }

case "$SUBCMD" in
  stage-status)
    echo "== state file: $STATE_FILE(只读观察,不触碰任何服务)=="
    if [ -f "$STATE_FILE" ]; then cat "$STATE_FILE"; else echo "(empty/absent)"; fi
    exit 0 ;;

  stage-restore-pg)
    [ -n "$DUMP" ] && [ -f "$DUMP" ] || usage_err "stage-restore-pg 需要 --dump <存在的文件>"
    arm_bail_guard                      # 数据修改阶段:启用失败关闭守护
    # attempt 屏障:非空历史状态不可复用;重置必须显式 --new-attempt
    if [ -s "$STATE_FILE" ]; then
      if [ "$NEW_ATTEMPT" = "yes" ]; then
        : > "$STATE_FILE"; log "attempt reset(--new-attempt): 状态文件已清空"
      else
        log "DENY: 状态文件非空(历史 attempt);重置必须显式 --new-attempt"; stop_entrance; exit 1
      fi
    fi
    identity_check || { stop_entrance; exit 1; }
    arm_bail_guard
    LIVE_SID=$(live_sid)
    ATTEMPT_ID=$(python3 -c 'import uuid; print(uuid.uuid4())')
    state_put "attempt-init" "\"sid\":\"$LIVE_SID\",\"hostname\":\"$WV_EXPECT_HOSTNAME\",\"dump_sha256\":\"$(shasum -a 256 "$DUMP" | awk '{print $1}')\""
    # mutation 前强制关闭入口并独立确认
    close_entrance_for_mutation || exit 1
    docker cp "$DUMP" "$PG_CONTAINER:/tmp/restore-in.dump" >/dev/null
    if [ "$DROP_SCHEMA" = "yes" ]; then
      docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" >/dev/null
    fi
    set +e
    docker exec "$PG_CONTAINER" sh -c "pg_restore -U $PG_USER -d $PG_DB --no-owner --role=$PG_USER /tmp/restore-in.dump > /tmp/restore.log 2>&1"
    PRC=$?
    docker exec "$PG_CONTAINER" sh -c "tail -3 /tmp/restore.log; rm -f /tmp/restore.log /tmp/restore-in.dump"
    set -e
    [ "$PRC" = "0" ] || { log "FATAL: pg_restore 退出码=$PRC(失败不被掩盖)=> 保持关闭"; exit 1; }
    PROV=$(pg -c "SELECT (SELECT count(*) FROM documents)||' docs, '||(SELECT count(*) FROM document_versions)||' vers, '||(SELECT count(*) FROM document_version_chunks)||' chunks';")
    log "provenance: restored totals = $PROV"
    state_put "restore-pg" "\"sid\":\"$LIVE_SID\",\"provenance\":\"$PROV\""
    disarm_bail_guard
    log "stage-restore-pg complete(恢复成功;入口保持关闭;清理为独立授权程序)"
    ;;

  stage-restore-weaviate)
    [ -n "$TGZ" ] && [ -f "$TGZ" ] && [ -n "$WV_DATA_DIR" ] || usage_err "stage-restore-weaviate 需要 --weaviate-backup/--weaviate-data-dir(容器实际挂载的数据目录)"
    [ "$WIPE" = "yes" ] || usage_err "该阶段会清空 weaviate 数据目录,必须显式 --i-know-this-wipes-weaviate-volume"
    arm_bail_guard
    identity_check || { stop_entrance; exit 1; }
    ATTEMPT_ID=$(attempt_id_from_state)
    [ -n "$ATTEMPT_ID" ] || { log "DENY: 无 attempt-init(先运行 stage-restore-pg)=> 保持关闭"; stop_entrance; exit 1; }
    stage_done_in_order "restore-pg" || { log "DENY: stage-incomplete(restore-pg 须先完成)=> 保持关闭"; stop_entrance; exit 1; }
    # F4: 数据目录强身份绑定 —— 必须是指定 weaviate 容器 /var/lib/weaviate 的实际挂载源
    ACTUAL_DIR=$(docker inspect "$WV_CONTAINER" --format '{{range .Mounts}}{{if eq .Destination "/var/lib/weaviate"}}{{.Source}}{{end}}{{end}}')
    [ -n "$ACTUAL_DIR" ] || { log "DENY: 容器 $WV_CONTAINER 未挂载 /var/lib/weaviate,无法绑定数据目录"; stop_entrance; exit 1; }
    [ "$ACTUAL_DIR" = "$WV_DATA_DIR" ] || { log "DENY: --weaviate-data-dir '$WV_DATA_DIR' != 容器实际挂载 '$ACTUAL_DIR'"; stop_entrance; exit 1; }
    # mutation 前强制关闭入口
    close_entrance_for_mutation || exit 1
    BSHA=$(shasum -a 256 "$TGZ" | awk '{print $1}')
    log "backup tgz sha256=$BSHA(原件只读)"
    docker stop "$WV_CONTAINER" >/dev/null
    docker run --rm -v "$WV_DATA_DIR":/wipe -v "$(cd "$(dirname "$TGZ")" && pwd)"/"$(basename "$TGZ")":/backup.tgz:ro alpine sh -c \
      "find /wipe -mindepth 1 -maxdepth 1 -exec rm -rf {} + && tar xzf /backup.tgz -C /wipe && find /wipe -name '._*' -type f -delete" >/dev/null
    docker start "$WV_CONTAINER" >/dev/null
    for i in $(seq 1 30); do curl -fsS -m 3 "$WV_URL/v1/meta" >/dev/null 2>&1 && break; sleep 2; done
    identity_check || exit 1
    TOTAL=""
    for i in $(seq 1 60); do
      TOTAL=$(curl -fsS -m 10 "$WV_URL/v1/graphql" -H "Content-Type: application/json" \
        --data-binary '{"query":"{Aggregate{Document{meta{count}}}}"}' 2>/dev/null \
        | python3 -c 'import json,sys
try: print(json.load(sys.stdin)["data"]["Aggregate"]["Document"][0]["meta"]["count"])
except Exception: print("")' 2>/dev/null) || true
      [ -n "$TOTAL" ] && break
      sleep 5
    done
    [ -n "$TOTAL" ] || { log "FATAL: weaviate 索引未在超时内就绪 => 保持关闭"; exit 1; }
    log "weaviate restored: total objects=$TOTAL"
    state_put "restore-weaviate" "\"hostname\":\"$WV_EXPECT_HOSTNAME\",\"backup_sha256\":\"$BSHA\",\"objects\":$TOTAL"
    disarm_bail_guard
    ;;

  stage-restore-uploads)
    [ -n "$UROOT" ] && [ -d "$UROOT" ] || usage_err "stage-restore-uploads 需要 --uploads-root <存在的宿主目录>"
    [ -n "$USRC" ] && [ -d "$USRC" ] || usage_err "stage-restore-uploads 需要 --uploads-src <已确认归属的副本目录>"
    arm_bail_guard
    identity_check || { stop_entrance; exit 1; }
    ATTEMPT_ID=$(attempt_id_from_state)
    [ -n "$ATTEMPT_ID" ] || { log "DENY: 无 attempt-init(先运行 stage-restore-pg)=> 保持关闭"; stop_entrance; exit 1; }
    stage_done_in_order "restore-pg" || { log "DENY: stage-incomplete(restore-pg 须先完成)=> 保持关闭"; stop_entrance; exit 1; }
    close_entrance_for_mutation || exit 1
    cp -a "$USRC"/. "$UROOT"/
    MANIFEST="$UROOT/../uploads-manifest.sha256"
    (cd "$UROOT" && find . -type f -print0 | sort -z | xargs -0 shasum -a 256 > "$MANIFEST")   # 失败即 FATAL(无 || true)
    NF=$(find "$UROOT" -type f | wc -l | tr -d ' ')
    log "uploads restored: files=$NF manifest=$MANIFEST"
    state_put "restore-uploads" "\"root\":\"$UROOT\",\"files\":$NF"
    disarm_bail_guard
    ;;

  stage-open)
    # R1-A:stage-open 是入口裁决事务——入口必须先关闭并独立确认;
    # 此后任何失败路径(参数/身份/阶段/门禁/启动/健康/中断)都保持关闭。
    stop_entrance || true
    verify_entrance_closed || exit 1
    arm_bail_guard
    [ -n "$START_CMD" ] || { log "DENY: 缺 --start-cmd"; exit 1; }
    [ -n "$HEALTH_URL" ] || { log "DENY: 缺 --health-url"; exit 1; }
    [ -n "$UROOT" ] || { log "DENY: 缺 --uploads-root(强制验真 uploads)"; exit 1; }
    [ -n "$UGUARD" ] || { log "DENY: 缺 --uploads-guard(UNKNOWN 守卫清单)"; exit 1; }
    [ -f "$STATE_FILE" ] && [ -s "$STATE_FILE" ] || { log "DENY: 状态文件为空/缺失 => 保持关闭"; exit 1; }
    ATTEMPT_ID=$(attempt_id_from_state)
    [ -n "$ATTEMPT_ID" ] || { log "DENY: 无 attempt-init(状态文件不可复用)=> 保持关闭"; exit 1; }
    identity_check || exit 1
    for stg in restore-pg restore-weaviate restore-uploads; do
      stage_done_in_order "$stg" || { log "DENY: stage-incomplete($stg 在当前 attempt 无记录)=> 保持关闭"; exit 1; }
    done
    # R1-B:uploads 绑定 —— open 检查目录必须等于本 attempt 实际恢复的目录
    RESTORED_ROOT=$(sed -n "s/.*\"stage\":\"restore-uploads\".*\"root\":\"\([^\"]*\)\".*/\1/p" "$STATE_FILE" | tail -1)
    [ -n "$RESTORED_ROOT" ] || { log "DENY: 状态无 restore-uploads root"; exit 1; }
    [ "$UROOT" = "$RESTORED_ROOT" ] || { log "DENY: uploads-root-mismatch open=$UROOT restored=$RESTORED_ROOT(禁止以未恢复目录充当受检对象)"; exit 1; }
    # 门禁(两连,防 TOCTOU);任何 DENY => 入口强制关闭
    GARGS=(--pg-container "$PG_CONTAINER" --pg-user "$PG_USER" --pg-db "$PG_DB" --expect-sid "$EXPECT_SID" \
           --weaviate-url "$WV_URL" --weaviate-container "$WV_CONTAINER" --weaviate-expect-hostname "$WV_EXPECT_HOSTNAME" \
           --uploads-root "$UROOT" --uploads-guard "$UGUARD")
    [ -n "$RECEIPT" ] && GARGS+=(--receipt "$RECEIPT")
    "$REPO_ROOT/scripts/restore_ingress_gate.sh" "${GARGS[@]}" || { stop_entrance; exit 1; }
    "$REPO_ROOT/scripts/restore_ingress_gate.sh" "${GARGS[@]}" || { stop_entrance; exit 1; }
    log "opening entrance"
    if ! bash -c "$START_CMD"; then
      log "FATAL: 启动命令失败 => 关闭入口"; stop_entrance; exit 1
    fi
    HOK=""
    for i in $(seq 1 30); do
      curl -fsS -m 5 "$HEALTH_URL" >/dev/null 2>&1 && { HOK=yes; log "/health OK after ${i}x5s"; break; }
      sleep 5
    done
    [ -n "$HOK" ] || { log "FATAL: /health 未就绪 => 关闭入口"; stop_entrance; exit 1; }
    PORTS=$(docker port "$APP_SERVICE" 2>/dev/null || true)
    [ -n "$PORTS" ] || { log "FATAL: 无真实发布端口 => 关闭入口"; stop_entrance; exit 1; }
    log "real listener: $PORTS"
    ENTRANCE_OPENED=1
    disarm_bail_guard
    state_put "open" "\"health_url\":\"$HEALTH_URL\""
    log "DONE: entrance OPEN (gated, health-verified, real listener confirmed)"
    ;;

  *) usage_err "未知子命令" ;;
esac
