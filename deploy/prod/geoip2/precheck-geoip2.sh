#!/usr/bin/env bash
# ============================================================================
# ask-ai 受信国家信号 —— 单次受控上线预检(fail-closed)
# Issue #114 阶段 E 交付(AC1 检查方式 / AC5 预检清单的机械执行面)
#
# 用途:阶段 P(受权操作者)在真实启用前后各跑一次;任一门 FAIL 即退出码 1
# 并给出结论「保持 off」。本脚本零写面:不改任何配置、不 reload、不发生产
# /ask 探针;E2E(真实访客路径国家入库)属于阶段 P 手工清单,见 README.md。
#
# 用法(生产宿主):
#   sudo ./precheck-geoip2.sh --expect off   # 默认:验证「默认关闭」状态健康
#   sudo ./precheck-geoip2.sh --expect on    # 启用前门检:全链路一致性
#
# 输出纪律:只输出类别/布尔/计数;直连 peer 派生值(G5)仅供操作员现场比对,
# 禁止粘贴进仓库/Issue/工单(内网 CIDR 红线)。本脚本不读取、不输出任何
# 访客 IP、原始请求头或凭据值。
# ============================================================================
set -uo pipefail

EXPECT="off"
case "${1:-}" in
    --expect) EXPECT="${2:?用法: $0 --expect {off|on}}" ;;
    -h|--help) echo "用法: $0 --expect {off|on}"; exit 0 ;;
    "") ;;
    *) echo "未知参数: $1"; exit 2 ;;
esac

COMPOSE_PROJECT="${COMPOSE_PROJECT:-tesla-t4}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-${COMPOSE_PROJECT}-backend-1}"
MMDB_PATH="${GEOLITE2_MMDB_PATH:-/etc/nginx/geoip/GeoLite2-Country.mmdb}"
NGINX_BIN="${NGINX_BIN:-nginx}"

PASS=0; FAIL=0
gate() { # gate <ID> <PASS|FAIL> <类别化说明>
    local id="$1" verdict="$2" msg="$3"
    if [ "$verdict" = "PASS" ]; then
        printf '[%s] PASS  %s\n' "$id" "$msg"; PASS=$((PASS+1))
    else
        printf '[%s] FAIL  %s\n' "$id" "$msg"; FAIL=$((FAIL+1))
    fi
}

[ "$(id -u)" -eq 0 ] || { echo "请用 sudo 运行(需读容器 env 与 nginx 状态)"; exit 2; }

# G0 前置工具面 --------------------------------------------------------------
command -v "$NGINX_BIN" >/dev/null 2>&1 \
    && gate G0 PASS "宿主 nginx 可用" \
    || gate G0 FAIL "宿主 nginx 不可用(本方案的前置载体缺失)"
command -v docker >/dev/null 2>&1 \
    && gate G0 PASS "docker CLI 可用" \
    || gate G0 FAIL "docker CLI 不可用(无法核验运行态)"

# G1 geoip2 动态模块:安装 + 装载 --------------------------------------------
SO=/usr/lib/nginx/modules/ngx_http_geoip2_module.so
if [ -f "$SO" ] && "$NGINX_BIN" -V 2>&1 | grep -q 'http-geoip2\|geoip2'; then
    gate G1 PASS "ngx_http_geoip2 动态模块已安装(同源包,ABI 与宿主 nginx 一致)"
else
    gate G1 FAIL "geoip2 模块缺失/来源不符 —— 停止,不得跨源拷贝 .so(ABI 断裂风险)"
fi
grep -qs 'ngx_http_geoip2_module.so' /etc/nginx/modules-enabled/*.conf \
    && gate G1 PASS "load_module 已在 modules-enabled 挂载" \
    || gate G1 FAIL "load_module 未挂载(modules-enabled 无 geoip2 条目)"

# G2 libmaxminddb ------------------------------------------------------------
(ldconfig -p 2>/dev/null | grep -q libmaxminddb) \
    && gate G2 PASS "libmaxminddb 运行库可用" \
    || gate G2 FAIL "libmaxminddb 缺失(模块 .so 无法加载)"

# G3 MMDB 就位与结构校验(只读)----------------------------------------------
if [ -s "$MMDB_PATH" ]; then
    if python3 - "$MMDB_PATH" <<'PY'
import sys

data = open(sys.argv[1], "rb").read()
idx = data.rfind(b"\xab\xcd\xefMaxMind.com")
sys.exit(0 if idx != -1 and b"GeoLite2-Country" in data[idx : idx + 4096] and len(data) >= 1_000_000 else 1)
PY
    then gate G3 PASS "MMDB 存在且 GeoLite2-Country 结构校验通过"
    else gate G3 FAIL "MMDB 结构校验未通过(疑似损坏/截断)—— 保持 off"
    fi
else
    gate G3 FAIL "MMDB 不存在(需 owner 接受许可后经 update-geolite2.sh 首次安装)"
fi

# G4 凭据文件存在与权限(只输出类别,不输出内容)------------------------------
KEY_FILE="${GEOLITE2_LICENSE_KEY_FILE:-/etc/ask-ai-geoip/geolite2-license.key}"
if [ -f "$KEY_FILE" ]; then
    p=$(stat -c '%a' "$KEY_FILE" 2>/dev/null || echo "?")
    [ "$p" = "600" ] && gate G4 PASS "license key 文件在位,权限 0600" \
                    || gate G4 FAIL "license key 权限过宽(${p}),要求 0600"
else
    gate G4 FAIL "license key 文件缺失(GeoLite2 许可/开户仍为 owner 前置项)"
fi

# G5 直连 peer 精确推导与信任面收敛 ------------------------------------------
# #144 实证拓扑:宿主 nginx → published port → backend;应用直连 peer = 网桥网关。
BRIDGE_SUBNET=$(docker network inspect "${COMPOSE_PROJECT}_default" \
    --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}' 2>/dev/null || true)
BRIDGE_GW=$(docker network inspect "${COMPOSE_PROJECT}_default" \
    --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}' 2>/dev/null || true)
if [ -n "$BRIDGE_SUBNET" ] && [ -n "$BRIDGE_GW" ]; then
    gate G5 PASS "compose 网络已推导: subnet=${BRIDGE_SUBNET} gateway=${BRIDGE_GW}(仅现场比对,勿外传)"
else
    gate G5 FAIL "无法推导 compose 网络(${COMPOSE_PROJECT}_default)—— CIDR 授权失去依据,保持 off"
fi
BACKEND_NET=$(docker inspect "$BACKEND_CONTAINER" \
    --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' 2>/dev/null || true)
case "$BACKEND_NET" in
    *"${COMPOSE_PROJECT}_default"*) gate G5 PASS "backend 容器确在 ${COMPOSE_PROJECT}_default 网络" ;;
    "") gate G5 FAIL "backend 容器 ${BACKEND_CONTAINER} 不可见(未运行/名字不符)" ;;
    *)  gate G5 FAIL "backend 容器不在预期网络(实际: ${BACKEND_NET:-未知})—— 拓扑与假设不符,保持 off" ;;
esac

# G6 backend 运行态三元组(类别输出)-----------------------------------------
ENV_TRIPLE=$(docker exec "$BACKEND_CONTAINER" env 2>/dev/null | grep -E '^(COUNTRY_RESOLUTION_MODE|COUNTRY_INGRESS_HEADER|GEO_TRUSTED_PROXY_CIDRS)=' || true)
MODE=$(sed -n 's/^COUNTRY_RESOLUTION_MODE=//p' <<<"$ENV_TRIPLE")
HEADER=$(sed -n 's/^COUNTRY_INGRESS_HEADER=//p' <<<"$ENV_TRIPLE")
CIDRS=$(sed -n 's/^GEO_TRUSTED_PROXY_CIDRS=//p' <<<"$ENV_TRIPLE")
[ -n "$MODE" ] || MODE="off(未注入)"
case "$EXPECT" in
    on)
        [ "$MODE" = "ingress" ] && gate G6 PASS "运行态 mode=ingress" \
            || gate G6 FAIL "运行态 mode=${MODE}(非 ingress)—— 先装配 env 并重建 backend"
        [ -n "$HEADER" ] && gate G6 PASS "运行态头名已配置(类别: 已设置)" \
            || gate G6 FAIL "运行态头名未配置"
        ;;
    off)
        { [ "$MODE" = "off(未注入)" ] || [ "$MODE" = "off" ]; } \
            && gate G6 PASS "运行态 mode=off(与 #144 基线一致,默认关闭健康)" \
            || gate G6 FAIL "运行态 mode=${MODE}:已偏离默认关闭;若非受控启用请立即回退"
        ;;
esac
# G6b CIDR 精确性:每项必须落在网桥网段内,且覆盖网关;拒绝全零/过宽授信 ----
if [ -z "$CIDRS" ]; then
    { [ "$EXPECT" = "off" ]; } \
        && gate G6 PASS "受信 CIDR 未配置(0 条 = 无人可信,默认关闭语义)" \
        || gate G6 FAIL "期望启用但受信 CIDR 为空 = 无人可信(恒 Unknown)"
else
    if [ -z "$BRIDGE_SUBNET" ]; then
        gate G6 FAIL "无法核验 CIDR 收敛性(网桥网段未知)—— 保持 off"
    else
        if python3 - "$CIDRS" "$BRIDGE_SUBNET" "$BRIDGE_GW" <<'PY'
import ipaddress
import sys

cidrs, subnet, gw = sys.argv[1], sys.argv[2], sys.argv[3]
bridge = ipaddress.ip_network(subnet)
nets = []
for raw in cidrs.split(","):
    raw = raw.strip()
    if not raw:
        continue
    net = ipaddress.ip_network(raw, strict=False)
    if net.num_addresses > 65536 or net.version != 4:
        sys.exit(f"过宽或非 IPv4 授信: {raw}")
    if not net.subnet_of(bridge):
        sys.exit(f"授信越出网桥网段: {raw}")
    nets.append(net)
if not nets:
    sys.exit("受信列表为空")
gw_addr = ipaddress.ip_address(gw)
if not any(gw_addr in n for n in nets):
    sys.exit(f"受信列表未覆盖直连 peer(网关 {gw})")
print("ok")
PY
        then gate G6 PASS "受信 CIDR 收敛:全部落在网桥网段内且覆盖直连 peer,无过宽授信"
        else gate G6 FAIL "受信 CIDR 不收敛($?)—— 禁止启用"
        fi
    fi
fi

# G7 nginx 配置面:语法 + 启用一致性 -----------------------------------------
# 头名交叉核验:nginx proxy_set_header 的头名必须与 backend 头名一致。
VHOST_HITS=$(grep -RIls --include='*' 'proxy_pass.*:18000' /etc/nginx/sites-enabled/ 2>/dev/null | head -3)
if [ "$EXPECT" = "on" ]; then
    "$NGINX_BIN" -t >/dev/null 2>&1 \
        && gate G7 PASS "nginx -t 通过" \
        || gate G7 FAIL "nginx -t 未通过 —— 禁止 reload,先修配置"
    grep -qs 'geoip2 ' /etc/nginx/conf.d/*.conf \
        && gate G7 PASS "conf.d 已含 geoip2 http 级配置" \
        || gate G7 FAIL "conf.d 缺少片段 A(geoip2/map)"
    if [ -n "$HEADER" ] && [ -n "$VHOST_HITS" ] \
        && grep -qs "proxy_set_header[[:space:]]${HEADER}[[:space:]]" $VHOST_HITS; then
        gate G7 PASS "vhost proxy_set_header 头名与 backend COUNTRY_INGRESS_HEADER 一致(类别: 已设置)"
    else
        gate G7 FAIL "vhost 未找到 proxy_set_header <配置头名>;或头名两侧不一致 —— 覆盖链断裂,保持 off"
    fi
else
    if grep -qs 'geoip2 ' /etc/nginx/conf.d/*.conf || { [ -n "$VHOST_HITS" ] && grep -qsE 'proxy_set_header[[:space:]]geo-country' $VHOST_HITS; }; then
        gate G7 FAIL "期望 off 但 nginx 侧已存在 geoip2/geo-country 配置 —— 请确认是否未授权启用"
    else
        gate G7 PASS "nginx 侧无 geoip2 生效配置(默认关闭成立)"
    fi
fi

# 汇总(fail-closed)-----------------------------------------------------------
printf -- '---- 预检汇总: expect=%s  PASS=%d  FAIL=%d ----\n' "$EXPECT" "$PASS" "$FAIL"
if [ "$FAIL" -gt 0 ]; then
    echo "结论: 存在未过门项 —— 保持 off(fail-closed)。逐门修复后重跑。"
    exit 1
fi
echo "结论: 本轮门检全部通过。E2E(真实访客路径入库)验证按 README 阶段 P 清单执行。"
exit 0
