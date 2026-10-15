#!/usr/bin/env bash
# ============================================================================
# GeoLite2-Country MMDB 更新器(Issue #114 阶段 E 交付)
#
# 职责(AC4):合法下载(需 owner 已接受 MaxMind GeoLite2 EULA 并持有
# license key)→ 临时下载 → 完整性/结构校验 → 原子替换(rename(2),不覆盖
# 正被 mmap 的旧文件,配合 nginx geoip2 auto_reload 免 reload 生效)→
# 失败自动恢复旧库。
#
# 默认不改变任何运行面:不 reload/重启 nginx(除非显式 --reload);
# 不打印、不持久化 license key;不输出任何访客 IP(校验探针只用
# RFC 5737 文档地址 203.0.113.1 / 环回地址)。
#
# 用法(生产宿主,受权操作者):
#   sudo ./update-geolite2.sh              # 首次安装或周期更新
#   sudo ./update-geolite2.sh --verify     # 只校验现网文件(只读)
#   sudo ./update-geolite2.sh --rollback   # 手动回滚到 .bak(受控)
#   sudo ./update-geolite2.sh --reload     # nginx -t 通过后 reload(可选;
#                                          # 已配置 auto_reload 时通常不需要)
#
# 周期更新(cron 示例,每周三 04:17,失败退出码留给 cron 邮件):
#   17 4 * * 3 root /home/ubuntu/ask-ai/deploy/prod/geoip2/update-geolite2.sh
#
# 凭据秘密管理(AC4):license key 只存生产宿主文件,权限 0600,不入仓库、
# 不入环境变量导出面、不出现在本脚本任何输出。若泄露:MaxMind 账户轮换。
# ============================================================================
set -euo pipefail

MMDB_PATH="${GEOLITE2_MMDB_PATH:-/etc/nginx/geoip/GeoLite2-Country.mmdb}"
KEY_FILE="${GEOLITE2_LICENSE_KEY_FILE:-/etc/ask-ai-geoip/geolite2-license.key}"
# MaxMind 官方下载端点(直连 tar.gz;suffix 参数化便于未来换库)。
DOWNLOAD_URL="${GEOLITE2_DOWNLOAD_URL:-https://download.maxmind.com/geoip/databases/GeoLite2-Country/download?suffix=tar.gz}"
# GeoLite2-Country 历史体积约 6-9MB;低于 1MB 一律判损坏(fail-closed)。
MIN_BYTES=1000000
NGINX_BIN="${NGINX_BIN:-nginx}"

log() { printf '[geoip2-update] %s\n' "$*"; }
die() { printf '[geoip2-update] FAIL: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- 校验 ------
# 结构校验:MMDB 尾部 metadata 标记(0xAB 0xCD 0xEF + "MaxMind.com")之后
# 必须能找到数据库类型串 GeoLite2-Country。纯 python3 stdlib,宿主机无
# mmdblookup/python3-geoip2 依赖(#144 探针实证);若日后安装了
# mmdblookup 则附加 best-effort 开库探测(非硬门,避免假阴性)。
validate_mmdb() {
    local f="$1"
    [ -s "$f" ] || { log "校验失败:文件不存在或为空"; return 1; }
    local size
    size=$(wc -c <"$f")
    [ "$size" -ge "$MIN_BYTES" ] || { log "校验失败:体积 ${size} 低于下限(疑似截断)"; return 1; }
    python3 - "$f" <<'PY'
import sys

path = sys.argv[1]
with open(path, "rb") as fh:
    data = fh.read()
marker = b"\xab\xcd\xefMaxMind.com"
idx = data.rfind(marker)
if idx == -1:
    print("校验失败:MMDB metadata 标记缺失")
    sys.exit(1)
# metadata 紧跟标记之后,db type 串位于前部;窗口放宽到 4KB 覆盖 utf8 字段
tail = data[idx : idx + 4096]
if b"GeoLite2-Country" not in tail:
    print("校验失败:database_type 不是 GeoLite2-Country")
    sys.exit(1)
print("校验通过:GeoLite2-Country metadata 完整, bytes=%d" % len(data))
PY
    if command -v mmdblookup >/dev/null 2>&1; then
        # best-effort:能打开文件即可;输出内容不作为硬门
        mmdblookup --file "$f" --ip 203.0.113.1 >/dev/null 2>&1 \
            || log "提示:mmdblookup 开库探测未通过(软提示,硬门以上方 metadata 校验为准)"
    fi
    return 0
}

# ---------------------------------------------------------------- 主流程 ----
do_update() {
    [ "$(id -u)" -eq 0 ] || die "请用 sudo 运行(需写 $MMDB_PATH 所在目录)"
    [ -r "$KEY_FILE" ] || die "license key 文件不可读: $KEY_FILE(owner 需先接受 GeoLite2 许可并开户)"
    local perms
    perms=$(stat -c '%a' "$KEY_FILE")
    [ "$perms" = "600" ] || die "license key 文件权限过宽($perms),要求 0600 —— 拒绝在弱权限下运行(fail-closed)"
    local key
    key=$(tr -d '[:space:]' <"$KEY_FILE")
    [ -n "$key" ] || die "license key 文件为空"

    command -v curl >/dev/null 2>&1 || die "缺少 curl"
    command -v python3 >/dev/null 2>&1 || die "缺少 python3"

    # 临时目录与目标同目录(同一文件系统)⇒ 最后一步 rename(2) 原子生效,
    # nginx 打开的旧 inode 不被就地覆盖(auto_reload 语义依赖)。
    local tmpdir
    mkdir -p "$(dirname "$MMDB_PATH")"
    tmpdir=$(mktemp -d "$(dirname "$MMDB_PATH")/.geoupdate.XXXXXX")
    local swapped=0
    cleanup() {
        if [ "$swapped" -eq 1 ]; then
            if [ -f "${MMDB_PATH}.bak" ]; then
                mv -f "${MMDB_PATH}.bak" "$MMDB_PATH" &&
                    log "失败恢复:已回滚到上一个有效库(原子替换)"
            fi
        fi
        rm -rf "$tmpdir"
    }
    trap cleanup EXIT

    log "开始下载(不回显凭据)…"
    # -sS:错误走 stderr;--max-time 兜底;URL 含 key,禁止 set -x / 打印
    local sep='&'
    case "$DOWNLOAD_URL" in *\?*) sep='&' ;; *) sep='?' ;; esac
    curl -fsS --max-time 300 --retry 2 \
        -o "$tmpdir/geolite2-country.tar.gz" \
        "${DOWNLOAD_URL}${sep}license_key=${key}" \
        || die "下载失败(网络/凭据/许可状态);现网文件未受影响"
    gzip -t "$tmpdir/geolite2-country.tar.gz" || die "gzip 完整性校验失败"
    # 解压前检查成员路径,拒绝路径穿越
    if tar -tzf "$tmpdir/geolite2-country.tar.gz" | grep -q '\.\./'; then
        die "压缩包含可疑路径(../),拒绝解压"
    fi
    tar -xzf "$tmpdir/geolite2-country.tar.gz" -C "$tmpdir"
    local newdb
    newdb=$(find "$tmpdir" -type f -name '*.mmdb' | head -1)
    [ -n "$newdb" ] || die "压缩包内未找到 .mmdb"
    validate_mmdb "$newdb" || die "新库结构校验未通过;现网文件未受影响"

    # 备份旧库(cp 保留现网文件继续服务,替换瞬间才切换)
    if [ -f "$MMDB_PATH" ]; then
        cp -p "$MMDB_PATH" "${MMDB_PATH}.bak"
    fi

    chmod 0644 "$newdb"
    # 原子替换:同目录 rename(2)。旧 mmap 句柄继续读旧 inode 直到 auto_reload。
    mv -f "$newdb" "$MMDB_PATH"
    swapped=1
    validate_mmdb "$MMDB_PATH" || die "替换后复核未通过(将自动回滚)"
    swapped=0    # 复核通过,清理 trap 不再回滚
    rm -f "${MMDB_PATH}.bak"
    trap - EXIT
    rm -rf "$tmpdir"

    log "更新完成: $MMDB_PATH"
    if "$NGINX_BIN" -T 2>/dev/null | grep -q 'auto_reload'; then
        log "nginx geoip2 auto_reload 已配置,将在检查周期内免 reload 生效"
    else
        log "提示:当前 nginx 配置未启用 auto_reload;执行 --reload 使新库生效"
    fi
    log "建议观察: sudo tail -n 20 /var/log/nginx/error.log  (应无 geoip2 报错)"
}

do_rollback() {
    [ -f "${MMDB_PATH}.bak" ] || die "无 .bak 可回滚"
    validate_mmdb "${MMDB_PATH}.bak" || die ".bak 校验未通过,拒绝回滚到损坏文件"
    mv -f "${MMDB_PATH}.bak" "$MMDB_PATH"
    log "已回滚: $MMDB_PATH"
    log "提示:如 nginx 未启用 auto_reload,执行 --reload 生效"
}

do_reload() {
    "$NGINX_BIN" -t || die "nginx -t 未通过,拒绝 reload(配置保持原状)"
    systemctl reload nginx
    log "nginx 已 reload"
}

case "${1:-update}" in
    update|"")  do_update ;;
    --verify)   validate_mmdb "$MMDB_PATH" || die "现网文件校验未通过" ;;
    --rollback) do_rollback ;;
    --reload)   do_reload ;;
    *) die "用法: $0 [update|--verify|--rollback|--reload]" ;;
esac
