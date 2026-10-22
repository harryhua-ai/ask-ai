#!/usr/bin/env bash
# G3 恢复入口门禁 v2:历史备份恢复实例在开放 Widget/API 入口前的强制核验。
#
# 语义:任何探针失败/残留非零/身份不符 => DENY(退出 1,原因写入回执);
#       全部通过 => ALLOW(退出 0);参数/环境错误 => 2。本脚本只读。
# 检查项(全部通过才 ALLOW;每次查询失败都 DENY,不吞错):
#   G1 可达性      PostgreSQL pg_control_system 可读
#   G2 身份        system_identifier == --expect-sid(必填)
#   G3 可达性      Weaviate /v1/graphql Aggregate 可读
#   G4 WV 实例身份 容器 env CLUSTER_HOSTNAME == --weaviate-expect-hostname(必填)
#   G5 PG 残留     两注销来源各自 documents/versions/chunks 严格字面前缀计数=0
#   G6 专属 generations 两注销来源名下 index_generations=0
#   G7 外部引用   引用两注销来源 generations 的外部版本=0
#   G8 注册       两来源无 enabled 且 lifecycle_state<>'retired' 的行
#   G9 重入        两来源无未终态 sync_requests(非 done/completed/failed/cancelled/skipped)
#   G10 WV 残留   source_type=filesystem 对象数=0
#   G11 共享层    *legacy* generation 存在(>=1)
#   G12 uploads   给定 --uploads-root 时:两注销来源目录内文件必须全部属于
#                 --uploads-guard 清单(sha256 匹配);未给 --uploads-root 时记 skipped
#
# 用法:
#   scripts/restore_ingress_gate.sh --pg-container <c> --expect-sid <sid> \
#     --weaviate-url <url> --weaviate-container <c> --weaviate-expect-hostname <h> \
#     [--pg-user <u>] [--pg-db <d>] [--uploads-root <dir>] [--uploads-guard <tsv>] \
#     [--receipt <file>]
set -euo pipefail

PG_CONTAINER="" PG_USER="ask_ai" PG_DB="ask_ai" EXPECT_SID=""
WV_URL="" WV_CONTAINER="" WV_EXPECT_HOSTNAME=""
UPLOADS_ROOT="" UPLOADS_GUARD="" RECEIPT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --pg-container) PG_CONTAINER="$2"; shift 2 ;;
    --pg-user) PG_USER="$2"; shift 2 ;;
    --pg-db) PG_DB="$2"; shift 2 ;;
    --expect-sid) EXPECT_SID="$2"; shift 2 ;;
    --weaviate-url) WV_URL="$2"; shift 2 ;;
    --weaviate-container) WV_CONTAINER="$2"; shift 2 ;;
    --weaviate-expect-hostname) WV_EXPECT_HOSTNAME="$2"; shift 2 ;;
    --uploads-root) UPLOADS_ROOT="$2"; shift 2 ;;
    --uploads-guard) UPLOADS_GUARD="$2"; shift 2 ;;
    --receipt) RECEIPT="$2"; shift 2 ;;
    *) echo "UNKNOWN_ARG: $1" >&2; exit 2 ;;
  esac
done
[ -n "$PG_CONTAINER" ] && [ -n "$EXPECT_SID" ] && [ -n "$WV_URL" ] && \
[ -n "$WV_CONTAINER" ] && [ -n "$WV_EXPECT_HOSTNAME" ] || \
  { echo "usage: --pg-container/--expect-sid/--weaviate-url/--weaviate-container/--weaviate-expect-hostname 必填" >&2; exit 2; }
if [ -n "$UPLOADS_ROOT" ]; then [ -n "$UPLOADS_GUARD" ] || \
  { echo "usage: --uploads-root 必须伴随 --uploads-guard(UNKNOWN 清单)" >&2; exit 2; }
fi

# 注销来源冻结清单(G3 范围;新增注销来源须修订本清单并重审)
SRC_A="knowledge-support-cases"; SRC_A_PLEN=$(( ${#SRC_A} + 1 ))
SRC_B="knowledge-cb70f5ae";      SRC_B_PLEN=$(( ${#SRC_B} + 1 ))

D=-1; V=-1; CH=-1; KD=-1; KV=-1; KC=-1; GENS=-1; EXT=-1; REGS=-1; REIDX=-1; WVFS=-1; LG=-1; UP=-1
finish(){ # $1=DENY|ALLOW $2=reason —— 唯一出口;写回执;DENY 退出 1
  local ts; ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  echo "VERDICT: $1 reason=${2:-ok}" >&2
  if [ -n "$RECEIPT" ]; then
    mkdir -p "$(dirname "$RECEIPT")"
    printf '{"ts":"%s","verdict":"%s","reason":"%s","sid":"%s","ksc":{"docs":%s,"versions":%s,"chunks":%s,"gens":%s,"ext_refs":%s},"kc":{"docs":%s,"versions":%s,"chunks":%s},"active_regs":%s,"pending_reindex":%s,"wv_filesystem":%s,"legacy_gens":%s,"uploads":%s}\n' \
      "$ts" "$1" "${2:-ok}" "${SID:-null}" "$D" "$V" "$CH" "$GENS" "$EXT" "$KD" "$KV" "$KC" "$REGS" "$REIDX" "$WVFS" "$LG" "$UP" >> "$RECEIPT"
  fi
  return 0
}
deny(){ finish DENY "$1"; exit 1; }
# 单次只读探针;失败 => 显式 DENY(不吞错)。$2=探针描述
q(){ local r; r=$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -tA -v ON_ERROR_STOP=1 -c "$1" 2>&1) || deny "probe-failed: $2 :: $r"; printf '%s' "$r"; }

# G1/G2 PG 可达 + 身份
SID=$(q "SELECT system_identifier FROM pg_control_system();" "pg identity") || exit 1
[ "$SID" = "$EXPECT_SID" ] || deny "identity-mismatch sid=$SID expected=$EXPECT_SID"
# G3/G4 Weaviate 可达 + 实例身份
# R1-C 端点绑定:--weaviate-url 的 host:port 必须属于 --weaviate-container
# (docker port 发布映射,或容器网络地址:8080)——杜绝"查 A 容器、验 B 实例"。
WV_ALLOWED=$(docker port "$WV_CONTAINER" 2>/dev/null | awk '{print $NF}' | sort -u)
WV_IPS=$(docker inspect "$WV_CONTAINER" --format '{{range $k,$v := .NetworkSettings.Networks}}{{$v.IPAddress}} {{end}}' 2>/dev/null || true)
python3 - "$WV_URL" "$WV_ALLOWED" "$WV_IPS" <<'PYCHK' || deny "weaviate-endpoint-mismatch: --weaviate-url 不由 --weaviate-container 提供(发布端口/容器地址均不匹配)"
import sys
from urllib.parse import urlparse
url, allowed, ips = sys.argv[1], sys.argv[2], sys.argv[3].split()
p = urlparse(url)
host = p.hostname or ""
port = p.port or (443 if p.scheme == "https" else 80)
mapped = any((h == host and str(pt) == str(port)) for ep in allowed.splitlines() if ep.strip()
             for h, pt in [ep.rsplit(":", 1)])
ip_direct = host in ips and port == 8080
sys.exit(0 if (mapped or ip_direct) else 1)
PYCHK
# 残留聚合必须经已绑定验证的 --weaviate-url 读取(与端点绑定同源,杜绝旁路)
WVFS_RAW=$(curl -fsS -m 10 "$WV_URL/v1/graphql" -H "Content-Type: application/json" \
  --data-binary '{"query":"{Aggregate{Document(groupBy:\"source_type\"){groupedBy{value} meta{count}}}}"}' 2>&1) \
  || deny "probe-failed: weaviate unreachable :: $WVFS_RAW"
WVFS=$(printf '%s' "$WVFS_RAW" | python3 -c 'import json,sys
d=json.load(sys.stdin)["data"]["Aggregate"]["Document"]
print(sum(x["meta"]["count"] for x in d if x["groupedBy"]["value"]=="filesystem"))') \
  || deny "probe-failed: weaviate aggregate parse"
WV_HOST=$(docker exec "$WV_CONTAINER" printenv CLUSTER_HOSTNAME 2>&1) || deny "probe-failed: weaviate cluster hostname env"
[ "$WV_HOST" = "$WV_EXPECT_HOSTNAME" ] || deny "weaviate-identity-mismatch host=$WV_HOST expected=$WV_EXPECT_HOSTNAME"
# G5 两来源 × 三层残留(严格字面前缀)
D=$(q "SELECT count(*) FROM documents WHERE left(source_id, $SRC_A_PLEN) = '$SRC_A' || '/';" "ksc documents") || exit 1
V=$(q "SELECT count(*) FROM document_versions WHERE left(source_id, $SRC_A_PLEN) = '$SRC_A' || '/';" "ksc versions") || exit 1
CH=$(q "SELECT count(*) FROM document_version_chunks c WHERE EXISTS (SELECT 1 FROM document_versions v WHERE v.id = c.version_id AND left(v.source_id, $SRC_A_PLEN) = '$SRC_A' || '/');" "ksc chunks") || exit 1
KD=$(q "SELECT count(*) FROM documents WHERE left(source_id, $SRC_B_PLEN) = '$SRC_B' || '/';" "kc documents") || exit 1
KV=$(q "SELECT count(*) FROM document_versions WHERE left(source_id, $SRC_B_PLEN) = '$SRC_B' || '/';" "kc versions") || exit 1
KC=$(q "SELECT count(*) FROM document_version_chunks c WHERE EXISTS (SELECT 1 FROM document_versions v WHERE v.id = c.version_id AND left(v.source_id, $SRC_B_PLEN) = '$SRC_B' || '/');" "kc chunks") || exit 1
if [ "$D" != "0" ] || [ "$V" != "0" ] || [ "$CH" != "0" ] || [ "$KD" != "0" ] || [ "$KV" != "0" ] || [ "$KC" != "0" ]; then
  deny "residue-pg ksc(docs/vers/chunks)=$D/$V/$CH kc=$KD/$KV/$KC"
fi
# G6 专属 generations
GA=$(q "SELECT count(*) FROM index_generations WHERE source_id='$SRC_A';" "ksc gens") || exit 1
GB=$(q "SELECT count(*) FROM index_generations WHERE source_id='$SRC_B';" "kc gens") || exit 1
GENS=$(( GA + GB ))
[ "$GENS" = "0" ] || deny "residue-generations count=$GENS"
# G7 外部引用(目标来源名下 generations 不得被外部版本引用)
EA=$(q "SELECT count(*) FROM document_versions v WHERE v.generation_id IN (SELECT id FROM index_generations WHERE source_id='$SRC_A') AND NOT (left(v.source_id, $SRC_A_PLEN) = '$SRC_A' || '/');" "ksc ext refs") || exit 1
EB=$(q "SELECT count(*) FROM document_versions v WHERE v.generation_id IN (SELECT id FROM index_generations WHERE source_id='$SRC_B') AND NOT (left(v.source_id, $SRC_B_PLEN) = '$SRC_B' || '/');" "kc ext refs") || exit 1
EXT=$(( EA + EB ))
[ "$EXT" = "0" ] || deny "residue-external-generations-refs count=$EXT"
# G8 注册(仅 enabled 且未退役的行)
RA=$(q "SELECT count(*) FROM data_sources WHERE id='$SRC_A' AND enabled=true AND coalesce(lifecycle_state,'active')<>'retired';" "ksc registration") || exit 1
RB=$(q "SELECT count(*) FROM data_sources WHERE id='$SRC_B' AND enabled=true AND coalesce(lifecycle_state,'active')<>'retired';" "kc registration") || exit 1
REGS=$(( RA + RB ))
[ "$REGS" = "0" ] || deny "registration-active count=$REGS"
# G9 重入(未终态 sync_requests)
PA=$(q "SELECT count(*) FROM sync_requests WHERE (source_id='$SRC_A' OR left(source_id, $SRC_A_PLEN) = '$SRC_A' || '/') AND status NOT IN ('done','completed','failed','cancelled','skipped');" "ksc reindex requests") || exit 1
PB=$(q "SELECT count(*) FROM sync_requests WHERE (source_id='$SRC_B' OR left(source_id, $SRC_B_PLEN) = '$SRC_B' || '/') AND status NOT IN ('done','completed','failed','cancelled','skipped');" "kc reindex requests") || exit 1
REIDX=$(( PA + PB ))
[ "$REIDX" = "0" ] || deny "reindex-pending count=$REIDX"
# G10 WV filesystem 残留
[ "$WVFS" = "0" ] || deny "residue-weaviate filesystem_objects=$WVFS"
# G11 共享层
LG=$(q "SELECT count(*) FROM index_generations WHERE source_id='*legacy*';" "legacy generations") || exit 1
[ "$LG" -ge 1 ] || deny "legacy-missing(共享 generation 缺失,疑误删)"
# G12 uploads(给定根目录时:注销来源目录内文件必须全部在 UNKNOWN 守卫清单内且哈希一致)
if [ -n "$UPLOADS_ROOT" ]; then
  [ -d "$UPLOADS_ROOT" ] || deny "uploads-root-missing $UPLOADS_ROOT"
  [ -f "$UPLOADS_GUARD" ] || deny "uploads-guard-missing $UPLOADS_GUARD"
  UP=0
  declare -a GUARD_S=() GUARD_P=()
  while IFS="$(printf '\t')" read -r gsid gp gsh; do
    [ -n "$gsid" ] || continue
    GUARD_S+=("$gsh"); GUARD_P+=("$gsid/$gp")
  done < "$UPLOADS_GUARD"
  FIND_ERR=$(mktemp "${TMPDIR:-/tmp}/gate-finderr.XXXXXX")
  FIND_OUT=$(mktemp "${TMPDIR:-/tmp}/gate-findout.XXXXXX")
  for sd in "$SRC_A" "$SRC_B"; do
    [ -d "$UPLOADS_ROOT/$sd" ] || { echo "uploads dir absent for $sd (no residue possible)"; continue; }
    set +e
    find "$UPLOADS_ROOT/$sd" ! -type d > "$FIND_OUT" 2>> "$FIND_ERR"
    FRC=$?
    set -e
    [ "$FRC" = "0" ] || { cat "$FIND_ERR" >&2; rm -f "$FIND_ERR" "$FIND_OUT"; deny "uploads-scan-failed (rc=$FRC) under $UPLOADS_ROOT/$sd — 无法证明目录内容"; }
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      rel="${f#"$UPLOADS_ROOT"/}"
      if [ -L "$f" ] || [ ! -f "$f" ]; then rm -f "$FIND_ERR" "$FIND_OUT"; deny "uploads-symlink-or-special: $f"; fi
      h=$(shasum -a 256 "$f" 2>/dev/null | awk '{print $1}')
      [ -n "$h" ] || { rm -f "$FIND_ERR" "$FIND_OUT"; echo "DENY: uploads-hash-unreadable: $f" >&2; UP=$((UP+1)); continue; }
      matched=""
      for gi in "${!GUARD_P[@]}"; do
        if [ "${GUARD_P[$gi]}" = "$rel" ] && [ "${GUARD_S[$gi]}" = "$h" ]; then matched=yes; break; fi
      done
      [ -n "$matched" ] || { echo "DENY: uploads-unrecognized: $rel (sha=$h)" >&2; UP=$((UP+1)); }
    done < "$FIND_OUT"
  done
  [ "$UP" = "0" ] || deny "uploads-unrecognized-files count=$UP(UNKNOWN 守卫之外或哈希漂移)"
  UP=1   # 1 = 检查通过(已核);回执语义:>=0 已检(0=目录内无任何文件),-1=未检查
fi
finish ALLOW
