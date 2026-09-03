#!/usr/bin/env bash
# 生成 RELEASE.json 发布清单(Issue #10 版本与发布治理)。
#
# CI(构建期)与本地镜像构建共用本脚本;产物随镜像 COPY 进 /app/RELEASE.json,
# 由 backend 启动时一次性加载为进程级 release identity(fail-closed)。
#
# 用法:
#   scripts/generate_release_manifest.sh <version> <git_sha> [image] [ci_run_id] [output]
#     version   SemVer(允许 v 前缀,归一为无前缀存储);非 tag 构建用 0.0.0+main.<sha8>
#     git_sha   精确源码 commit(7..40 位 hex)
#     image     镜像引用(默认 ghcr.io/harryhua-ai/ask-ai:dev)
#     ci_run_id CI 运行 id(可选)
#     output    输出路径(默认 ./RELEASE.json)
#
# built_at 由本脚本生成 = 权威构建钟(CI/构建机时间),绝非浏览器时间。
set -euo pipefail

VERSION="${1:?用法: $0 <version> <git_sha> [image] [ci_run_id] [output]}"
GIT_SHA="${2:?缺少 git_sha}"
IMAGE="${3:-ghcr.io/harryhua-ai/ask-ai:dev}"
CI_RUN_ID="${4:-}"
OUTPUT="${5:-RELEASE.json}"

# SemVer 校验(允许可选 v 前缀;与 backend/release.py 同一词法)
SEMVER_RE='^(v|V)?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-((0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*)(\.(0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*))*))?(\+([0-9a-zA-Z-]+(\.[0-9a-zA-Z-]+)*))?$'
if ! printf '%s' "$VERSION" | grep -Eq "$SEMVER_RE"; then
    echo "❌ version 非法 SemVer: $VERSION" >&2
    exit 2
fi
VERSION="${VERSION#v}"; VERSION="${VERSION#V}"

if ! printf '%s' "$GIT_SHA" | grep -Eq '^[0-9a-fA-F]{7,40}$'; then
    echo "❌ git_sha 非法(期望 7..40 位 hex): $GIT_SHA" >&2
    exit 2
fi
GIT_SHA="$(printf '%s' "$GIT_SHA" | tr 'A-F' 'a-f')"

if [ -z "$IMAGE" ]; then
    echo "❌ image 不能为空" >&2
    exit 2
fi

BUILT_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

python3 - "$OUTPUT" "$VERSION" "$GIT_SHA" "$BUILT_AT" "$IMAGE" "$CI_RUN_ID" <<'PYEOF'
import json, sys
out, version, sha, built_at, image, run_id = sys.argv[1:7]
manifest = {
    "version": version,
    "git_sha": sha,
    "built_at": built_at,
    "image": image,
    **({"ci_run_id": run_id} if run_id else {}),
}
with open(out, "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
print(f"RELEASE.json -> {out}: version={version} git_sha={sha[:12]} built_at={built_at}")
PYEOF
