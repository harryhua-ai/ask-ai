#!/usr/bin/env bash
# 阶段⑨ AC6 真实容器生命周期验收(Planner PARTIAL 修正)。
#
# 证明:backend 容器 `restart` 与 `up -d --force-recreate` 两种真实
# Docker 生命周期操作,都不终止独立 sync-executor 容器上进行中的同步;
# backend 恢复后 /health 正常;无重复启动;执行面容器自身零重启。
#
# 取证注意(macOS Docker Desktop 绑定挂载对容器新建文件存在宿主侧
# 可见性滞后):所有平面内断言一律经 `docker compose exec` 在容器内
# 完成,不经宿主路径轮询。
#
# 用法:bash scripts/dev/syncexec_lifecycle/run_acceptance.sh
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d /tmp/syncexec-lifecycle.XXXXXX)"
cp "$SRC/docker-compose.yml" "$WORK/"
mkdir -p "$WORK/plane"
cp "$SRC/backend_stub.py" "$SRC/executor_loop.py" "$SRC/sync_runner.py" "$WORK/plane/"
cd "$WORK"

EXECUTOR=syncexec-lifecycle-sync-executor-1
HEALTH=http://localhost:18001/health
PASS=0
FAIL=0

cleanup() { docker compose down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

say() { echo ""; echo "=== $1 ==="; }
ok() { echo "[PASS] $1"; PASS=$((PASS+1)); }
bad() { echo "[FAIL] $1"; FAIL=$((FAIL+1)); }
executor_logs() { docker compose logs sync-executor 2>&1 | tail -15; }
in_executor() { docker compose exec -T sync-executor sh -c "$1"; }
wait_health() { # $1=标签
  for _ in $(seq 1 30); do
    if curl -sf "$HEALTH" >/dev/null 2>&1; then echo "[health] $1 → 200"; return 0; fi
    sleep 1
  done
  echo "[health] $1 → 仍未恢复"; return 1
}
lines() { in_executor "wc -l < '$1' 2>/dev/null" | tr -d '[:space:]'; }
executor_started_at() {
  docker inspect --format '{{.State.StartedAt}}' "$EXECUTOR"
}

say "0. 起栈(python:3.11-slim × 2:backend 触发面 + sync-executor 执行面)"
docker compose up -d
wait_health "初启"
for _ in $(seq 1 20); do
  if docker compose logs sync-executor 2>&1 | grep -q "plane up"; then break; fi
  sleep 1
done
if docker compose logs sync-executor 2>&1 | grep -q "plane up"; then
  echo "[executor] 执行面已就绪(plane up)"
else
  echo "[executor] 执行面未就绪,最近日志:"; executor_logs
  bad "执行面启动失败"
  exit 1
fi

say "1. 触发一次同步(backend 只写持久交接,立即 202)"
TRIG=$(curl -sf -XPOST http://localhost:18001/trigger)
echo "trigger → $TRIG"
echo "$TRIG" | grep -q '"accepted"' && ok "触发返回 accepted(accepted≠完成)" || bad "触发未返回 accepted"
RID=$(echo "$TRIG" | sed -E 's/.*"id": *([0-9]+).*/\1/')
LOG="/plane/running/run-$RID.log"

say "2. 等待执行面领用并启动长跑 runner(~20s)"
for _ in $(seq 1 30); do
  if in_executor "test -f '$LOG'" >/dev/null 2>&1; then break; fi
  sleep 1
done
if in_executor "test -f '$LOG'" >/dev/null 2>&1; then
  ok "runner 已在执行面启动(执行面内可见心跳文件)"
else
  executor_logs
  bad "runner 未启动"
  exit 1
fi
N1=$(lines "$LOG"); echo "runner 心跳行数:$N1"

BEFORE_RESTART=$(executor_started_at)
echo "executor StartedAt(前): $BEFORE_RESTART"

say "3. 真实 Docker 生命周期操作 A:docker compose restart backend"
docker compose restart backend
wait_health "restart backend 后"
sleep 3
N2=$(lines "$LOG")
echo "runner 心跳行数:$N2(重启前 $N1)"
if [ "${N2:-0}" -gt "${N1:-0}" ]; then ok "backend 容器 restart 期间同步继续推进"; else bad "同步在 restart 后停滞"; fi
AFTER_RESTART=$(executor_started_at)
if [ "$AFTER_RESTART" = "$BEFORE_RESTART" ]; then ok "执行面容器未被波及(StartedAt 不变)"; else bad "执行面容器被重启"; fi

say "4. 真实 Docker 生命周期操作 B:docker compose up -d --force-recreate backend"
docker compose up -d --force-recreate backend >/dev/null
wait_health "force-recreate backend 后"
sleep 3
N3=$(lines "$LOG")
echo "runner 心跳行数:$N3(上一次检查 $N2)"
if [ "${N3:-0}" -gt "${N2:-0}" ]; then ok "backend 容器重建期间同步继续推进"; else bad "同步在 recreate 后停滞"; fi
AFTER_RECREATE=$(executor_started_at)
if [ "$AFTER_RECREATE" = "$BEFORE_RESTART" ]; then ok "执行面容器仍未被波及(StartedAt 不变)"; else bad "执行面容器被重启(recreate)"; fi

say "5. 等 runner 自然跑完,核对结果唯一性与退出码(容器内取证)"
RESULT_JSON="/plane/results/result-$RID.json"
for _ in $(seq 1 40); do
  if in_executor "test -f '$RESULT_JSON'" >/dev/null 2>&1; then break; fi
  sleep 1
done
if in_executor "test -f '$RESULT_JSON'" >/dev/null 2>&1; then
  RESULT=$(in_executor "cat '$RESULT_JSON'")
  echo "result → $RESULT"
  echo "$RESULT" | grep -q '"exit_code": *0' && ok "同步正常结束(exit_code=0)" || bad "同步异常结束"
else
  executor_logs
  bad "同步未在时限内结束"
fi
NRES=$(in_executor "ls /plane/results/ | wc -l" | tr -d '[:space:]')
echo "结果数(容器内):$NRES"
if [ "${NRES:-0}" = "1" ]; then ok "backend 两次重启均未导致重复启动(结果仅 1 份)"; else bad "出现重复启动/结果数异常"; fi

say "6. 最终 /health"
curl -sf "$HEALTH" >/dev/null && ok "backend /health 正常" || bad "backend /health 异常"

echo ""
echo "================ ACCEPTANCE SUMMARY ================"
echo "PASS=$PASS FAIL=$FAIL"
if [ "$FAIL" = "0" ]; then echo "AC6 CONTAINER-LIFECYCLE ACCEPTANCE: PASS"; else echo "AC6 CONTAINER-LIFECYCLE ACCEPTANCE: FAIL"; fi
exit "$FAIL"
