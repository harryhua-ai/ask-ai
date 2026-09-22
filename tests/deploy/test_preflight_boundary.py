"""Issue #46 AC1 RED→GREEN:preflight 边界必须先于任何生产 mutation。

v1.4.0 事故(#46 触发):发布身份/CI/SSH/镜像核验全部按设计工作,但
「既有生产环境能否安全升级到该发布」没有任何 pre-mutation 兼容性门 ——
一个声明了不兼容要求的 release 在现状下可以一路走到 DB migration 与
application rollout。

本文件是**边界位置**的机械断言(与实现无关):

- RED(现状):update.sh 与 deploy-production.yml 中不存在任何
  release_preflight 调用 ⇒ 声明不兼容要求的发布可越过 pre-mutation 边界;
- GREEN:evaluator 调用必须出现,且其位置必须先于
  a) workflow 的数据库迁移步骤(首个生产 mutation);
  b) update.sh 的应用 rollout(up -d backend)。
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
UPDATE_SH = REPO / "deploy" / "prod" / "update.sh"
WORKFLOW = REPO / ".github" / "workflows" / "deploy-production.yml"
MANIFEST = REPO / "deploy" / "prod" / "compatibility.json"
EVALUATOR = REPO / "scripts" / "release_preflight.py"


def test_release_tree_owns_compatibility_manifest_and_evaluator():
    """AC2:兼容性要求与 evaluator 属于发布树本身(随 tag 冻结,非宿主副本)。"""
    assert MANIFEST.is_file(), (
        "发布树必须自带 deploy/prod/compatibility.json(AC2:release-owned manifest;"
        "stdlib-JSON ⇒ 宿主侧 evaluator 零第三方依赖)"
    )
    assert EVALUATOR.is_file(), "scripts/release_preflight.py 必须属于发布树"


def _pos(text: str, needle: str) -> int:
    idx = text.find(needle)
    assert idx != -1, f"未找到锚点: {needle!r}"
    return idx


def test_update_sh_preflight_runs_before_application_rollout():
    """AC1:update.sh 必须在 rollout(up -d backend)之前调用 preflight evaluator。"""
    text = UPDATE_SH.read_text()
    preflight = text.find("release_preflight.py")
    rollout = _pos(text, "up -d backend")
    assert preflight != -1, (
        "RED(现状):update.sh 无任何兼容性 preflight —— 声明不兼容要求的发布"
        "可直接 rollout(生产 mutation),无 pre-mutation 边界(#46 v1.4.0 事故类)"
    )
    assert preflight < rollout, "preflight 必须先于应用 rollout"


def test_update_sh_preflight_after_identity_assertion():
    """preflight 使用冻结镜像,必须位于镜像 RELEASE.json 身份断言之后。"""
    text = UPDATE_SH.read_text()
    preflight = text.find("release_preflight.py")
    identity = _pos(text, "RELEASE.json")
    assert preflight > identity, "preflight 必须在镜像身份断言之后(绑定冻结镜像)"


def test_deploy_workflow_preflight_runs_before_database_migration():
    """AC1:workflow 的兼容性 preflight 必须先于数据库迁移步骤(首个 mutation)。"""
    text = WORKFLOW.read_text()
    preflight = text.find("release_preflight.py")
    migrate = _pos(text, "Migrate database")
    assert preflight != -1, (
        "RED(现状):deploy-production.yml 无兼容性 preflight 步骤 —— 声明不兼容"
        "要求的发布可直抵 DB migration(首个不可逆生产 mutation)"
    )
    assert preflight < migrate, "兼容性 preflight 必须先于数据库迁移步骤"


def test_workflow_preflight_is_fail_closed():
    """preflight 失败必须使 workflow 失败(fail-closed),不能仅告警。"""
    text = WORKFLOW.read_text()
    idx = text.find("release_preflight.py")
    assert idx != -1
    # preflight 调用所在的 run 块必须不吞退出码(set -euo pipefail 语义下
    # 直接调用;不允许 `|| true` 容忍失败)
    window = text[max(0, idx - 2000) : idx + 500]
    assert "release_preflight.py ... || true" not in window
    assert "|| true" not in window.split("release_preflight.py")[-1][:200], (
        "preflight 失败不得被 `|| true` 吞掉(fail-closed)"
    )


# --------------------------------------------------------------------------- #
# REVIEW_1 blockers 1/2/3/5:打包契约、精确镜像身份、era 判定、rollback 贯通
# --------------------------------------------------------------------------- #

DOCKERFILE = REPO / "Dockerfile"
DOCKERIGNORE = REPO / ".dockerignore"
GENERATOR = REPO / "scripts" / "generate_release_manifest.sh"


def test_dockerfile_packages_compatibility_manifest_into_image():
    """blocker 1:manifest 必须真实打进 frozen image(packaging contract,
    不只是 repo 文件存在)。.dockerignore 不得排除之。"""
    text = DOCKERFILE.read_text()
    assert 'COPY deploy/prod/compatibility.json /app/deploy/prod/compatibility.json' in text, (
        "Dockerfile 必须 COPY compatibility.json 进镜像(契约期镜像缺 manifest = "
        "preflight fail-closed 的前提是打包真实存在)"
    )
    di = DOCKERIGNORE.read_text()
    for line in di.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("!"):
            continue
        assert "deploy/" not in stripped, f".dockerignore 不得排除 deploy 相关路径: {stripped}"


def test_image_packaging_three_way_path_consistency():
    """镜像内路径三方一致:Dockerfile dest == update.sh 提取源 == workflow 提取源。"""
    docker_dest = "/app/deploy/prod/compatibility.json"
    assert docker_dest in DOCKERFILE.read_text()
    assert docker_dest in UPDATE_SH.read_text(), "update.sh 从镜像提取的路径必须与打包路径一致"
    assert docker_dest in WORKFLOW.read_text(), "workflow 提取路径必须与打包路径一致"
    # evaluator 打包:scripts/ 目录整目录 COPY(update.sh/workflow 提取
    # /app/scripts/release_preflight.py 必须存在对应来源)
    assert "COPY scripts/ ./scripts/" in DOCKERFILE.read_text()


def test_update_sh_preflight_extracts_exact_tagged_image():
    """blocker 2:preflight 必须从 "$IMAGE:$TAG" 提取;禁止 untagged 引用回潮。"""
    text = UPDATE_SH.read_text()
    assert 'PREFLIGHT_CID=$(docker create "$IMAGE:$TAG")' in text, (
        "preflight 必须从请求的精确不可变镜像提取(evaluator+manifest 同源)"
    )
    import re
    bare = re.search(r'docker create "\$IMAGE"(?!:)', text)
    assert bare is None, (
        "update.sh 存在 untagged docker create \"$IMAGE\"(= :latest 语义,REVIEW_1 blocker 2)"
    )


def _workflow_run_of(step_id_marker: str) -> str:
    text = WORKFLOW.read_text()
    idx = text.find(step_id_marker)
    assert idx != -1
    return text[idx: text.find("- name:", idx + 10)]


def test_era_decided_by_release_json_flag_not_artifact_absence():
    """blocker 3:era 判定源 = 镜像内 RELEASE.json compatibility_contract 旗标
    (独立/不可变/确定性);禁止以 evaluator 文件缺失直接推断 pre-contract。"""
    up = UPDATE_SH.read_text()
    assert "compatibility_contract" in up, "update.sh 必须读取镜像内时代旗标"
    assert "PREFLIGHT_ERA" in up
    # 有界路径分支必须由 ERA 驱动,而非 EVAL_OK(evaluator 存在性):
    # preflight 分支结构 = if [ "$PREFLIGHT_ERA" = "contract" ] … else 有界 …
    era_if = up.find('if [ "$PREFLIGHT_ERA" = "contract" ]')
    pre_contract_marker = up.find("PRE-CONTRACT RELEASE")
    assert era_if != -1 and pre_contract_marker != -1
    assert era_if < pre_contract_marker, (
        "有界兼容路径必须由 RELEASE.json 时代旗标分支驱动(if contract … else pre-contract)"
    )
    # era 分支与 evaluator 存在性检查之间不得存在「EVAL_OK ⇒ 有界」的推断链
    branch_block = up[era_if:pre_contract_marker]
    assert "PREFLIGHT_EVAL_OK" in branch_block, "契约期分支内做 evaluator 存在性检查"
    assert branch_block.index('PREFLIGHT_ERA') < branch_block.index("PREFLIGHT_EVAL_OK")
    # 契约期 evaluator 缺失 ⇒ 显式 fail-closed(打包违约),不得降级
    assert "打包违约" in up and "fail-closed" in up
    wf = WORKFLOW.read_text()
    assert "compatibility_contract" in wf, "workflow 时代判定必须读镜像内旗标"
    assert "打包违约" in wf, "workflow 契约期缺 evaluator 必须 fail-closed"


def test_release_manifest_generator_emits_era_flag():
    """blocker 3:era 旗标由构建期权威写入 RELEASE.json(不可变/确定性)。"""
    import json
    import subprocess

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "RELEASE.json"
        proc = subprocess.run(
            ["bash", str(GENERATOR), "v1.6.4", "a" * 40,
             "ghcr.io/harryhua-ai/ask-ai:v1.6.4", "7", str(out)],
            capture_output=True, text=True, check=False,
        )
        assert proc.returncode == 0, proc.stderr
        data = json.loads(out.read_text(encoding="utf-8"))
    assert data.get("compatibility_contract") is True, (
        "RELEASE.json 必须携带不可变时代旗标 compatibility_contract(true)"
    )


def test_update_sh_forwards_remediation_ack_and_documents_rollback_contract():
    """blocker 5:end-to-end invocation/runbook surface —— update.sh 必须接受
    并转发 --remediation-ack;runbook 必须声明 rollback 兼容契约语义。"""
    text = UPDATE_SH.read_text()
    assert "--remediation-ack" in text, "update.sh 必须接受 --remediation-ack"
    assert 'REMEDIATION_ACK="$2"' in text, "ack 值必须被捕获"
    assert "ACK_ARGS=(--remediation-ack \"$REMEDIATION_ACK\")" in text.replace("\\\n", ""), (
        "evaluator 调用必须转发 ack(真实 deployment path,非仅函数级)"
    )
    assert "RELEASE-ROLLBACK-COMPATIBILITY" in text, (
        "runbook 必须显式声明 rollback 兼容契约(previous_compatible=false ⇒ "
        "普通 previous-tag 回滚不再适用,需确认 remediation gate)"
    )


# --------------------------------------------------------------------------- #
# REVIEW_2:post-deploy operator guidance 条件化(AC4 端到端行为级)
# --------------------------------------------------------------------------- #


def _guidance_fn_bash() -> str:
    """从 update.sh 机械提取 print_postdeploy_rollback_guidance 函数体
    (纯 shell、零外部依赖,可在测试中真实执行)。"""
    text = UPDATE_SH.read_text()
    start = text.index("print_postdeploy_rollback_guidance() {")
    end = text.index("\n}", start) + 2
    return text[start:end]


def _run_guidance(env: dict) -> str:
    import subprocess

    proc = subprocess.run(
        ["bash", "-c", f"{_guidance_fn_bash()}\nprint_postdeploy_rollback_guidance"],
        env={"PATH": "/usr/bin:/bin", **env},
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_postdeploy_guidance_compatible_true_keeps_ordinary_rollback():
    """compatible=true ⇒ 普通 previous-tag 回滚指引存在(既有行为保持)。"""
    out = _run_guidance({"ROLLBACK_COMPATIBLE": "true", "ROLLBACK_GATE": ""})
    assert "回滚:./deploy/prod/update.sh <上一个不可变版本 tag>(同一契约)" in out


def test_postdeploy_guidance_compatible_false_removes_ordinary_and_names_gate():
    """compatible=false ⇒ 普通回滚指引不得出现;必须输出声明的 remediation gate
    与显式恢复路径指向,且声明不自动回滚。"""
    out = _run_guidance({
        "PREFLIGHT_ERA": "contract",
        "ROLLBACK_COMPATIBLE": "false",
        "ROLLBACK_GATE": "release_mig_002_reindex",
    })
    assert "回滚:./deploy/prod/update.sh <上一个不可变版本 tag>" not in out, (
        "声明不兼容的发布不得向操作员宣传 ordinary previous-tag rollback"
    )
    assert "previous_compatible=false" in out
    assert "release_mig_002_reindex" in out, "必须输出该 release 声明的修复门"
    assert "remediation" in out.lower(), "必须指向显式 remediation/recovery path"
    assert "不执行自动回滚" in out


def test_postdeploy_guidance_defaults_to_ordinary_without_verdict():
    """verdict 缺省(理论不可达:contract 时代必经 [3.5/6])保持既有普通指引。"""
    out = _run_guidance({})
    assert "回滚:./deploy/prod/update.sh" in out


def test_postdeploy_guidance_pre_contract_notes_deferred():
    """前契约时代:普通指引 + 显式「回退兼容性未证明」注记。"""
    out = _run_guidance({"PREFLIGHT_ERA": "pre_contract"})
    assert "回滚:./deploy/prod/update.sh" in out
    assert "回退兼容性未证明" in out


def test_update_sh_wires_verdict_from_manifest_and_calls_guidance():
    """机械接线断言:[3.5/6] 必须从镜像内 manifest 读取 verdict(stdlib),
    部署完成阶段必须调用条件化指引函数;无条件的普通回滚 echo 不得残存。"""
    text = UPDATE_SH.read_text()
    assert "previous_compatible', True" in text or "previous_compatible\", True" in text, (
        "[3.5/6] 必须从镜像内 compatibility manifest 读取 rollback verdict"
    )
    assert "print_postdeploy_rollback_guidance" in text
    # 部署完成阶段的调用必须存在,且普通回滚指引字符串只存在于指引函数内部
    call_idx = text.rfind("print_postdeploy_rollback_guidance")
    assert call_idx > text.index("=== 部署完成:"), "部署完成后必须调用条件化指引"
    body_start = text.index("print_postdeploy_rollback_guidance() {")
    body_end = text.index("\n}", body_start)
    fn_body = text[body_start:body_end]
    assert text.count("回滚:./deploy/prod/update.sh <上一个不可变版本 tag>(同一契约)") == (
        fn_body.count("回滚:./deploy/prod/update.sh <上一个不可变版本 tag>(同一契约)")
    ), "普通回滚指引不得残留在指引函数之外的任何位置"
