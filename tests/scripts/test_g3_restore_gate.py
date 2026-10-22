"""G3 restore-gate fail-closed semantics: official Linux fault-injection suite.

Drives the real scripts (scripts/restore_ingress_gate.sh,
scripts/controlled_restore.sh) against disposable docker fixtures and asserts
DENY/ALLOW behavior, entrance lifecycle, and the attempt state barrier.
Skipped automatically when docker is unavailable (e.g. sandboxed CI jobs).
"""
import hashlib
import json
import socket
import subprocess
import time
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "restore_ingress_gate.sh"
FLOW = REPO / "scripts" / "controlled_restore.sh"
WV_HOST = "g3gate-test-hostname"
KSC = "knowledge-support-cases"
KC = "knowledge-cb70f5ae"
FS_OBJ = str(uuid.uuid4())

_docker_ok = None


def docker_available() -> bool:
    global _docker_ok
    if _docker_ok is None:
        try:
            _docker_ok = subprocess.run(["docker", "info"], capture_output=True,
                                        timeout=20).returncode == 0
        except Exception:
            _docker_ok = False
    return _docker_ok


requires_docker = pytest.mark.skipif(not docker_available(), reason="docker unavailable")


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def sh(cmd: str, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout)


def docker_run(*args):
    return subprocess.run(["docker", "run", "-d", *args], check=True, capture_output=True).stdout.decode().strip()


def psql(container: str, sql: str):
    return subprocess.run(["docker", "exec", container, "psql", "-U", "ask_ai", "-d", "ask_ai",
                           "-c", sql], check=True, capture_output=True)


@pytest.fixture(scope="module")
def pg():
    name = f"g3gate-pg-{uuid.uuid4().hex[:10]}"
    subprocess.run(["docker", "run", "-d", "--name", name,
                    "-e", "POSTGRES_USER=ask_ai", "-e", "POSTGRES_PASSWORD=x",
                    "-e", "POSTGRES_DB=ask_ai", "postgres:16-alpine"],
                   check=True, capture_output=True)
    for _ in range(40):
        if subprocess.run(["docker", "exec", name, "pg_isready", "-U", "ask_ai"],
                          capture_output=True).returncode == 0:
            break
        time.sleep(1)
    for _ in range(40):  # wait for the real ask_ai DB (entrypoint creates it after first start)
        r = subprocess.run(["docker", "exec", name, "psql", "-U", "ask_ai", "-d", "ask_ai",
                            "-c", "SELECT 1;"], capture_output=True)
        if r.returncode == 0:
            break
        time.sleep(1)
    ddl = """
    CREATE TABLE documents(source_id text);
    CREATE TABLE document_versions(id uuid DEFAULT gen_random_uuid(), source_id text, generation_id uuid);
    CREATE TABLE document_version_chunks(id uuid DEFAULT gen_random_uuid(), version_id uuid);
    CREATE TABLE index_generations(id uuid DEFAULT gen_random_uuid(), source_id text);
    CREATE TABLE data_sources(id text, enabled bool, lifecycle_state text, config jsonb);
    CREATE TABLE sync_requests(source_id text, status text);
    INSERT INTO index_generations SELECT gen_random_uuid(), '*legacy*';
    """
    subprocess.run(["docker", "exec", name, "psql", "-U", "ask_ai", "-d", "ask_ai", "-c", ddl],
                   check=True, capture_output=True)
    yield name
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@pytest.fixture(scope="module")
def pg_sid(pg):
    return subprocess.run(["docker", "exec", pg, "psql", "-U", "ask_ai", "-d", "ask_ai",
                           "-tA", "-c", "SELECT system_identifier FROM pg_control_system();"],
                          check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(scope="module")
def wv(tmp_path_factory):
    name = f"g3gate-wv-{uuid.uuid4().hex[:10]}"
    data_dir = tmp_path_factory.mktemp("wvdata")
    port = free_port()
    subprocess.run(["docker", "run", "-d", "--name", name,
                    "-e", "CLUSTER_HOSTNAME=" + WV_HOST,
                    "-e", "PERSISTENCE_DATA_PATH=/var/lib/weaviate",
                    "-e", "AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true",
                    "-e", "DEFAULT_VECTORIZER_MODULE=none",
                    "-e", "ENABLE_MODULES=",
                    "-p", f"127.0.0.1:{port}:8080",
                    "-v", f"{data_dir}:/var/lib/weaviate",
                    "cr.weaviate.io/semitechnologies/weaviate:1.28.0"],
                   check=True, capture_output=True)
    # 真实 weaviate(生产同镜像 1.28.0):G3 端点绑定与 G10 聚合均为实测而非 stub
    wait_wv(f"http://127.0.0.1:{port}")
    create_document_schema(f"http://127.0.0.1:{port}")
    yield {"name": name, "data_dir": str(data_dir), "url": f"http://127.0.0.1:{port}"}
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)



@pytest.fixture()
def clean_pg(pg):
    subprocess.run(["docker", "exec", pg, "psql", "-U", "ask_ai", "-d", "ask_ai", "-c",
                    "TRUNCATE documents, document_versions, document_version_chunks, sync_requests; "
                    "DELETE FROM data_sources; "
                    "DELETE FROM index_generations WHERE source_id <> '*legacy*';"],
                   check=True, capture_output=True)
    return pg


def add_residue(pg, kind: str, count: int = 1):
    sql = {
        "documents": f"INSERT INTO documents SELECT 'knowledge-support-cases/x' || g FROM generate_series(1,{count}) g;",
        "versions": f"INSERT INTO document_versions(source_id) SELECT 'knowledge-support-cases/x' || g FROM generate_series(1,{count}) g;",
        "kc_documents": f"INSERT INTO documents SELECT 'knowledge-cb70f5ae/x' || g FROM generate_series(1,{count}) g;",
        "kc_versions": f"INSERT INTO document_versions(source_id) SELECT 'knowledge-cb70f5ae/x' || g FROM generate_series(1,{count}) g;",
        "gens": f"INSERT INTO index_generations(source_id) SELECT 'knowledge-support-cases' FROM generate_series(1,{count}) i;",
    }
    psql(pg, sql[kind])


def gate(pg_name, pg_sid, wv_url, wv_container, receipt=None, expect_sid=None, hostname=WV_HOST,
         uploads_root=None, uploads_guard=None):
    cmd = ["bash", str(GATE), "--pg-container", pg_name, "--expect-sid", expect_sid or pg_sid,
           "--weaviate-url", wv_url, "--weaviate-container", wv_container,
           "--weaviate-expect-hostname", hostname]
    if receipt:
        cmd += ["--receipt", receipt]
    if uploads_root:
        cmd += ["--uploads-root", uploads_root, "--uploads-guard", uploads_guard]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def flow(stage, state_file, pg_name, pg_sid, wv_container, wv_url, extra=(), timeout=300):
    return subprocess.run(["bash", str(FLOW), stage,
                           "--state-file", state_file, "--pg-container", pg_name,
                           "--expect-sid", pg_sid, "--weaviate-url", wv_url,
                           "--weaviate-container", wv_container,
                           "--weaviate-expect-hostname", WV_HOST, "--app-service", "g3gate-app",
                           *extra], capture_output=True, text=True, timeout=timeout)


def wv_container_name():
    out = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                         capture_output=True, text=True).stdout
    for n in out.splitlines():
        if n.startswith("g3gate-wv-"):
            return n
    return ""


def wait_wv(url, tries=60):
    for _ in range(tries):
        if subprocess.run(["curl", "-fsS", "-m", "3", f"{url}/v1/meta"],
                          capture_output=True).returncode == 0:
            return
        time.sleep(2)
    raise RuntimeError(f"weaviate not ready at {url}")


def create_document_schema(url):
    r = subprocess.run(["curl", "-fsS", "-m", "10", "-X", "POST", f"{url}/v1/schema",
                        "-H", "Content-Type: application/json",
                        "-d", json.dumps({"class": "Document", "vectorizer": "none",
                                          "properties": [
                                              {"name": "source_type", "dataType": ["text"]},
                                              {"name": "source_id", "dataType": ["text"]},
                                              {"name": "channel_visibility", "dataType": ["text[]"]},
                                              {"name": "title", "dataType": ["text"]}]})],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"schema create failed: {r.stderr}"


def wv_put(url, obj_id):
    r = subprocess.run(["curl", "-fsS", "-m", "10", "-X", "POST", f"{url}/v1/objects",
                        "-H", "Content-Type: application/json",
                        "-d", json.dumps({"class": "Document", "id": obj_id,
                                          "properties": {"source_type": "filesystem",
                                                         "source_id": "uploads/x"}})],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"weaviate PUT failed: {r.stderr}"


def wv_del(url, obj_id):
    subprocess.run(["curl", "-fsS", "-m", "10", "-X", "DELETE", f"{url}/v1/objects/{obj_id}"],
                   capture_output=True)


def dump_of(pg_name, tmp_path):
    d = tmp_path / "fixture.dump"
    subprocess.run(["docker", "exec", pg_name, "pg_dump", "-U", "ask_ai", "-d", "ask_ai",
                    "-Fc", "-f", "/tmp/fixture.dump"], check=True, capture_output=True)
    subprocess.run(["docker", "cp", f"{pg_name}:/tmp/fixture.dump", str(d)], check=True, capture_output=True)
    subprocess.run(["docker", "exec", pg_name, "rm", "-f", "/tmp/fixture.dump"], capture_output=True)
    return d


# ---------------- gate: fail-closed semantics ----------------

@requires_docker
def test_gate_missing_args():
    assert subprocess.run(["bash", str(GATE)], capture_output=True, text=True).returncode == 2


@requires_docker
def test_gate_pg_unreachable(pg, pg_sid, wv):
    r = gate("g3gate-no-such-container-xyz", pg_sid, wv["url"], wv_container_name())
    assert r.returncode == 1 and "probe-failed: pg identity" in r.stdout + r.stderr


@requires_docker
def test_gate_identity_mismatch(pg, pg_sid, wv):
    r = gate(pg, pg_sid, wv["url"], wv_container_name(), expect_sid="dead" * 8)
    assert r.returncode == 1 and "identity-mismatch" in r.stdout + r.stderr


@requires_docker
def test_gate_probe_failure_denies(pg, pg_sid, wv, clean_pg):
    psql(pg, "ALTER TABLE data_sources RENAME TO data_sources_x;")
    r = gate(pg, pg_sid, wv["url"], wv_container_name())
    psql(pg, "ALTER TABLE data_sources_x RENAME TO data_sources;")
    assert r.returncode == 1 and "probe-failed: ksc registration" in r.stdout + r.stderr


@requires_docker
def test_gate_residue_then_clean_allow(pg, pg_sid, wv, clean_pg, tmp_path):
    recv = tmp_path / "receipt.log"
    add_residue(pg, "documents")
    add_residue(pg, "versions")
    r = gate(pg, pg_sid, wv["url"], wv_container_name(), receipt=str(recv))
    assert r.returncode == 1 and "residue-pg" in r.stdout + r.stderr
    psql(pg, "DELETE FROM documents WHERE source_id LIKE 'knowledge-support-cases/%'; "
             "DELETE FROM document_versions WHERE source_id LIKE 'knowledge-support-cases/%';")
    r = gate(pg, pg_sid, wv["url"], wv_container_name(), receipt=str(recv))
    assert r.returncode == 0
    assert '"verdict":"ALLOW"' in recv.read_text()


@requires_docker
def test_gate_kc_and_generations_and_registration_and_reindex(pg, pg_sid, wv, clean_pg):
    add_residue(pg, "kc_documents")
    add_residue(pg, "kc_versions")
    r = gate(pg, pg_sid, wv["url"], wv_container_name())
    assert r.returncode == 1 and "residue-pg" in r.stdout + r.stderr
    psql(pg, "DELETE FROM documents WHERE source_id LIKE 'knowledge-cb70f5ae/%'; "
             "DELETE FROM document_versions WHERE source_id LIKE 'knowledge-cb70f5ae/%';")
    add_residue(pg, "gens")
    out = gate(pg, pg_sid, wv["url"], wv_container_name())
    assert out.returncode == 1 and "residue-generations" in out.stdout + out.stderr
    psql(pg, "DELETE FROM index_generations WHERE source_id='knowledge-support-cases';")
    psql(pg, "INSERT INTO data_sources VALUES ('knowledge-support-cases', true, 'active', '{}');")
    r = gate(pg, pg_sid, wv["url"], wv_container_name())
    assert r.returncode == 1 and "registration-active" in r.stdout + r.stderr
    psql(pg, "UPDATE data_sources SET lifecycle_state='retired', enabled=false "
             "WHERE id='knowledge-support-cases'; "
             "INSERT INTO sync_requests VALUES ('knowledge-support-cases','running');")
    r = gate(pg, pg_sid, wv["url"], wv_container_name())
    assert r.returncode == 1 and "reindex-pending" in r.stdout + r.stderr
    psql(pg, "UPDATE sync_requests SET status='done' WHERE source_id='knowledge-support-cases';")
    assert gate(pg, pg_sid, wv["url"], wv_container_name()).returncode == 0


@requires_docker
def test_gate_weaviate_and_legacy(pg, pg_sid, wv, clean_pg):
    wv_put(wv["url"], FS_OBJ)
    r = gate(pg, pg_sid, wv["url"], wv_container_name())
    assert r.returncode == 1 and "residue-weaviate" in r.stdout + r.stderr
    wv_del(wv["url"], FS_OBJ)
    psql(pg, "DELETE FROM index_generations WHERE source_id='*legacy*';")
    r = gate(pg, pg_sid, wv["url"], wv_container_name())
    assert r.returncode == 1 and "legacy-missing" in r.stdout + r.stderr
    psql(pg, "INSERT INTO index_generations SELECT gen_random_uuid(), '*legacy*';")
    assert gate(pg, pg_sid, wv["url"], wv_container_name()).returncode == 0


@requires_docker
def test_gate_uploads_guard(pg, pg_sid, wv, clean_pg, tmp_path):
    root = tmp_path / "uploads"
    guard = tmp_path / "guard.tsv"
    (root / KSC / "experience").mkdir(parents=True)
    known = root / KSC / "experience" / "unknown-guard.md"
    known.write_text("guard\n")
    guard.write_text(f"{KSC}\texperience/unknown-guard.md\t"
                     f"{hashlib.sha256(known.read_bytes()).hexdigest()}\n")
    unlisted = root / KSC / "2026-09"
    unlisted.mkdir(parents=True)
    (unlisted / "unlisted.md").write_text("nope\n")
    cmd = ["bash", str(GATE), "--pg-container", pg, "--expect-sid", pg_sid,
           "--weaviate-url", wv["url"], "--weaviate-container", wv_container_name(),
           "--weaviate-expect-hostname", WV_HOST,
           "--uploads-root", str(root), "--uploads-guard", str(guard)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 1 and "uploads-unrecognized" in r.stdout + r.stderr
    (unlisted / "unlisted.md").unlink()
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0


# ---------------- controlled_restore: staged lifecycle ----------------

@requires_docker
def test_flow_pg_restore_failure_is_fatal_and_barrier_holds(pg, pg_sid, wv, clean_pg, tmp_path):
    state = tmp_path / "state.jsonl"
    bad = tmp_path / "corrupt.dump"
    bad.write_bytes(b"NOTAFDUMP" * 100)
    r = flow("stage-restore-pg", str(state), pg, pg_sid, wv["name"], wv["url"],
             extra=("--dump", str(bad)))
    assert r.returncode == 1
    assert "restore-pg" not in state.read_text()
    r = flow("stage-open", str(state), pg, pg_sid, wv["name"], wv["url"],
             extra=("--start-cmd", "false", "--health-url", "http://127.0.0.1:1/health",
                    "--uploads-root", str(tmp_path / "up-root-x"),
                    "--uploads-guard", str(tmp_path / "guard-x.tsv")))
    assert r.returncode == 1 and "stage-incomplete" in r.stdout + r.stderr


@requires_docker
def test_flow_full_lifecycle_replay_refusal_identity_binding_and_open(
        pg, pg_sid, wv, clean_pg, tmp_path):
    state = tmp_path / "state.jsonl"
    fixture = dump_of(pg, tmp_path)
    r = flow("stage-restore-pg", str(state), pg, pg_sid, wv["name"], wv["url"],
             extra=("--dump", str(fixture), "--drop-schema"))
    assert r.returncode == 0
    # attempt replay refusal without explicit --new-attempt
    r = flow("stage-restore-pg", str(state), pg, pg_sid, wv["name"], wv["url"],
             extra=("--dump", str(fixture), "--drop-schema"))
    assert r.returncode == 1 and "new-attempt" in r.stdout + r.stderr
    # weaviate data dir must be bound to the container's actual mount;
    # snapshot is taken from the fixture's real data dir(停机后打包,内含 Document schema,
    # 否则 stage 内置的恢复后聚合就绪检查不可能通过)
    subprocess.run(["docker", "stop", wv["name"]], check=True, capture_output=True)
    snap = tmp_path / "wv-snap.tgz"
    # 容器内打包:数据文件属 weaviate 镜像用户,Linux 宿主账户直读会被拒
    # (macOS bind-mount 权限放宽会掩盖这一点);alpine root 可读,产物 644
    # 供宿主 shasum 与后续 wipe 容器共同消费。
    subprocess.run(["docker", "run", "--rm",
                    "-v", f"{wv['data_dir']}:/data:ro",
                    "-v", f"{tmp_path}:/out",
                    "alpine:3.20", "sh", "-c",
                    "tar czf /out/wv-snap.tgz -C /data . && chmod 644 /out/wv-snap.tgz"],
                   check=True, capture_output=True)
    subprocess.run(["docker", "start", wv["name"]], check=True, capture_output=True)
    wait_wv(wv["url"])
    wrong = str(tmp_path / "not-the-mount")
    r = flow("stage-restore-weaviate", str(state), pg, pg_sid, wv["name"], wv["url"],
             extra=("--weaviate-backup", str(snap), "--weaviate-data-dir", wrong,
                    "--i-know-this-wipes-weaviate-volume"))
    assert r.returncode == 1
    # correct binding completes
    r = flow("stage-restore-weaviate", str(state), pg, pg_sid, wv["name"], wv["url"],
             extra=("--weaviate-backup", str(snap), "--weaviate-data-dir", wv["data_dir"],
                    "--i-know-this-wipes-weaviate-volume"))
    assert r.returncode == 0, "weaviate stage rc=%d :: %s || %s" % (r.returncode, r.stdout[-400:], r.stderr[-400:])
    # uploads stage
    usrc = tmp_path / "up-src"
    uroot = tmp_path / "up-root"
    (usrc / KSC / "experience").mkdir(parents=True)
    known = usrc / KSC / "experience" / "unknown-guard.md"
    known.write_text("guard\n")
    guard = tmp_path / "guard.tsv"
    guard.write_text(f"{KSC}\texperience/unknown-guard.md\t"
                     f"{hashlib.sha256(known.read_bytes()).hexdigest()}\n")
    uroot.mkdir(parents=True, exist_ok=True)
    r = flow("stage-restore-uploads", str(state), pg, pg_sid, wv["name"], wv["url"],
             extra=("--uploads-root", str(uroot), "--uploads-src", str(usrc)))
    assert r.returncode == 0
    # stage-open: start failure is fatal, entrance stays closed
    r = flow("stage-open", str(state), pg, pg_sid, wv["name"], wv["url"],
             extra=("--start-cmd", "false", "--health-url", "http://127.0.0.1:1/health",
                    "--uploads-root", str(uroot), "--uploads-guard", str(guard)))
    assert r.returncode == 1
    # stage-open: full happy path on a real listening app
    port = free_port()
    app = f"g3gate-app-{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "run", "-d", "--name", app, "-p", f"127.0.0.1:{port}:80",
                    "python:3.12-alpine", "python", "-m", "http.server", "80"],
                   check=True, capture_output=True)
    try:
        r = flow("stage-open", str(state), pg, pg_sid, wv["name"], wv["url"],
                 extra=("--app-service", app,
                        "--start-cmd", f"docker start {app}",
                        "--health-url", f"http://127.0.0.1:{port}/",
                        "--uploads-root", str(uroot), "--uploads-guard", str(guard)))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "real listener" in r.stdout
        assert subprocess.run(["curl", "-fsS", "-m", "5", f"http://127.0.0.1:{port}/"],
                              capture_output=True).returncode == 0
    finally:
        subprocess.run(["docker", "rm", "-f", app], capture_output=True)


@requires_docker
def test_flow_stage_status_is_readonly(pg_sid, wv, tmp_path):
    app = f"g3gate-app-{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "run", "-d", "--name", app, "busybox:1.36", "sleep", "infinity"],
                   check=True, capture_output=True)
    try:
        r = flow("stage-status", str(tmp_path / "s.json"), "any-container", pg_sid, wv["name"], wv["url"],
                 extra=("--app-service", app))
        assert r.returncode == 0
        running = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", app],
                                 capture_output=True, text=True).stdout.strip()
        assert running == "true", "stage-status must not stop a running service"
    finally:
        subprocess.run(["docker", "rm", "-f", app], capture_output=True)
