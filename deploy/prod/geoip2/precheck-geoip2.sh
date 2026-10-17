#!/usr/bin/env bash
# ============================================================================
# ask-ai 受信国家信号 —— 单次受控上线预检(fail-closed)
# Issue #114 阶段 E 交付(AC1 检查方式 / AC5 预检清单的机械执行面)
# R2 修正版:G6b 精确网关 /32;G7 基于 nginx -T 生效配置;新增 G8 发布端口
# 边界(受信跳可达性);G5 全程类别化输出(真实网关/子网/CIDR 值不回显)。
#
# 用途:阶段 P(受权操作者)在真实启用前后各跑一次;任一门 FAIL 即退出码 1
# 并给出结论「保持 off」。本脚本零写面:不改任何配置、不 reload、不发生产
# /ask 探针;E2E(真实访客路径国家入库)属于阶段 P 手工清单,见 README.md。
#
# 用法(生产宿主):
#   sudo ./precheck-geoip2.sh --expect off   # 默认:验证「默认关闭」状态健康
#   sudo ./precheck-geoip2.sh --expect on    # 启用前门检:全链路一致性
#
# 输出纪律:只输出类别/布尔/计数。真实网桥网段/网关/CIDR/头值组合一律**不
# 回显**(R2 红线:禁止落入持久日志/Issue/工单);操作员按 README 现场比对
# 命令自查。本脚本不读取、不输出任何访客 IP、原始请求头或凭据值。
#
# G8 语义(R1 修正):0.0.0.0 端口发布下,外部/同网段流量经 DNAT 后与
# nginx 转发流量同样表现为网桥网关 peer —— 网关 /32 授信可被旁路。因此
# 「受信跳边界」是独立硬门:发布端口必须仅绑定 loopback(或等效防火墙,
# 属另行授权的网络变更),未收口前一律 FAIL = 保持 off。
# ============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
BACKEND_PORT="${BACKEND_PORT:-18000}"

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
command -v python3 >/dev/null 2>&1 \
    && gate G0 PASS "python3 可用(机械门执行面)" \
    || gate G0 FAIL "python3 不可用(G6b/G7/G8 机械门无法执行)"

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

# G3 MMDB 就位与**硬结构校验**(只读;R2 修正:完整 metadata 解析 + 真实走树,
#    拒绝「标记子串 + 体积」假 PASS)---------------------------------------------
if [ -s "$MMDB_PATH" ]; then
    if python3 "$SCRIPT_DIR/mmdb_validate.py" "$MMDB_PATH"; then
        gate G3 PASS "MMDB 硬结构校验通过(metadata 解析 + 字段语义 + 走树越界门)"
    else
        gate G3 FAIL "MMDB 硬结构校验拒绝(损坏/截断/类型不符)—— 保持 off"
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

# G5 compose 网络推导(全程类别化;真实网段/网关值不回显,R2 红线)------------
BRIDGE_SUBNET=$(docker network inspect "${COMPOSE_PROJECT}_default" \
    --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}' 2>/dev/null || true)
BRIDGE_GW=$(docker network inspect "${COMPOSE_PROJECT}_default" \
    --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}' 2>/dev/null || true)
if [ -n "$BRIDGE_SUBNET" ] && [ -n "$BRIDGE_GW" ]; then
    gate G5 PASS "compose 网络已推导(网段/网关均非空;值仅现场比对,不回显)"
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
            || gate G6 FAIL "运行态 mode 非 ingress —— 先装配 env 并重建 backend"
        [ -n "$HEADER" ] && gate G6 PASS "运行态头名已配置(类别: 已设置)" \
            || gate G6 FAIL "运行态头名未配置"
        ;;
    off)
        { [ "$MODE" = "off(未注入)" ] || [ "$MODE" = "off" ]; } \
            && gate G6 PASS "运行态 mode=off(与 #144 基线一致,默认关闭健康)" \
            || gate G6 FAIL "运行态 mode 已偏离默认关闭;若非受控启用请立即回退"
        ;;
esac
# G6b CIDR 精确性(R2 修正):受信列表必须与网桥网关 /32 **精确相等** ----------
# (旧逻辑接受含网关的任意网桥子网,整 /24 也假 PASS;现拒绝任何过宽/偏离授信)
if [ -z "$CIDRS" ]; then
    { [ "$EXPECT" = "off" ]; } \
        && gate G6 PASS "受信 CIDR 未配置(0 条 = 无人可信,默认关闭语义)" \
        || gate G6 FAIL "期望启用但受信 CIDR 为空 = 无人可信(恒 Unknown)"
elif [ -z "$BRIDGE_GW" ]; then
    gate G6 FAIL "无法核验 CIDR 精确性(网桥网关未知)—— 保持 off"
else
    if python3 "$SCRIPT_DIR/precheck_checks.py" cidr --cidrs "$CIDRS" --gateway "$BRIDGE_GW"; then
        gate G6 PASS "受信 CIDR = 网桥网关 /32(精确相等;必要非充分条件,发布端口边界见 G8)"
    else
        gate G6 FAIL "受信 CIDR 非精确网关 /32(过宽/偏离/非法)—— 禁止启用,保持 off"
    fi
fi

# G7 nginx 配置面(R2 修正):nginx -t + **nginx -T 生效配置**机械校验 ----------
# (旧逻辑 grep 源文件,会命中被注释指令或静态值;nginx -T dump 无注释,
#  静态值仍可见 ⇒ 注释假 PASS 与静态值假 PASS 双双闭合。dump 只走 stdin/
#  变量,不落盘、不回显。)
DUMP="$("$NGINX_BIN" -T 2>/dev/null)"
if [ "$EXPECT" = "on" ]; then
    "$NGINX_BIN" -t >/dev/null 2>&1 \
        && gate G7 PASS "nginx -t 通过" \
        || gate G7 FAIL "nginx -t 未通过 —— 禁止 reload,先修配置"
    if [ -z "$DUMP" ]; then
        gate G7 FAIL "nginx -T 生效配置不可得(语法错误/权限不足)—— 无法证明覆盖链,保持 off"
    elif [ -z "$HEADER" ]; then
        gate G7 FAIL "backend 头名未配置,nginx 侧一致性无从核验 —— 保持 off"
    else
        if printf '%s' "$DUMP" | python3 "$SCRIPT_DIR/precheck_checks.py" nginx \
              --header "$HEADER" --mmdb "$MMDB_PATH" --port "$BACKEND_PORT" --expect on; then
            gate G7 PASS "生效配置覆盖链完整(geoip2+auto_reload+map 兜底+无条件同名头覆盖)"
        else
            gate G7 FAIL "生效配置覆盖链断裂(细节见上一行类别消息)—— 保持 off"
        fi
    fi
else
    if [ -z "$DUMP" ]; then
        gate G7 FAIL "nginx -T 生效配置不可得 —— 无法证明默认关闭(fail-closed)"
    else
        if printf '%s' "$DUMP" | python3 "$SCRIPT_DIR/precheck_checks.py" nginx \
              --header "geo-country" --mmdb "$MMDB_PATH" --port "$BACKEND_PORT" --expect off; then
            gate G7 PASS "nginx 生效配置无 geoip2/geo 头(默认关闭成立)"
        else
            gate G7 FAIL "期望 off 但 nginx 生效配置已含 geoip2/geo 头 —— 请确认是否未授权启用"
        fi
    fi
fi

# G8 发布端口边界(R1 修正):受信跳可达性 fail-closed --------------------------
# 0.0.0.0/:: 发布 = 外部与同网段流量可经 DNAT 伪装成网桥网关 peer,网关 /32
# 授信被旁路 ⇒ 必须仅 loopback 绑定(或等效防火墙)。该收口属另行授权的网络
# 变更(README §2.4):执行须 owner 授权,验证 = 本门复验,回滚 = 恢复原 ports。
HOSTIP=$(docker inspect "$BACKEND_CONTAINER" \
    --format '{{(index (index .NetworkSettings.Ports "8000/tcp") 0).HostIp}}' 2>/dev/null || true)
HOSTPORT=$(docker inspect "$BACKEND_CONTAINER" \
    --format '{{(index (index .NetworkSettings.Ports "8000/tcp") 0).HostPort}}' 2>/dev/null || true)
if python3 "$SCRIPT_DIR/precheck_checks.py" binding --host-ip "$HOSTIP"; then
    gate G8 PASS "backend 发布端口仅绑定 loopback(受信跳边界成立)"
else
    gate G8 FAIL "backend 发布端口绑定非 loopback(HOSTIP 类别: ${HOSTIP:-不可得})—— 保持 off;收口为另行授权变更(README §2.4)"
fi
# G8b 宿主监听交叉核验(best-effort;iptables DNAT 直通模式可能无 ss 条目)
if command -v ss >/dev/null 2>&1 && [ -n "$HOSTPORT" ]; then
    if ss -ltn 2>/dev/null | awk -v p=":$HOSTPORT" '$4 ~ p {print $4}' | grep -qvE '^(127\.0\.0\.1|\[::1\])'; then
        gate G8 FAIL "宿主存在非 loopback 监听于发布端口(类别: 非 loopback)—— 保持 off"
    else
        gate G8 PASS "宿主监听交叉核验无非 loopback 条目(或 DNAT 直通无 ss 条目)"
    fi
else
    gate G8 PASS "ss 不可用/端口未得 —— 交叉核验跳过(以 G8 docker inspect 绑定为准)"
fi

# 汇总(fail-closed)-----------------------------------------------------------
printf -- '---- 预检汇总: expect=%s  PASS=%d  FAIL=%d ----\n' "$EXPECT" "$PASS" "$FAIL"
if [ "$FAIL" -gt 0 ]; then
    echo "结论: 存在未过门项 —— 保持 off(fail-closed)。逐门修复后重跑。"
    echo "提示: G8 未收口 = 受信跳边界未证实;loopback/防火墙变更属另行授权(README §2.4)。"
    exit 1
fi
echo "结论: 本轮门检全部通过。E2E(真实访客路径入库)验证按 README 阶段 P 清单执行。"
exit 0
