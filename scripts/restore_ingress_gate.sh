#!/usr/bin/env bash
# G3 恢复入口门禁:历史备份恢复实例在开放 Widget/API 入口前的强制核验。
#
# 语义:任一检查失败 => DENY(退出 1);全部通过 => ALLOW(退出 0);参数/环境错误 => 2。
# 检查项(全部通过才 ALLOW):
#   G1 可达性  PostgreSQL pg_control_system 可读(不可读 => DENY unreachable-pg)
#   G2 可达性  Weaviate Aggregate 可读(不可读 => DENY unreachable-weaviate)
#   G3 身份    若给定 --expect-sid,则必须与实例 system_identifier 精确一致
#   G4 PG 残留 两注销上传来源(knowledge-support-cases / knowledge-cb70f5ae)的
#              documents/versions/chunks 严格字面前缀计数必须全零
#   G5 WV 残留 weaviate Document 中 source_type=filesystem 对象数必须为 0
#   G6 注册    两来源不得存在 enabled=true 且 lifecycle_state<>'retired' 的行
#   G7 共享层  *legacy* generation 必须存在(>=1),否则判定共享层被误删
# 本脚本只读;删除/注销属独立授权程序(见 docs/operations/restore-with-g3-gate.md)。
#
# 用法:
#   scripts/restore_ingress_gate.sh --pg-container <c> --weaviate-url <url>
#     [--pg-user <u>] [--pg-db <d>] [--expect-sid <sid>] [--receipt <file>]
set -euo pipefail

PG_CONTAINER="" PG_USER="ask_ai" PG_DB="ask_ai" WV_URL="" EXPECT_SID="" RECEIPT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --pg-container) PG_CONTAINER="$2"; shift 2 ;;
    --pg-user) PG_USER="$2"; shift 2 ;;
    --pg-db) PG_DB="$2"; shift 2 ;;
    --weaviate-url) WV_URL="$2"; shift 2 ;;
    --expect-sid) EXPECT_SID="$2"; shift 2 ;;
    --receipt) RECEIPT="$2"; shift 2 ;;
    *) echo "UNKNOWN_ARG: $1" >&2; exit 2 ;;
  esac
done
[ -n "$PG_CONTAINER" ] && [ -n "$WV_URL" ] || { echo "usage: --pg-container 与 --weaviate-url 必填" >&2; exit 2; }

# 注销来源冻结清单(G3 范围;新增注销来源须修订本清单并重审)
SRC_A="knowledge-support-cases"; SRC_A_PLEN=$(( ${#SRC_A} + 1 ))
SRC_B="knowledge-cb70f5ae";      SRC_B_PLEN=$(( ${#SRC_B} + 1 ))

verdict() { # $1=DENY|ALLOW $2=reason(ALLOW 可省)
  local reason="${2:-ok}"
  local ts; ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  echo "VERDICT: $1 reason=$reason"
  if [ -n "$RECEIPT" ]; then
    mkdir -p "$(dirname "$RECEIPT")"
    printf '{"ts":"%s","verdict":"%s","reason":"%s","sid":"%s","docs":%s,"versions":%s,"chunks":%s,"kc_versions":%s,"wv_filesystem":%s,"active_regs":%s,"legacy_gens":%s}\n' \
      "$ts" "$1" "$reason" "${SID:-null}" "${D:--1}" "${V:--1}" "${CH:--1}" "${KC:--1}" "${WVFS:--1}" "${REGS:--1}" "${LG:--1}" >> "$RECEIPT"
  fi
  [ "$1" = "ALLOW" ]
}

q() { docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -tA -v ON_ERROR_STOP=1 -c "$1" 2>/dev/null; }

# G1 可达性
SID=$(q "SELECT system_identifier FROM pg_control_system();") || { verdict DENY unreachable-pg >&2; exit 1; }
[ -n "$SID" ] || { verdict DENY unreachable-pg >&2; exit 1; }
# G2/G5 Weaviate
WVFS=$(curl -fsS -m 10 "$WV_URL/v1/graphql" -H "Content-Type: application/json" \
  --data-binary '{"query":"{Aggregate{Document(groupBy:\"source_type\"){groupedBy{value} meta{count}}}}"}' 2>/dev/null \
  | python3 -c 'import json,sys
d=json.load(sys.stdin)["data"]["Aggregate"]["Document"]
print(sum(x["meta"]["count"] for x in d if x["groupedBy"]["value"]=="filesystem"))' 2>/dev/null) || { verdict DENY unreachable-weaviate >&2; exit 1; }
[ -n "$WVFS" ] || { verdict DENY unreachable-weaviate >&2; exit 1; }
[ "$WVFS" = "0" ] || { verdict DENY "residue-weaviate filesystem_objects=$WVFS" >&2; exit 1; }

# G3 身份
if [ -n "$EXPECT_SID" ] && [ "$SID" != "$EXPECT_SID" ]; then
  verdict DENY "identity-mismatch sid=$SID expected=$EXPECT_SID" >&2; exit 1
fi
# G4 PG 残留(严格字面前缀,%/_ 为字面字符)
D=$(q "SELECT count(*) FROM documents WHERE left(source_id, $SRC_A_PLEN) = '$SRC_A' || '/';") || { verdict DENY unreachable-pg >&2; exit 1; }
V=$(q "SELECT count(*) FROM document_versions WHERE left(source_id, $SRC_A_PLEN) = '$SRC_A' || '/';") || { verdict DENY unreachable-pg >&2; exit 1; }
CH=$(q "SELECT count(*) FROM document_version_chunks c WHERE EXISTS (SELECT 1 FROM document_versions v WHERE v.id = c.version_id AND left(v.source_id, $SRC_A_PLEN) = '$SRC_A' || '/');") || { verdict DENY unreachable-pg >&2; exit 1; }
KC=$(q "SELECT count(*) FROM document_versions WHERE left(source_id, $SRC_B_PLEN) = '$SRC_B' || '/';") || { verdict DENY unreachable-pg >&2; exit 1; }
if [ "$D" != "0" ] || [ "$V" != "0" ] || [ "$CH" != "0" ] || [ "$KC" != "0" ]; then
  verdict DENY "residue-pg docs=$D versions=$V chunks=$CH kc=$KC" >&2; exit 1
fi
# G6 注册(仅 enabled 且未退役的行阻止)
REGS=$(( $(q "SELECT count(*) FROM data_sources WHERE id='$SRC_A' AND enabled=true AND coalesce(lifecycle_state,'active')<>'retired';") + \
          $(q "SELECT count(*) FROM data_sources WHERE id='$SRC_B' AND enabled=true AND coalesce(lifecycle_state,'active')<>'retired';") ))
[ "$REGS" = "0" ] || { verdict DENY "registration-active count=$REGS" >&2; exit 1; }
# G7 共享层
LG=$(q "SELECT count(*) FROM index_generations WHERE source_id='*legacy*';") || { verdict DENY unreachable-pg >&2; exit 1; }
[ "${LG:-0}" -ge 1 ] || { verdict DENY "legacy-missing(共享 generation 缺失,疑误删)" >&2; exit 1; }
verdict ALLOW
