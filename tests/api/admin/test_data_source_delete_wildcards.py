"""AC-FIX-01:数据源删除的 literal 前缀所有权回归测试。

源 ID 允许包含 SQL LIKE 通配符(%/_)。删除路径必须把 DataSource ID 当作
字面标识符匹配(不得当 LIKE 模式),否则会误删他源知识(合同「不得删除
另一个源的知识」)。

三组用例:
1. 普通前缀重叠:source-a vs source-ab
2. 下划线:afp_src_a vs afpXsrcXa(未转义时 _ 匹配任意单字符)
3. 百分号:afp%pct vs afp-x-pct(未转义时 % 匹配任意后缀)

每组:删除 A → A 文档/账本清空、向量清理仅收 A 账本;B 配置/文档原样。
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import DataSource, Document, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

_USER_EMAIL = "afp-wildcard@test.com"

CASES = [
    ("source-a", "source-ab"),
    ("afp_src_a", "afpXsrcXa"),
    ("afp%pct", "afp-x-pct"),
]


@pytest_asyncio.fixture(loop_scope="session")
async def wild_seed():
    factory = app.state.session_factory
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.email == _USER_EMAIL))
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
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.email == _USER_EMAIL))
        await session.commit()


def _mk_purge(monkeypatch, store: list):
    def _fake(weaviate_url, class_name, prefix, ledger):
        store.append({"prefix": prefix, "ledger": sorted(ledger)})
        return {"ledger_docs": len(ledger), "orphans": 0}

    monkeypatch.setattr(
        "backend.api.admin.data_sources._purge_source_corpus_sync", _fake
    )
    return store


async def _seed_source_and_docs(sid: str) -> None:
    factory = app.state.session_factory
    async with factory() as session:
        # 幂等预清理(上轮失败残留)
        await session.execute(DataSource.__table__.delete().where(DataSource.id == sid))
        await session.execute(
            Document.__table__.delete().where(Document.source_id == f"{sid}/doc")
        )
        await session.commit()
    async with factory() as session:
        session.add(
            DataSource(
                id=sid,
                type="github",
                product="t",
                enabled=True,
                config={"repo_url": f"https://example.com/{sid}.git"},
                sync_interval="24h",
            )
        )
        session.add(
            Document(
                content_hash=uuid.uuid4().hex,
                source_id=f"{sid}/doc",
                source_type="github",
                product="t",
                title=sid,
                url="https://example.com",
                metadata_={},
                branch="",
                chunk_count=2,
            )
        )
        await session.commit()


async def _doc_count(sid: str) -> int:
    from sqlalchemy import func

    factory = app.state.session_factory
    async with factory() as session:
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Document)
                    .where(Document.source_id.startswith(f"{sid}/", autoescape=True))
                )
            ).scalar()
            or 0
        )


@pytest.mark.parametrize("src_a,src_b", CASES)
async def test_wildcard_id_deletion_is_literal(wild_seed, monkeypatch, src_a, src_b):
    """通配符/重叠前缀下,删除 A 只清 A;B 配置/账本原样;purge 仅收 A 账本。"""
    store: list = []
    _mk_purge(monkeypatch, store)
    await _seed_source_and_docs(src_a)
    await _seed_source_and_docs(src_b)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            f"/api/admin/data-sources/{src_a}", headers=wild_seed
        )
    assert resp.status_code == 204

    # A:配置与账本清空;purge 账本精确等于 A 自己的文档
    factory = app.state.session_factory
    async with factory() as session:
        gone = (
            await session.execute(select(DataSource).where(DataSource.id == src_a))
        ).scalar_one_or_none()
        assert gone is None
    assert await _doc_count(src_a) == 0
    assert len(store) == 1 and store[0]["prefix"] == src_a
    assert store[0]["ledger"] == [(f"{src_a}/doc", 2)]

    # B:配置与账本原样(通配符不得越界)
    async with factory() as session:
        keep = (
            await session.execute(select(DataSource).where(DataSource.id == src_b))
        ).scalar_one_or_none()
        assert keep is not None
    assert await _doc_count(src_b) == 1
