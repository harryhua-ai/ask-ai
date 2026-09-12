"""#7 Admin 系统运行时端点契约测试(GET /api/admin/system/runtime)。

- auth:required(未认证 401;viewer/editor/admin 均可读——Admin 只读页约定);
- 只读、GET-only:system router 全路由 methods=={"GET"}(diff 可证 + 测试锁);
- 每项观测含 as_of + available/reason 语义;
- 两态覆盖:全量事实 mock(Linux+NVIDIA+runtime)与无 GPU/无 proc 降级态;
- 响应键精确锁定(无 env dump、无密钥面、无操作控制字段)。
"""

import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from unittest import mock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import User
from backend.main import app
from backend.release import reset_release_identity_cache
from backend.runtime.hardware import GpuDevice
from backend.services import host_runtime
from backend.services.host_runtime import _CmdResult

pytestmark = pytest.mark.asyncio(loop_scope="session")

MANIFEST = {
    "version": "1.2.3",
    "git_sha": "c" * 40,
    "built_at": "2026-09-12T08:30:00Z",
    "image": "ghcr.io/harryhua-ai/ask-ai:v1.2.3",
    "ci_run_id": "99999",
}

FAKE_NOW = "2026-09-12T00:00:00+00:00"

NVIDIA_SMI_QUERY_CSV = (
    "0, 3caad314-1c9e-4c1e-a0de-0e04b1d0c3f9, NVIDIA Tesla T4, 535.104.05, "
    "12, 1234, 14126, 15360, 41\n"
)
NVIDIA_SMI_HEADER = (
    "| NVIDIA-SMI 535.104.05   Driver Version: 535.104.05   CUDA Version: 12.2     |\n"
)


class _StubModelRuntime:
    def snapshot(self):
        return {
            "devices": [{"kind": "gpu", "uuid": "GPU-x", "label": "Tesla T4 · GPU 0"}],
            "policies": [
                {
                    "workload": "query_embedding",
                    "status": "loaded",
                    "effective": {"kind": "gpu", "label": "Tesla T4 · GPU 0"},
                }
            ],
            "shared_embedding_runtime": True,
            "runtime_plan": {"mode": "GPU_RESIDENT", "generation": 1},
            "capacity": {"state": "HEALTHY", "gpu_free_mb": 14126},
        }


@asynccontextmanager
async def _pinned_model_runtime(value):
    """把 app.state.model_runtime 钉到指定值(None=未就绪 / stub=就绪),退出还原。"""
    sentinel = object()
    original = getattr(app.state, "model_runtime", sentinel)
    app.state.model_runtime = value
    try:
        yield
    finally:
        if original is sentinel:
            try:
                del app.state.model_runtime
            except AttributeError:
                pass
        else:
            app.state.model_runtime = original


@pytest.fixture
def pinned_release(tmp_path: Path, monkeypatch):
    """钉 release authority(与 test_system_release 同法)。"""
    f = tmp_path / "RELEASE.json"
    f.write_text(json.dumps(MANIFEST), encoding="utf-8")
    monkeypatch.setattr("backend.release._RELEASE_FILE", f)
    monkeypatch.setenv("APP_MODE", "prod")
    reset_release_identity_cache()
    yield
    reset_release_identity_cache()


@pytest.fixture
def full_facts_env(monkeypatch):
    """采集器 seam 注入「Linux+NVIDIA」全量可得事实(经 API 端到端)。"""
    monkeypatch.setattr(host_runtime, "_now_iso", lambda: FAKE_NOW)
    proc_files = {
        "/proc/cpuinfo": "model name\t: Intel(R) Xeon(R) Silver 4210 CPU @ 2.20GHz\n",
        "/proc/meminfo": (
            "MemTotal:       16384000 kB\nMemAvailable:    8192000 kB\n"
            "SwapTotal:       2048000 kB\nSwapFree:        1024000 kB\n"
        ),
        "/proc/uptime": "2678400.50 5300000.25\n",
    }
    proc_stat = iter(["cpu  100 0 100 700 0 0 0 0 0 0\n", "cpu  100 0 200 800 0 0 0 0 0 0\n"])

    def fake_read_file(path):
        if path == "/proc/stat":
            return next(proc_stat, None)
        return proc_files.get(path)

    monkeypatch.setattr(host_runtime, "_read_file", fake_read_file)
    monkeypatch.setattr(host_runtime, "_sleep", lambda _s: None)

    def fake_smi(args):
        if len(args) > 1 and "query-gpu" in args[1]:
            return _CmdResult(ok=True, stdout=NVIDIA_SMI_QUERY_CSV)
        return _CmdResult(ok=True, stdout=NVIDIA_SMI_HEADER)

    monkeypatch.setattr(host_runtime, "_run_readonly", fake_smi)
    monkeypatch.setattr(
        host_runtime,
        "discover_gpus",
        lambda: [
            GpuDevice(
                index=0,
                uuid="GPU-3caad314-1c9e-4c1e-a0de-0e04b1d0c3f9",
                name="NVIDIA Tesla T4",
                total_memory_mb=15360,
            )
        ],
    )
    monkeypatch.setattr(host_runtime, "_hostname", lambda: "prod-gpu-host-1")
    monkeypatch.setattr(
        host_runtime,
        "_platform_facts",
        lambda: ("Linux", "5.15.0-107-generic", "x86_64"),
    )
    monkeypatch.setattr(host_runtime, "_loadavg", lambda: (0.42, 0.35, 0.30))
    usage = mock.Mock(total=100 * 2**30, used=40 * 2**30, free=60 * 2**30)
    monkeypatch.setattr(host_runtime, "_disk_usage", lambda _path: usage)


@pytest.fixture
def degraded_env(monkeypatch):
    """采集器 seam 注入「无 GPU / 无 proc」降级态(macOS 开发机等价)。"""
    monkeypatch.setattr(host_runtime, "_now_iso", lambda: FAKE_NOW)
    monkeypatch.setattr(host_runtime, "_read_file", lambda _p: None)
    monkeypatch.setattr(
        host_runtime,
        "_run_readonly",
        lambda _args: _CmdResult(ok=False, error="nvidia-smi 不可执行(未安装)"),
    )
    monkeypatch.setattr(host_runtime, "discover_gpus", list)
    monkeypatch.setattr(host_runtime, "_hostname", lambda: "dev-host")

    def _no_loadavg():
        raise OSError("no loadavg")

    monkeypatch.setattr(host_runtime, "_loadavg", _no_loadavg)

    def _no_disk(_p):
        raise OSError("statvfs failed")

    monkeypatch.setattr(host_runtime, "_disk_usage", _no_disk)


def _make_role_headers(role: str):
    user_id = uuid.uuid4()

    async def make() -> dict[str, str]:
        factory = app.state.session_factory
        async with factory() as session:
            session.add(
                User(
                    id=user_id,
                    email=f"i7-{role}-{user_id.hex[:8]}@test.com",
                    role=role,
                    password_hash=hash_password("pass123"),
                )
            )
            await session.commit()
        token = create_access_token(str(user_id), role, app.state.settings.jwt_secret)
        return {"Authorization": f"Bearer {token}"}

    async def cleanup() -> None:
        factory = app.state.session_factory
        async with factory() as session:
            await session.execute(User.__table__.delete().where(User.id == user_id))
            await session.commit()

    return make, cleanup


@pytest_asyncio.fixture(loop_scope="session")
async def role_headers(request):
    """间接参数化角色(request.param = viewer/editor/admin)。"""
    make, cleanup = _make_role_headers(request.param)
    headers = await make()
    yield headers
    await cleanup()


@pytest_asyncio.fixture(loop_scope="session")
async def viewer_headers():
    make, cleanup = _make_role_headers("viewer")
    headers = await make()
    yield headers
    await cleanup()


@pytest_asyncio.fixture(loop_scope="session")
async def editor_headers():
    make, cleanup = _make_role_headers("editor")
    headers = await make()
    yield headers
    await cleanup()


@pytest_asyncio.fixture(loop_scope="session")
async def admin_headers():
    make, cleanup = _make_role_headers("admin")
    headers = await make()
    yield headers
    await cleanup()


# ---------------- auth / 只读边界 ----------------


async def test_runtime_requires_auth(pinned_release, degraded_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/system/runtime")
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "role_headers", ["viewer", "editor", "admin"], indirect=True
)
async def test_runtime_readable_by_all_admin_roles(
    pinned_release, degraded_env, role_headers
):
    """读权限沿用 admin 读约定:viewer/editor/admin 均 200(未就绪 runtime 不影响可读)。"""
    async with _pinned_model_runtime(None):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/admin/system/runtime", headers=role_headers)
    assert resp.status_code == 200


async def test_system_router_is_get_only():
    """只读证明:system router 全部路由 methods=={"GET"}(无写端点、无操作控制)。"""
    from backend.api.admin.system import router as system_router

    routes = [r for r in system_router.routes if hasattr(r, "methods")]
    assert len(routes) == 2
    for r in routes:
        assert r.methods == {"GET"}, r.path
    assert {r.path for r in routes} == {"/system/release", "/system/runtime"}


# ---------------- 响应形状锁 ----------------


async def test_runtime_response_keys_locked(pinned_release, degraded_env, admin_headers):
    async with _pinned_model_runtime(None):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/admin/system/runtime", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"as_of", "host", "resources", "accelerator", "service"}
    assert set(body["host"].keys()) == {"as_of", "hostname", "os", "kernel", "uptime_seconds"}
    assert set(body["resources"].keys()) == {
        "as_of",
        "cpu_model",
        "cpu_logical_cores",
        "cpu_utilization_percent",
        "loadavg_1m",
        "loadavg_5m",
        "loadavg_15m",
        "memory_total_mb",
        "memory_used_mb",
        "memory_available_mb",
        "swap_total_mb",
        "swap_used_mb",
        "disk_path",
        "disk_total_gb",
        "disk_used_gb",
        "disk_free_gb",
        "disk_used_percent",
    }
    assert set(body["accelerator"].keys()) == {
        "as_of",
        "available",
        "reason",
        "driver_version",
        "cuda_version",
        "gpus",
        "nvidia_smi_error",
    }
    assert set(body["service"].keys()) == {"as_of", "health", "release", "model_runtime"}
    # 无 env dump / 无密钥面:响应顶层不得出现 env 类标记键
    assert not ({"env", "environment", "secrets"} & set(body.keys()))


async def test_runtime_degraded_no_gpu_explicit_unavailable(
    pinned_release, degraded_env, admin_headers
):
    """无 GPU/无 proc → 显式 unavailable + 原因(非错误、非空壳、非崩溃)。"""
    async with _pinned_model_runtime(None):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/admin/system/runtime", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    accel = body["accelerator"]
    assert accel["available"] is False
    assert isinstance(accel["reason"], str) and accel["reason"]
    assert accel["gpus"] == []
    assert accel["driver_version"]["available"] is False
    assert accel["driver_version"]["reason"]
    resources = body["resources"]
    for key in ("cpu_utilization_percent", "memory_total_mb", "disk_total_gb"):
        assert resources[key]["available"] is False, key
        assert resources[key]["value"] is None, key
        assert resources[key]["reason"], key
    assert body["host"]["uptime_seconds"]["available"] is False
    service = body["service"]
    assert service["model_runtime"]["available"] is False
    assert "模型运行时" in service["model_runtime"]["reason"]
    assert service["health"]["available"] is True
    assert body["as_of"] == FAKE_NOW


async def test_runtime_full_facts_end_to_end(pinned_release, full_facts_env, admin_headers):
    async with _pinned_model_runtime(_StubModelRuntime()):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/admin/system/runtime", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    host = body["host"]
    assert host["hostname"] == {
        "available": True,
        "value": "prod-gpu-host-1",
        "reason": None,
        "as_of": FAKE_NOW,
    }
    assert host["uptime_seconds"]["value"] == 2678400
    resources = body["resources"]
    assert resources["cpu_utilization_percent"]["value"] == 50.0
    assert resources["memory_total_mb"]["value"] == 16000
    assert resources["disk_used_percent"]["value"] == 40.0
    accel = body["accelerator"]
    assert accel["available"] is True
    assert accel["driver_version"]["value"] == "535.104.05"
    assert accel["cuda_version"]["value"] == "12.2"
    assert len(accel["gpus"]) == 1
    gpu = accel["gpus"][0]
    assert gpu["uuid"] == "GPU-3caad314-1c9e-4c1e-a0de-0e04b1d0c3f9"
    assert gpu["utilization_percent"] == 12
    assert gpu["temperature_c"] == 41
    assert gpu["memory_total_mb"] == 15360
    service = body["service"]
    assert service["release"]["value"]["version"] == MANIFEST["version"]
    assert service["release"]["value"]["git_sha"] == MANIFEST["git_sha"]
    assert service["health"]["value"] == "ok"
    assert service["model_runtime"]["available"] is True
    assert service["model_runtime"]["value"]["capacity"]["state"] == "HEALTHY"


async def test_runtime_coexists_with_release_endpoint(pinned_release, degraded_env, admin_headers):
    """既有 /system/release 零回归:同 router 下两端点并存。"""
    async with _pinned_model_runtime(None):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            release = await client.get("/api/admin/system/release", headers=admin_headers)
            runtime = await client.get("/api/admin/system/runtime", headers=admin_headers)
    assert release.status_code == 200
    assert set(release.json().keys()) == {
        "version",
        "git_sha",
        "built_at",
        "app_mode",
        "image",
        "ci_run_id",
        "source",
    }
    assert runtime.status_code == 200
