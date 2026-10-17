#!/usr/bin/env bash
# ============================================================================
# GeoLite2-Country MMDB 更新器(Issue #114 阶段 E 交付;R2 修正版)
#
# 职责(AC4):合法下载(需 owner 已接受 MaxMind GeoLite2 EULA 并持有
# license key)→ 临时下载 → **硬结构校验**(mmdb_validate.py:完整 metadata
# 解析 + 字段语义 + 走树越界门,拒绝「标记子串」假 PASS)→ 原子替换
# (rename(2),不覆盖正被 mmap 的旧文件,配合 nginx geoip2 auto_reload 免
# reload 生效)→ 失败自动恢复旧库。
#
# R2 修正:
#   1. 凭据零 argv:license key 只进同目录 0600 curl 配置文件(-K),不再拼进
#      URL 命令行参数(OS 进程 ps/proc 可见即泄漏面);curl stderr 经脱敏后
#      才输出(key 与 license_key= 查询参数一律抹除);
#   2. 回滚常备:成功更新后**保留** ${MMDB_PATH}.bak(上一个已验证有效库),
#      --rollback 在最需要时(更新后发现问题)恒可用;每次成功更新用当前
#      现网文件刷新 .bak。
#
# 默认不改变任何运行面:不 reload/重启 nginx(除非显式 --reload);
# 不打印、不持久化 license key;不输出任何访客 IP(校验探针只用
# RFC 5737 文档地址)。mmdb_validate.py 同目录,零第三方依赖。
#
# 用法(生产宿主,受权操作者):
#   sudo ./update-geolite2.sh              # 首次安装或周期更新
#   sudo ./update-geolite2.sh --verify     # 只校验现网文件(只读)
#   sudo ./update-geolite2.sh --rollback   # 回滚到上一个已验证有效库(.bak)
#   sudo ./update-geolite2.sh --reload     # nginx -t 通过后 reload(可选;
#                                          # 已配置 auto_reload 时通常不需要)
#
# 周期更新(cron 示例,每周三 04:17,失败退出码留给 cron 邮件):
#   17 4 * * 3 root /home/ubuntu/ask-ai/deploy/prod/geoip2/update-geolite2.sh
#
# 凭据秘密管理(AC4):license key 只存生产宿主文件,权限 0600,不入仓库、
# 不入环境变量导出面、不进任何进程 argv、不出现在本脚本任何输出。
# 若泄露:MaxMind 账户轮换。
# ============================================================================
set -euo pipefail

MMDB_PATH="${GEOLITE2_MMDB_PATH:-/etc/nginx/geoip/GeoLite2-Country.mmdb}"
KEY_FILE="${GEOLITE2_LICENSE_KEY_FILE:-/etc/ask-ai-geoip/geolite2-license.key}"
# MaxMind 官方下载端点(直连 tar.gz;suffix 参数化便于未来换库)。
# license key 不拼在本 URL 的命令行参数里 —— 下载时写入 0600 curl 配置文件。
DOWNLOAD_URL="${GEOLITE2_DOWNLOAD_URL:-https://download.maxmind.com/geoip/databases/GeoLite2-Country/download?suffix=tar.gz}"
# GeoLite2-Country 历史体积约 6-9MB;低于 1MB 一律判损坏(fail-closed)。
MIN_BYTES=1000000
NGINX_BIN="${NGINX_BIN:-nginx}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { printf '[geoip2-update] %s\n' "$*"; }
die() { printf '[geoip2-update] FAIL: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- 校验 ------
# 硬结构校验:完整 metadata 解码 + 字段语义 + 布局一致 + 真实走树越界门
# (mmdb_validate.py,纯 stdlib;探针为 RFC 5737 文档地址,非真实访客 IP)。
# 任何一步失败即非零退出 → 调用方拒绝落库(fail-closed)。
validate_mmdb() {
    local f="$1"
    [ -s "$f" ] || { log "校验失败:文件不存在或为空"; return 1; }
    python3 "$SCRIPT_DIR/mmdb_validate.py" "$f" --min-bytes "$MIN_BYTES"
}

# ---------------------------------------------------------------- 脱敏 ------
# curl 失败时,stderr 缓冲经脱敏再输出:key 字面量与 license_key= 查询参数
# 一律抹除(key 经环境变量传给本函数的 python3 —— 环境仅同用户可见,
# 不进 argv;这是唯一一处 key 需要在进程间传递的地方)。
_redact_and_die() { # <errfile> <rc>
    CURL_SCRUB_KEY="$key" python3 - "$1" <<'PY' >&2
import os, re, sys

try:
    text = open(sys.argv[1], errors="replace").read()
except OSError:
    text = ""
key = os.environ.get("CURL_SCRUB_KEY", "")
if key:
    text = text.replace(key, "***")
text = re.sub(r"license_key=[^&\s\"']+", "license_key=***", text)
sys.stdout.write(text)
PY
    die "下载失败(curl exit=$2;网络/凭据/许可状态);现网文件未受影响"
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

    log "开始下载(凭据经 0600 curl 配置文件,零 argv 暴露)…"
    # license key 只写进同目录 0600 curl 配置文件(-K):不进 URL 命令行参数,
    # 不进进程 argv;配置文件随 tmpdir(0700)清理。
    local curlcfg="$tmpdir/curl.cfg"
    local sep='?'
    case "$DOWNLOAD_URL" in *\?*) sep='&' ;; esac
    printf 'silent\nshow-error\nmax-time = "300"\nurl = "%s%slicense_key=%s"\n' \
        "$DOWNLOAD_URL" "$sep" "$key" >"$curlcfg"
    chmod 0600 "$curlcfg"
    set +e
    curl -K "$curlcfg" --retry 2 \
        -o "$tmpdir/geolite2-country.tar.gz" \
        2>"$tmpdir/curl.err"
    local rc=$?
    set -e
    [ "$rc" -eq 0 ] || _redact_and_die "$tmpdir/curl.err" "$rc"
    gzip -t "$tmpdir/geolite2-country.tar.gz" || die "gzip 完整性校验失败"
    # 解压前检查成员路径,拒绝路径穿越
    if tar -tzf "$tmpdir/geolite2-country.tar.gz" | grep -q '\.\./'; then
        die "压缩包含可疑路径(../),拒绝解压"
    fi
    tar -xzf "$tmpdir/geolite2-country.tar.gz" -C "$tmpdir"
    local newdb
    newdb=$(find "$tmpdir" -type f -name '*.mmdb' | head -1)
    [ -n "$newdb" ] || die "压缩包内未找到 .mmdb"
    validate_mmdb "$newdb" || die "新库硬结构校验未通过;现网文件未受影响"

    # 备份旧库(cp 保留现网文件继续服务,替换瞬间才切换);成功后保留 .bak
    # 作为「上一个已验证有效库」—— --rollback 恒可用(R2 修正,不再删除)。
    if [ -f "$MMDB_PATH" ]; then
        cp -p "$MMDB_PATH" "${MMDB_PATH}.bak"
    fi

    chmod 0644 "$newdb"
    # 原子替换:同目录 rename(2)。旧 mmap 句柄继续读旧 inode 直到 auto_reload。
    mv -f "$newdb" "$MMDB_PATH"
    swapped=1
    validate_mmdb "$MMDB_PATH" || die "替换后复核未通过(将自动回滚)"
    swapped=0    # 复核通过,清理 trap 不再回滚
    trap - EXIT
    rm -rf "$tmpdir"

    log "更新完成: $MMDB_PATH"
    log "上一个已验证有效库保留于 ${MMDB_PATH}.bak(--rollback 恒可用;下次更新自动刷新)"
    if "$NGINX_BIN" -T 2>/dev/null | grep -q 'auto_reload'; then
        log "nginx geoip2 auto_reload 已配置,将在检查周期内免 reload 生效"
    else
        log "提示:当前 nginx 配置未启用 auto_reload;执行 --reload 使新库生效"
    fi
    log "建议观察: sudo tail -n 20 /var/log/nginx/error.log  (应无 geoip2 报错)"
}

do_rollback() {
    [ "$(id -u)" -eq 0 ] || die "请用 sudo 运行"
    [ -f "${MMDB_PATH}.bak" ] || die "无 .bak 可回滚(首次安装后从未成功更新过)"
    validate_mmdb "${MMDB_PATH}.bak" || die ".bak 校验未通过,拒绝回滚到损坏文件"
    mv -f "${MMDB_PATH}.bak" "$MMDB_PATH"
    log "已回滚到上一个已验证有效库: $MMDB_PATH"
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
