"""r3gate R4-3:冻结代码 vs 宿主 runtime 边界 —— r2 runtime 非生产兼容性验证。

A 实码复审阻塞(R3 = 三项确定性阻塞之一)要点:R3 候选从**目标冻结镜像**
``docker cp`` 提取 release_preflight.py 再 ``docker compose exec -T backend``
执行 —— 代码来自 r3 镜像但 Python/依赖/env 来自**现役 r2 容器**;须对已发布
r2 runtime 做非生产版本契约兼容性验证,不得用部署后 r3 runtime 的测试成功
代替部署前 r2 runtime 兼容性证据。

基线(User 精化,优先于胶囊原表述):
- 兼容性基准 = 生产现行 **v1.6.4-r2 官方发布镜像不可变身份 + r2 tag 的
  deploy/prod/docker-compose.yml 拓扑**(backend env 来源/挂载/网络/进入方式);
- 镜像身份:ghcr.io/harryhua-ai/ask-ai:v1.6.4-r2 →
  sha256:ce7902fcf29eebf83180516ed9004bb68585b520c447990131f4ce42373fecb1
  (`docker pull --platform linux/amd64` 实测 Digest = RepoDigest = 镜像 ID;
  另:arm64 客户端 manifest inspect 见 sha256:5b35883f... = buildx provenance
  证明 index;两者均记录于 r2-runtime-compatibility.md。
  linux/amd64;构建链:build-image.yml type=ref,event=tag → 同名 image tag,
  构建期生成 RELEASE.json —— r2 tag 树内无 RELEASE.json 文件,其为 CI 构建期
  工件,镜像内存在性在 live 测试实测);
- 本地复现载体(/tmp 临时 compose 项目 r4r2):backend 服务按 r2 topology
  精简副本(env_file+environment 同源、uploads 命名卷、compose 网络内
  postgres:16-alpine + weaviate 1.28.0、健康依赖、`docker compose exec -T
  backend` 同生产进入方式),镜像按上述 digest 钉扎;
- 如实 unverified(不冒充):GPU reservation(nvidia)、宿主 corpus/models
  只读挂载(/home/ubuntu/...)、生产 Docker Engine 版本 —— 本地无法复现。

本文件三层验证:
1. 沙箱负例(T-RT-01..07,fake ssh/docker shim 真实执行路径):评估器非零
   退出/backend 容器未启动/weaviate 容器未运行/提取失败/内容不匹配
   (R4-3① 完整性核验)/迁移步防护;
2. live 实测(T-RT-L1..L6,真实 r2 官方镜像,skipif 镜像缺失):依赖矩阵
   (psycopg2/psql/sha256sum)、pg_control_system() 应用账号实测权限、
   生产 argv 端到端 evaluator、锚不匹配/依赖不可达负例、真实冻结 manifest
   在非 GPU 复现环境的诚实 fail-closed;
3. R4-3① 缺陷修复钉住:提取侧哈希 ↔ 容器内侧哈希 执行前核对。

红线:全部离线本地容器/沙箱;凭据为 R4GRN-*/本地 .env 假口令;零生产
触碰(生产只读预检归 A 按授权执行);不冒充、不伪造 PASS。
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from test_r4gate_weaviate_identity_anchor import (
    _CP_HOST,
    _CP_IMG,
    _CP_MAN,
    _CP_VOL,
    REPO,
    WORKFLOW,
    EVALUATOR_SRC,
    ControlPlaneSandbox,
    _preflight_run_text,
)

EVALUATOR = EVALUATOR_SRC
COMPOSE_DIR = Path("/tmp/r4-r2env")
R2_IMAGE_REF = "ghcr.io/harryhua-ai/ask-ai:v1.6.4-r2"
R2_IMAGE_DIGEST = "sha256:ce7902fcf29eebf83180516ed9004bb68585b520c447990131f4ce42373fecb1"


# --------------------------------------------------------------------------- #
# 沙箱(R4-3 专用注入开关:提取失败/容器未启动/内容不匹配)
# --------------------------------------------------------------------------- #


class R2CompatSandbox(ControlPlaneSandbox):
    """在 R4-1 控制面沙箱之上追加 R4-3 注入开关(fake docker shim 扩展)。"""

    def _write_shims(self) -> None:
        super()._write_shims()
        docker = self.bin / "docker"
        body = docker.read_text(encoding="utf-8")
        # cp 提取失败注入:release_preflight.py 的 docker cp 失败(打包违约路径)
        old = '    src="${args[1]}"; dest="${args[$((${#args[@]} - 1))]}"\n'
        new = (
            '    if [ "${TSL_CP_EVAL_FAIL:-}" = "1" ] && printf \'%s\' "${args[1]}" '
            "| grep -q release_preflight.py; then\n"
            '      echo "fake docker cp: extraction failed (injected)" >&2; exit 1\n'
            "    fi\n"
            f"    {old}"
        )
        assert old in body
        body = body.replace(old, new, 1)
        # compose exec 失败注入:backend 容器未启动语义
        # anchor = 主沙箱 ps 分支改写后的形态(per-service cid;注入保序)
        old2 = '    if [ "$sub" = "ps" ]; then\n'
        assert old2 in body
        new2 = old2 + (
            '    if [ "${TSL_CP_EXEC_FAIL:-}" = "1" ]; then\n'
            '      echo "fake compose exec: backend container not running (injected)" >&2\n'
            "      exit 1\n"
            '    fi\n'
        )
        body = body.replace(old2, new2, 1)
        docker.write_text(body, encoding="utf-8")


@pytest.fixture
def r2_sandbox(tmp_path):
    return R2CompatSandbox(tmp_path)


def _r2_env(sandbox: R2CompatSandbox, **overrides) -> dict:
    return sandbox.step_env(**overrides)


# --------------------------------------------------------------------------- #
# 沙箱负例 T-RT-01..07
# --------------------------------------------------------------------------- #


def test_trt01_evaluator_nonzero_exit_aborts_no_mutation(r2_sandbox):
    """T-RT-01 容器内 evaluator 非零退出(fail verdict)→ 步骤中止。"""
    rc, out, err = r2_sandbox.run_step(_r2_env(r2_sandbox, TSL_EVAL_RC="2"))
    assert rc != 0
    assert "部署中止" in err
    assert "PREFLIGHT PASS" not in out


def test_trt02_backend_container_not_running_aborts(r2_sandbox):
    """T-RT-02 backend 容器未启动(compose exec 失败)→ 中止,无 PASS 输出。"""
    rc, out, err = r2_sandbox.run_step(_r2_env(r2_sandbox, TSL_CP_EXEC_FAIL="1"))
    assert rc != 0
    assert "PREFLIGHT PASS" not in out


def test_trt03_weaviate_container_not_running_aborts(r2_sandbox):
    """T-RT-03 weaviate 容器未运行(控制面 ps 为空)→ 身份无法核验中止。"""
    rc, out, err = r2_sandbox.run_step(_r2_env(r2_sandbox, TSL_PS_EMPTY="1"))
    assert rc != 0
    assert "weaviate 容器未运行" in err


def test_trt04_evaluator_extraction_failed_contract_era_aborts(r2_sandbox):
    """T-RT-04 契约期镜像缺 release_preflight.py(提取失败)→ 打包违约中止。"""
    rc, out, err = r2_sandbox.run_step(_r2_env(r2_sandbox, TSL_CP_EVAL_FAIL="1"))
    assert rc != 0
    assert "打包违约" in err or "缺失 scripts/release_preflight.py" in err
    assert r2_sandbox.eval_argv_text() == ""


def test_trt05_content_mismatch_rejected_before_execution(r2_sandbox):
    """T-RT-05 容器内工件哈希 ≠ 提取侧哈希(R4-3①)→ 拒绝执行评估器。"""
    rc, out, err = r2_sandbox.run_step(_r2_env(r2_sandbox, TSL_TAMPER="1"))
    assert rc != 0
    assert "内容核验不匹配" in err or "完整性核验失败" in err
    assert r2_sandbox.eval_argv_text() == "", "完整性不匹配 → evaluator 绝不执行"


def test_trt06_migrate_step_is_gated_behind_preflight():
    """T-RT-06 防护静态断言:preflight 步骤先于 migrate; migrate 无 always()
    (preflight 非零 ⇒ 迁移与 rollout 绝不执行)。"""
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = wf["jobs"]["deploy"]["steps"]
    ids = [s.get("id") for s in steps]
    assert ids.index("preflight") < ids.index("migrate")
    migrate = steps[ids.index("migrate")]
    assert not str(migrate.get("if") or "").strip(), "migrate 步绝不无条件执行"
    assert "always()" not in str(migrate.get("if") or "")
    # preflight 步骤失败即整体失败(run 脚本非零退出;无 continue-on-error)
    preflight = steps[ids.index("preflight")]
    assert not preflight.get("continue-on-error")


def test_trt07_integrity_pass_on_happy_path(r2_sandbox):
    """T-RT-07 正例:内容核验通过 → 评估器执行(哈希通道真实生效)。"""
    rc, out, err = r2_sandbox.run_step(_r2_env(r2_sandbox))
    assert rc == 0, f"{out}\n{err}"
    assert f"PREFLIGHT EVALUATOR SOURCE IMAGE:v1.0.0 image={_CP_IMG}" in out
    assert r2_sandbox.eval_argv_text() != ""


# --------------------------------------------------------------------------- #
# live 实测(真实 r2 官方镜像;镜像缺失 → skip,不冒充)
# --------------------------------------------------------------------------- #


def _r2_image_available() -> bool:
    r = subprocess.run(  # noqa: S603
        ["docker", "image", "inspect", f"{R2_IMAGE_REF}"],
        capture_output=True, text=True,
    )
    return r.returncode == 0


def _compose(*args: str, check: bool = True, timeout: int = 600,
             env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["R4_R2_IMAGE_DIGEST"] = R2_IMAGE_DIGEST
    if env_extra:
        env.update(env_extra)
    r = subprocess.run(  # noqa: S603
        ["docker", "compose", "-f", str(COMPOSE_DIR / "docker-compose.yml"), *args],
        capture_output=True, text=True, timeout=timeout, env=env, cwd=str(COMPOSE_DIR),
    )
    if check and r.returncode != 0:
        raise AssertionError(f"compose {args} failed: {r.stderr[-2000:]}")
    return r


def _backend_exec(args: list[str], *, stdin: str | None = None,
                  env_extra: list[str] | None = None,
                  timeout: int = 300, check: bool = True):
    cmd = ["docker", "compose", "-f", str(COMPOSE_DIR / "docker-compose.yml"),
           "exec", "-T"]
    for e in env_extra or []:
        cmd += ["-e", e]
    cmd += ["backend", *args]
    r = subprocess.run(  # noqa: S603
        cmd, input=stdin, capture_output=True, timeout=timeout, cwd=str(COMPOSE_DIR),
        env={**os.environ, "R4_R2_IMAGE_DIGEST": R2_IMAGE_DIGEST}, text=True,
    )
    if check and r.returncode != 0:
        raise AssertionError(
            f"backend exec {args} rc={r.returncode}: {r.stderr[-2000:]}"
        )
    return r


@pytest.fixture(scope="module")
def r2_stack():
    if not _r2_image_available():
        pytest.skip("官方 v1.6.4-r2 镜像未在本机(如实 skip,不冒充)")
    if shutil.which("docker") is None:
        pytest.skip("docker 不可用")
    _compose("down", "--volumes", "--remove-orphans", check=False, timeout=300)
    _compose("up", "-d", "--wait", timeout=900)
    yield
    _compose("down", "--volumes", "--remove-orphans", check=False, timeout=300)


def _live_pg_system_id() -> str:
    r = _compose("exec", "-T", "postgres", "psql", "-U", "ask_ai", "-d", "ask_ai",
                 "-tAc", "SELECT system_identifier FROM pg_control_system()")
    return r.stdout.strip().splitlines()[-1].strip()


def _seed_isolation_fixtures() -> str:
    """端到端净集 fixture:data_sources 表(upload_mode 空)= 0 注册;
    Document collection 1 个 upload 对象 = total>0、filesystem=0。
    返回本地 v2 锚(非秘密,本地自造标识)。"""
    # 六表按生产形状重建(残留电池/注册计数谓词依赖 enabled/lifecycle_state/
    # 文本 id 形态;一次性栈内 DROP 幂等)
    _compose("exec", "-T", "postgres", "psql", "-U", "ask_ai", "-d", "ask_ai", "-q", "-c",
             "DROP TABLE IF EXISTS document_version_chunks;"
             "DROP TABLE IF EXISTS document_versions;"
             "DROP TABLE IF EXISTS documents;"
             "DROP TABLE IF EXISTS index_generations;"
             "DROP TABLE IF EXISTS sync_requests;"
             "DROP TABLE IF EXISTS data_sources;"
             "CREATE TABLE data_sources (id text primary key, enabled bool,"
             " lifecycle_state text, config jsonb);"
             "CREATE TABLE documents (source_id text);"
             "CREATE TABLE document_versions (id uuid DEFAULT gen_random_uuid(),"
             " source_id text, generation_id uuid);"
             "CREATE TABLE document_version_chunks"
             " (id uuid DEFAULT gen_random_uuid(), version_id uuid);"
             "CREATE TABLE index_generations"
             " (id uuid DEFAULT gen_random_uuid(), source_id text);"
             "CREATE TABLE sync_requests (source_id text, status text);"
             "INSERT INTO data_sources (id, config) SELECT 'seed-row',"
             " '{\"source\":\"seed\"}'::jsonb WHERE true;"
             "INSERT INTO index_generations SELECT gen_random_uuid(), '*legacy*';")
    _backend_exec(
        ["python3", "-c",
         "import json, os, urllib.request\n"
         "base = os.environ['WEAVIATE_URL']\n"
         "req = urllib.request.Request(base + '/v1/schema', method='POST',\n"
         "    data=json.dumps({'class': 'Document', 'vectorizer': 'none',\n"
         "        'properties': [{'name': 'text', 'dataType': ['text']},\n"
         "                       {'name': 'source_type', 'dataType': ['text']}]}).encode(),\n"
         "    headers={'Content-Type': 'application/json'})\n"
         "try:\n"
         "    urllib.request.urlopen(req)\n"
         "except Exception:\n"
         "    pass\n"
         "req = urllib.request.Request(base + '/v1/graphql', method='POST',\n"
         "    data=json.dumps({'query': '{Aggregate{Document_TOTAL:Document{meta{count}}}}'}).encode(),\n"
         "    headers={'Content-Type': 'application/json'})\n"
         "total = json.load(urllib.request.urlopen(req))['data']['Aggregate']['Document_TOTAL']\n"
         "count = total[0]['meta']['count'] if total else 0\n"
         "if count == 0:\n"
         "    req = urllib.request.Request(base + '/v1/objects', method='POST',\n"
         "        data=json.dumps({'class': 'Document',\n"
         "            'properties': {'text': 'seed', 'source_type': 'upload'},\n"
         "            'vector': [0.1, 0.2]}).encode(),\n"
         "        headers={'Content-Type': 'application/json'})\n"
         "    urllib.request.urlopen(req)\n"]
    )
    return json.dumps({
        "version": 2,
        "pg_system_id": _live_pg_system_id(),
        # 本地复现栈 CLUSTER_HOSTNAME 与 r2 tag 生产 compose 同值(树内非秘密)
        "weaviate_cluster_hostname": "7adc06acc397",
        "weaviate_image_digest": _CP_IMG,
        "weaviate_volume_name": _CP_VOL,
        "weaviate_volume_manifest_sha256": _CP_MAN,
    })


def _push_and_run_evaluator(anchor_json: str, manifest_path: Path,
                            env_extra: list[str] | None = None):
    """生产等价进入方式:评估器经 stdin 管道送入运行中 backend 容器,
    以与 deploy-production.yml 相同的 argv 执行,返回 (rc, verdict dict)。"""
    _backend_exec(["sh", "-c", "cat > /tmp/r4-evaluator.py"], stdin=EVALUATOR.read_text(encoding="utf-8"))
    _backend_exec(["sh", "-c", "cat > /tmp/r4-manifest.json"], stdin=manifest_path.read_text(encoding="utf-8"))
    _backend_exec(["sh", "-c", "cat > /tmp/r4-anchor.json"], stdin=anchor_json)
    argv = [
        "python3", "/tmp/r4-evaluator.py",
        "--manifest", "/tmp/r4-manifest.json",
        "--verify-upload-isolation",
        "--isolation-pg-dsn-parts",
        "--isolation-trust-anchor-file", "/tmp/r4-anchor.json",
        "--isolation-weaviate-url-env", "WEAVIATE_URL",
        "--isolation-weaviate-class-env", "WEAVIATE_CLASS_NAME",
    ]
    r = _backend_exec(argv, env_extra=env_extra, check=False, timeout=600)
    try:
        verdict = json.loads(r.stdout)
    except json.JSONDecodeError:
        verdict = {"_raw_stdout": r.stdout[-2000:], "_stderr": r.stderr[-2000:]}
    return r.returncode, verdict


_MINIMAL_MANIFEST = json.dumps({
    "version": 1, "config": [], "host": [], "topology": [],
    "dependencies": [], "rollback": {"previous_compatible": True},
})


def test_trtl1_dependency_matrix_in_r2_image(r2_stack):
    """T-RT-L1 r2 镜像内依赖矩阵实测:python3/psycopg2/sha256sum 在,
    psql 缺(驱动回退通道是主路径),evaluator 可编译可执行。"""
    r = _backend_exec(["python3", "--version"])
    assert "Python 3.12" in r.stdout, "r2 runtime python 版本实测"
    r = _backend_exec(["python3", "-c",
                       "import psycopg2; print(psycopg2.__version__)"])
    assert r.stdout.strip().startswith("2."), "psycopg2 在 r2 镜像内可用"
    r = _backend_exec(["sh", "-c", "command -v psql || echo NO_PSQL"])
    assert "NO_PSQL" in r.stdout, "r2 runtime 无 psql(驱动回退为唯一 DB 通道)"
    r = _backend_exec(["sh", "-c", "command -v sha256sum || echo NO_SHA"])
    assert "NO_SHA" not in r.stdout, "R4-3① 容器内侧哈希核验依赖 sha256sum"
    r = _backend_exec(["sh", "-c", "cat > /tmp/r4-compile-check.py"],
                      stdin=EVALUATOR.read_text(encoding="utf-8"))
    _backend_exec(["python3", "-c",
                   "import py_compile; py_compile.compile('/tmp/r4-compile-check.py', doraise=True)"])
    r = _backend_exec(["python3", "/tmp/r4-compile-check.py", "--help"], check=False)
    assert r.returncode == 0, "evaluator 在 r2 runtime 内 CLI 可执行"


def test_trtl2_pg_control_system_permission_as_app_account(r2_stack):
    """T-RT-L2 pg_control_system() 以应用账号(env 凭据,同生产 DSN 组件通道)
    实测:返回十进制 system_identifier(权限实测,非假定)。"""
    r = _backend_exec(["python3", "-c",
                       "import os, psycopg2\n"
                       "conn = psycopg2.connect(host=os.environ['POSTGRES_HOST'],\n"
                       "    port=os.environ['POSTGRES_PORT'], user=os.environ['POSTGRES_USER'],\n"
                       "    password=os.environ['POSTGRES_PASSWORD'], dbname=os.environ['POSTGRES_DB'],\n"
                       "    connect_timeout=10)\n"
                       "cur = conn.cursor()\n"
                       "cur.execute('SELECT system_identifier FROM pg_control_system()')\n"
                       "row = cur.fetchone()\n"
                       "assert row is not None and str(row[0]).isdigit(), row\n"
                       "print('OK', row[0])\n"
                       "conn.rollback(); conn.close()\n"])
    assert r.stdout.startswith("OK ")


def test_trtl3_end_to_end_evaluator_pass_in_r2_runtime(r2_stack, tmp_path):
    """T-RT-L3 生产 argv 端到端:评估器在 r2 runtime 内对本地净集 fixture
    → exit 0 / verdict pass / 双隔离子项 clean pass。"""
    anchor = _seed_isolation_fixtures()
    m = tmp_path / "compatibility.json"
    m.write_text(_MINIMAL_MANIFEST, encoding="utf-8")
    rc, verdict = _push_and_run_evaluator(anchor, m)
    assert rc == 0, json.dumps(verdict, ensure_ascii=False)[:2000]
    assert verdict["status"] == "pass"
    iso = [c for c in verdict["checks"] if c["section"] == "isolation"]
    pg = [c for c in iso if c["name"] == "upload_mode_rows"][0]
    wv = [c for c in iso if c["name"] == "filesystem_objects"][0]
    assert pg["class"] == "isolation_upload_mode_clean" and pg["status"] == "pass"
    assert wv["class"] == "isolation_filesystem_clean" and wv["status"] == "pass"


def test_trtl4_pg_anchor_mismatch_fails_closed_in_r2_runtime(r2_stack, tmp_path):
    """T-RT-L4 版本/身份不符负例:锚 system_identifier ≠ 实测 → fail-closed。"""
    anchor = json.loads(_seed_isolation_fixtures())
    anchor["pg_system_id"] = "1" + anchor["pg_system_id"][1:]
    m = tmp_path / "compatibility.json"
    m.write_text(_MINIMAL_MANIFEST, encoding="utf-8")
    rc, verdict = _push_and_run_evaluator(json.dumps(anchor), m)
    assert rc == 2 and verdict["status"] == "fail"
    pg = [c for c in verdict["checks"] if c["section"] == "isolation"
          and c["name"] == "upload_mode_rows"][0]
    assert pg["status"] == "fail"
    assert pg["class"] == "isolation_upload_mode_identity_mismatch"


def test_trtl5_dependency_unreachable_fails_closed_in_r2_runtime(r2_stack, tmp_path):
    """T-RT-L5 健康检查失败/依赖不可达负例:WEAVIATE_URL 指死端口 →
    filesystem 子项 probe failed fail-closed(绝不 PASS)。"""
    anchor = _seed_isolation_fixtures()
    m = tmp_path / "compatibility.json"
    m.write_text(_MINIMAL_MANIFEST, encoding="utf-8")
    rc, verdict = _push_and_run_evaluator(
        anchor, m, env_extra=["WEAVIATE_URL=http://weaviate:9999"])
    assert rc == 2 and verdict["status"] == "fail"
    wv = [c for c in verdict["checks"] if c["section"] == "isolation"
          and c["name"] == "filesystem_objects"][0]
    assert wv["status"] == "fail"
    assert wv["class"] == "isolation_filesystem_probe_failed"


def test_trtl6_frozen_manifest_honest_failclosed_no_gpu(r2_stack, tmp_path):
    """T-RT-L6 诚实边界:真实冻结 manifest(nvidia_gpu + remediation gate)
    在非 GPU 本地复现环境 → 诚实 fail(能力不可证 + 门未确认);
    GPU capability/宿主挂载面如实 unverified,不冒充。"""
    anchor = _seed_isolation_fixtures()
    m = tmp_path / "compatibility.json"
    m.write_text((REPO / "deploy" / "prod" / "compatibility.json").read_text(encoding="utf-8"),
                 encoding="utf-8")
    rc, verdict = _push_and_run_evaluator(anchor, m)
    assert rc == 2 and verdict["status"] == "fail"
    gpu = [c for c in verdict["checks"] if c["section"] == "host"]
    assert gpu and gpu[0]["status"] == "fail", "非 GPU 环境:能力不可证 = 诚实 fail"
