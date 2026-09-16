"""Issue #25 Track A(Acceptance 5):#50 文档详情面暴露持久化退休/缺席真相。

契约(docs/engineering/tasks/v164-track-a-lifecycle-retirement-contract.md):
- A-6:退休决策(reason/evidence/actor)持久化后**必须**可经 admin detail
  端点读取;缺席确认状态(A-2 计数 / A-3 政策 reason)同样投影;
- 无持久化事实的行 → 字段恒 null(不推断、不编造,与 #50 只读真相面纪律
  一致);viewer 可读(RBAC 与既有读约定一致)。

真实 Postgres(TEST_DATABASE_URL);不触向量库(chunk_serving=None 路径)。
"""

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import (
    DataSource,
    Document,
    DocumentVersion,
    User,
)
from backend.main import app
from backend.services.document_lifecycle import (
    ABSENCE_META_KEY,
    RETIREMENT_META_KEY,
    RETIRE_REASON_DISCOVERY,
    ACTOR_SYNC_ABSENCE,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

SRC = f"issue25-{uuid.uuid4().hex[:10]}"
DETAIL_URL = f"/api/admin/data-sources/{SRC}/documents/detail"
RETIRED_DOC = f"{SRC}/main/retired.md"
ABSENT_DOC = f"{SRC}/main/absent.md"
PLAIN_DOC = f"{SRC}/main/plain.md"


def _retirement_record() -> dict:
    now = datetime.now(UTC)
    return {
        "reason": RETIRE_REASON_DISCOVERY,
        "actor": ACTOR_SYNC_ABSENCE,
        "evidence": {"confirmations": 2, "first_absence_at": now.isoformat(), "sync_run_id": 973},
        "retired_at": now.isoformat(),
        "gc_eligible_at": now.isoformat(),
    }


@pytest_asyncio.fixture(loop_scope="session")
async def seed():
    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            DataSource(
                id=SRC,
                type="filesystem",
                product="issue25",
                config={"root_path": "/tmp/issue25-probe"},
                sync_interval="24h",
                enabled=True,
            )
        )
        session.add(
            Document(
                source_id=RETIRED_DOC,
                content_hash="r" * 64,
                source_type="filesystem",
                product="issue25",
                title="retired",
                url="file:///retired.md",
                branch="main",
                chunk_count=1,
                lifecycle="deleted",
                metadata_={RETIREMENT_META_KEY: _retirement_record()},
            )
        )
        session.add(
            Document(
                source_id=ABSENT_DOC,
                content_hash="a" * 64,
                source_type="filesystem",
                product="issue25",
                title="absent",
                url="file:///absent.md",
                branch="main",
                chunk_count=1,
                lifecycle="missing_candidate",
                metadata_={
                    ABSENCE_META_KEY: {
                        "confirmations": 1,
                        "since": datetime.now(UTC).isoformat(),
                        "policy_reason": None,
                        "last_observed_at": datetime.now(UTC).isoformat(),
                    }
                },
            )
        )
        session.add(
            Document(
                source_id=PLAIN_DOC,
                content_hash="p" * 64,
                source_type="filesystem",
                product="issue25",
                title="plain",
                url="file:///plain.md",
                branch="main",
                chunk_count=1,
                lifecycle="active",
            )
        )
        await session.commit()
    yield
    async with factory() as session:
        await session.execute(
            DocumentVersion.__table__.delete().where(
                DocumentVersion.source_id.like(f"{SRC}/%")
            )
        )
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


async def _get(headers, doc_source_id: str) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            DETAIL_URL, headers=headers, params={"doc_source_id": doc_source_id}
        )
        assert resp.status_code == 200, resp.text
        return resp.json()


async def test_retirement_record_readable_via_detail(seed, admin_headers):
    """A-6/Acceptance 5:持久化退休决策经详情面可读(reason/evidence/actor)。"""
    payload = await _get(admin_headers, RETIRED_DOC)
    assert payload["lifecycle"] == "deleted"
    record = payload["retirement"]
    assert record is not None, "持久化退休记录必须经详情面可读"
    assert record["reason"] == RETIRE_REASON_DISCOVERY
    assert record["actor"] == ACTOR_SYNC_ABSENCE
    assert record["evidence"]["confirmations"] == 2
    assert record["evidence"]["sync_run_id"] == 973
    assert record["retired_at"] is not None
    assert record["gc_eligible_at"] is not None


async def test_absence_state_readable_via_detail(seed, admin_headers):
    """A-2/A-3:缺席确认状态(计数/reason)经详情面可读。"""
    payload = await _get(admin_headers, ABSENT_DOC)
    assert payload["lifecycle"] == "missing_candidate"
    absence = payload["absence"]
    assert absence is not None
    assert int(absence["confirmations"]) == 1
    assert absence["policy_reason"] is None
    assert absence["since"] is not None
    assert payload["retirement"] is None  # 未退休行无退休记录


async def test_plain_document_has_no_inferred_facts(seed, admin_headers):
    """无持久化事实的行:retirement/absence 恒 null(不推断,#50 纪律)。"""
    payload = await _get(admin_headers, PLAIN_DOC)
    assert payload["lifecycle"] == "active"
    assert payload["retirement"] is None
    assert payload["absence"] is None
