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
        for sid in (
            marker,
            marker + "-pot",
            marker + "-done",
            marker + "-bystander",
            marker + "-real",
            marker + "-ov1",
            marker + "-ov2",
            # #124 R2 回归种子
            marker + "-ccv",
            marker + "-ccok",
            marker + "-qv",
            marker + "-hv",
        ):
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


# --------------------------------------------------------------------------- #
# #124 错误联系方式可审计作废(POST /leads/{id}/void-contact)
# --------------------------------------------------------------------------- #


async def test_void_contact_requires_auth(leads_env):
    """未认证方不可作废(AC3 权限边界)。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/admin/leads/{leads_env['lead_id']}/void-contact",
            json={"confirm": True, "reason": "误报"},
        )
    assert resp.status_code == 401


async def test_void_contact_admin_only(leads_env):
    """仅 admin 可作废;editor/viewer 403(AC1「已授权管理员」+ AC3 未授权方不可作废)。"""
    lead_id = leads_env["lead_id"]
    body = {"confirm": True, "reason": "误报"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_viewer = await client.post(
            f"/api/admin/leads/{lead_id}/void-contact",
            json=body,
            headers=leads_env["headers"]["viewer"],
        )
        r_editor = await client.post(
            f"/api/admin/leads/{lead_id}/void-contact",
            json=body,
            headers=leads_env["headers"]["editor"],
        )
    assert r_viewer.status_code == 403
    assert r_editor.status_code == 403
    # 未授权尝试不得改写数据
    factory = app.state.session_factory
    async with factory() as session:
        lead = await session.get(SalesLead, uuid.UUID(lead_id))
        assert lead.contact_voided is False


async def test_void_contact_requires_confirm_and_reason(leads_env):
    """明确确认后才能作废:缺 confirm / confirm=false / 空白理由 → 422(AC1 二次确认)。"""
    lead_id = leads_env["lead_id"]
    admin = leads_env["headers"]["admin"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_no_confirm = await client.post(
            f"/api/admin/leads/{lead_id}/void-contact",
            json={"confirm": False, "reason": "误报"},
            headers=admin,
        )
        r_missing_confirm = await client.post(
            f"/api/admin/leads/{lead_id}/void-contact",
            json={"reason": "误报"},
            headers=admin,
        )
        r_blank_reason = await client.post(
            f"/api/admin/leads/{lead_id}/void-contact",
            json={"confirm": True, "reason": "   "},
            headers=admin,
        )
        r_missing_reason = await client.post(
            f"/api/admin/leads/{lead_id}/void-contact",
            json={"confirm": True},
            headers=admin,
        )
    assert r_no_confirm.status_code == 422
    assert r_missing_confirm.status_code == 422
    assert r_blank_reason.status_code == 422
    assert r_missing_reason.status_code == 422


async def test_void_contact_saves_audit_and_idempotent(leads_env):
    """作废保存操作人/时间/理由;contact_value 原文保留(审计);重复提交幂等
    (首写审计不被覆盖);其余线索零误改(AC1)。"""
    marker = leads_env["marker"]
    factory = app.state.session_factory
    async with factory() as session:
        other = _mk_lead(
            marker + "-bystander",
            contact_type="phone",
            contact_value="13900001111",
            contact_masked="139******11",
        )
        session.add(other)
        await session.commit()
        other_id = str(other.id)

    lead_id = leads_env["lead_id"]
    admin = leads_env["headers"]["admin"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post(
            f"/api/admin/leads/{lead_id}/void-contact",
            json={"confirm": True, "reason": "时间戳被误判为电话"},
            headers=admin,
        )
        first = r1.json()
        # 幂等:再次提交(不同理由)→ 200,首写审计不变
        r2 = await client.post(
            f"/api/admin/leads/{lead_id}/void-contact",
            json={"confirm": True, "reason": "第二次补充理由"},
            headers=admin,
        )
    assert r1.status_code == 200
    body = first
    assert body["contact_voided"] is True
    assert body["contact_voided_by"]  # 操作人 email
    assert body["contact_voided_at"] is not None
    assert body["contact_voided_reason"] == "时间戳被误判为电话"
    # 原文保留(必要历史审计,不可恢复擦除被禁止)
    assert body["contact_value"] == "sales-buyer@example.com"
    assert body["contact_masked"] == "s***@example.com"

    assert r2.status_code == 200
    again = r2.json()
    assert again["contact_voided_at"] == body["contact_voided_at"]
    assert again["contact_voided_by"] == body["contact_voided_by"]
    assert again["contact_voided_reason"] == "时间戳被误判为电话"

    # 目标性:其它线索零误改
    async with factory() as session:
        o = await session.get(SalesLead, uuid.UUID(other_id))
        assert o.contact_voided is False
        assert o.contact_voided_by is None
        assert o.contact_value == "13900001111"


async def test_void_contact_not_found_and_no_contact(leads_env):
    """404:线索不存在/非法 UUID;409:线索没有已捕获联系方式可作废。"""
    admin = leads_env["headers"]["admin"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_missing = await client.post(
            f"/api/admin/leads/{uuid.uuid4()}/void-contact",
            json={"confirm": True, "reason": "误报"},
            headers=admin,
        )
        r_bad = await client.post(
            "/api/admin/leads/not-a-uuid/void-contact",
            json={"confirm": True, "reason": "误报"},
            headers=admin,
        )
        # marker+"-pot" 种子线索无联系方式
        factory = app.state.session_factory
        async with factory() as session:
            from sqlalchemy import select

            row = (
                await session.execute(
                    select(SalesLead).where(SalesLead.session_id == leads_env["marker"] + "-pot")
                )
            ).scalar_one()
        r_no_contact = await client.post(
            f"/api/admin/leads/{row.id}/void-contact",
            json={"confirm": True, "reason": "误报"},
            headers=admin,
        )
    assert r_missing.status_code == 404
    assert r_bad.status_code == 404
    assert r_no_contact.status_code == 409


async def test_voided_lead_list_and_filter_semantics(leads_env):
    """AC2/AC3:作废后列表 has_contact=False;contact=with 排除;contact=voided
    可单独查看(审计);列表永不回原文;详情仍保留原文与作废审计。"""
    marker = leads_env["marker"]
    lead_id = leads_env["lead_id"]
    viewer = leads_env["headers"]["viewer"]
    admin = leads_env["headers"]["admin"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        rv = await client.post(
            f"/api/admin/leads/{lead_id}/void-contact",
            json={"confirm": True, "reason": "误报"},
            headers=admin,
        )
        assert rv.status_code == 200

        r_with = await client.get("/api/admin/leads?contact=with", headers=viewer)
        r_voided = await client.get("/api/admin/leads?contact=voided", headers=viewer)
        r_all = await client.get(f"/api/admin/leads?q={_NS}-acme", headers=viewer)
        r_detail = await client.get(f"/api/admin/leads/{lead_id}", headers=viewer)

    assert all(
        x["has_contact"] is False for x in r_with.json()["leads"] if x["session_id"] == marker
    )
    voided_rows = [x for x in r_voided.json()["leads"] if x["session_id"] == marker]
    assert len(voided_rows) == 1
    vrow = voided_rows[0]
    assert vrow["contact_voided"] is True
    assert vrow["has_contact"] is False
    assert vrow["contact_masked"] == "s***@example.com"
    # 列表不回原文(既有 PII 边界不因作废放宽)
    assert "sales-buyer@example.com" not in r_with.text
    assert "sales-buyer@example.com" not in r_voided.text
    assert "sales-buyer@example.com" not in r_all.text

    # 列表仍可见该线索(审计可见),状态徽章独立于作废标记
    all_rows = [x for x in r_all.json()["leads"] if x["session_id"] == marker]
    assert len(all_rows) == 1
    assert all_rows[0]["contact_voided"] is True

    # 详情(授权角色)保留原文 + 作废审计(AC3 可追溯)
    detail = r_detail.json()
    assert detail["contact_value"] == "sales-buyer@example.com"
    assert detail["contact_voided"] is True
    assert detail["contact_voided_reason"] == "误报"
    assert detail["contact_voided_by"]


async def test_funnel_counts_voided_separately(leads_env):
    """AC2:作废后不再计入有效联系数(contactable);漏斗单独统计作废数量;
    既有真实有效联系方式不受影响。"""
    marker = leads_env["marker"]
    factory = app.state.session_factory
    # 一条真实有效联系方式对照(不受作废影响)
    async with factory() as session:
        session.add(
            _mk_lead(
                marker + "-real",
                status="contact_captured",
                contact_type="email",
                contact_value="realbuyer@example.com",
                contact_masked="r***@example.com",
            )
        )
        await session.commit()

    lead_id = leads_env["lead_id"]
    viewer = leads_env["headers"]["viewer"]
    admin = leads_env["headers"]["admin"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_before = await client.get("/api/admin/business/overview?range=7d", headers=viewer)
        contactable_before = r_before.json()["leads"]["contactable"]

        rv = await client.post(
            f"/api/admin/leads/{lead_id}/void-contact",
            json={"confirm": True, "reason": "误报"},
            headers=admin,
        )
        assert rv.status_code == 200

        r_after = await client.get("/api/admin/business/overview?range=7d", headers=viewer)

    leads = r_after.json()["leads"]
    assert "contact_voided" in leads  # 漏斗单独统计作废数量
    assert leads["contact_voided"] >= 1
    # 作废后有效联系数恰好减一(误报不再冒充可联系线索)
    assert leads["contactable"] == contactable_before - 1


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


# --------------------------------------------------------------------------- #
# #124 R2(评审 blocking 修复)三回归:
#   R2-1 生效语义:作废行不得在筛选/漏斗/徽章口径继续宣称「有效已留联」;
#   R2-2 并发首写:同行竞态下首写审计不可被覆盖(见 tests/services/test_lead_service.py);
#   R2-3 列表面 PII:作废理由自由文本只在授权详情回传,列表投影最小化。
# --------------------------------------------------------------------------- #


async def _seed(factory, sid: str, **kw) -> str:
    async with factory() as session:
        lead = _mk_lead(sid, **kw)
        session.add(lead)
        await session.commit()
        return str(lead.id)


async def test_voided_contact_captured_not_claimed_as_valid_captured(leads_env):
    """R2-1(AC2):作废后生效口径不再宣称有效已留联。

    - GET /leads?status=contact_captured 不再包含已作废行(生效视图/筛选);
    - 列表暴露 effective_status(生效状态):作废的 contact_captured 生效回落
      potential(线索存在、意图未确证),raw status 原样保留(不可变历史);
    - 对照:真实有效的 contact_captured 行不受影响。"""
    marker = leads_env["marker"]
    factory = app.state.session_factory
    ccv_id = await _seed(
        factory,
        marker + "-ccv",
        status="contact_captured",
        contact_type="phone",
        contact_value="13800001111",
        contact_masked="138******11",
    )
    await _seed(
        factory,
        marker + "-ccok",
        status="contact_captured",
        contact_type="email",
        contact_value="okbuyer@example.com",
        contact_masked="o***@example.com",
    )

    admin = leads_env["headers"]["admin"]
    viewer = leads_env["headers"]["viewer"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        rv = await client.post(
            f"/api/admin/leads/{ccv_id}/void-contact",
            json={"confirm": True, "reason": "时间戳被误判为电话"},
            headers=admin,
        )
        assert rv.status_code == 200
        r_cc = await client.get("/api/admin/leads?status=contact_captured", headers=viewer)
        r_pot = await client.get("/api/admin/leads?status=potential", headers=viewer)
        r_detail = await client.get(f"/api/admin/leads/{ccv_id}", headers=viewer)

    # 作废行退出 contact_captured 生效筛选;真实有效行不受影响
    cc_sessions = {x["session_id"] for x in r_cc.json()["leads"]}
    assert marker + "-ccv" not in cc_sessions
    assert marker + "-ccok" in cc_sessions
    assert all(x["effective_status"] == "contact_captured" for x in r_cc.json()["leads"])

    # 作废行落回 potential 生效档(仍审计可见,不凭空消失)
    pot_rows = [x for x in r_pot.json()["leads"] if x["session_id"] == marker + "-ccv"]
    assert len(pot_rows) == 1
    vrow = pot_rows[0]
    assert vrow["effective_status"] == "potential"
    assert vrow["status"] == "contact_captured"  # raw 历史不改写
    assert vrow["contact_voided"] is True

    # 详情:raw 历史保留 + 生效语义并存
    detail = r_detail.json()
    assert detail["status"] == "contact_captured"
    assert detail["effective_status"] == "potential"


async def test_funnel_qualified_drops_voided_contact_only_rows(leads_env):
    """R2-1(AC2):漏斗 qualified 不再把已作废的 contact_captured 行当合格档
    (其资格仅由已作废联系方式支撑);真正独立成立的 qualified / handed_off
    行不因作废联系方式被盲目降级(独立购买意图/人工移交是历史事实)。"""
    marker = leads_env["marker"]
    factory = app.state.session_factory
    ccv_id = await _seed(
        factory,
        marker + "-ccv",
        status="contact_captured",
        contact_type="phone",
        contact_value="13800002222",
        contact_masked="138******22",
    )
    qv_id = await _seed(
        factory,
        marker + "-qv",
        status="qualified",
        contact_type="email",
        contact_value="qbuyer@example.com",
        contact_masked="q***@example.com",
    )
    hv_id = await _seed(
        factory,
        marker + "-hv",
        status="handed_off",
        contact_type="email",
        contact_value="hbuyer@example.com",
        contact_masked="h***@example.com",
        handoff_by="boss",
    )

    admin = leads_env["headers"]["admin"]
    viewer = leads_env["headers"]["viewer"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_before = await client.get("/api/admin/business/overview?range=7d", headers=viewer)
        qualified_before = r_before.json()["leads"]["qualified"]

        for lid in (ccv_id, qv_id, hv_id):
            rv = await client.post(
                f"/api/admin/leads/{lid}/void-contact",
                json={"confirm": True, "reason": "误报"},
                headers=admin,
            )
            assert rv.status_code == 200

        r_after = await client.get("/api/admin/business/overview?range=7d", headers=viewer)

    leads = r_after.json()["leads"]
    assert leads["contact_voided"] >= 3
    # 仅「资格只靠已作废联系方式」的 contact_captured 行退出合格档(恰好 -1);
    # qualified / handed_off 行作废联系方式后仍保有独立资格,不被盲目降级。
    assert leads["qualified"] == qualified_before - 1


async def test_voided_reason_pii_minimized_in_list_projection(leads_env):
    """R2-3(AC3):作废理由是自由文本(admin 可写入任意内容),列表投影必须
    PII 最小化 —— 含敏感字面(手机号/邮箱)的完整理由只保留在授权详情视图,
    列表响应(admin/editor/viewer 可见)不得回传理由内容。"""
    marker = leads_env["marker"]
    lead_id = leads_env["lead_id"]
    phone, email = "13800138000", "buyer-secret@example.com"
    reason = f"误填手机 {phone} / 邮箱 {email},请作废"

    admin = leads_env["headers"]["admin"]
    viewer = leads_env["headers"]["viewer"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        rv = await client.post(
            f"/api/admin/leads/{lead_id}/void-contact",
            json={"confirm": True, "reason": reason},
            headers=admin,
        )
        assert rv.status_code == 200
        r_list = await client.get(f"/api/admin/leads?q={_NS}-acme", headers=viewer)
        r_voided = await client.get("/api/admin/leads?contact=voided", headers=viewer)
        r_detail = await client.get(f"/api/admin/leads/{lead_id}", headers=viewer)

    # 列表两视图均不泄露敏感字面,且投影不含理由字段
    for resp in (r_list, r_voided):
        assert phone not in resp.text
        assert email not in resp.text
        rows = [x for x in resp.json()["leads"] if x["session_id"] == marker]
        assert len(rows) == 1
        assert "contact_voided_reason" not in rows[0]
        assert rows[0]["contact_voided"] is True
        assert rows[0]["contact_voided_by"]  # 归因保留(操作人非敏感自由文本)

    # 授权详情视图保留完整审计理由(可追溯,读权限不弱化)
    detail = r_detail.json()
    assert detail["contact_voided_reason"] == reason
    assert phone in r_detail.text and email in r_detail.text
