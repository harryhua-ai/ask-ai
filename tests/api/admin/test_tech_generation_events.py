"""#51 B2 技术洞察事件信号区 — 生成级事件只读读面测试(GET /tech/generation-events)。

契约依据(v162-i51 contract):
- 复用优先裁定:同步级事件已由既有 GET /sync-runs 权威表达(前端直接消费,
  零新增后端);生成级事件(index_generations.status/failure)无既有读端点,
  是唯一可证明的新读缺口 → 本端点只读补齐,所有权归 #51,不复制 #50 逐源清单。
- 冻结断言:只读(GET-only);P 轴词表 failed/retired 才是事件;ready/processing/
  pending 非事件不呈现;failed severity=error / retired severity=info;
  failure JSONB 原样透传(不虚构摘要);event_at 如实派生
  (retired→retired_at;failed→updated_at,无 failed_at 列的诚实近似);
  RBAC 不变(viewer+ 可读,未认证 401)。
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import IndexGeneration, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

_USER_EMAIL = "b2-genevt@test.com"
_SRC_PREFIX = "b2-genevt-src"
# ordinal 全表 UNIQUE(共享测试库)→ 用高位随机段避让,按 source_id 前缀清理
_ORD_BASE = 9_100_000


def _ordinal(i: int) -> int:
    return _ORD_BASE + i


@pytest_asyncio.fixture(loop_scope="session")
async def genevt_seed():
    """seed:1 failed(带 failure 证据)/ 1 retired / 1 ready / 1 processing。"""
    factory = app.state.session_factory
    async with factory() as session:
        await session.execute(
            delete(IndexGeneration).where(IndexGeneration.source_id.like(f"{_SRC_PREFIX}%"))
        )
        await session.execute(delete(User).where(User.email == _USER_EMAIL))
        await session.commit()

    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email=_USER_EMAIL,
                role="admin",
                password_hash=hash_password("pass"),
            )
        )
        session.add(
            IndexGeneration(
                ordinal=_ordinal(1),
                source_id=f"{_SRC_PREFIX}-a",
                status="failed",
                doc_count=3,
                chunk_count=0,
                failure={"error": "doc build failures", "docs": ["d1", "d2"]},
            )
        )
        session.add(
            IndexGeneration(
                ordinal=_ordinal(2),
                source_id=f"{_SRC_PREFIX}-b",
                status="retired",
                doc_count=5,
                chunk_count=50,
                activated_at=None,
            )
        )
        session.add(
            IndexGeneration(
                ordinal=_ordinal(3),
                source_id=f"{_SRC_PREFIX}-c",
                status="ready",
                doc_count=2,
                chunk_count=20,
            )
        )
        session.add(
            IndexGeneration(
                ordinal=_ordinal(4),
                source_id=f"{_SRC_PREFIX}-d",
                status="processing",
                doc_count=0,
                chunk_count=0,
            )
        )
        await session.commit()

    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}

    async with factory() as session:
        await session.execute(
            delete(IndexGeneration).where(IndexGeneration.source_id.like(f"{_SRC_PREFIX}%"))
        )
        await session.execute(delete(User).where(User.email == _USER_EMAIL))
        await session.commit()


async def _get(headers, query: str = ""):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/api/admin/tech/generation-events{query}", headers=headers
        )
    return resp


async def test_generation_events_only_failed_and_retired(genevt_seed):
    """P 轴事件词表:仅 failed/retired 是事件;ready/processing 不呈现。

    范围注记(Role A 窄加固):``total == 2`` 依赖共享测试库当前没有其他
    failed/retired 的 index_generations 行(grep 全测试集证实仅本文件播种
    此类行;ordinal 用高位随机段避让 unique)。若未来其他用例也播种
    failed/retired 行,须把断言收窄为本前缀(source_id 集断言已是精确形态)。
    """
    resp = await _get(genevt_seed)
    assert resp.status_code == 200
    j = resp.json()
    assert j["total"] == 2
    statuses = {it["status"] for it in j["items"]}
    assert statuses == {"failed", "retired"}
    source_ids = {it["source_id"] for it in j["items"]}
    assert source_ids == {f"{_SRC_PREFIX}-a", f"{_SRC_PREFIX}-b"}


async def test_generation_events_item_shape_and_severity(genevt_seed):
    """事件行含源归属/类型/时间/原因摘要/严重度;failure 证据原样透传。"""
    resp = await _get(genevt_seed)
    items = {it["status"]: it for it in resp.json()["items"]}

    failed = items["failed"]
    assert failed["source_id"] == f"{_SRC_PREFIX}-a"
    assert failed["severity"] == "error"
    assert failed["ordinal"] == _ordinal(1)
    assert failed["generation_id"]
    assert failed["failure"] == {"error": "doc build failures", "docs": ["d1", "d2"]}
    assert failed["reason_summary"] == "doc build failures"
    assert failed["event_at"]

    retired = items["retired"]
    assert retired["severity"] == "info"
    assert retired["event_at"]
    assert retired["reason_summary"]


async def test_generation_events_event_at_semantics(genevt_seed):
    """event_at 派生:retired → retired_at;failed → updated_at(诚实近似,不虚构)。

    Role A 窄加固:failed 分支补 `event_at == updated_at` 精确等值断言
    (此前仅断言非空)。
    """
    factory = app.state.session_factory
    async with factory() as session:
        failed_row = (
            await session.execute(
                select(IndexGeneration).where(
                    IndexGeneration.source_id == f"{_SRC_PREFIX}-a"
                )
            )
        ).scalar_one()
        failed_updated_at = failed_row.updated_at
        row = (
            await session.execute(
                select(IndexGeneration).where(
                    IndexGeneration.source_id == f"{_SRC_PREFIX}-b"
                )
            )
        ).scalar_one()
        row.retired_at = row.updated_at.replace(year=2020)
        await session.commit()
        retired_at = row.retired_at

    resp = await _get(genevt_seed)
    items = {it["status"]: it for it in resp.json()["items"]}
    assert items["retired"]["event_at"] == retired_at.isoformat()
    assert items["retired"]["retired_at"] == retired_at.isoformat()
    assert items["failed"]["event_at"] == failed_updated_at.isoformat()


async def test_generation_events_ordering_recent_first(genevt_seed):
    """最近事件在前(retired_at 新者先;跨类型混合排序)。"""
    factory = app.state.session_factory
    async with factory() as session:
        row = (
            await session.execute(
                select(IndexGeneration).where(
                    IndexGeneration.source_id == f"{_SRC_PREFIX}-b"
                )
            )
        ).scalar_one()
        row.retired_at = row.updated_at
        await session.commit()

    resp = await _get(genevt_seed)
    items = resp.json()["items"]
    assert len(items) == 2
    times = [it["event_at"] for it in items]
    assert times == sorted(times, reverse=True)


async def test_generation_events_limit(genevt_seed):
    resp = await _get(genevt_seed, "?limit=1")
    assert resp.status_code == 200
    j = resp.json()
    assert len(j["items"]) == 1
    assert j["total"] == 2


async def test_generation_events_requires_auth():
    """只读读面 RBAC 不变:未认证 401。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/tech/generation-events")
    assert resp.status_code == 401


async def test_generation_events_empty_ok(genevt_seed):
    """空态显式:无事件时 items=[] / total=0,不假装数据。"""
    factory = app.state.session_factory
    async with factory() as session:
        await session.execute(
            delete(IndexGeneration).where(IndexGeneration.source_id.like(f"{_SRC_PREFIX}%"))
        )
        await session.commit()

    resp = await _get(genevt_seed)
    assert resp.status_code == 200
    j = resp.json()
    assert j["items"] == []
    assert j["total"] == 0
