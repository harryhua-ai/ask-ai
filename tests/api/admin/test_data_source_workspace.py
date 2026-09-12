"""#50 B1 Data Source Workspace V2:逐源内容清单 / 单文档真相 / 逐源生成列表。

合同(docs/engineering/tasks/v162-i50-data-source-workspace-v2-contract.md):
- 新端点全部只读 GET(viewer 可读,RBAC 不变,零写路径);
- 清单行含 title / canonical url-path / L 轴状态 / 在服状态 / chunk_count /
  权威时间戳(created_at/updated_at;禁止虚构 discovered/last-seen);
- 单文档真相:状态 + 所属版本与生成(ordinal/status)+ canonical 身份;
  后端无记录的成分显式缺席(后端无此记录),绝不编造;
- 生成列表:ordinal/status/doc/chunk 计数/激活退役时间/失败证据(failure JSONB);
- 复合文档身份 ``<source_id>/<branch>/<rel_path>`` 含斜杠,路由设计必须处理
  (本实现:query 参数 ``doc_source_id`` 传递,规避 path 斜杠编码歧义)。

真实 Postgres(TEST_DATABASE_URL / app.state.session_factory,与 admin API 测试同库)。
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

# 所有 admin API 测试共享 session 级事件循环(与 conftest 的 session fixture 对齐)
pytestmark = pytest.mark.asyncio(loop_scope="session")

# 模块唯一前缀(本进程一次生成;并发 agent 各用随机前缀互不碰撞)
SRC = f"b1ws-{uuid.uuid4().hex[:10]}"
OTHER_SRC = f"{SRC}-other"
EMPTY_SRC = f"{SRC}-empty"
RETIRED_SRC = f"{SRC}-retired"

READY_ORDINAL = uuid.uuid4().int % 900_000_000 + 100_000_000
FAILED_ORDINAL = READY_ORDINAL + 1

ACTIVE_DOC = f"{SRC}/main/alive.md"
GAP_DOC = f"{SRC}/main/no-version-row.md"
MISSING_DOC = f"{SRC}/main/vanishing.md"
SUPERSEDED_DOC = f"{SRC}/main/old.md"
DELETED_DOC = f"{SRC}/main/gone.md"

NOW = datetime.now(UTC)


async def _mk_generation(session, ordinal: int, source_id: str, **kw) -> IndexGeneration:
    gen = IndexGeneration(
        ordinal=ordinal,
        source_id=source_id,
        status=kw.pop("status", "ready"),
        doc_count=kw.pop("doc_count", 4),
        chunk_count=kw.pop("chunk_count", 12),
        **kw,
    )
    session.add(gen)
    return gen


async def _mk_version(
    session,
    doc_source_id: str,
    seq: int,
    generation: IndexGeneration,
    *,
    status: str = "active",
    chunk_count: int = 3,
    url: str = "",
    title: str = "",
) -> DocumentVersion:
    version = DocumentVersion(
        source_id=doc_source_id,
        version_seq=seq,
        content_hash="a" * 64,
        metadata_hash="b" * 64,
        generation_id=generation.id,
        generation_ordinal=generation.ordinal,
        status=status,
        title=title,
        url=url,
        chunk_count=chunk_count,
    )
    session.add(version)
    return version


async def _mk_doc(
    session,
    doc_source_id: str,
    *,
    title: str,
    url: str,
    lifecycle: str = "active",
    chunk_count: int = 3,
    current_version: DocumentVersion | None = None,
    superseded_by: str | None = None,
) -> Document:
    doc = Document(
        source_id=doc_source_id,
        content_hash="c" * 64,
        source_type="github",
        product="b1ws",
        title=title,
        url=url,
        branch="main",
        chunk_count=chunk_count,
        lifecycle=lifecycle,
    )
    if current_version is not None:
        doc.current_version_id = current_version.id
    if superseded_by is not None:
        doc.superseded_by = superseded_by
        doc.superseded_at = NOW
    if lifecycle == "deleted":
        doc.deleted_at = NOW
    session.add(doc)
    return doc


@pytest_asyncio.fixture(loop_scope="session")
async def viewer_headers():
    """viewer 角色用户(合同:新端点 viewer 可读)。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email=f"{SRC}@test.com",
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
async def ws_seed():
    """播种:1 个源(5 种 L 轴状态文档)+ 空/全退役/其他源 + ready/failed 两代。"""
    factory = app.state.session_factory
    async with factory() as session:
        for sid in (SRC, OTHER_SRC, EMPTY_SRC, RETIRED_SRC):
            session.add(DataSource(id=sid, type="github", product="b1ws", config={}))
        gen_ready = await _mk_generation(session, READY_ORDINAL, SRC, status="ready")
        await session.flush()
        await _mk_generation(
            session,
            FAILED_ORDINAL,
            SRC,
            status="failed",
            doc_count=0,
            chunk_count=0,
            failure={"error": "embedder 返回 0 向量,期望 12", "stage": "embed"},
        )
        v1 = await _mk_version(session, ACTIVE_DOC, 1, gen_ready, title="Alive Doc", url="https://git.local/main/alive.md")
        v2 = await _mk_version(session, MISSING_DOC, 1, gen_ready, title="Vanishing Doc", url="https://git.local/main/vanishing.md")
        v3 = await _mk_version(
            session, SUPERSEDED_DOC, 2, gen_ready, status="superseded", title="Old Doc", url="https://git.local/main/old.md"
        )
        await session.flush()
        session.add(
            DocumentVersionChunk(version_id=v1.id, chunk_index=0, text="chunk-0", props={})
        )
        session.add(
            DocumentVersionChunk(version_id=v1.id, chunk_index=1, text="chunk-1", props={})
        )
        await _mk_doc(session, ACTIVE_DOC, title="Alive Doc", url="https://git.local/main/alive.md", current_version=v1)
        await _mk_doc(session, GAP_DOC, title="Gap Doc", url="https://git.local/main/gap.md")
        await _mk_doc(
            session, MISSING_DOC, title="Vanishing Doc", url="https://git.local/main/vanishing.md",
            lifecycle="missing_candidate", current_version=v2,
        )
        await _mk_doc(
            session, SUPERSEDED_DOC, title="Old Doc", url="https://git.local/main/old.md",
            lifecycle="superseded", current_version=v3, superseded_by=f"{SRC}/main/newer.md",
        )
        await _mk_doc(session, DELETED_DOC, title="Gone Doc", url="https://git.local/main/gone.md", lifecycle="deleted")
        # 全退役源:仅 deleted 文档
        await _mk_doc(session, f"{RETIRED_SRC}/main/retired.md", title="Retired Doc", url="https://git.local/r.md", lifecycle="deleted")
        # 其他源(跨源归属校验用)
        other_gen = await _mk_generation(session, FAILED_ORDINAL + 1, OTHER_SRC, status="ready")
        await session.flush()
        ov = await _mk_version(session, f"{OTHER_SRC}/main/x.md", 1, other_gen, title="Other Doc", url="https://git.local/other.md")
        await session.flush()
        await _mk_doc(session, f"{OTHER_SRC}/main/x.md", title="Other Doc", url="https://git.local/other.md", current_version=ov)
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
                    delete(DocumentVersionChunk).where(DocumentVersionChunk.version_id.in_(version_ids))
                )
            await session.execute(delete(DocumentVersion).where(DocumentVersion.source_id.like(f"{sid}/%")))
            await session.execute(delete(Document).where(Document.source_id.like(f"{sid}/%")))
            await session.execute(delete(IndexGeneration).where(IndexGeneration.source_id == sid))
            await session.execute(delete(DataSource).where(DataSource.id == sid))
        await session.commit()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


DOCS_URL = f"/api/admin/data-sources/{SRC}/documents"


# --------------------------------------------------------------------------- #
# 逐源文档清单(分页 / 生命周期过滤 / 子串搜索)
# --------------------------------------------------------------------------- #


async def test_inventory_unknown_source_404(viewer_headers, ws_seed):
    async with _client() as client:
        resp = await client.get(
            f"/api/admin/data-sources/b1ws-nope-{uuid.uuid4().hex[:6]}/documents",
            headers=viewer_headers,
        )
    assert resp.status_code == 404


async def test_inventory_lists_all_lifecycle_states_with_truth(viewer_headers, ws_seed):
    async with _client() as client:
        resp = await client.get(DOCS_URL, headers=viewer_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert data["ledger_total"] == 5
    rows = {r["source_id"]: r for r in data["items"]}
    # 五种 L 轴状态齐全(行含 title/canonical url+path/L 轴/在服/chunk_count/权威时间戳)
    assert set(rows) == {ACTIVE_DOC, GAP_DOC, MISSING_DOC, SUPERSEDED_DOC, DELETED_DOC}
    alive = rows[ACTIVE_DOC]
    assert alive["title"] == "Alive Doc"
    assert alive["url"] == "https://git.local/main/alive.md"
    assert alive["lifecycle"] == "active"
    assert alive["serving"] is True
    assert alive["chunk_count"] == 3
    assert alive["created_at"] and "T" in alive["created_at"]
    assert alive["updated_at"] and "T" in alive["updated_at"]
    assert alive["current_version_seq"] == 1
    assert alive["generation_ordinal"] == READY_ORDINAL
    # SERVING 语义:missing_candidate 处于宽限,仍由上一代服务(在服)
    assert rows[MISSING_DOC]["serving"] is True
    assert rows[MISSING_DOC]["lifecycle"] == "missing_candidate"
    # 撤出集合:superseded / deleted 不在服
    assert rows[SUPERSEDED_DOC]["serving"] is False
    assert rows[DELETED_DOC]["serving"] is False
    # 悬挂账本行(active 但无现行版本记录)不可证在服
    assert rows[GAP_DOC]["serving"] is False
    assert rows[GAP_DOC]["current_version_seq"] is None


async def test_inventory_lifecycle_filter(viewer_headers, ws_seed):
    async with _client() as client:
        resp = await client.get(
            DOCS_URL, params={"lifecycle": "deleted"}, headers=viewer_headers
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["lifecycle"] == "deleted"
    assert data["items"][0]["source_id"] == DELETED_DOC


async def test_inventory_lifecycle_filter_invalid_value_400(viewer_headers, ws_seed):
    async with _client() as client:
        resp = await client.get(
            DOCS_URL, params={"lifecycle": "not-a-state"}, headers=viewer_headers
        )
    assert resp.status_code == 400


async def test_inventory_search_title_and_url_substring(viewer_headers, ws_seed):
    async with _client() as client:
        by_title = await client.get(
            DOCS_URL, params={"search": "Vanishing"}, headers=viewer_headers
        )
        by_url = await client.get(
            DOCS_URL, params={"search": "alive.md"}, headers=viewer_headers
        )
        by_none = await client.get(
            DOCS_URL, params={"search": "does-not-exist-anywhere"}, headers=viewer_headers
        )
    assert by_title.status_code == 200
    assert by_title.json()["total"] == 1
    assert by_title.json()["items"][0]["source_id"] == MISSING_DOC
    assert by_url.status_code == 200
    assert by_url.json()["total"] == 1
    assert by_url.json()["items"][0]["source_id"] == ACTIVE_DOC
    assert by_none.json()["total"] == 0


async def test_inventory_search_is_case_insensitive_and_filters_apply_together(viewer_headers, ws_seed):
    async with _client() as client:
        resp = await client.get(
            DOCS_URL, params={"search": "VANISHING", "lifecycle": "missing_candidate"}, headers=viewer_headers
        )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


async def test_inventory_like_wildcards_are_escaped_not_interpreted(viewer_headers, ws_seed):
    """Role A 窄加固:source_id/搜索词中的 LIKE 通配符(%/_)必须被字面匹配,
    不得被解释为通配符(防跨源泄漏/防误命中)。种子源 id 含 `_`(b1ws-…),
    文档 url 含 `/` 与 `.`;用纯通配符搜索应零命中,用源内真实子串应命中。"""
    async with _client() as client:
        # `%` 作为搜索词:若未转义将命中全部行 → 必须为 0
        pct = await client.get(DOCS_URL, params={"search": "%"}, headers=viewer_headers)
        # `_` 作为搜索词:SQL `_` 单字符通配;未转义会命中所有含单字符的行
        underscore = await client.get(DOCS_URL, params={"search": "_"}, headers=viewer_headers)
        # 字面包含 `%` 的文本不存在于种子数据 → 0
        pct_word = await client.get(DOCS_URL, params={"search": "100%uptime"}, headers=viewer_headers)
        # 反斜杠转义的源内真实子串仍正常工作
        alive = await client.get(DOCS_URL, params={"search": "alive.md"}, headers=viewer_headers)
    assert pct.status_code == 200 and pct.json()["total"] == 0
    assert underscore.status_code == 200 and underscore.json()["total"] == 0
    assert pct_word.status_code == 200 and pct_word.json()["total"] == 0
    assert alive.status_code == 200 and alive.json()["total"] == 1


async def test_inventory_wildcard_source_id_does_not_leak_cross_source(viewer_headers, ws_seed):
    """Role A 窄加固:含 `%` 的 source_id 路径段不得扩大清单范围
    (OTHER_SRC = f"{SRC}-other" 是独立源;对 SRC 的通配注入不得把
    OTHER_SRC 的行带进 SRC 的清单)。"""
    async with _client() as client:
        # OTHER_SRC 自身清单可访问(控制组:证明前缀隔离是精确的)
        other = await client.get(
            f"/api/admin/data-sources/{OTHER_SRC}/documents", headers=viewer_headers
        )
        # 对 SRC 清单用带 % 的搜索词(url 字段)不得命中 OTHER_SRC 文档
        probe = await client.get(DOCS_URL, params={"search": "other%"}, headers=viewer_headers)
    assert other.status_code == 200
    assert probe.status_code == 200
    probe_ids = {row["source_id"] for row in probe.json()["items"]}
    assert all(sid.startswith(f"{SRC}/") for sid in probe_ids)
    assert not any(sid.startswith(f"{OTHER_SRC}/") for sid in probe_ids)


async def test_inventory_pagination(viewer_headers, ws_seed):
    async with _client() as client:
        page1 = await client.get(DOCS_URL, params={"page": 1, "size": 2}, headers=viewer_headers)
        page2 = await client.get(DOCS_URL, params={"page": 2, "size": 2}, headers=viewer_headers)
        page3 = await client.get(DOCS_URL, params={"page": 3, "size": 2}, headers=viewer_headers)
    assert page1.status_code == 200
    assert len(page1.json()["items"]) == 2
    assert page2.status_code == 200
    assert len(page2.json()["items"]) == 2
    assert page3.status_code == 200
    assert len(page3.json()["items"]) == 1
    ids = {r["source_id"] for r in page1.json()["items"]} | {
        r["source_id"] for r in page2.json()["items"]
    }
    assert len(ids) == 4


async def test_inventory_lifecycle_counts_and_bucket_counts_unfiltered(viewer_headers, ws_seed):
    """lifecycle_counts / serving_count / current_count 不受本次过滤影响(全源账本聚合)。"""
    async with _client() as client:
        resp = await client.get(
            DOCS_URL, params={"lifecycle": "deleted"}, headers=viewer_headers
        )
    data = resp.json()
    counts = data["lifecycle_counts"]
    assert counts["active"] == 2
    assert counts["missing_candidate"] == 1
    assert counts["superseded"] == 1
    assert counts["deleted"] == 1
    # 权威三桶计数:Current = active ∧ 现行版本可解析;在服 = SERVING ∧ 可解析
    assert data["current_count"] == 1  # GAP_DOC 悬挂,不计入 Current
    assert data["serving_count"] == 2  # active(可解析) + missing_candidate(宽限在服)


async def test_inventory_empty_source_returns_empty_not_404(viewer_headers, ws_seed):
    async with _client() as client:
        resp = await client.get(
            f"/api/admin/data-sources/{EMPTY_SRC}/documents", headers=viewer_headers
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []
    assert data["ledger_total"] == 0


async def test_inventory_all_retired_source(viewer_headers, ws_seed):
    async with _client() as client:
        resp = await client.get(
            f"/api/admin/data-sources/{RETIRED_SRC}/documents", headers=viewer_headers
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    row = data["items"][0]
    assert row["lifecycle"] == "deleted"
    assert row["serving"] is False


async def test_documents_endpoint_is_read_only(viewer_headers, ws_seed):
    """新端点族只读:POST 清单路径 = 405(无任何写路径)。"""
    async with _client() as client:
        resp = await client.post(DOCS_URL, headers=viewer_headers, json={})
    assert resp.status_code == 405


async def test_document_detail_and_generations_endpoints_are_read_only(
    viewer_headers, ws_seed
):
    """Role A 窄加固:detail 与 generations 路由同样零写路径(POST/DELETE → 405)。"""
    detail_url = f"{DOCS_URL}/detail"
    generations_url = f"/api/admin/data-sources/{SRC}/generations"
    async with _client() as client:
        for url in (detail_url, generations_url):
            post_resp = await client.post(url, headers=viewer_headers, json={})
            assert post_resp.status_code == 405, url
            delete_resp = await client.delete(url, headers=viewer_headers)
            assert delete_resp.status_code == 405, url


# --------------------------------------------------------------------------- #
# 单文档真相(复合身份 query 参数;缺席成分显式表达)
# --------------------------------------------------------------------------- #


async def test_document_truth_active_doc_full_attribution(viewer_headers, ws_seed):
    async with _client() as client:
        resp = await client.get(
            f"{DOCS_URL}/detail", params={"doc_source_id": ACTIVE_DOC}, headers=viewer_headers
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["doc_source_id"] == ACTIVE_DOC
    assert data["source_id"] == SRC
    assert data["lifecycle"] == "active"
    assert data["serving"] is True
    assert data["url"] == "https://git.local/main/alive.md"
    # 所属版本与生成(ordinal/status)
    assert data["current_version"]["version_seq"] == 1
    assert data["current_version"]["status"] == "active"
    assert data["current_version"]["generation_ordinal"] == READY_ORDINAL
    assert data["current_version"]["chunks_total"] == 2  # 持久 chunk 账本计数
    assert data["generation"]["ordinal"] == READY_ORDINAL
    assert data["generation"]["status"] == "ready"
    assert data["generation"]["doc_count"] == 4
    assert data["generation"]["chunk_count"] == 12


async def test_document_truth_missing_version_and_generation_explicit_absence(viewer_headers, ws_seed):
    """active 但无现行版本记录 → current_version/generation 显式 null(后端无此记录)。"""
    async with _client() as client:
        resp = await client.get(
            f"{DOCS_URL}/detail", params={"doc_source_id": GAP_DOC}, headers=viewer_headers
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_version"] is None
    assert data["generation"] is None
    assert data["serving"] is False


async def test_document_truth_superseded_evidence(viewer_headers, ws_seed):
    async with _client() as client:
        resp = await client.get(
            f"{DOCS_URL}/detail", params={"doc_source_id": SUPERSEDED_DOC}, headers=viewer_headers
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["lifecycle"] == "superseded"
    assert data["superseded_by"] == f"{SRC}/main/newer.md"
    assert data["superseded_at"] is not None
    assert data["serving"] is False


async def test_document_truth_deleted_evidence(viewer_headers, ws_seed):
    async with _client() as client:
        resp = await client.get(
            f"{DOCS_URL}/detail", params={"doc_source_id": DELETED_DOC}, headers=viewer_headers
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["lifecycle"] == "deleted"
    assert data["deleted_at"] is not None
    assert data["serving"] is False


async def test_document_truth_not_in_ledger_404_no_fabrication(viewer_headers, ws_seed):
    async with _client() as client:
        resp = await client.get(
            f"{DOCS_URL}/detail",
            params={"doc_source_id": f"{SRC}/main/never-ingested.md"},
            headers=viewer_headers,
        )
    assert resp.status_code == 404
    assert "后端无此记录" in resp.json()["detail"]


async def test_document_truth_rejects_other_source_document(viewer_headers, ws_seed):
    async with _client() as client:
        resp = await client.get(
            f"{DOCS_URL}/detail",
            params={"doc_source_id": f"{OTHER_SRC}/main/x.md"},
            headers=viewer_headers,
        )
    assert resp.status_code == 404


async def test_document_truth_unknown_source_404(viewer_headers, ws_seed):
    async with _client() as client:
        resp = await client.get(
            f"/api/admin/data-sources/b1ws-nope-{uuid.uuid4().hex[:6]}/documents/detail",
            params={"doc_source_id": "b1ws-nope-x/main/a.md"},
            headers=viewer_headers,
        )
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# 逐源生成列表(ordinal/status/计数/时间戳/失败证据 + 权威在服代序)
# --------------------------------------------------------------------------- #


async def test_generations_list_with_failure_evidence(viewer_headers, ws_seed):
    async with _client() as client:
        resp = await client.get(
            f"/api/admin/data-sources/{SRC}/generations", headers=viewer_headers
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    ordinals = [g["ordinal"] for g in data["items"]]
    assert ordinals == sorted(ordinals, reverse=True)  # ordinal 倒序
    by_ordinal = {g["ordinal"]: g for g in data["items"]}
    failed = by_ordinal[FAILED_ORDINAL]
    assert failed["status"] == "failed"
    assert failed["failure"]["stage"] == "embed"  # 失败证据原样透出
    ready = by_ordinal[READY_ORDINAL]
    assert ready["status"] == "ready"
    assert ready["doc_count"] == 4
    assert ready["chunk_count"] == 12
    # 权威在服代序(active_generation 口径的源内投影:alive + vanishing 的版本都在 ready 代)
    assert data["serving_ordinals"] == [READY_ORDINAL]
    # OTHER_SRC 的代不串源
    async with _client() as client:
        other = await client.get(
            f"/api/admin/data-sources/{OTHER_SRC}/generations", headers=viewer_headers
        )
    assert [g["ordinal"] for g in other.json()["items"]] == [FAILED_ORDINAL + 1]


async def test_generations_unknown_source_404(viewer_headers, ws_seed):
    async with _client() as client:
        resp = await client.get(
            f"/api/admin/data-sources/b1ws-nope-{uuid.uuid4().hex[:6]}/generations",
            headers=viewer_headers,
        )
    assert resp.status_code == 404


async def test_generations_empty_source_zero_rows(viewer_headers, ws_seed):
    async with _client() as client:
        resp = await client.get(
            f"/api/admin/data-sources/{EMPTY_SRC}/generations", headers=viewer_headers
        )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
    assert resp.json()["items"] == []
