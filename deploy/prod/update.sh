#!/usr/bin/env bash
# ask-ai 生产部署/更新脚本(tesla-t4)—— #10 版本与发布治理契约
#
# 用法(自 v1.0.0 起强制版本化):
#   ssh tesla-t4 'cd ~/ask-ai && ./deploy/prod/update.sh <version-tag>'   # 如 v1.0.0
#   回滚 = 同一命令 + 上一个不可变版本 tag(如 ./deploy/prod/update.sh v0.9.0)
#
# 回滚兼容契约(#46 RELEASE-ROLLBACK-COMPATIBILITY):
#   - 回滚兼容性由【目标发布】冻结镜像内的 compatibility manifest 声明权威裁定;
#   - 目标发布声明 previous_compatible: true ⇒ 普通 previous-tag 回滚照常可用;
#   - 目标发布声明 previous_compatible: false ⇒ 普通 previous-tag 回滚不再适用。
#     2026-10-22 通道裁决(A #138 正式授权):新增离线 RSA 签发与 4 项
#     Environment Secrets 退出发布依赖(User 无私钥/新增秘密配置通道;整改
#     实质已由已验收的来源清零与 #187 恢复门禁落地)。不安全旧版回滚改由
#     【deployed-version 守卫】强制([1.3/6],标记 ASKAI_DEPLOYED_VERSION_GUARD_V1):
#       - 已部署版本事实 = 宿主部署标记 deploy/prod/.deployed-release.json
#         (本脚本每次成功部署后写;优先)> 运行中 backend 容器
#         /app/RELEASE.json + /app/deploy/prod/compatibility.json(只读
#         docker exec 读;已部署事实与被部署目标分离,不自证);
#       - 已部署发布声明 previous_compatible=false 且目标 tag 旧于已部署
#         ⇒ 任何 rollout mutation 之前 fail-closed(历史 ref dispatch 的
#         旧 workflow 调用本脚本同样被拦截 —— evaluator 冻结于各自镜像,
#         无法覆盖该旁路面,本守卫补上);
#       - 已部署版本不可证明 ⇒ 显式告警后继续:仅在宿主无任何已部署 r3
#         状态(无标记、无运行容器)的 bootstrap 语境可达;此时不存在
#         "从声明不兼容的已发布版本回退"的状态(诚实披露,非静默跳过);
#       - 退役整改证据通道的三参数(记录文件/证据工件/验证公钥)整体移除;
#         --remediation-ack 仅保留 CLI 兼容并透传 evaluator 显式判 FAIL
#         (字符串 ACK 永不构成放行,A #138 P3 原则不变)。
#   - 本脚本不自行判定回退安全性,也不自动回滚 —— 只执行目标发布的冻结声明。
#
# 宿主脚本身份自验(R6v3,A R6v2 审查阻塞 3 修复;--pinned-update-sh-sha256):
#   - 工作流恒传 --pinned-update-sh-sha256 <64hex>(= 受信工件哈希,git 冻结
#     发行树权威解析);本脚本在【自身 flock 持有区间内】(内部锁获取后、
#     任何 mutation 之前,步骤 [1.2/6])对自身文件计算 sha256 并与钉扎值
#     精确比对,不一致 ⇒ fail-closed(零 rollout)——「校验 + 执行」在同一
#     锁持有区间内原子完成,消除 R6v2「锁外预复核与执行之间的竞争窗」;
#   - 诚实边界(不夸大):DB migration 由【冻结镜像一次性容器】执行
#     (workflow 步骤 4),【不依赖本宿主脚本】⇒ 迁移与本脚本之间的宿主
#     脚本漂移只会导致 rollout 在 [1.2/6] 被 fail-closed 拒绝(migration
#     本身不受宿主脚本影响);所有「宿主脚本不匹配 ⇒ 拒绝」发生在任何
#     rollout mutation 之前,但不宣称阻止 migration;
#   - 手动 break-glass 旁路:本脚本在提供 --pinned-update-sh-sha256 时同样
#     强制自验(工作流恒传);未提供该旗标时不做哈希自验,由 evaluator
#     证据门(工件 SHA256 + 签名审批 + 身份绑定)独立兜底 —— 该边界如实
#     写明,本脚本不宣称未钉扎路径具备哈希自验能力。
#
# 契约(#10 冻结):
#   - 缺少 tag 参数 → 失败(禁止隐式升级);
#   - latest → 拒绝(生产部署/回滚必须显式不可变版本 tag);
#   - backend / sync-cron / sync-executor 三应用服务**同批**更新到同一 tag,
#     不允许任何服务停留在不同 ASK-AI release tag;
#   - 切换前校验镜像内 RELEASE.json(version/git_sha)与请求 tag 一致(fail-closed);
#   - 切换后核验 /health 上报 version 与请求 tag 一致(运行时身份 = 镜像身份);
#   - 基础设施服务(postgres/weaviate 等)不受影响。
#
# 前置(一次性):
#   1. docker login ghcr.io -u harryhua-ai -p <GHCR token>(首次)
#   2. cp deploy/prod/.env.example .env,填生产凭证(仓库根 .env)
#   3. corpus 在 /home/ubuntu/ask-ai-corpus;models 在 /home/ubuntu/ask-ai/models
#
# ⚠️ 本脚本只适用于内嵌 RELEASE.json 的镜像(#10 之后由 CI 构建的 tag 镜像);
#    旧镜像(无清单)会被步骤 [3/6] 显式拒绝,不会静默部署。
#
# 部署后证据记录(运行簿契约,#10 · adoption 跟进 ③):
#   顺序不可颠倒:DEPLOY → VERIFY RUNTIME IDENTITY → RECORD EVIDENCE
#   1. 本脚本完整成功(退出码 0;含 [3/6] 镜像 RELEASE.json 断言与
#      [5/6] /health 运行时身份核验);
#   2. 之后才允许:
#        GH_TOKEN=<token> python3 scripts/record_production_deployment.py --tag <tag>
#      它回写 GitHub Deployment + status=success,作为生产 SHA 的机器可读镜像;
#   3. 绝不允许:未部署先记录 / 本脚本失败仍记录 / 部署刚启动就记录成功 ——
#      违反顺序写入的记录是伪证(守卫 production-closure 按 SHA 一致 +
#      最新 status=success + Runtime Acceptance manifest 三重核验)。
#
# 两条等价部署路径(同一原语、同一证据模型,#10 生产部署编排):
#   - 正常路径:GitHub Actions deploy-production.yml(workflow_dispatch,
#     production Environment 审批)→ Guard → Deployment=in_progress →
#     SSH + flock 调本脚本 → /health version+git_sha 双断言
#     (scripts/verify_runtime_identity.py)→ Deployment=success;
#   - break-glass 路径:手动 SSH 调本脚本 → 用同一验证器独立核验
#     version+git_sha(发布 SHA 须来自仓库侧权威解析;主机 ~/ask-ai 目录
#     不是 git 仓库,不得用主机侧 git 解析身份)→ 同一 recorder 记录
#     (原子模式或 --phase success)。
#   两路径写同一 GitHub Deployment 模型,守卫核验无差别;无第二部署真相。

set -euo pipefail

IMAGE="ghcr.io/harryhua-ai/ask-ai"

# 参数解析(#46 REVIEW_1 blocker 5):位置参数 = 不可变 tag;可选
# --remediation-ack <gate> 仅在目标发布的 compatibility manifest 声明
# previous_compatible=false 时由 preflight evaluator 消费(精确匹配其
# remediation_gate)。普通 previous-tag 回滚不受影响;声明不兼容的发布
# 必须显式确认所声明的修复门才能继续(见文末 RELEASE-ROLLBACK-COMPATIBILITY)。
TAG=""
REMEDIATION_ACK=""
PINNED_UPDATE_SH_SHA256=""
while [ $# -gt 0 ]; do
    case "$1" in
        --remediation-ack)
            [ -n "${2:-}" ] || { echo "❌ --remediation-ack 需要 gate 值" >&2; exit 2; }
            REMEDIATION_ACK="$2"; shift 2 ;;
        --remediation-ack=*)
            REMEDIATION_ACK="${1#*=}"; shift ;;
        --pinned-update-sh-sha256)
            [ -n "${2:-}" ] || { echo "❌ --pinned-update-sh-sha256 需要 64 位 hex 钉扎值" >&2; exit 2; }
            PINNED_UPDATE_SH_SHA256="$2"; shift 2 ;;
        --pinned-update-sh-sha256=*)
            PINNED_UPDATE_SH_SHA256="${1#*=}"; shift ;;
        --*)
            echo "❌ 未知选项: $1" >&2; exit 2 ;;
        *)
            if [ -z "$TAG" ]; then TAG="$1"; shift; else
                echo "❌ 多余位置参数: $1(用法: $0 <version-tag> [--pinned-update-sh-sha256 <64hex>] [--remediation-ack <gate>])" >&2; exit 2
            fi ;;
    esac
done
if [ -z "$TAG" ]; then
    echo "❌ 缺少版本 tag 参数。用法: $0 <version-tag>(如 v1.0.0;回滚传上一个不可变 tag)" >&2
    exit 2
fi

# ---------- [1/6] 版本化契约守卫 ----------
if [ -z "$TAG" ]; then
    echo "❌ 缺少版本 tag 参数。用法: $0 <version-tag>(如 v1.0.0;回滚传上一个不可变 tag)"
    exit 2
fi
if [ "$TAG" = "latest" ]; then
    echo "❌ 生产部署/回滚禁止 latest(#10 契约):必须显式不可变版本 tag(如 v1.0.0)"
    exit 2
fi
export ASKAI_IMAGE_TAG="$TAG"
# compose 文件相对脚本位置;脚本从仓库根运行(cd ~/ask-ai)
COMPOSE_FILE="$(dirname "$0")/docker-compose.yml"
BACKEND_PORT="${BACKEND_PORT:-18000}"
EXPECTED_VERSION="${TAG#v}"   # RELEASE.json 内为无前缀 SemVer

echo "=== ask-ai 部署:$IMAGE:$TAG(期望 version=$EXPECTED_VERSION)==="

# ---------- [1.1/6] 宿主部署锁(R6v3 阻塞 3:锁所有权移入本脚本) ----------
# 本脚本自身获取与 provision/migrate 同一把宿主锁(非阻塞;与并发部署/
# 更新互斥)—— 锁从任何 mutation 之前一直持有到脚本退出,自验与执行
# 由此处于同一锁持有区间(替代 R6v2 由 workflow 外层 flock 包装的形态)。
exec 9>"${TMPDIR:-/tmp}/askai-deploy.lock"
flock -w 0 9 || { echo "❌ 部署锁被占用(另一生产变更在执行),拒绝部署" >&2; exit 1; }

# ---------- [1.2/6] 宿主脚本身份自验(R6v3 阻塞 3;锁内、任何 mutation 前) ----------
# 工作流恒传 --pinned-update-sh-sha256(= 受信工件哈希,git 冻结发行树权威
# 解析)。在自身 flock 持有区间内对自身文件实测 sha256 并精确比对;不一致
# ⇒ 零 rollout fail-closed(自分发后漂移/篡改在执行前被拒)。
# 诚实边界:未提供钉扎值时不做哈希自验(手动 break-glass 旁路),由
# evaluator 证据门独立兜底 —— 见头注。
if [ -n "$PINNED_UPDATE_SH_SHA256" ]; then
    case "$PINNED_UPDATE_SH_SHA256" in
        *[!0-9a-f]*|"")
            echo "❌ --pinned-update-sh-sha256 形状非法(须为 64 位小写 hex)—— 任何 mutation 之前 fail-closed" >&2
            exit 1 ;;
    esac
    if [ "${#PINNED_UPDATE_SH_SHA256}" -ne 64 ]; then
        echo "❌ --pinned-update-sh-sha256 形状非法(须为 64 位小写 hex)—— 任何 mutation 之前 fail-closed" >&2
        exit 1
    fi
    SELF_SH_HASH="$(python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$0")"
    if [ "$SELF_SH_HASH" != "$PINNED_UPDATE_SH_SHA256" ]; then
        echo "❌ update.sh 锁内自验失败:自身文件 sha256 与 --pinned-update-sh-sha256 钉扎值不一致" >&2
        echo "   (宿主脚本与受信工件不一致:自分发后漂移/篡改;got=$SELF_SH_HASH want=$PINNED_UPDATE_SH_SHA256)" >&2
        echo "   —— 零 rollout:任何 mutation 之前 fail-closed(R6v3 阻塞 3:校验+执行同锁区间原子完成)" >&2
        exit 1
    fi
    echo "  ✅ 宿主脚本身份自验通过(锁内;sha256=$SELF_SH_HASH;先于任何 mutation)"
fi


# ---------- [1.3/6] deployed-version 回滚守卫(ASKAI_DEPLOYED_VERSION_GUARD_V1) ----------
# 见头注「不安全旧版回滚」节。已部署事实源优先级:宿主标记 > 运行中 backend
# 容器(只读)。已部署声明 previous_compatible=false 且目标旧于已部署 ⇒ 在
# 任何 mutation(含 [2/6] 镜像拉取)之前 fail-closed。此守卫独立于 evaluator
# (evaluator 随各自镜像冻结;经历史 ref dispatch 调用旧 workflow 时,目标
# 镜像的 evaluator 不含本语义 —— 本守卫在宿主侧补上该旁路面)。
DEPLOYED_VERSION_ARGS=()
MARKER_FILE="$(dirname "$0")/.deployed-release.json"
DEPLOYED_VERSION=""
DEPLOYED_PREV_COMPAT=""
if [ -f "$MARKER_FILE" ]; then
    DEPLOYED_VERSION="$(python3 -c 'import json,sys
try: print(str(json.load(open(sys.argv[1])).get("version") or ""))
except Exception: print("")' "$MARKER_FILE" 2>/dev/null || true)"
    DEPLOYED_PREV_COMPAT="$(python3 -c 'import json,sys
try: m=json.load(open(sys.argv[1])); print("true" if m.get("previous_compatible", True) else "false")
except Exception: print("")' "$MARKER_FILE" 2>/dev/null || true)"
fi
if [ -z "$DEPLOYED_VERSION" ]; then
    BACKEND_CID="$(docker compose -f "$COMPOSE_FILE" ps -q backend 2>/dev/null || true)"
    if [ -n "$BACKEND_CID" ]; then
        DEPLOYED_VERSION="$(docker exec "$BACKEND_CID" cat /app/RELEASE.json 2>/dev/null \
            | python3 -c 'import json,sys
try: print(str(json.load(sys.stdin).get("version") or ""))
except Exception: print("")' 2>/dev/null || true)"
        DEPLOYED_PREV_COMPAT="$(docker exec "$BACKEND_CID" cat /app/deploy/prod/compatibility.json 2>/dev/null \
            | python3 -c 'import json,sys
try: m=json.load(sys.stdin); print("true" if m.get("rollback",{}).get("previous_compatible", True) else "false")
except Exception: print("")' 2>/dev/null || true)"
    fi
fi
askai_version_lt() {  # $1=candidate $2=deployed → rc0 当 candidate < deployed(可解析时)
    [ "$(python3 -c 'import re,sys
def v(s):
    m=re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:-r(\d+))?", str(s).strip())
    return (int(m.group(1)),int(m.group(2)),int(m.group(3)),int(m.group(4) or 0)) if m else None
a,b=v(sys.argv[1]),v(sys.argv[2])
print("lt" if (a is not None and b is not None and a<b) else "no")' "$1" "$2")" = "lt" ]
}
if [ -n "$DEPLOYED_VERSION" ] && [ "$DEPLOYED_PREV_COMPAT" = "false" ]; then
    if askai_version_lt "$EXPECTED_VERSION" "$DEPLOYED_VERSION"; then
        echo "❌ deployed-version 回滚守卫:目标 $TAG 旧于当前已部署 $DEPLOYED_VERSION," >&2
        echo "   而已部署发布声明 previous_compatible=false ⇒ 普通 previous-tag 回滚不适用" >&2
        echo "   (旧上传来源默认可见性语义可能重暴露已清理/禁止公开的数据;零 rollout fail-closed)" >&2
        exit 1
    fi
    echo "  ✅ deployed-version 回滚守卫:目标 $TAG 不旧于已部署 $DEPLOYED_VERSION(先于任何 mutation)"
    DEPLOYED_VERSION_ARGS=(--deployed-release-version "$DEPLOYED_VERSION")
elif [ -n "$DEPLOYED_VERSION" ]; then
    echo "  ✅ deployed-version 回滚守卫:已部署 $DEPLOYED_VERSION 声明回退兼容,旧版回滚语义不变"
    DEPLOYED_VERSION_ARGS=(--deployed-release-version "$DEPLOYED_VERSION")
else
    echo "  ⚠️ deployed-version 回滚守卫:已部署版本不可证明(无宿主标记且无运行中" >&2
    echo "     backend)—— 仅 bootstrap 语境可达(宿主无任何已部署 r3 状态);显式告警后继续" >&2
fi

# ---------- post-deploy 回退指引(#46 REVIEW_2;AC4 条件化) ----------
# post-deploy operator guidance 必须遵循【本次已部署发布】冻结声明的 rollback
# verdict(由 [3.5/6] 从镜像内 compatibility manifest 读取):
#   previous_compatible=true  ⇒ 普通 previous-tag 回滚指引照常输出;
#   previous_compatible=false ⇒ 绝不输出普通回滚指引,改为输出所声明的
#                                remediation gate 与显式恢复路径指向;
#   pre_contract 时代          ⇒ 普通指引 + 显式「回退兼容性未证明」deferred 注记。
# 本脚本永不执行自动回滚(只输出指引)。
print_postdeploy_rollback_guidance() {
    if [ "${PREFLIGHT_ERA:-contract}" = "pre_contract" ]; then
        echo "回滚:./deploy/prod/update.sh <上一个不可变版本 tag>(同一契约;前契约发布,回退兼容性未证明 —— 显式 deferred)"
        return 0
    fi
    if [ "${ROLLBACK_COMPATIBLE:-true}" = "true" ]; then
        echo "回滚:./deploy/prod/update.sh <上一个不可变版本 tag>(同一契约)"
    else
        echo "⚠️ 回退兼容:本发布声明 previous_compatible=false —— 普通 previous-tag 回滚不适用。"
        echo "   本发布声明的修复门(remediation gate): ${ROLLBACK_GATE:-<未声明>}"
        echo "   如需回退/恢复,必须先按该门指向的 remediation/recovery path 显式执行后再评估;"
        echo "   本脚本不执行自动回滚。"
    fi
}

# ---------- [2/6] 拉取镜像 ----------
echo "[2/6] 拉取镜像 $IMAGE:$TAG ..."
docker compose -f "$COMPOSE_FILE" pull

# ---------- [3/6] 镜像内 RELEASE.json 断言(fail-closed) ----------
echo "[3/6] 校验镜像内发布清单 ..."
CID=$(docker create "$IMAGE:$TAG")
RELEASE_TMP="$(mktemp /tmp/askai-release.XXXXXX.json)"
docker cp "$CID:/app/RELEASE.json" "$RELEASE_TMP" || {
    docker rm "$CID" >/dev/null 2>&1 || true
    echo "❌ 镜像内无 RELEASE.json:$TAG 不是 #10 契约的版本化镜像,拒绝部署"
    exit 1
}
docker rm "$CID" >/dev/null
ACTUAL_VERSION=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['version'])" "$RELEASE_TMP")
ACTUAL_SHA=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['git_sha'])" "$RELEASE_TMP")
# Issue #46 REVIEW_1 blocker 3:时代判定源 = 镜像内不可变 RELEASE.json 的
# compatibility_contract 旗标(构建期由 generate_release_manifest.sh 写入),
# 独立于门禁工件(evaluator/manifest)自身的存在性 —— 打包回归不得把契约期
# 发布静默降级为有界路径。前 #46 构建无此键 ⇒ 天然 pre_contract。
COMPATIBILITY_CONTRACT=$(python3 -c "import json,sys;print('true' if json.load(open(sys.argv[1])).get('compatibility_contract') else 'false')" "$RELEASE_TMP")
if [ "$COMPATIBILITY_CONTRACT" = "true" ]; then
    PREFLIGHT_ERA="contract"
else
    PREFLIGHT_ERA="pre_contract"
fi
echo "  兼容性契约时代: $PREFLIGHT_ERA(来源 = 镜像内 RELEASE.json)"
rm -f "$RELEASE_TMP"
if [ "$ACTUAL_VERSION" != "$EXPECTED_VERSION" ]; then
    echo "❌ 镜像内 version=$ACTUAL_VERSION ≠ 请求 $EXPECTED_VERSION,拒绝部署"
    exit 1
fi
if [ -z "$ACTUAL_SHA" ]; then
    echo "❌ 镜像内 git_sha 为空,拒绝部署"
    exit 1
fi
echo "  ✅ 镜像身份: version=$ACTUAL_VERSION git_sha=$ACTUAL_SHA"

# ---------- [3.5/6] 发布兼容性 preflight(#46;fail-closed;先于任何 mutation) ----------
# evaluator 与 manifest 都从**请求的精确不可变镜像** "$IMAGE:$TAG" 内提取
# (REVIEW_1 blocker 2:绝不允许 untagged/latest 引用)。时代判定来自 [3/6]
# 已核验的镜像内 RELEASE.json compatibility_contract 旗标(独立/不可变/确定性;
# blocker 3:禁止以门禁工件存在性推断时代):
#   - contract 时代:evaluator 与 manifest 必须真实存在(打包回归 ⇒ fail-closed),
#     判定全部由 evaluator 给出;deployed-version 回滚守卫贯通不安全旧版
#     回滚拒绝(2026-10-22 通道裁决);
#   - pre_contract 时代:有界兼容路径,显式留痕(AC4)。
# 本步骤只是调用者,不是 policy engine。
echo "[3.5/6] 发布兼容性 preflight..."
# rollback verdict 缺省 = 前契约语境未证明(指引函数对 pre_contract 有专门分支;
# contract 时代由下方 manifest 读取覆盖)
ROLLBACK_COMPATIBLE="true"
ROLLBACK_GATE=""
PREFLIGHT_CID=$(docker create "$IMAGE:$TAG")
PREFLIGHT_MAN="$(mktemp /tmp/askai-compat.XXXXXX.json)"
PREFLIGHT_EVAL="$(mktemp /tmp/askai-preflight.XXXXXX.py)"
PREFLIGHT_EVAL_OK=1
docker cp "$PREFLIGHT_CID:/app/scripts/release_preflight.py" "$PREFLIGHT_EVAL" >/dev/null 2>&1 || PREFLIGHT_EVAL_OK=0
if [ "$PREFLIGHT_ERA" = "contract" ]; then
    # 契约期:evaluator 缺失 = 打包违约,显式 fail-closed(绝不降级为有界路径)
    if [ "$PREFLIGHT_EVAL_OK" != 1 ]; then
        docker rm "$PREFLIGHT_CID" >/dev/null 2>&1 || true
        rm -f "$PREFLIGHT_MAN" "$PREFLIGHT_EVAL"
        echo "❌ 契约期镜像缺失 scripts/release_preflight.py(打包违约,#46 blocker 1)—— 在任何 mutation 之前 fail-closed" >&2
        exit 1
    fi
    docker cp "$PREFLIGHT_CID:/app/deploy/prod/compatibility.json" "$PREFLIGHT_MAN" >/dev/null 2>&1 || true
    docker rm "$PREFLIGHT_CID" >/dev/null
    # manifest 缺失由 evaluator 自身 manifest_missing fail-closed(AC2);
    # --remediation-ack 仅当目标发布声明 rollback 不兼容时被 evaluator 消费。
    ACK_ARGS=()
    if [ -n "$REMEDIATION_ACK" ]; then
        ACK_ARGS=(--remediation-ack "$REMEDIATION_ACK")
    fi
    python3 "$PREFLIGHT_EVAL" \
        --manifest "$PREFLIGHT_MAN" \
        --env-file "$(dirname "$COMPOSE_FILE")/../../.env" \
        --release-tag "$TAG" \
        --release-sha "$ACTUAL_SHA" \
        ${DEPLOYED_VERSION_ARGS[@]+"${DEPLOYED_VERSION_ARGS[@]}"} \
        ${ACK_ARGS[@]+"${ACK_ARGS[@]}"} \
        || { rm -f "$PREFLIGHT_MAN" "$PREFLIGHT_EVAL"; exit 1; }
    # REVIEW_2:把本发布的 rollback verdict 保留到部署完成阶段 ——
    # post-deploy 指引据此条件化(stdlib 读取,值绝不外泄;manifest 内无密值)
    ROLLBACK_COMPATIBLE=$(python3 -c "import json,sys;m=json.load(open(sys.argv[1]));print('true' if m.get('rollback',{}).get('previous_compatible', True) else 'false')" "$PREFLIGHT_MAN")
    ROLLBACK_GATE=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('rollback',{}).get('remediation_gate','') or '')" "$PREFLIGHT_MAN")
    echo "  ✅ 兼容性 preflight 通过(先于 migration/rollout,零 mutation;rollback verdict 已保留)"
else
    # 前契约时代:有界兼容路径,显式留痕(各类未证明,deferred)
    docker rm "$PREFLIGHT_CID" >/dev/null 2>&1 || true
    echo "  ⚠️ PRE-CONTRACT RELEASE:$TAG(镜像 RELEASE.json 无 compatibility_contract 旗标)——"
    echo "     有界兼容路径(config/host/topology/dependencies/回退兼容 各类未证明,显式 deferred)"
fi
rm -f "$PREFLIGHT_MAN" "$PREFLIGHT_EVAL"

# ---------- [4/6] GPU 预检(基础设施不受影响,仅提示) ----------
echo "[4/6] GPU 预检..."
GPU_USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
echo "  GPU 已用: ${GPU_USED} MiB / 16384 MiB"
if [ "$GPU_USED" -gt 15000 ]; then
    echo "  ⚠️ GPU 显存 >15GB(共享服务占用高),继续但 sync 可能 OOM"
    echo "  若 OOM,降 EMBEDDER_BATCH_SIZE=8"
fi

# ---------- [5/6] 更新 backend(健康轮询 + 运行时版本核验) ----------
echo "[5/6] 更新 backend ..."
docker compose -f "$COMPOSE_FILE" up -d backend
# BGE 模型加载 ~45s+(有界轮询,最长 180s);就绪后核验 /health 上报版本
HEALTH_OK=0
HEALTH_JSON=""
for _ in $(seq 1 36); do
    sleep 5
    HEALTH_JSON=$(curl -sf "http://localhost:${BACKEND_PORT}/health" 2>/dev/null || true)
    if [ -n "$HEALTH_JSON" ]; then
        HEALTH_OK=1
        break
    fi
done
if [ "$HEALTH_OK" -ne 1 ]; then
    echo "  ❌ backend 健康检查失败(localhost:${BACKEND_PORT}/health,等待 180s)"
    echo "  查日志:docker compose -f $COMPOSE_FILE logs backend"
    exit 1
fi
RUNTIME_VERSION=$(printf '%s' "$HEALTH_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin).get('version',''))")
if [ "$RUNTIME_VERSION" != "$EXPECTED_VERSION" ]; then
    echo "  ❌ 运行时 /health version=$RUNTIME_VERSION ≠ 镜像 $EXPECTED_VERSION(身份不一致,拒绝完成部署)"
    exit 1
fi
echo "  ✅ backend 健康,运行时 version=$RUNTIME_VERSION(与镜像一致)"

# ---------- [6/6] 更新 sync-cron + sync-executor(三服务同 tag)并一致性核验 ----------
echo "[6/6] 更新 sync-cron + sync-executor ..."
docker compose -f "$COMPOSE_FILE" up -d sync-cron sync-executor
for SVC in backend sync-cron sync-executor; do
    SVC_CID=$(docker compose -f "$COMPOSE_FILE" ps -q "$SVC")
    SVC_IMG=$(docker inspect --format '{{.Config.Image}}' "$SVC_CID")
    if [[ "$SVC_IMG" != *":$TAG" ]]; then
        echo "  ❌ $SVC 镜像 $SVC_IMG ≠ $TAG(发布身份不一致)"
        exit 1
    fi
    echo "  ✅ $SVC @ $SVC_IMG"
done

echo ""
echo "=== 部署完成:$TAG(version=$EXPECTED_VERSION,git_sha=$ACTUAL_SHA)==="
docker compose -f "$COMPOSE_FILE" ps
# ---------- [6.1/6] 宿主部署标记(回滚守卫事实源;成功路径唯一写入点) ----------
# 值全部来自已校验来源(TAG 形状校验 / 镜像内 RELEASE.json / manifest 布尔);
# printf 模板固定,无注入面。
printf '{\n  "tag": "%s",\n  "version": "%s",\n  "git_sha": "%s",\n  "previous_compatible": %s,\n  "updated_at": "%s"\n}\n' \
    "$TAG" "$ACTUAL_VERSION" "$ACTUAL_SHA" "$ROLLBACK_COMPATIBLE" \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$MARKER_FILE"
echo "  ✅ 宿主部署标记已更新:$MARKER_FILE"

echo ""
print_postdeploy_rollback_guidance
echo "手动同步 / reindex(按需):"
echo "  docker compose -f $COMPOSE_FILE run --rm sync python scripts/sync.py            # 增量同步"
echo "  docker compose -f $COMPOSE_FILE run --rm sync python scripts/sync.py --reindex  # ⚠️ 删 collection 全量重灌"
echo ""
echo "查看日志:docker compose -f $COMPOSE_FILE logs -f backend"
