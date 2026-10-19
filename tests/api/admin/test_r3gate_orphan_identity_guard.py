"""r3 发布安全门 G2/G3(修复 1):注册期孤儿身份碰撞 fail-closed guard。

12 项测试映射(胶囊 /tmp/zcode-g2g3.md):
- T1  基线:0 孤儿 + 全新 id → 注册 201,guard 不误伤;
- T2  存在孤儿 DocumentVersion/Chunk(generation 前缀身份)但无注册源 →
      注册该 id 必须拒绝。修复前 RED:注册端点静默 201 接受(跨版本重暴露
      入口,#178/#179 已证);修复后 GREEN:409 + 可发现错误锚点
      ``source identity collides with orphaned historical content``,零副作用;
- T3  重注册历史 source id(参数化孤儿表面:documents / index_generations /
      document_versions / document_version_chunks / uploads 孤儿子树)→ 同 T2;
- T4  恢复的 DB 含缺显式 grant 的 upload 源 → 查询侧 fail-closed(钉住既有
      行为:visibility_for_source 空 grant → 空 channels → DENY);
- T5  幽灵源 / 权威快照缺失 → 查询侧 DENY(钉住既有 fail-closed 语义);
- T12 正常合法来源注册 + 普通检索读面 → 零误伤(guard 只拦碰撞 id)。

身份谓词复用 #174 source_deletion:复合路径列(documents/document_versions)
用 ``startswith(f"{source_id}/", autoescape=True)`` 精确前缀(防 %/_
通配符越界);裸 id 列(index_generations.source_id)用精确相等。
"""

from __future__ import annotations

import uuid

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

_USER_EMAIL = "g2g3-guard@test.com"
_PREFIX = "g2g3-"
# 胶囊指定的可发现错误锚点(规格常量,不 import 被测模块,保证 RED 阶段可采集)
_ORPHAN_ANCHOR = "source identity collides with orphaned historical content"


async def _wipe_prefix(session, prefix: str) -> None:
    """清理本模块前缀的全部行(共享测试库纪律:绝不动其他模块的行)。"""
    version_ids = list(
        (
            await session.execute(
                select(DocumentVersion.id).where(
                    DocumentVersion.source_id.startswith(prefix, autoescape=True)
                )
            )
        ).scalars()
    )
    if version_ids:
        await session.execute(
            DocumentVersionChunk.__table__.delete().where(
                DocumentVersionChunk.version_id.in_(version_ids)
            )
        )
    await session.execute(
        DocumentVersion.__table__.delete().where(
            DocumentVersion.source_id.startswith(prefix, autoescape=True)
        )
    )
    await session.execute(
        Document.__table__.delete().where(
            Document.source_id.startswith(prefix, autoescape=True)
        )
    )
    await session.execute(
        IndexGeneration.__table__.delete().where(
            IndexGeneration.source_id.like(f"{prefix}%")
        )
    )
    await session.execute(
        DataSource.__table__.delete().where(DataSource.id.like(f"{prefix}%"))
    )


@pytest_asyncio.fixture(loop_scope="session")
async def guard_seed():
    factory = app.state.session_factory
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.email == _USER_EMAIL))
        await _wipe_prefix(session, _PREFIX)
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
        await _wipe_prefix(session, _PREFIX)
        await session.commit()


async def _post_create(headers, sid: str, *, type_: str = "github", config: dict | None = None):
    body = {
        "id": sid,
        "type": type_,
        "product": "g2g3",
        "config": config
        if config is not None
        else {"repo_url": f"https://example.com/{sid}.git"},
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post("/api/admin/data-sources", headers=headers, json=body)


async def _source_row(sid: str) -> DataSource | None:
    factory = app.state.session_factory
    async with factory() as session:
        return (
            await session.execute(select(DataSource).where(DataSource.id == sid))
        ).scalar_one_or_none()


async def _seed_orphan_version(sid: str, *, with_chunk: bool = True) -> None:
    """孤儿 DocumentVersion(+Chunk):身份 = ``{sid}/doc1`` 前缀,无注册源持有。"""
    factory = app.state.session_factory
    vid = uuid.uuid4()
    async with factory() as session:
        session.add(
            DocumentVersion(
                id=vid,
                source_id=f"{sid}/doc1",
                version_seq=1,
                content_hash=uuid.uuid4().hex,
                metadata_hash=uuid.uuid4().hex,
                generation_id=uuid.uuid4(),
                generation_ordinal=0,
                status="superseded",
                chunk_count=1,
            )
        )
        if with_chunk:
            session.add(
                DocumentVersionChunk(
                    version_id=vid, chunk_index=0, text="orphan content", props={}
                )
            )
        await session.commit()


async def _seed_orphan_document(sid: str) -> None:
    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            Document(
                content_hash=uuid.uuid4().hex,
                source_id=f"{sid}/doc1",
                source_type="github",
                product="g2g3",
                title="orphan",
                url="https://example.com/orphan",
                metadata_={},
                branch="",
                chunk_count=1,
            )
        )
        await session.commit()


async def _seed_orphan_generation(sid: str) -> None:
    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            IndexGeneration(
                id=uuid.uuid4(),
                # ordinal 全局唯一:用大随机数避开共享测试库的既有行
                ordinal=(int(uuid.uuid4().hex[:12], 16) % 900_000_000) + 100_000_000,
                source_id=sid,
                status="retired",
                doc_count=1,
                chunk_count=1,
            )
        )
        await session.commit()


# --------------------------------------------------------------------------- #
# T1 / T12:零误伤
# --------------------------------------------------------------------------- #


async def test_t1_fresh_id_registration_unharmed(guard_seed):
    """T1:0 孤儿 + 全新 id → 注册 201(guard 不误伤全新身份)。"""
    sid = f"{_PREFIX}fresh-ok"
    resp = await _post_create(guard_seed, sid)
    assert resp.status_code == 201, resp.text
    assert await _source_row(sid) is not None


async def test_t12_legit_source_and_normal_reads_unharmed(guard_seed):
    """T12:正常合法来源注册 + 普通检索读面 → 零误伤。"""
    sid = f"{_PREFIX}legit"
    resp = await _post_create(guard_seed, sid)
    assert resp.status_code == 201, resp.text
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        docs = await client.get(
            f"/api/admin/data-sources/{sid}/documents", headers=guard_seed
        )
        listing = await client.get("/api/admin/data-sources", headers=guard_seed)
    assert docs.status_code == 200, docs.text
    assert listing.status_code == 200
    assert any(item["id"] == sid for item in listing.json())


# --------------------------------------------------------------------------- #
# T2 / T3:孤儿身份碰撞 → 拒绝注册(修复前 RED:静默 201)
# --------------------------------------------------------------------------- #


async def test_t2_orphan_version_and_chunk_block_registration(guard_seed):
    """T2:孤儿 DocumentVersion/Chunk 在场 → 注册该 id 必须 409 + 锚点,零副作用。"""
    sid = f"{_PREFIX}orphver"
    await _seed_orphan_version(sid, with_chunk=True)
    resp = await _post_create(guard_seed, sid)
    assert resp.status_code == 409, (
        f"孤儿身份碰撞被静默接受(status={resp.status_code}):跨版本重暴露入口未封死"
    )
    assert _ORPHAN_ANCHOR in resp.json()["detail"]
    assert await _source_row(sid) is None  # fail-closed:零副作用


@pytest.mark.parametrize(
    ("label", "expected_surfaces", "seeder"),
    [
        ("documents", ["documents"], _seed_orphan_document),
        ("generations", ["index_generations"], _seed_orphan_generation),
        ("versions", ["document_versions"], lambda sid: _seed_orphan_version(sid, with_chunk=False)),
        ("versions+chunks", ["document_versions", "document_version_chunks"],
         lambda sid: _seed_orphan_version(sid, with_chunk=True)),
    ],
)
async def test_t3_reregister_historical_identity_blocks(guard_seed, label, expected_surfaces, seeder):
    """T3:重注册历史 source id(各孤儿表面参数化)→ 409 + 表面点名。"""
    sid = f"{_PREFIX}hist-{label.replace('+', '-')}"
    await seeder(sid)
    resp = await _post_create(guard_seed, sid)
    assert resp.status_code == 409, f"表面 {label} 被静默接受"
    detail = resp.json()["detail"]
    assert _ORPHAN_ANCHOR in detail
    for surface in expected_surfaces:
        assert surface in detail, f"错误必须点名碰撞表面 {surface}: {detail}"
    assert await _source_row(sid) is None


async def test_t3_uploads_orphan_subtree_blocks(guard_seed, tmp_path, monkeypatch):
    """T3(uploads 孤儿子树):uploads 根下存在该 id 目录 → 注册 409。"""
    sid = f"{_PREFIX}hist-uploads"
    import backend.services.source_identity_guard as sig

    orphan_dir = tmp_path / sid
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "doc.pdf").write_bytes(b"orphan")
    monkeypatch.setattr(sig, "UPLOADS_CORPUS_ROOT", tmp_path)
    resp = await _post_create(guard_seed, sid)
    assert resp.status_code == 409
    assert _ORPHAN_ANCHOR in resp.json()["detail"]
    assert "uploads_subtree" in resp.json()["detail"]
    assert await _source_row(sid) is None


# --------------------------------------------------------------------------- #
# T4 / T5:查询侧 fail-closed(钉住既有行为)
# --------------------------------------------------------------------------- #


async def test_t4_restored_upload_source_without_grant_fails_closed(guard_seed):
    """T4:恢复的 DB 行(filesystem+upload_mode,缺显式 grant)→ 查询侧 DENY;
    注册侧既有缺省语义 = channel_visibility [](零公开渠道)。"""
    from backend.services.source_visibility import (
        SourceVisibilityGuard,
        make_db_loader,
    )

    sid = f"{_PREFIX}upnogrant"
    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            DataSource(
                id=sid,
                type="filesystem",
                product="g2g3",
                enabled=True,
                config={"upload_mode": True, "root_path": f"data/uploads/data-sources/{sid}"},
            )
        )
        await session.commit()
    try:
        loader = make_db_loader(app.state.session_factory)
        mapping = await loader()
        policy = mapping[sid]
        assert policy.upload_mode is True
        assert policy.channels == (), "缺显式 grant 的 upload 源不得继承公开缺省"
        guard = SourceVisibilityGuard(loader, ttl=0.0)
        for channel in ("widget", "api", "admin"):
            decision = await guard.resolve(f"{sid}/doc1", channel)
            assert decision.allowed is False, f"channel={channel} 必须 DENY(fail-closed)"

        # 注册侧既有语义(钉住):缺省补 channel_visibility=[](C9 上传默认不公开)
        resp = await _post_create(
            guard_seed,
            f"{_PREFIX}updefault",
            type_="filesystem",
            config={"upload_mode": True},
        )
        assert resp.status_code == 201
        assert resp.json()["config"]["channel_visibility"] == []
    finally:
        factory = app.state.session_factory
        async with factory() as session:
            await session.execute(
                DataSource.__table__.delete().where(DataSource.id.like(f"{_PREFIX}up%"))
            )
            await session.commit()


async def test_t5_ghost_and_missing_snapshot_deny(guard_seed):
    """T5:恢复旧 filesystem 向量后查询侧的两类既有 fail-closed:权威快照
    缺失 → DENY(Case A);幽灵前缀(不在权威配置)→ DENY(Case B)。"""
    from backend.services.source_visibility import (
        SourceVisibilityGuard,
        policy_for_source,
    )

    async def _broken_loader():
        raise RuntimeError("authoritative snapshot unavailable")

    guard = SourceVisibilityGuard(_broken_loader)
    decision = await guard.resolve("restored-ghost/doc1", "widget")
    assert decision.allowed is False, "无权威快照必须 DENY,不得放行未证实候选"
    assert decision.upload_mode is None

    async def _ok_loader():
        return {"known-src": policy_for_source("github", {})}

    guard2 = SourceVisibilityGuard(_ok_loader)
    assert (await guard2.resolve("restored-other/doc1", "widget")).allowed is False
    assert (await guard2.resolve("known-src/doc1", "widget")).allowed is True
