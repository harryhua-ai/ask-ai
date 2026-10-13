"""Issue #113:范围外孤儿行(missing_candidate + A-3 policy-absence)的显式退休运营动作。

生产背景(2026-09-22,179 孤儿行事件):旧路径形态的行落在 ``include_dirs``
白名单外 → A-3 政策缺席语义把退休计数永久冻结(``policy_absent=N(不计数)``),
源详情页永远显示「N 项知识需要处理」,而 repair-all 对这些行永远不可能成功
(文件已物理丢失)。A-3 分类与 A-2 确认阈值按设计正确且**不得削弱**。

本契约交付(frozen,Issue #113):

- AC1:admin 手动、显式、可审计的退休动作 —— 逐行确认 + A-6 式审计记录
  (操作人/时间/理由/政策原因),复用既有退休语义(即时撤出服务 + 7 天
  GC 资格);绝不适用于 active 行,绝不绕过 A-2(范围内缺席行拒绝);
- AC2:横幅分类真相 —— /documents 响应区分「可修复缺席」与「范围外孤儿」,
  repair-all 资格排除范围外孤儿(对修不好的行不再以修复为动作);
- AC3:A-2/A-3 语义不变(本文件对 lifecycle 词表/确认阈值零触碰;
  回归由 tests/scripts/test_fs_disappearance_retirement.py 等既有套件守卫);
- 负例:未确认(confirm 缺失)、空理由、越权(viewer/editor)、active 行、
  范围内缺席行、陌生 id 一律拒绝或逐项 refused,零部分突变。

真实 Postgres(与 admin API 测试同约定;TEST_DATABASE_URL 或本地 .env)。
"""

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import DataSource, Document, User
from backend.main import app

SRC = f"issue113-{uuid.uuid4().hex[:10]}"
BASE = f"/api/admin/data-sources/{SRC}"

# 旧路径形态(include_dirs 白名单外;2025.2 legacy 前缀,无上传根段)
DOC_ORPHAN_A = f"{SRC}/main/2025.2/case-alpha.md"
# file_types 范围外(.log 不在后缀白名单;在 include_dirs 白名单内)
DOC_ORPHAN_B = f"{SRC}/main/2025.3/case-beta.log"
# 范围内缺席(两次连续确认由 A-2 自动退休;手动动作必须拒绝绕过)
DOC_INSCOPE_MISSING = f"{SRC}/main/experience/in-scope-missing.md"
# 健康在服行(绝不适用)
DOC_ACTIVE = f"{SRC}/main/experience/live.md"


def _absence_meta(policy_reason: str | None) -> dict:
    """A-3/A-2 缺席状态形状(documents.metadata_['absence'];sync 侧真值)。"""
    return {
        "absence": {
            "confirmations": 0,
            "since": "2026-09-01T00:00:00+00:00",
            "policy_reason": policy_reason,
            "last_observed_at": "2026-09-22T00:00:00+00:00",
        }
    }


@pytest_asyncio.fixture(loop_scope="session")
async def seed(tmp_path):
    """播种:1 filesystem 源 + 2 范围外孤儿 + 1 范围内缺席 + 1 健康在服。

    R2 契约(A RC 修正):物理缺失证明在退休时由服务端对**当前**源根执行,
    因此源根必须真实可枚举(R2 之前测试不需要盘面);且**当前**配置必须能
    重放出持久化的 A-3 分类,否则退休判定为「分类陈旧」拒绝:

    - DOC_ORPHAN_A(2025.2/case-alpha.md):include_dirs 只白名单 ``2025.3``
      → 当前分类 ``include_dirs`` == 持久化分类;文件未创建 ⇒ 可验证物理缺失;
    - DOC_ORPHAN_B(2025.3/case-beta.log):``.log`` 不在 file_types 白名单
      → 当前分类 ``file_types`` == 持久化分类;文件未创建 ⇒ 可验证物理缺失。
    """
    root = tmp_path / "uploads"
    root.mkdir(parents=True)
    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            DataSource(
                id=SRC,
                type="filesystem",
                product="probe",
                config={"root_path": str(root), "include_dirs": ["2025.3"]},
                sync_interval="24h",
                enabled=True,
            )
        )
        session.add(
            Document(
                source_id=DOC_ORPHAN_A,
                content_hash="a" * 64,
                source_type="filesystem",
                product="probe",
                title="case-alpha",
                url=f"file:///{DOC_ORPHAN_A}",
                branch="",
                chunk_count=1,
                lifecycle="missing_candidate",
                metadata_=_absence_meta("include_dirs"),
            )
        )
        session.add(
            Document(
                source_id=DOC_ORPHAN_B,
                content_hash="b" * 64,
                source_type="filesystem",
                product="probe",
                title="case-beta",
                url=f"file:///{DOC_ORPHAN_B}",
                branch="",
                chunk_count=1,
                lifecycle="missing_candidate",
                metadata_=_absence_meta("file_types"),
            )
        )
        session.add(
            Document(
                source_id=DOC_INSCOPE_MISSING,
                content_hash="c" * 64,
                source_type="filesystem",
                product="probe",
                title="in-scope-missing",
                url=f"file:///{DOC_INSCOPE_MISSING}",
                branch="",
                chunk_count=1,
                lifecycle="missing_candidate",
                metadata_=_absence_meta(None),
            )
        )
        session.add(
            Document(
                source_id=DOC_ACTIVE,
                content_hash="d" * 64,
                source_type="filesystem",
                product="probe",
                title="live",
                url=f"file:///{DOC_ACTIVE}",
                branch="",
                chunk_count=1,
                lifecycle="active",
            )
        )
        await session.commit()
    yield
    async with factory() as session:
        await session.execute(
            Document.__table__.delete().where(Document.source_id.like(f"{SRC}/%"))
        )
        await session.execute(DataSource.__table__.delete().where(DataSource.id == SRC))
        await session.execute(User.__table__.delete().where(User.email.like(f"{SRC}%")))
        await session.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def admin_headers():
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email=f"{SRC}-admin@test.com",
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


async def _make_role_headers(role: str) -> dict:
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email=f"{SRC}-{role}-{uuid.uuid4().hex[:6]}@test.com",
                role=role,
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), role, app.state.settings.jwt_secret)
    return {"Authorization": f"Bearer {token}"}


class _FakeCollection:
    """weaviate v4 collection 测试替身(与既有 repair-all 门测试同约定)。"""

    def __init__(self) -> None:
        self.objects: list[dict] = []

    def iterator(self, return_properties=None, **kw):
        def _gen():
            for o in self.objects:
                props = dict(o)
                if return_properties:
                    props = {k: props.get(k) for k in return_properties}
                yield SimpleNamespace(properties=props)

        return _gen()


class _FakeEmbedder:
    def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


@pytest_asyncio.fixture(loop_scope="session")
async def vector_stack():
    saved = {
        k: getattr(app.state, k, None)
        for k in ("weaviate_client", "embedder", "weaviate_class_name")
    }
    client = SimpleNamespace(
        collections=SimpleNamespace(get=lambda _name: _FakeCollection())
    )
    app.state.weaviate_client = client
    app.state.embedder = _FakeEmbedder()
    app.state.weaviate_class_name = "Document"
    yield
    for k, v in saved.items():
        if v is not None:
            setattr(app.state, k, v)


async def _doc(source_id: str) -> Document | None:
    async with app.state.session_factory() as session:
        return (
            await session.execute(
                select(Document).where(Document.source_id == source_id)
            )
        ).scalar_one_or_none()


async def _set_source_config(config: dict) -> None:
    """改写测试源的**当前**配置(模拟管理操作:白名单放宽/根路径丢失等)。"""
    async with app.state.session_factory() as session:
        ds = (
            await session.execute(select(DataSource).where(DataSource.id == SRC))
        ).scalar_one()
        ds.config = config
        await session.commit()


# --------------------------------------------------------------------------- #
# AC1:显式退休动作(确认 + 审计 + 既有退休语义)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio(loop_scope="session")
async def test_retire_requires_explicit_confirmation(admin_headers, seed):
    """负例:缺 confirm=true ⇒ 400,零行突变(显式确认是硬门槛)。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            f"{BASE}/documents/retire",
            headers=admin_headers,
            json={"doc_source_ids": [DOC_ORPHAN_A], "reason": "files lost"},
        )
    assert resp.status_code == 400, "未显式确认的退休必须 400 拒绝"
    doc = await _doc(DOC_ORPHAN_A)
    assert doc is not None and doc.lifecycle == "missing_candidate", (
        "拒绝路径不得突变任何行"
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_retire_requires_reason(admin_headers, seed):
    """负例:空理由 ⇒ 400(审计留痕必须携带操作理由)。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        for reason in ("", "   "):
            resp = await client.post(
                f"{BASE}/documents/retire",
                headers=admin_headers,
                json={
                    "doc_source_ids": [DOC_ORPHAN_A],
                    "confirm": True,
                    "reason": reason,
                },
            )
            assert resp.status_code == 400, f"空理由(reason={reason!r})必须 400 拒绝"
    doc = await _doc(DOC_ORPHAN_A)
    assert doc.lifecycle == "missing_candidate"


@pytest.mark.asyncio(loop_scope="session")
async def test_retire_viewer_and_editor_forbidden(seed):
    """负例:viewer/editor 越权 ⇒ 403(退休是 admin 专属运营动作)。"""
    for role in ("viewer", "editor"):
        headers = await _make_role_headers(role)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as client:
            resp = await client.post(
                f"{BASE}/documents/retire",
                headers=headers,
                json={
                    "doc_source_ids": [DOC_ORPHAN_A],
                    "confirm": True,
                    "reason": "files lost",
                },
            )
        assert resp.status_code == 403, f"{role} 不得触发退休动作"
    doc = await _doc(DOC_ORPHAN_A)
    assert doc.lifecycle == "missing_candidate"


@pytest.mark.asyncio(loop_scope="session")
async def test_retire_scope_external_orphans_with_a6_audit(admin_headers, seed, tmp_path):
    """AC1 主链:逐行显式退休范围外孤儿 + A-6 式审计(操作人/时间/理由/政策原因)。

    退休语义与既有发现确认退休同一原语:lifecycle→deleted(即时撤出服务)
    + 7 天 GC 资格(retired_at + 7d);缺席状态清除;reason=manual 封闭词表。

    R2(A RC):正向主链同时就是「可验证物理缺失」证明 —— 文件未创建,
    服务端对当前源根解析出的绝对路径做存在性检查通过(verified_absent),
    证明写进 A-6 审计记录 evidence.physical_absence。
    """
    reason_text = "2026-09-22 事件:文件在 pre-#100 上传纪元物理丢失,路径形态迁移致范围外"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            f"{BASE}/documents/retire",
            headers=admin_headers,
            json={
                "doc_source_ids": [DOC_ORPHAN_A, DOC_ORPHAN_B],
                "confirm": True,
                "reason": reason_text,
            },
        )
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert body["retired"] == 2
    assert body["refused"] == 0
    by_doc = {i["doc_source_id"]: i for i in body["items"]}
    assert by_doc[DOC_ORPHAN_A]["status"] == "retired"
    assert by_doc[DOC_ORPHAN_B]["status"] == "retired"

    for sid, policy in ((DOC_ORPHAN_A, "include_dirs"), (DOC_ORPHAN_B, "file_types")):
        doc = await _doc(sid)
        assert doc is not None and doc.lifecycle == "deleted", (
            "退休行必须 lifecycle=deleted(即时撤出服务投影)"
        )
        assert doc.deleted_at is not None
        record = (doc.metadata_ or {}).get("retirement")
        assert isinstance(record, dict), "A-6 审计记录必须持久化到 metadata_[retirement]"
        assert record.get("reason") == "manual"
        assert str(record.get("actor", "")).startswith("admin:"), (
            f"审计必须记录操作人(实际: {record.get('actor')!r})"
        )
        evidence = record.get("evidence") or {}
        assert evidence.get("policy_reason") == policy, "审计必须记录 A-3 政策原因"
        assert evidence.get("justification") == reason_text, "审计必须记录操作理由"
        assert record.get("gc_eligible_at"), "发现确认语义:退休必须携带 7 天 GC 资格时刻"
        retired_at = datetime.fromisoformat(record["retired_at"])
        gc_at = datetime.fromisoformat(record["gc_eligible_at"])
        assert timedelta(days=6) < gc_at - retired_at <= timedelta(days=7), (
            "GC 资格 = retired_at + 7d(与发现确认退休同一冻结时序)"
        )
        assert "absence" not in (doc.metadata_ or {}), "退休后缺席状态必须清除"
        # R2:物理缺失证明必须随审计留痕(服务端对当前源根的当前检查)。
        proof = evidence.get("physical_absence")
        assert isinstance(proof, dict), "退休审计必须携带 physical_absence 证明"
        assert proof.get("resolved_path"), "证明必须记录存在性检查的解析绝对路径"
        assert proof.get("root"), "证明必须记录当前源根"
        assert proof.get("checked_at"), "证明必须记录检查时点"
        assert str(proof["resolved_path"]).endswith(sid.rsplit("/", 1)[-1]), (
            "解析路径必须对应该行身份的末段"
        )


@pytest.mark.asyncio(loop_scope="session")
async def test_retire_all_scope_external_mode(admin_headers, seed):
    """AC1(all 形态):all_scope_external=true ⇒ 服务端选取全部资格行并逐行退休。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            f"{BASE}/documents/retire",
            headers=admin_headers,
            json={"all_scope_external": True, "confirm": True, "reason": "batch close-out"},
        )
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert body["retired"] == 2
    assert (await _doc(DOC_ACTIVE)).lifecycle == "active", "active 行绝不适用"
    assert (await _doc(DOC_INSCOPE_MISSING)).lifecycle == "missing_candidate", (
        "范围内缺席行绝不适用手动退休(由 A-2 确认语义负责)"
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_retire_idempotent_on_already_retired(admin_headers, seed):
    """幂等:重复退休同一行 ⇒ already_retired,审计记录零改写。"""
    body_in = {
        "doc_source_ids": [DOC_ORPHAN_A],
        "confirm": True,
        "reason": "first pass",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        first = await client.post(f"{BASE}/documents/retire", headers=admin_headers, json=body_in)
        assert first.status_code == 200
        doc_after_first = await _doc(DOC_ORPHAN_A)
        record_first = doc_after_first.metadata_["retirement"]
        second = await client.post(f"{BASE}/documents/retire", headers=admin_headers, json=body_in)
    assert second.status_code == 200
    body = second.json()
    by_doc = {i["doc_source_id"]: i for i in body["items"]}
    assert by_doc[DOC_ORPHAN_A]["status"] == "already_retired"
    assert body["retired"] == 0
    doc_after_second = await _doc(DOC_ORPHAN_A)
    assert doc_after_second.metadata_["retirement"] == record_first, (
        "重复退休不得改写既有审计记录"
    )


# --------------------------------------------------------------------------- #
# 边界:A-2 不可绕过 / active 行保护 / 陌生 id
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio(loop_scope="session")
async def test_retire_refuses_active_inscope_and_unknown_rows(admin_headers, seed):
    """负例:active / 范围内缺席 / 陌生 id ⇒ 逐项 refused,资格行照常退休。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            f"{BASE}/documents/retire",
            headers=admin_headers,
            json={
                "doc_source_ids": [
                    DOC_ORPHAN_A,
                    DOC_ACTIVE,
                    DOC_INSCOPE_MISSING,
                    f"{SRC}/main/never-existed.md",
                ],
                "confirm": True,
                "reason": "mixed request",
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    by_doc = {i["doc_source_id"]: i for i in body["items"]}
    assert by_doc[DOC_ORPHAN_A]["status"] == "retired"
    assert by_doc[DOC_ACTIVE]["status"] == "refused" and by_doc[DOC_ACTIVE]["error"]
    assert by_doc[DOC_INSCOPE_MISSING]["status"] == "refused" and (
        by_doc[DOC_INSCOPE_MISSING]["error"]
    )
    assert body["refused"] == 3
    active = await _doc(DOC_ACTIVE)
    assert active.lifecycle == "active" and active.deleted_at is None
    inscope = await _doc(DOC_INSCOPE_MISSING)
    assert inscope.lifecycle == "missing_candidate"
    absence = (inscope.metadata_ or {}).get("absence") or {}
    assert absence.get("confirmations") == 0 and absence.get("policy_reason") is None, (
        "范围内缺席行的 A-2 确认计数状态必须原样保留(手动动作不绕过 A-2)"
    )


# --------------------------------------------------------------------------- #
# AC2:横幅分类真相(可修复缺席 vs 范围外孤儿)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio(loop_scope="session")
async def test_documents_response_classifies_scope_external_orphans(admin_headers, seed):
    """AC2:/documents 响应区分「可修复」与「范围外孤儿」计数 + 行级政策原因。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(f"{BASE}/documents", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["attention_scope_external_orphan_count"] == 2, (
        "2 个范围外孤儿行必须被分类呈现(横幅不再把 repair-all 当成它们的动作)"
    )
    attention = body["ledger_total"] - (
        body["lifecycle_counts"].get("superseded", 0)
        + body["lifecycle_counts"].get("deleted", 0)
    ) - body["current_count"]
    assert body["attention_repairable_count"] == attention - 2
    by_doc = {i["source_id"]: i for i in body["items"]}
    assert by_doc[DOC_ORPHAN_A]["absence_policy_reason"] == "include_dirs"
    assert by_doc[DOC_ORPHAN_B]["absence_policy_reason"] == "file_types"
    assert by_doc[DOC_INSCOPE_MISSING]["absence_policy_reason"] is None
    assert by_doc[DOC_ACTIVE]["absence_policy_reason"] is None


@pytest.mark.asyncio(loop_scope="session")
async def test_repair_all_excludes_scope_external_orphans(admin_headers, seed, vector_stack):
    """AC2:repair-all 资格排除范围外孤儿 —— 对修不好的行不再以修复为动作。

    文件已物理丢失 + 范围外:修复(从盘重摄取)永远不可能成功;资格集必须
    只含可修复缺席行,孤儿不得入批(也不再产生注定失败的修复任务记录)。
    修复执行以测试替身注入(与既有 repair-all 门测试同约定)。
    """
    captured: list[str] = []

    async def _spy_execute(*args, **kwargs):
        # 记录进入执行的任务 id,由调用方断言孤儿绝不入批
        captured.append(str(kwargs.get("task_id") or (args[1] if len(args) > 1 else "")))
        from backend.services.document_repair import STAGE_VERIFY

        task = SimpleNamespace(
            id=kwargs.get("task_id"),
            status="rebuild_requested",
            stage=STAGE_VERIFY,
            error=None,
            result={"sync_request_id": None},
        )
        return task

    import backend.api.admin.data_sources as ds_mod

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(ds_mod, "execute_repair_task", _spy_execute)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as client:
            resp = await client.post(f"{BASE}/documents/repair-all", headers=admin_headers)
    finally:
        monkeypatch.undo()
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    batch_ids = {i["doc_source_id"] for i in body["items"]}
    assert DOC_ORPHAN_A not in batch_ids, "范围外孤儿不得进入修复批(修不好 ≠ 待修复)"
    assert DOC_ORPHAN_B not in batch_ids
    assert DOC_INSCOPE_MISSING in batch_ids, "范围内缺席行仍是可修复资格(语义不变)"


# --------------------------------------------------------------------------- #
# R2(A REQUEST_CHANGES 修正):配置策略排除 ≠ 文件物理丢失。
# 退休前服务端做**当前**物理缺失证明;无法证明(UNKNOWN)或分类陈旧一律拒绝;
# 横幅/计数不再把范围外排除标注为确定性丢失。
# --------------------------------------------------------------------------- #


async def _seed_orphan(doc_source_id: str, policy_reason: str) -> None:
    """补种一行范围外孤儿(混合态用;teardown 的 like 清理已覆盖)。"""
    async with app.state.session_factory() as session:
        session.add(
            Document(
                source_id=doc_source_id,
                content_hash="e" * 64,
                source_type="filesystem",
                product="probe",
                title=doc_source_id.rsplit("/", 1)[-1],
                url=f"file:///{doc_source_id}",
                branch="",
                chunk_count=1,
                lifecycle="missing_candidate",
                metadata_=_absence_meta(policy_reason),
            )
        )
        await session.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_retire_refuses_present_but_excluded_file(admin_headers, seed, tmp_path):
    """负例(误杀场景本体):文件仍在盘上但被 include_dirs 排除 ⇒ 拒绝退休。

    范围外排除 ≠ 物理丢失:服务端必须对当前源根解析出的绝对路径做存在性
    检查;文件在盘 ⇒ 可恢复文档,绝不撤出(撤出后 7 天可被物理 GC)。
    """
    present = tmp_path / "uploads" / "2025.2" / "case-alpha.md"
    present.parent.mkdir(parents=True, exist_ok=True)
    present.write_text("仍在盘上", encoding="utf-8")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            f"{BASE}/documents/retire",
            headers=admin_headers,
            json={
                "doc_source_ids": [DOC_ORPHAN_A],
                "confirm": True,
                "reason": "全选退休(误杀场景:旧分类合格但文件其实还在)",
            },
        )
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert body["retired"] == 0, "present-but-excluded 绝不允许被退休"
    assert body["refused"] == 1
    item = body["items"][0]
    assert item["status"] == "refused"
    assert "仍在盘上" in (item["error"] or ""), f"拒绝理由必须说明文件在盘: {item['error']}"
    doc = await _doc(DOC_ORPHAN_A)
    assert doc is not None and doc.lifecycle == "missing_candidate", "拒绝路径零突变"
    assert (doc.metadata_ or {}).get("retirement") is None, "拒绝不得写退休审计"
    absence = (doc.metadata_ or {}).get("absence") or {}
    assert absence.get("policy_reason") == "include_dirs", "缺席状态必须原样保留"


@pytest.mark.asyncio(loop_scope="session")
async def test_retire_refuses_stale_classification_after_whitelist_relaxation(
    admin_headers, seed, tmp_path
):
    """负例(陈旧分类):白名单放宽后未重跑 discovery ⇒ 持久化分类不得授权退休。

    持久化 policy_reason='include_dirs',但**当前**配置已无 include_dirs
    (该身份回到范围内)—— 分类与当前配置对账失败,必须拒绝(否则以陈旧
    分类退休,绕过 A-2 对「现在范围内缺席」的两次确认语义)。
    """
    await _set_source_config({"root_path": str(tmp_path / "uploads")})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            f"{BASE}/documents/retire",
            headers=admin_headers,
            json={
                "doc_source_ids": [DOC_ORPHAN_A],
                "confirm": True,
                "reason": "白名单已放宽,顺手收口旧行",
            },
        )
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert body["retired"] == 0, "陈旧分类绝不得授权退休"
    item = body["items"][0]
    assert item["status"] == "refused"
    assert "陈旧" in (item["error"] or ""), f"拒绝理由必须指出分类陈旧: {item['error']}"
    doc = await _doc(DOC_ORPHAN_A)
    assert doc.lifecycle == "missing_candidate"
    assert (doc.metadata_ or {}).get("retirement") is None


@pytest.mark.asyncio(loop_scope="session")
async def test_retire_refuses_when_source_root_unavailable(admin_headers, seed, tmp_path):
    """负例(源不可达):当前源根不可枚举 ⇒ 无法证明物理缺失,UNKNOWN 拒绝。"""
    await _set_source_config(
        {"root_path": str(tmp_path / "does-not-exist"), "include_dirs": ["2025.3"]}
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            f"{BASE}/documents/retire",
            headers=admin_headers,
            json={
                "doc_source_ids": [DOC_ORPHAN_A],
                "confirm": True,
                "reason": "根挂载缺失时的批量清理",
            },
        )
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert body["retired"] == 0, "源根不可达时绝不允许退休(无法证明缺失)"
    item = body["items"][0]
    assert item["status"] == "refused"
    assert "无法证明物理缺失" in (item["error"] or ""), (
        f"拒绝理由必须说明 UNKNOWN: {item['error']}"
    )
    doc = await _doc(DOC_ORPHAN_A)
    assert doc.lifecycle == "missing_candidate"
    assert (doc.metadata_ or {}).get("retirement") is None


@pytest.mark.asyncio(loop_scope="session")
async def test_retire_refuses_when_source_config_invalid(admin_headers, seed):
    """负例(配置不可用):config 缺 root_path ⇒ 连接器不可构建,UNKNOWN 拒绝。"""
    await _set_source_config({})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            f"{BASE}/documents/retire",
            headers=admin_headers,
            json={
                "doc_source_ids": [DOC_ORPHAN_A],
                "confirm": True,
                "reason": "配置已损坏,清理孤儿",
            },
        )
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert body["retired"] == 0, "当前配置不可用时绝不允许退休"
    item = body["items"][0]
    assert item["status"] == "refused"
    assert "无法证明物理缺失" in (item["error"] or ""), (
        f"拒绝理由必须落入 UNKNOWN 家族: {item['error']}"
    )
    doc = await _doc(DOC_ORPHAN_A)
    assert doc.lifecycle == "missing_candidate"


@pytest.mark.asyncio(loop_scope="session")
async def test_retire_bulk_mixed_states_adjudicates_per_row(
    admin_headers, seed, tmp_path
):
    """负例(批量混合态):verified-absent / present / 陈旧 / 越界身份 / active /
    范围内缺席逐行独立裁决 —— 只有可验证物理缺失的行退休,其余逐项 refused
    并携带原因;零部分突变扩散。"""
    present = tmp_path / "uploads" / "2025.3" / "still-here.log"
    present.parent.mkdir(parents=True, exist_ok=True)
    present.write_text("在盘", encoding="utf-8")
    doc_present = f"{SRC}/main/2025.3/still-here.log"
    doc_stale = f"{SRC}/main/2025.2/stale-classification.md"  # 持久化 exclusion_policy ≠ 当前 include_dirs
    doc_escape = f"{SRC}/main/../escape.md"  # 越界路径段:身份不可解析 → UNKNOWN
    await _seed_orphan(doc_present, "file_types")
    await _seed_orphan(doc_stale, "exclusion_policy")
    await _seed_orphan(doc_escape, "include_dirs")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            f"{BASE}/documents/retire",
            headers=admin_headers,
            json={
                "doc_source_ids": [
                    DOC_ORPHAN_A,
                    doc_present,
                    doc_stale,
                    doc_escape,
                    DOC_ACTIVE,
                    DOC_INSCOPE_MISSING,
                ],
                "confirm": True,
                "reason": "混合态批量收口",
            },
        )
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert body["retired"] == 1, "只有可验证物理缺失的行允许退休"
    assert body["refused"] == 5
    by_doc = {i["doc_source_id"]: i for i in body["items"]}
    assert by_doc[DOC_ORPHAN_A]["status"] == "retired"
    assert by_doc[doc_present]["status"] == "refused"
    assert "仍在盘上" in (by_doc[doc_present]["error"] or "")
    assert by_doc[doc_stale]["status"] == "refused"
    assert "陈旧" in (by_doc[doc_stale]["error"] or "")
    assert by_doc[doc_escape]["status"] == "refused"
    assert "无法证明物理缺失" in (by_doc[doc_escape]["error"] or "")
    assert by_doc[DOC_ACTIVE]["status"] == "refused"
    assert by_doc[DOC_INSCOPE_MISSING]["status"] == "refused"
    # 被拒行零突变(逐行裁决不得扩散)。
    for sid in (doc_present, doc_stale, doc_escape):
        doc = await _doc(sid)
        assert doc.lifecycle == "missing_candidate"
        assert (doc.metadata_ or {}).get("retirement") is None
    retired = await _doc(DOC_ORPHAN_A)
    assert retired.lifecycle == "deleted"
