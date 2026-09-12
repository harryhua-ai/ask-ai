"""v1.6.3 B1(KB-OPS-V163-002):数据源运营汇总读面。

新只读 GET 端点 ``GET /data-sources/attention-summary``(v1.6.2 B1 只读投影先例):
- 逐源权威桶聚合投影(ledger_total / current_count / serving_count /
  retired_count / attention_count / lifecycle_counts),SQL 语义与
  ``GET /data-sources/{id}/documents`` 聚合计数**同一定义**:
  current = active ∧ 现行版本可解析;retired = superseded + deleted;
  attention = ledger_total − current − retired(冻结公式);
- 零写路径、零新语义、仅查 Postgres;viewer 可读;
- 无文档源也出现在列表(零值),供扫描优先列表页一次取全。

同文件覆盖 documents 清单端点新增的**只读过滤参数**(additive,默认行为不变):
- ``bucket`` = current|attention|retired(运营桶投影,与冻结桶公式一致);
- ``order`` = -updated_at(默认,原行为)| title;
- ``source_type`` = 精确匹配 documents.source_type。

真实 Postgres(TEST_DATABASE_URL,与 admin API 测试同库)。
"""

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import (
    DataSource,
    Document,
    DocumentVersion,
    DocumentVersionChunk,
    IndexGeneration,
    User,
)
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

PREFIX = f"b1att-{uuid.uuid4().hex[:10]}"
SRC = f"{PREFIX}-src"
OTHER_SRC = f"{PREFIX}-other"
EMPTY_SRC = f"{PREFIX}-empty"
RETIRED_SRC = f"{PREFIX}-retired"
NOW = datetime.now(UTC)

READY_ORDINAL = uuid.uuid4().int % 900_000_000 + 100_000_000

ACTIVE_DOC = f"{SRC}/main/alive.md"
GAP_DOC = f"{SRC}/main/no-version-row.md"
MISSING_DOC = f"{SRC}/main/vanishing.md"
SUPERSEDED_DOC = f"{SRC}/main/old.md"
DELETED_DOC = f"{SRC}/main/gone.md"


async def _mk_generation(session, ordinal: int, source_id: str) -> IndexGeneration:
    gen = IndexGeneration(
        ordinal=ordinal,
        source_id=source_id,
        status="ready",
        doc_count=4,
        chunk_count=12,
    )
    session.add(gen)
    return gen


async def _mk_version(session, doc_source_id: str, seq: int, generation: IndexGeneration) -> DocumentVersion:
    version = DocumentVersion(
        source_id=doc_source_id,
        version_seq=seq,
        content_hash="a" * 64,
        metadata_hash="b" * 64,
        generation_id=generation.id,
        generation_ordinal=generation.ordinal,
        status="active",
        title="v",
        url="",
        chunk_count=2,
    )
    session.add(version)
    return version


async def _mk_doc(
    session,
    doc_source_id: str,
    *,
    title: str,
    lifecycle: str = "active",
    source_type: str = "github",
    current_version: DocumentVersion | None = None,
) -> Document:
    doc = Document(
        source_id=doc_source_id,
        content_hash="c" * 64,
        source_type=source_type,
        product="b1att",
        title=title,
        url=f"https://git.local/{title}",
        branch="main",
        chunk_count=1,
        lifecycle=lifecycle,
    )
    if current_version is not None:
        doc.current_version_id = current_version.id
    if lifecycle == "superseded":
        doc.superseded_by = f"{doc_source_id}-newer"
        doc.superseded_at = NOW
    if lifecycle == "deleted":
        doc.deleted_at = NOW
    session.add(doc)
    return doc


@pytest_asyncio.fixture(loop_scope="session")
async def viewer_headers():
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email=f"{PREFIX}@test.com",
                role="viewer",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "viewer", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def att_seed():
    """播种:SRC=5 态文档 / OTHER=1 现行 / EMPTY=0 文档 / RETIRED=1 墓碑。"""
    factory = app.state.session_factory
    async with factory() as session:
        for sid in (SRC, OTHER_SRC, EMPTY_SRC, RETIRED_SRC):
            session.add(DataSource(id=sid, type="github", product="b1att", config={}))
        gen = await _mk_generation(session, READY_ORDINAL, SRC)
        await session.flush()
        v1 = await _mk_version(session, ACTIVE_DOC, 1, gen)
        v2 = await _mk_version(session, MISSING_DOC, 1, gen)
        v3 = await _mk_version(session, SUPERSEDED_DOC, 2, gen)
        v3.status = "superseded"
        await session.flush()
        await _mk_doc(session, ACTIVE_DOC, title="Alive Doc", current_version=v1)
        await _mk_doc(session, GAP_DOC, title="Zeta Gap")  # active 但现行版本悬挂
        await _mk_doc(session, MISSING_DOC, title="Vanish", lifecycle="missing_candidate", current_version=v2)
        await _mk_doc(session, SUPERSEDED_DOC, title="Old Doc", lifecycle="superseded", current_version=v3)
        await _mk_doc(session, DELETED_DOC, title="Gone Doc", lifecycle="deleted")
        await _mk_doc(session, f"{RETIRED_SRC}/main/r.md", title="Retired", lifecycle="deleted")
        other_gen = await _mk_generation(session, READY_ORDINAL + 1, OTHER_SRC)
        await session.flush()
        ov = await _mk_version(session, f"{OTHER_SRC}/main/x.md", 1, other_gen)
        await session.flush()
        await _mk_doc(session, f"{OTHER_SRC}/main/x.md", title="Other Doc", current_version=ov)
        await session.commit()
    yield
    async with factory() as session:
        for sid in (SRC, OTHER_SRC, EMPTY_SRC, RETIRED_SRC):
            version_ids = (
                await session.execute(
                    select(DocumentVersion.id).where(DocumentVersion.source_id.like(f"{sid}/%"))
                )
            ).scalars().all()
            if version_ids:
                await session.execute(
                    delete(DocumentVersionChunk).where(
                        DocumentVersionChunk.version_id.in_(version_ids)
                    )
                )
            await session.execute(delete(DocumentVersion).where(DocumentVersion.source_id.like(f"{sid}/%")))
            await session.execute(delete(Document).where(Document.source_id.like(f"{sid}/%")))
            await session.execute(delete(IndexGeneration).where(IndexGeneration.source_id == sid))
            await session.execute(delete(DataSource).where(DataSource.id == sid))
        await session.commit()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


SUMMARY_URL = "/api/admin/data-sources/attention-summary"
DOCS_URL = f"/api/admin/data-sources/{SRC}/documents"


async def test_attention_summary_unauthenticated_rejected():
    async with _client() as client:
        resp = await client.get(SUMMARY_URL)
    assert resp.status_code == 401


async def test_attention_summary_projects_authoritative_buckets(viewer_headers, att_seed):
    async with _client() as client:
        resp = await client.get(SUMMARY_URL, headers=viewer_headers)
    assert resp.status_code == 200
    data = resp.json()
    by_source = {item["source_id"]: item for item in data["items"]}
    # 全部源都出现(含零文档源)
    for sid in (SRC, OTHER_SRC, EMPTY_SRC, RETIRED_SRC):
        assert sid in by_source

    src = by_source[SRC]
    assert src["ledger_total"] == 5
    assert src["current_count"] == 1
    assert src["serving_count"] == 2  # active + missing_candidate(宽限中仍由上一代服务)
    assert src["retired_count"] == 2  # superseded + deleted
    assert src["attention_count"] == 2  # 5 − 1 − 2(missing_candidate + active 悬挂)
    assert src["lifecycle_counts"] == {
        "active": 2,
        "missing_candidate": 1,
        "superseded": 1,
        "deleted": 1,
    }

    assert by_source[EMPTY_SRC]["ledger_total"] == 0
    assert by_source[EMPTY_SRC]["attention_count"] == 0

    other = by_source[OTHER_SRC]
    assert other["current_count"] == 1
    assert other["attention_count"] == 0

    retired = by_source[RETIRED_SRC]
    assert retired["retired_count"] == 1
    assert retired["attention_count"] == 0


async def test_attention_summary_matches_documents_aggregates(viewer_headers, att_seed):
    """与逐源 documents 端点聚合字段同定义(三角一致)。"""
    async with _client() as client:
        summary = await client.get(SUMMARY_URL, headers=viewer_headers)
        docs = await client.get(DOCS_URL, headers=viewer_headers)
    assert summary.status_code == 200 and docs.status_code == 200
    src = next(i for i in summary.json()["items"] if i["source_id"] == SRC)
    d = docs.json()
    assert src["ledger_total"] == d["ledger_total"]
    assert src["current_count"] == d["current_count"]
    assert src["serving_count"] == d["serving_count"]
    assert src["lifecycle_counts"] == d["lifecycle_counts"]


# --------------------------------------------------------------------------- #
# documents 清单新只读参数(additive)
# --------------------------------------------------------------------------- #


async def test_documents_bucket_filter_attention(viewer_headers, att_seed):
    async with _client() as client:
        resp = await client.get(DOCS_URL, params={"bucket": "attention"}, headers=viewer_headers)
    assert resp.status_code == 200
    rows = {r["source_id"] for r in resp.json()["items"]}
    assert rows == {GAP_DOC, MISSING_DOC}
    assert resp.json()["total"] == 2


async def test_documents_bucket_filter_current_and_retired(viewer_headers, att_seed):
    async with _client() as client:
        cur = await client.get(DOCS_URL, params={"bucket": "current"}, headers=viewer_headers)
        ret = await client.get(DOCS_URL, params={"bucket": "retired"}, headers=viewer_headers)
    assert cur.status_code == 200 and ret.status_code == 200
    assert {r["source_id"] for r in cur.json()["items"]} == {ACTIVE_DOC}
    assert {r["source_id"] for r in ret.json()["items"]} == {SUPERSEDED_DOC, DELETED_DOC}


async def test_documents_bucket_invalid_value_400(viewer_headers, att_seed):
    async with _client() as client:
        resp = await client.get(DOCS_URL, params={"bucket": "bogus"}, headers=viewer_headers)
    assert resp.status_code == 400


async def test_documents_order_title(viewer_headers, att_seed):
    async with _client() as client:
        resp = await client.get(DOCS_URL, params={"order": "title"}, headers=viewer_headers)
    assert resp.status_code == 200
    titles = [r["title"] for r in resp.json()["items"]]
    assert titles == sorted(titles)


async def test_documents_source_type_filter(viewer_headers, att_seed):
    factory = app.state.session_factory
    async with factory() as session:
        gen = await _mk_generation(session, READY_ORDINAL + 2, SRC)
        await session.flush()
        v = await _mk_version(session, f"{SRC}/main/web.md", 1, gen)
        await session.flush()
        await _mk_doc(
            session, f"{SRC}/main/web.md", title="Web Doc",
            lifecycle="active", source_type="web_crawl", current_version=v,
        )
        await session.commit()
    try:
        async with _client() as client:
            resp = await client.get(
                DOCS_URL, params={"source_type": "web_crawl"}, headers=viewer_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["source_type"] == "web_crawl"
        assert data["items"][0]["title"] == "Web Doc"
    finally:
        async with factory() as session:
            await session.execute(
                delete(Document).where(Document.source_id == f"{SRC}/main/web.md")
            )
            await session.execute(
                delete(DocumentVersion).where(DocumentVersion.source_id == f"{SRC}/main/web.md")
            )
            await session.execute(
                delete(IndexGeneration).where(IndexGeneration.source_id == SRC)
            )
            await session.commit()
