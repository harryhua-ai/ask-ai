"""Issue #55:Document Inspector 权威真值面(current→target 矩阵 gap 闭环)。

矩阵审计(基线 777b737 = Knowledge Integrity canonical artifact)证明的
PARTIAL/MISSING 项,本套件逐项冻结 read-model 契约:

- (A/PARTIAL)身份维度:truth 响应已携带 doc_source_id/branch/source_type/
  product 权威列 —— 契约冻结其对外暴露(Inspector 身份区消费);
- (D/MISSING)版本历史:DocumentVersion 权威行按 version_seq 降序暴露
  (versions),含状态/生效区间/生成代;截断诚实标注;
- (G/MISSING)引用与链接有效性:复用 #48 既有权威派生
  (wiki_canonical_url + rag._derive_link_state,零第二真值):
  公开 GitHub blob → external;wiki blob 无 slug 权威 → stale;
  wiki blob + frontmatter_slug → citation_url 为映射路由 + external;
  visitor_reachability=private → private(元数据未记录 → None 显式);
  空白 URL → none(知识案例 url='' 语义);
- (L/PARTIAL)退役 ≠ healthy:墓碑文档 serving=False 与 chunk 投影
  真值(12/12 一致性绿)同时在场 —— 呈现层据此不得把退役文档渲染为
  「不完整/健康」(生产事故同型:#83 前的 8/8 一致 + 墓碑)。

真实 Postgres(TEST_DATABASE_URL);Weaviate 用测试替身(SimpleNamespace
collections.get;与 test_data_sources_track_c 同构)。
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

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

SRC = f"u55-{uuid.uuid4().hex[:10]}"
ORDINAL = uuid.uuid4().int % 900_000_000 + 100_000_000
NOW = datetime.now(UTC)
DETAIL_URL = f"/api/admin/data-sources/{SRC}/documents/detail"

DOC_GITHUB_PUBLIC = f"{SRC}/main/README.md"
DOC_GITHUB_PRIVATE = f"{SRC}/main/internal-notes.md"
DOC_WIKI_STALE = f"{SRC}/main/docs/2-sdk-reference.md"
DOC_WIKI_SLUGGED = f"{SRC}/main/docs/0-overview.md"
DOC_RETIRED_GREEN = f"{SRC}/main/retired-but-green.md"
DOC_BLANK_URL = f"{SRC}/main/knowledge-case.md"

GITHUB_PUBLIC_URL = "https://github.com/camthink-ai/neoruntime/blob/main/README.md"
GITHUB_PRIVATE_URL = (
    "https://github.com/camthink-ai/neoruntime/blob/main/internal-notes.md"
)
WIKI_BLOB_STALE = (
    "https://github.com/camthink-ai/wiki-documents/blob/main/docs/2-sdk-reference.md"
)
WIKI_BLOB_SLUGGED = (
    "https://github.com/camthink-ai/wiki-documents/blob/main/docs/0-overview.md"
)
RETIRED_URL = "https://github.com/camthink-ai/neoruntime/blob/main/retired.md"

# (doc_source_id, lifecycle, url, metadata_)
SEED_DOCS = [
    (DOC_GITHUB_PUBLIC, "active", GITHUB_PUBLIC_URL, {}),
    (DOC_GITHUB_PRIVATE, "active", GITHUB_PRIVATE_URL, {"visitor_reachability": "private"}),
    (DOC_WIKI_STALE, "active", WIKI_BLOB_STALE, {}),
    (DOC_WIKI_SLUGGED, "active", WIKI_BLOB_SLUGGED, {"frontmatter_slug": "/ne301/overview"}),
    (DOC_RETIRED_GREEN, "deleted", RETIRED_URL, {}),
    (DOC_BLANK_URL, "active", "", {}),
]


@pytest_asyncio.fixture(loop_scope="session")
async def inspector_seed():
    """播种:1 源 + 6 个 truth-state 文档 + 每文档 2 个权威版本行。

    DOC_RETIRED_GREEN 为墓碑(生产事故同型:lifecycle=deleted 但版本/
    chunk 权威行保留为审计真相)+ 12 持久 chunk 行(现行版本账本)。
    """
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        gen = IndexGeneration(ordinal=ORDINAL, source_id=SRC, status="ready")
        session.add(gen)
        await session.flush()
        session.add(
            DataSource(
                id=SRC,
                type="github",
                product="u55",
                config={"base_url": "https://wiki.example.com"},
                sync_interval="24h",
                enabled=True,
            )
        )
        for doc_id, lifecycle, url, meta in SEED_DOCS:
            versions = []
            for seq, status in ((1, "retired" if lifecycle == "deleted" else "active"), (2, "retired" if lifecycle == "deleted" else "active")):
                v = DocumentVersion(
                    source_id=doc_id,
                    version_seq=seq,
                    content_hash=("a" if seq == 1 else "c") * 64,
                    metadata_hash=("b" if seq == 1 else "d") * 64,
                    generation_id=gen.id,
                    generation_ordinal=ORDINAL,
                    status=status,
                    title=doc_id.rsplit("/", 1)[-1],
                    url=url or None,
                    chunk_count=12,
                    valid_from=NOW - timedelta(days=(2 if seq == 1 else 1)),
                )
                session.add(v)
                versions.append(v)
            await session.flush()
            if doc_id == DOC_RETIRED_GREEN:
                for i in range(12):
                    session.add(
                        DocumentVersionChunk(
                            version_id=versions[1].id,
                            chunk_index=i,
                            text=f"{doc_id}#chunk-{i}",
                            props={"source_id": doc_id, "chunk_index": i},
                        )
                    )
            doc = Document(
                source_id=doc_id,
                content_hash="e" * 64,
                source_type="github",
                product="u55",
                title=doc_id.rsplit("/", 1)[-1],
                url=url,
                branch="main",
                chunk_count=12,
                lifecycle=lifecycle,
                current_version_id=versions[1].id,
                metadata_=meta,
            )
            if lifecycle == "deleted":
                doc.deleted_at = NOW
            session.add(doc)
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
    yield {"headers": {"Authorization": f"Bearer {token}"}}
    async with factory() as session:
        await session.execute(
            DocumentVersionChunk.__table__.delete().where(
                DocumentVersionChunk.version_id.in_(
                    select(DocumentVersion.id).where(DocumentVersion.source_id.like(f"{SRC}/%"))
                )
            )
        )
        await session.execute(
            DocumentVersion.__table__.delete().where(DocumentVersion.source_id.like(f"{SRC}/%"))
        )
        await session.execute(Document.__table__.delete().where(Document.source_id.like(f"{SRC}/%")))
        await session.execute(IndexGeneration.__table__.delete().where(IndexGeneration.source_id == SRC))
        await session.execute(DataSource.__table__.delete().where(DataSource.id == SRC))
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


async def _truth(headers, doc_source_id: str) -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            DETAIL_URL, params={"doc_source_id": doc_source_id}, headers=headers
        )
    assert resp.status_code == 200, resp.text
    return resp.json()


# --------------------------------------------------------------------------- #
# (A)身份维度:权威身份列在 truth 响应显式在场
# --------------------------------------------------------------------------- #


async def test_u55_identity_dimensions_exposed(inspector_seed):
    body = await _truth(inspector_seed["headers"], DOC_GITHUB_PUBLIC)
    assert body["doc_source_id"] == DOC_GITHUB_PUBLIC
    assert body["branch"] == "main"
    assert body["source_type"] == "github"
    assert body["product"] == "u55"
    assert body["title"].endswith("README.md")


# --------------------------------------------------------------------------- #
# (D)版本历史:权威 DocumentVersion 行降序暴露
# --------------------------------------------------------------------------- #


async def test_u55_version_history_descends_and_carries_authority(inspector_seed):
    body = await _truth(inspector_seed["headers"], DOC_GITHUB_PUBLIC)
    versions = body["versions"]
    assert [v["version_seq"] for v in versions] == [2, 1]
    latest = versions[0]
    assert latest["status"] == "active"
    assert latest["chunk_count"] == 12
    assert latest["generation_ordinal"] == ORDINAL
    assert latest["valid_from"] is not None
    # 现行版本指针与历史行一致(同一权威关系,非第二真值)
    assert body["current_version"]["version_seq"] == 2
    assert body["versions_truncated"] is False


async def test_u55_retired_versions_keep_audit_status(inspector_seed):
    """墓碑文档的版本行保留审计状态(零删除语义)。"""
    body = await _truth(inspector_seed["headers"], DOC_RETIRED_GREEN)
    assert {v["status"] for v in body["versions"]} == {"retired"}


# --------------------------------------------------------------------------- #
# (G)引用与链接有效性:#48 既有权威派生,零第二真值
# --------------------------------------------------------------------------- #


async def test_u55_citation_public_github_blob_is_external(inspector_seed):
    body = await _truth(inspector_seed["headers"], DOC_GITHUB_PUBLIC)
    citation = body["citation"]
    assert citation["link_state"] == "external"
    assert citation["url"] == GITHUB_PUBLIC_URL
    assert citation["citation_url"] == GITHUB_PUBLIC_URL
    assert citation["visitor_reachability"] is None  # 未记录 → 显式 None,不推断


async def test_u55_citation_private_repo_is_private(inspector_seed):
    body = await _truth(inspector_seed["headers"], DOC_GITHUB_PRIVATE)
    citation = body["citation"]
    assert citation["link_state"] == "private"
    assert citation["visitor_reachability"] == "private"
    # identity 保全:URL 原样保留(C-4 acceptance 3),只是状态禁止点击
    assert citation["citation_url"] == GITHUB_PRIVATE_URL


async def test_u55_citation_wiki_blob_without_slug_is_stale(inspector_seed):
    body = await _truth(inspector_seed["headers"], DOC_WIKI_STALE)
    citation = body["citation"]
    assert citation["link_state"] == "stale"
    assert citation["citation_url"] == WIKI_BLOB_STALE


async def test_u55_citation_wiki_with_slug_maps_route_and_external(inspector_seed):
    body = await _truth(inspector_seed["headers"], DOC_WIKI_SLUGGED)
    citation = body["citation"]
    assert citation["link_state"] == "external"
    assert citation["url"] == WIKI_BLOB_SLUGGED
    assert citation["citation_url"] != citation["url"]  # slug 权威映射路由
    assert "blob/" not in citation["citation_url"]


async def test_u55_citation_blank_url_is_none(inspector_seed):
    """知识案例 url='':显式 none,绝不伪造外部目的地。"""
    body = await _truth(inspector_seed["headers"], DOC_BLANK_URL)
    citation = body["citation"]
    assert citation["link_state"] == "none"
    assert citation["citation_url"] is None


# --------------------------------------------------------------------------- #
# (L)退役 ≠ healthy:一致性绿不改变 serving=False(权威事实面)
# --------------------------------------------------------------------------- #


async def test_u55_retired_doc_serving_false_despite_full_projection(
    inspector_seed, vector_stack_u55
):
    """墓碑文档:chunk 投影真值在场(12/12 绿)且 serving=False 同时成立 ——
    呈现层消费这两个事实后不得把退役文档渲染为「不完整/健康」。"""
    body = await _truth(inspector_seed["headers"], DOC_RETIRED_GREEN)
    assert body["lifecycle"] == "deleted"
    assert body["serving"] is False
    assert body["chunk_serving"] is not None
    assert body["chunk_serving"]["serving_chunks"] == 12
    assert body["chunk_serving"]["total_chunks"] == 12
    assert body["chunk_serving"]["consistent"] is True
    assert body["deleted_at"] is not None


@pytest_asyncio.fixture(loop_scope="session")
async def vector_stack_u55():
    """注入向量替身:墓碑文档 12 个在服对象(一致性绿的最小构造)。"""
    saved = {
        k: getattr(app.state, k, None)
        for k in ("weaviate_client", "weaviate_class_name")
    }
    objects = [
        {"source_id": DOC_RETIRED_GREEN, "chunk_index": i, "generation_ordinal": ORDINAL}
        for i in range(12)
    ]
    collection = SimpleNamespace(
        iterator=lambda return_properties=None, **kw: iter(
            SimpleNamespace(properties=dict(o)) for o in objects
        )
    )
    app.state.weaviate_client = SimpleNamespace(
        collections=SimpleNamespace(get=lambda _name: collection)
    )
    app.state.weaviate_class_name = "Document"
    yield
    for k, v in saved.items():
        if v is not None:
            setattr(app.state, k, v)
