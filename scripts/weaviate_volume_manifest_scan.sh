#!/bin/sh
# weaviate_volume_manifest_scan.sh — Weaviate 数据卷**元数据清单**哈希扫描。
#
# r3gate R5 窄修(A 审查裁决 issuecomment-6281863560):替换
# deploy-production.yml 旧管道
#   `find . -type f -printf "%P\t%s\t%T@\n" 2>/dev/null | LC_ALL=C sort | sha256sum`
# 的三个确定性缺陷:
#   1. `-printf` 是 GNU find 扩展 —— Weaviate 1.28.0 官方镜像
#      (cr.weaviate.io/semitechnologies/weaviate,Alpine/BusyBox v1.37.0
#      实测)不支持,报错且无输出;
#   2. `2>/dev/null` 把扫描错误整体吞掉(失败原因不可见);
#   3. 管道无逐段校验 —— 末环 sha256sum 对空输入仍返回有效哈希
#      e3b0c44298fc…,空/部分清单两次扫出同一"合法"哈希 → G2 控制面
#      假 PASS 风险(真实容器实测:非空卷上旧命令 rc=0 输出空清单哈希)。
#
# 语义(与 R4-1 一致,**元数据清单,绝不读文件内容**):
#   清单 = 卷内全部常规文件的 `<路径>|<大小字节>|<mtime 自纪元秒>` 行,
#   LC_ALL=C 排序后取 sha256。客户内容零读取;元数据清单的原理性边界
#   (内容被整体替换而 path/size/mtime 秒级元数据恰好一致时不可辨别)
#   如实保留为 PARTIAL 残余,本脚本不宣称排除。
#
# fail-closed 契约(逐段显式校验,不依赖最后一环,不隐藏 stderr):
#   段0 卷根存在且可进入 → 段1 find 退出码显式校验 + stderr 必须为空
#   (stderr 始终透传,且非空即判部分遍历 → fail)→ 段2 文件清单非空(-s)
#   → 段3 逐文件 stat 成功 + size/mtime 纯数字形状校验 → 段4 sort/
#   sha256sum 退出码显式校验 → 哈希 64-hex 形状校验 → 文件计数 ≥1。
#   任一段失败:stderr 输出 `VOLSCAN FAIL: <原因>`(原因可见),退出码 3,
#   stdout 绝无哈希 —— 绝不产生空/部分清单哈希。
#
# 成功输出(stdout 恰一行,供 runner 端机器校验;FILES≥1 = 非空清单证据):
#   VOLSCAN_OK MANIFEST_SHA256=<64hex> FILES=<n>
#
# 用法(部署 workflow 经 stdin 送入 weaviate 容器,同 R3 脚本-via-stdin
# 无注入面模式;A 生产锚采集必须使用同一脚本与同一调用形态):
#   docker exec -i <weaviate 容器> sh -s /var/lib/weaviate < 本脚本
#
# 环境与已实测边界(2026-10-20,r4-weaviate-128 真实容器 BusyBox v1.37.0):
#   - 仅依赖 busybox 多调用二进制:sh/find/stat/sha256sum/mktemp/sort/cut;
#   - 路径按 find 换行协议:含换行的文件名不在 Weaviate 数据卷出现;含
#     `|` 的文件名会被行形状校验(size/mtime 必须纯数字)拦截为 fail;
#   - 000 目录使 find 部分遍历(实测 stderr + rc=1)→ fail-closed;
#   - 000 **常规文件**的元数据(path/size/mtime)仍可 stat(元数据读取
#     不需要文件读权限)→ 不构成扫描故障,与"元数据清单"语义一致,
#     内容仍零读取 —— 此为元数据清单的如实边界,非隐藏错误。
set -u

ROOT="${1:-/var/lib/weaviate}"

fail() {
    echo "VOLSCAN FAIL: $*" >&2
    exit 3
}

# 段0:卷根必须存在且可进入(目标不可达/不可进入 = fail-closed)
[ -d "$ROOT" ] || fail "卷根目录不可达: $ROOT"
cd "$ROOT" || fail "无法进入卷根: $ROOT"

LIST="$(mktemp "${TMPDIR:-/tmp}/askai-volscan-list.XXXXXX")" \
    || fail "mktemp(文件清单)失败"
META="$(mktemp "${TMPDIR:-/tmp}/askai-volscan-meta.XXXXXX")" \
    || fail "mktemp(元数据清单)失败"
ERR="$(mktemp "${TMPDIR:-/tmp}/askai-volscan-err.XXXXXX")" \
    || fail "mktemp(stderr 捕获)失败"
cleanup() { rm -f "$LIST" "$META" "$ERR"; }
trap cleanup EXIT INT TERM

# 段1:find —— 退出码显式校验;stderr 捕获后**始终透传**(绝不隐藏),
#       且 stderr 非空即视为部分遍历(如 000 目录权限拒绝)→ fail-closed
LC_ALL=C find . -type f -print > "$LIST" 2> "$ERR"
FIND_RC=$?
if [ -s "$ERR" ]; then
    cat "$ERR" >&2
fi
[ "$FIND_RC" -eq 0 ] || fail "find 扫描失败(rc=$FIND_RC;目标不可达/权限异常,stderr 已透传见上)"
[ ! -s "$ERR" ] || fail "find 扫描产生错误输出(部分遍历风险,stderr 已透传见上)"

# 段2:文件清单必须非空 —— 空/部分清单绝不产生哈希
[ -s "$LIST" ] || fail "文件清单为空(卷内 0 个常规文件)—— 空/部分清单绝不输出哈希"

# 段3:逐文件 stat 成功 + 行形状校验(任一失败 → fail-closed,绝无哈希)
N=0
while IFS= read -r F || [ -n "$F" ]; do
    [ -n "$F" ] || fail "文件清单含空行(部分扫描可疑)"
    LINE="$(stat -c '%n|%s|%Y' "$F")" \
        || fail "stat 失败: $F(扫描期间文件消失/权限异常)"
    SZ="${LINE##*|}"
    REST="${LINE%|*}"
    MT="${REST##*|}"
    case "$SZ" in ""|*[!0-9]*) fail "size 非数字(stat 输出形状异常): $LINE" ;; esac
    case "$MT" in ""|*[!0-9]*) fail "mtime 非数字(stat 输出形状异常): $LINE" ;; esac
    printf '%s\n' "$LINE" || fail "元数据清单写出失败"
    N=$((N + 1))
done < "$LIST" > "$META"

# 段4:排序 + sha256sum —— 退出码显式校验(最后一环不单独信任)
LC_ALL=C sort -o "$META" "$META" || fail "sort 失败"
[ -s "$META" ] || fail "元数据清单为空(与文件清单不一致)—— fail-closed"
SUM_OUT="$(sha256sum "$META")" || fail "sha256sum 失败"
HEX="$(printf '%s\n' "$SUM_OUT" | cut -d ' ' -f1)"
case "$HEX" in
    ????????????????????????????????????????????????????????????????) ;;
    *) fail "哈希形状异常(非 64 字符): $SUM_OUT" ;;
esac
case "$HEX" in
    *[!0-9a-f]*) fail "哈希含非 [0-9a-f] 字符: $HEX" ;;
esac
[ "$N" -ge 1 ] || fail "文件计数为 0 —— fail-closed"

echo "VOLSCAN_OK MANIFEST_SHA256=$HEX FILES=$N"
exit 0
