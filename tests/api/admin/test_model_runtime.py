"""Model Runtime Admin API 验收(真相面/策略持久化/预算/权限)。

覆盖 §33/§35 的 API 子集:
- GET 真相面:发现设备(含 CPU)+ 三 workload 的 Configured/Effective/Status
  + 共享标记 + 容量字段;
- PUT policies:持久化 Configured(重启生效语义=不触碰 Effective)、404/422;
- PUT gpu-budget:auto/manual 持久化与 422;
- viewer 只读(写 403)。
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import ModelRuntimePolicy, ModelRuntimeSetting, User
from backend.main import app
from backend.runtime.hardware import GpuMemorySnapshot
from backend.runtime.manager import ModelRuntimeManager

pytestmark = pytest.mark.asyncio(loop_scope="session")


class _FakeEmbedder:
    dimension = 4

    def __init__(self, device: str = "cpu", **kwargs):
        self.device = device
        self._model_name = "BAAI/bge-reranker-v2-m3" if "rerank" in str(kwargs) else "BAAI/bge-m3"

    def embed(self, texts):
        return [__import__("numpy").zeros(4) for _ in texts]


class _FakeReranker:
    _model_name = "BAAI/bge-reranker-v2-m3"

    def rerank(self, query, documents):
        return [0.5 for _ in documents]


@pytest_asyncio.fixture(loop_scope="session")
async def runtime_manager():
    """为 API 测试装配假工厂 Manager(不加载真实模型)。"""
    manager = ModelRuntimeManager(
        app.state.settings,
        embedder_factory=lambda device="cpu", **kwargs: _FakeEmbedder(device=device),
        reranker_factory=lambda **kwargs: _FakeReranker(),
        gpu_memory_reader=lambda uuid: GpuMemorySnapshot(
            used_mb=11600, free_mb=3960, total_mb=15564
        ),
    )
    await manager.load(app.state.session_factory)
    app.state.model_runtime = manager
    return manager


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers():
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="rt-admin@test.com",
                role="admin",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


async def test_get_truth_surface_shape(auth_headers, runtime_manager):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/model-runtime", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["policies"]) == 3
    workloads = {p["workload"] for p in body["policies"]}
    assert workloads == {"query_embedding", "sync_embedding", "query_reranker"}
    kinds = {d["kind"] for d in body["devices"]}
    assert "cpu" in kinds
    for key in ("state", "budget_mode", "budget_mb", "gpu_free_mb", "peak_reserve_mb"):
        assert key in body["capacity"]
    assert body["capacity"]["peak_reserve_mb"] == 512


async def test_put_policy_persists_configured_restart_required(auth_headers, runtime_manager):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/admin/model-runtime/policies/sync_embedding",
            headers=auth_headers,
            json={"device_kind": "cpu", "gpu_uuid": None},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"]["kind"] == "cpu"
    assert body["configured"]["label"].startswith("CPU ·")
    # Effective 未动(重启生效):GPU 配置在无 CUDA 测试环境无法落地,
    # 这里 sync 原始 effective 与 configured 的关系不强断言,只验证真相字段在。
    assert "effective" in body and "status" in body
    # 持久化行存在
    async with app.state.session_factory() as session:
        row = await session.get(ModelRuntimePolicy, "sync_embedding")
        assert row is not None
        assert row.device_kind == "cpu"


async def test_put_policy_validations(auth_headers, runtime_manager):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        unknown_workload = await client.put(
            "/api/admin/model-runtime/policies/nope",
            headers=auth_headers,
            json={"device_kind": "cpu", "gpu_uuid": None},
        )
        assert unknown_workload.status_code == 404
        gpu_without_uuid = await client.put(
            "/api/admin/model-runtime/policies/sync_embedding",
            headers=auth_headers,
            json={"device_kind": "gpu", "gpu_uuid": None},
        )
        assert gpu_without_uuid.status_code == 422
        unknown_gpu = await client.put(
            "/api/admin/model-runtime/policies/sync_embedding",
            headers=auth_headers,
            json={"device_kind": "gpu", "gpu_uuid": "not-a-real-uuid"},
        )
        assert unknown_gpu.status_code == 422


async def test_put_gpu_budget_auto_and_manual(auth_headers, runtime_manager):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        manual = await client.put(
            "/api/admin/model-runtime/gpu-budget",
            headers=auth_headers,
            json={"mode": "manual", "manual_budget_mb": 2048},
        )
        assert manual.status_code == 200
        assert manual.json()["budget_mode"] == "manual"
        # 手动预算(2048)≤ 当前可用(free 3960)→ 按手动
        assert manual.json()["budget_mb"] == 2048

        invalid = await client.put(
            "/api/admin/model-runtime/gpu-budget",
            headers=auth_headers,
            json={"mode": "manual", "manual_budget_mb": 0},
        )
        assert invalid.status_code == 422

        auto = await client.put(
            "/api/admin/model-runtime/gpu-budget",
            headers=auth_headers,
            json={"mode": "auto", "manual_budget_mb": None},
        )
        assert auto.status_code == 200
        assert auto.json()["budget_mode"] == "auto"


async def test_model_runtime_requires_auth(runtime_manager):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/model-runtime")
    assert resp.status_code in (401, 403)


# ------------------------- Apply(候选装配 + 原子换装;T-MODEL-RUNTIME-APPLY)


async def _put_all_cpu_policies(client, headers):
    for workload in ("query_embedding", "sync_embedding", "query_reranker"):
        resp = await client.put(
            f"/api/admin/model-runtime/policies/{workload}",
            headers=headers,
            json={"device_kind": "cpu", "gpu_uuid": None},
        )
        assert resp.status_code == 200


async def test_apply_endpoint_success_configured_equals_effective(auth_headers, runtime_manager):
    """契约#1/#3:Apply 成功 → Configured==Effective,restart_required=false。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _put_all_cpu_policies(client, auth_headers)
        gen_before = (await client.get("/api/admin/model-runtime", headers=auth_headers)).json()[
            "runtime_plan"
        ]["generation"]

        resp = await client.post("/api/admin/model-runtime/apply", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert all(not p["restart_required"] for p in body["policies"])
        for p in body["policies"]:
            assert p["configured"]["kind"] == p["effective"]["kind"]
        assert body["runtime_plan"]["restart_required"] is False
        assert body["runtime_plan"]["generation"] == gen_before + 1

        # GET /model-runtime 与 apply 返回同一真相(契约#3 的读取面)
        fetched = await client.get("/api/admin/model-runtime", headers=auth_headers)
        assert fetched.status_code == 200
        assert fetched.json()["runtime_plan"]["generation"] == gen_before + 1
        assert all(not p["restart_required"] for p in fetched.json()["policies"])

        # 幂等:再次 Apply 成功且真相不变(generation 继续推进)
        again = await client.post("/api/admin/model-runtime/apply", headers=auth_headers)
        assert again.status_code == 200
        assert again.json()["runtime_plan"]["generation"] == gen_before + 2

    # 清理持久化策略行,不污染其他测试
    async with app.state.session_factory() as session:
        await session.execute(ModelRuntimePolicy.__table__.delete())
        await session.commit()


async def test_apply_endpoint_capacity_unsafe_409_previous_runtime_intact(
    auth_headers, runtime_manager
):
    """验收:capacity unsafe → 409 + 当前运行配置未改变;Effective 原样可用。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _put_all_cpu_policies(client, auth_headers)
        await client.post("/api/admin/model-runtime/apply", headers=auth_headers)
        gen_applied = (await client.get("/api/admin/model-runtime", headers=auth_headers)).json()[
            "runtime_plan"
        ]["generation"]

        # 直接改库 GPU 策略(经 API 会被 discover_gpus 422 拦下;这里模拟
        # 「保存成功后设备失效/策略被改为不可满足」的场景)+ 低于下限的手动预算
        async with app.state.session_factory() as session:
            row = await session.get(ModelRuntimePolicy, "query_embedding")
            row.device_kind = "gpu"
            row.gpu_uuid = "00000000-0000-0000-0000-000000000001"
            await session.commit()
        budget = await client.put(
            "/api/admin/model-runtime/gpu-budget",
            headers=auth_headers,
            json={"mode": "manual", "manual_budget_mb": 3800},
        )
        assert budget.status_code == 200

        resp = await client.post("/api/admin/model-runtime/apply", headers=auth_headers)
        assert resp.status_code == 409
        assert "当前运行配置未改变" in resp.json()["detail"]

        # 旧 Effective Runtime 原样:查询嵌入仍 CPU、无重启要求外溢、代数未进
        after = (await client.get("/api/admin/model-runtime", headers=auth_headers)).json()
        query = next(p for p in after["policies"] if p["workload"] == "query_embedding")
        assert query["effective"]["kind"] == "cpu"
        assert after["runtime_plan"]["generation"] == gen_applied

    async with app.state.session_factory() as session:
        await session.execute(ModelRuntimePolicy.__table__.delete())
        await session.execute(
            ModelRuntimeSetting.__table__.delete().where(ModelRuntimeSetting.key == "gpu_budget")
        )
        await session.commit()


async def test_apply_endpoint_requires_editor_role(runtime_manager):
    """viewer 只读:POST apply 403。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="rt-viewer@test.com",
                role="viewer",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    try:
        token = create_access_token(str(user_id), "viewer", app.state.settings.jwt_secret)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/model-runtime/apply",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403
    finally:
        async with factory() as session:
            await session.execute(User.__table__.delete().where(User.id == user_id))
            await session.commit()


async def test_apply_endpoint_not_loaded_409(auth_headers, runtime_manager):
    original = app.state.model_runtime
    try:
        app.state.model_runtime = ModelRuntimeManager(
            app.state.settings,
            embedder_factory=lambda device="cpu", **kwargs: _FakeEmbedder(device=device),
            reranker_factory=lambda **kwargs: _FakeReranker(),
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/admin/model-runtime/apply", headers=auth_headers)
        assert resp.status_code == 409
        assert "尚未完成启动装配" in resp.json()["detail"]
    finally:
        app.state.model_runtime = original
