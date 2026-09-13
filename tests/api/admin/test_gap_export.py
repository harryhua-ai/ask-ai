"""V1.6.3 Wave 1 Track E — U-16 导出与隐私端点测试。

冻结合同(track-e-contract.md / U-16 / IF-5):
- admin-only 导出(RBAC);范围 = 所选 gap 的权威对话集(真实查询
  conversations.cluster_id,非当前渲染行;window 参数继承队列激活窗词表);
- 最小必要字段(IF-5 冻结列集);排除直接个人身份(姓名/邮箱/IP/session/
  国家等一律零包含);真实 CSV 下载;导出动作审计行持久化可查。
"""

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import (
    Conversation,
    GapExportAudit,
    QuestionCluster,
    User,
)
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

_ADMIN_EMAIL = "we-exp-admin@test.com"
_EDITOR_EMAIL = "we-exp-editor@test.com"
_RQ_PREFIX = "WEEXP"
_SEG = 0xEFEF0000000040008000000000000000

_NOW = datetime(2026, 9, 13, 12, 0, 0, tzinfo=UTC)

# IF-5 冻结列集(最小必要;权威真相见 backend/api/admin/tech_export.py)
IF5_COLUMNS = [
    "conversation_id",
    "created_at",
    "question",
    "answer",
    "is_answered",
    "sources",
]
# IF-5 隐私排除清单(直接个人身份/身份可关联字段零包含)
IF5_EXCLUDED = [
    "session_id",
    "country",
    "channel",
    "intent_tag",
    "custom_tags",
    "customization_id",
    "site_id",
    "response_time_ms",
    "feedback",
]


def _uid(i: int) -> uuid.UUID:
    return uuid.UUID(int=_SEG + i)


async def _cleanup(factory):
    async with factory() as session:
        clusters = (
            await session.execute(
                select(QuestionCluster).where(
                    QuestionCluster.representative_question.like(f"{_RQ_PREFIX}%")
                )
            )
        ).scalars().all()
        ids = [str(c.id) for c in clusters]
        if ids:
            await session.execute(
                delete(GapExportAudit).where(GapExportAudit.cluster_id.in_(ids))
            )
            await session.execute(delete(Conversation).where(Conversation.cluster_id.in_(ids)))
            await session.execute(
                delete(QuestionCluster).where(QuestionCluster.id.in_([c.id for c in clusters]))
            )
        await session.execute(delete(User).where(User.email.in_([_ADMIN_EMAIL, _EDITOR_EMAIL])))
        await session.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def export_seed():
    """seed:1 个 gap + 3 条归属会话(2 条 7d 窗内、1 条 30d 前窗外;
    会话携带 session_id/country 等隐私排除清单字段供零包含断言)。"""
    factory = app.state.session_factory
    await _cleanup(factory)
    ids: dict[str, tuple[uuid.UUID, str]] = {}
    async with factory() as session:
        for email, role in ((_ADMIN_EMAIL, "admin"), (_EDITOR_EMAIL, "editor")):
            uid = uuid.uuid4()
            ids[role] = (uid, email)
            session.add(
                User(id=uid, email=email, role=role, password_hash=hash_password("pass"))
            )
        gap_id = _uid(1)
        session.add(
            QuestionCluster(
                id=gap_id,
                cluster_type="gap",
                representative_question=f"{_RQ_PREFIX}-A SD 版本回答错误?",
                sample_questions=[f"{_RQ_PREFIX}-A SD 最新版本是多少?"],
                question_count=3,
                status="open",
            )
        )
        await session.flush()
        rows = [
            ("SD 最新版本是多少? 1.2 还是 1.1?", "SD 当前版本为 1.2。", True, 2, "sess-we-a", "US"),
            ("SD 可以降级到 1.1 吗?", None, False, 5, "sess-we-b", "DE"),
            ("SD 旧版本文档在哪里?", "旧版本已归档。", True, 40, "sess-we-c", "FR"),
        ]
        for i, (q, a, ans, days_ago, sess, country) in enumerate(rows):
            session.add(
                Conversation(
                    question=q,
                    answer=a,
                    is_answered=ans,
                    cluster_id=str(gap_id),
                    sources=[] if a is None else [
                        {"source_id": "we-src-exp/doc-1", "title": "SD Release Notes",
                         "url": "https://example.com/sd/rel"}
                    ],
                    session_id=sess,
                    country=country,
                    created_at=_NOW - timedelta(days=days_ago),
                )
            )
        await session.commit()

    secret = app.state.settings.jwt_secret
    headers = {
        role: {"Authorization": f"Bearer {create_access_token(str(uid), role, secret)}"}
        for role, (uid, _) in ids.items()
    }
    yield {"headers": headers, "gap_id": str(gap_id)}
    await _cleanup(factory)


def _export_url(gap_id: str) -> str:
    return f"/api/admin/tech/answer-gaps/{gap_id}/conversations/export"


def _audits_url(gap_id: str) -> str:
    return f"/api/admin/tech/answer-gaps/{gap_id}/export-audits"


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _parse_csv(text: str) -> tuple[list[str], list[list[str]]]:
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    return rows[0], rows[1:]


# --------------------------------------------------------------------------- #
# RBAC:admin-only
# --------------------------------------------------------------------------- #


async def test_export_admin_only(export_seed):
    headers, gap_id = export_seed["headers"], export_seed["gap_id"]
    async with _client() as client:
        assert (await client.get(_export_url(gap_id))).status_code == 401
        assert (
            await client.get(_export_url(gap_id), headers=headers["editor"])
        ).status_code == 403
        ok = await client.get(_export_url(gap_id), headers=headers["admin"])
        assert ok.status_code == 200
        # 审计读面同 admin-only
        assert (await client.get(_audits_url(gap_id), headers=headers["editor"])).status_code == 403


# --------------------------------------------------------------------------- #
# 真实 CSV 下载 + 范围 = 权威对话集
# --------------------------------------------------------------------------- #


async def test_export_real_csv_download(export_seed):
    headers, gap_id = export_seed["headers"], export_seed["gap_id"]
    async with _client() as client:
        resp = await client.get(_export_url(gap_id), headers=headers["admin"])
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers.get("content-disposition", "")
    header, rows = _parse_csv(resp.text)
    assert header == IF5_COLUMNS
    assert len(rows) == 3  # window=all → 权威全集(3 条归属会话)
    by_q = {r[IF5_COLUMNS.index("question")]: r for r in rows}
    assert "SD 最新版本是多少? 1.2 还是 1.1?" in by_q
    # answer / is_answered 权威透传
    r = by_q["SD 可以降级到 1.1 吗?"]
    assert r[IF5_COLUMNS.index("answer")] == ""
    assert r[IF5_COLUMNS.index("is_answered")] == "false"


async def test_export_scope_window_inheritance(export_seed):
    """范围 = 权威对话集 ∩ 激活窗(window 词表继承队列);7d 只含窗内 2 条。"""
    headers, gap_id = export_seed["headers"], export_seed["gap_id"]
    async with _client() as client:
        resp = await client.get(
            _export_url(gap_id) + "?window=7d", headers=headers["admin"]
        )
    assert resp.status_code == 200
    header, rows = _parse_csv(resp.text)
    assert len(rows) == 2
    assert header == IF5_COLUMNS


# --------------------------------------------------------------------------- #
# 最小必要字段 + 直接个人身份零包含
# --------------------------------------------------------------------------- #


async def test_export_minimal_columns_and_no_direct_pii(export_seed):
    headers, gap_id = export_seed["headers"], export_seed["gap_id"]
    async with _client() as client:
        resp = await client.get(_export_url(gap_id), headers=headers["admin"])
    header, rows = _parse_csv(resp.text)
    # IF-5 冻结列集精确一致(多列/少列都违反最小必要)
    assert header == IF5_COLUMNS
    # 隐私排除清单字段值零包含(session_id/country 真实存在于库,但不得出现在 CSV)
    assert "sess-we-a" not in resp.text
    assert "sess-we-b" not in resp.text
    assert "sess-we-c" not in resp.text
    for col in IF5_EXCLUDED:
        assert col not in header
    # 引用信息仅 title/url 投影(最小必要)
    r = next(
        r for r in rows if r[IF5_COLUMNS.index("question")] == "SD 最新版本是多少? 1.2 还是 1.1?"
    )
    src_cell = r[IF5_COLUMNS.index("sources")]
    assert "SD Release Notes" in src_cell
    assert "we-src-exp" not in src_cell  # 内部 source_id 路径不在导出面


# --------------------------------------------------------------------------- #
# 审计 trail
# --------------------------------------------------------------------------- #


async def test_export_action_audited_and_queryable(export_seed):
    factory = app.state.session_factory
    headers, gap_id = export_seed["headers"], export_seed["gap_id"]
    async with _client() as client:
        r1 = await client.get(_export_url(gap_id), headers=headers["admin"])
        assert r1.status_code == 200
        r2 = await client.get(
            _export_url(gap_id) + "?window=7d", headers=headers["admin"]
        )
        assert r2.status_code == 200
        audits = await client.get(_audits_url(gap_id), headers=headers["admin"])
    assert audits.status_code == 200
    items = audits.json()["items"]
    assert len(items) == 2
    by_window = {it["window"]: it for it in items}
    assert by_window["all"]["row_count"] == 3
    assert by_window["7d"]["row_count"] == 2
    assert all(it["actor"] == _ADMIN_EMAIL for it in items)
    assert all(it["created_at"] for it in items)
    # 审计行持久化(DB 三角)
    async with factory() as session:
        n = (
            await session.execute(
                select(GapExportAudit).where(
                    GapExportAudit.cluster_id == uuid.UUID(gap_id)
                )
            )
        ).scalars().all()
        assert len(n) == 2


async def test_export_404_unknown_gap(export_seed):
    headers = export_seed["headers"]
    async with _client() as client:
        resp = await client.get(
            _export_url(str(uuid.uuid4())), headers=headers["admin"]
        )
    assert resp.status_code == 404
