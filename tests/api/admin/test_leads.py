"""销售线索 Admin API 测试(/api/admin/leads)。

覆盖:鉴权矩阵(401/403/角色)、列表过滤与 PII 面收缩(列表不回原文)、
详情含联系方式原文、会话线程聚合、手动移交(幂等/审计字段)、404。
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import Conversation, SalesLead, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

_NS = "lead-admin"


def _mk_lead(session_id: str, **kw) -> SalesLead:
    defaults = dict(
        session_id=session_id,
        status="qualified",
        source_conversation_id=uuid.uuid4(),
        last_conversation_id=uuid.uuid4(),
        company=f"{_NS}-acme",
        product_interest="NE503",
        quantity="500 台",
        ai_summary="采购意向",
    )
    defaults.update(kw)
    return SalesLead(**defaults)


@pytest_asyncio.fixture(loop_scope="session")
async def leads_env():
    """创建 admin/editor/viewer 三角色用户 + 种子线索,返回认证头与清理锚。"""
    factory = app.state.session_factory
    marker = f"{_NS}-{uuid.uuid4().hex[:8]}"
    users: dict[str, str] = {}
    async with factory() as session:
        for role in ("admin", "editor", "viewer"):
            uid = uuid.uuid4()
            session.add(
                User(
                    id=uid,
                    email=f"{role}-{marker}@test.com",
                    role=role,
                    password_hash=hash_password("pass"),
                )
            )
            users[role] = str(uid)
        lead = _mk_lead(
            marker,
            contact_type="email",
            contact_value="sales-buyer@example.com",
            contact_masked="s***@example.com",
        )
        session.add(lead)
        # 无联系方式线索(status 过滤用)
        session.add(_mk_lead(marker + "-pot", status="potential"))
        # 已移交线索
        session.add(_mk_lead(marker + "-done", status="handed_off", handoff_by="boss"))
        await session.commit()
        lead_id = str(lead.id)

    headers = {
        role: {
            "Authorization": "Bearer "
            + create_access_token(uid, role, app.state.settings.jwt_secret)
        }
        for role, uid in users.items()
    }
    yield {"marker": marker, "lead_id": lead_id, "headers": headers}

    async with factory() as session:
        for sid in (marker, marker + "-pot", marker + "-done"):
            await session.execute(SalesLead.__table__.delete().where(SalesLead.session_id == sid))
        for role, uid in users.items():
            await session.execute(
                User.__table__.delete().where(User.email == f"{role}-{marker}@test.com")
            )
        await session.commit()


async def test_list_requires_auth(leads_env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/leads")
    assert resp.status_code == 401


async def test_list_viewer_ok_and_masks_contact(leads_env):
    """列表对 viewer 可读;PII 面收缩:不回 contact_value 原文(G013/G014)。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/leads", headers=leads_env["headers"]["viewer"])
    assert resp.status_code == 200
    data = resp.json()
    mine = [x for x in data["leads"] if x["session_id"] == leads_env["marker"]]
    assert len(mine) == 1
    row = mine[0]
    assert "sales-buyer@example.com" not in resp.text
    assert row["has_contact"] is True
    assert row["contact_masked"] == "s***@example.com"
    assert row["company"] == f"{_NS}-acme"
    assert row["status"] == "qualified"


async def test_list_filters(leads_env):
    h = leads_env["headers"]["viewer"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_status = await client.get("/api/admin/leads?status=handed_off", headers=h)
        r_contact = await client.get("/api/admin/leads?contact=with", headers=h)
        r_q = await client.get(f"/api/admin/leads?q={_NS}-acme", headers=h)
    assert r_status.status_code == 200
    assert all(x["status"] == "handed_off" for x in r_status.json()["leads"])
    assert r_contact.status_code == 200
    assert all(x["has_contact"] for x in r_contact.json()["leads"])
    assert r_q.status_code == 200
    assert any(x["session_id"] == leads_env["marker"] for x in r_q.json()["leads"])


async def test_detail_contains_contact_value(leads_env):
    """详情(销售跟进必需)含联系方式原文,仍仅授权角色可达。"""
    h = leads_env["headers"]["editor"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/admin/leads/{leads_env['lead_id']}", headers=h)
    assert resp.status_code == 200
    body = resp.json()
    assert body["contact_value"] == "sales-buyer@example.com"
    assert body["quantity"] == "500 台"


async def test_detail_404(leads_env):
    h = leads_env["headers"]["viewer"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_missing = await client.get(f"/api/admin/leads/{uuid.uuid4()}", headers=h)
        r_bad = await client.get("/api/admin/leads/not-a-uuid", headers=h)
    assert r_missing.status_code == 404
    assert r_bad.status_code == 404


async def test_thread_aggregates_session_turns(leads_env):
    """G009:按 session_id 聚合完整会话线程(时间正序)。"""
    factory = app.state.session_factory
    marker = leads_env["marker"]
    async with factory() as session:
        for i in range(3):
            session.add(
                Conversation(
                    question=f"{marker}-q{i}",
                    answer=f"a{i}",
                    session_id=marker,
                    channel="widget",
                )
            )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/api/admin/leads/{leads_env['lead_id']}/thread",
            headers=leads_env["headers"]["viewer"],
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == marker
    qs = [m["question"] for m in body["messages"]]
    assert qs == sorted(qs)
    assert f"{marker}-q0" in qs and len(qs) >= 3


async def test_handoff_role_enforced_and_idempotent(leads_env):
    """viewer 403;editor 成功且写审计字段;重复移交幂等;契约 §8 不自动承诺。"""
    lead_id = leads_env["lead_id"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_viewer = await client.post(
            f"/api/admin/leads/{lead_id}/handoff", headers=leads_env["headers"]["viewer"]
        )
        r_editor = await client.post(
            f"/api/admin/leads/{lead_id}/handoff", headers=leads_env["headers"]["editor"]
        )
        r_again = await client.post(
            f"/api/admin/leads/{lead_id}/handoff", headers=leads_env["headers"]["editor"]
        )
    assert r_viewer.status_code == 403
    assert r_editor.status_code == 200
    body = r_editor.json()
    assert body["status"] == "handed_off"
    assert body["handoff_at"] is not None
    assert body["handoff_by"]  # editor 用户名/邮箱
    assert r_again.status_code == 200
    assert r_again.json()["status"] == "handed_off"


async def test_business_overview_new_leads_semantics(leads_env):
    """G010:overview 线索口径 = sales_leads,且不再有 valid(=commercial)混淆。"""
    factory = app.state.session_factory
    async with factory() as session:
        session.add(_mk_lead(leads_env["marker"] + "-ov1", status="potential"))
        session.add(
            _mk_lead(
                leads_env["marker"] + "-ov2",
                status="contact_captured",
                contact_type="phone",
                contact_value="13812345678",
                contact_masked="138******78",
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/business/overview?range=7d", headers=leads_env["headers"]["viewer"]
        )
    assert resp.status_code == 200
    leads = resp.json()["leads"]
    assert "valid" not in leads  # 旧混淆口径已移除
    for key in ("commercial_conversations", "potential", "qualified", "contactable", "handed_off"):
        assert key in leads
    assert leads["potential"] >= 2
    assert leads["contactable"] >= 1
