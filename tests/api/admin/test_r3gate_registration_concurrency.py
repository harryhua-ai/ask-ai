"""r3gate R2-3:注册期孤儿身份碰撞 guard 的并发语义(READ COMMITTED)。

竞态分析(详见 backend/api/admin/data_sources.py R2-3 注释与交接报告):
- R1 现码 check→insert 同事务,但 READ COMMITTED 下每条语句独立快照:
  并发同 id 双注册的双双 existing-check / guard 探测可全部先于对方 commit
  执行 → 双双放行 → PK 唯一约束兜底,后到 INSERT 抛 IntegrityError →
  未处理 500(数据不损坏,但语义非确定、无碰撞 409 锚点)。RED 由
  ``test_concurrent_same_id_registration_exactly_one_success`` 在 R1 现码
  上实证(第二响应 500);
- 最小修复:注册事务入口 ``pg_advisory_xact_lock(hashtextextended(:sid,0))``
  (事务级咨询锁,复用 PG 原生机制,非新锁服务)串行化同 id 并发注册:
  后到者等待前者 commit → existing-check 见已提交行 → 干净 409。锁随事务
  自动释放,不同 id 各锁各键(hashtextextended 碰撞仅导致无害额外串行);
- 删除侧交互:删除流程 final 事务原子移除「账本行+配置行」
  (source_deletion._claim_and_delete_one;purge 异常绝不先删行),删除在途
  期间 data_sources 行始终存在 → 注册被 existing-check 拦截;final commit
  后孤儿不存在 → 注册安全。即 PG 侧不存在「已提交的瞬态孤儿窗」。
- 「guard 检查期间出现孤儿」的确定性复现:离线无法构造(孤儿只能由删除
  final 事务产生,而该事务与 existing-check 的交错不会产生"探测时不存在、
  commit 后存在且无主"的提交态)→ 不做确定性复现断言,如实记录;缓解 =
  注册 id 一经注册即被 PK + advisory 锁保护,后续删除走 lifecycle 流程,
  重注册再次经过 guard。
- Weaviate source_id-only 孤儿索引碰撞:离线无 Weaviate,guard 未覆盖
  → **BLOCKED 如实记录**(见交接 review-findings-closure),不假装已覆盖。

本文件钉住(胶囊要求):
- 并发同 id 注册(asyncio.gather 双注册)恰一成功、另一 409(绝不 500);
- 孤儿 id 注册并发下仍被拒(guard 与锁叠加不互扰);
- guard 探针 DB 异常 → 注册失败零残留(回滚干净,后续注册正常);
- 不同 id 并发注册互不串行阻断(双双 201);
- 通配符/前缀/大小写/ID 边界负例(谓词 autoescape + 精确相等不越界)。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import (
    DataSource,
    DocumentVersion,
    DocumentVersionChunk,
    User,
)
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

_USER_EMAIL = "g2g3-concurrency@test.com"
_PREFIX = "g2g3cc-"
_ORPHAN_ANCHOR = "source identity collides with orphaned historical content"


async def _wipe_prefix(session, prefix: str) -> None:
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
        DataSource.__table__.delete().where(DataSource.id.like(f"{prefix}%"))
    )


@pytest_asyncio.fixture(loop_scope="session")
async def concurrency_seed():
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


async def _post_create(headers, sid: str, *, type_: str = "github") -> tuple[int, dict]:
    body = {
        "id": sid,
        "type": type_,
        "product": "g2g3",
        "config": {"repo_url": f"https://example.com/{sid}.git"},
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/admin/data-sources", headers=headers, json=body)
    detail = {}
    try:
        detail = resp.json()
    except Exception:
        detail = {"raw": resp.text[:200]}
    return resp.status_code, detail


async def _source_rows(sid: str) -> list[DataSource]:
    factory = app.state.session_factory
    async with factory() as session:
        return list(
            (
                await session.execute(
                    select(DataSource).where(DataSource.id == sid)
                )
            ).scalars()
        )


async def _seed_orphan_version(sid: str) -> None:
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
        session.add(
            DocumentVersionChunk(version_id=vid, chunk_index=0, text="o", props={})
        )
        await session.commit()


# --------------------------------------------------------------------------- #
# 并发同 id 注册
# --------------------------------------------------------------------------- #


async def test_concurrent_same_id_registration_exactly_one_success(concurrency_seed):
    """asyncio.gather 双注册同 id:恰一 201,另一必须 409(绝不 500)。"""
    sid = f"{_PREFIX}race-same"
    results = await asyncio.gather(
        _post_create(concurrency_seed, sid),
        _post_create(concurrency_seed, sid),
    )
    statuses = sorted(code for code, _ in results)
    assert statuses == [201, 409], (
        f"并发同 id 注册语义非确定:statuses={statuses}, "
        f"details={[d for _, d in results]}(RED:500 = check→insert 竞态窗未封闭)"
    )
    rows = await _source_rows(sid)
    assert len(rows) == 1, "并发双注册最终必须恰有一行"


async def test_concurrent_orphan_id_registrations_both_refused(concurrency_seed):
    """孤儿 id 并发注册:双双 409 + 锚点,零行落库(guard 与锁叠加不互扰)。"""
    sid = f"{_PREFIX}race-orphan"
    await _seed_orphan_version(sid)
    results = await asyncio.gather(
        _post_create(concurrency_seed, sid),
        _post_create(concurrency_seed, sid),
    )
    for code, detail in results:
        assert code == 409, f"孤儿 id 并发注册被放行:status={code} detail={detail}"
        assert _ORPHAN_ANCHOR in str(detail)
    assert await _source_rows(sid) == []


# --------------------------------------------------------------------------- #
# guard 探针异常 → 回滚零残留
# --------------------------------------------------------------------------- #


async def test_guard_db_exception_rolls_back_registration(
    concurrency_seed, monkeypatch
):
    """guard 探测 DB 异常 → 注册失败、零残留;修复后正常注册不受影响。"""
    import backend.api.admin.data_sources as mod

    sid = f"{_PREFIX}guard-boom"

    async def _boom(session, source_id, **kwargs):
        raise RuntimeError("guard probe db failure (injected)")

    monkeypatch.setattr(mod, "find_orphan_identity_surfaces", _boom)
    code, detail = await _post_create(concurrency_seed, sid)
    assert code >= 500, f"探针异常必须向上暴露(不得静默放行):status={code}"
    assert await _source_rows(sid) == [], "异常路径不得残留半注册状态"
    monkeypatch.undo()
    code2, detail2 = await _post_create(concurrency_seed, sid)
    assert code2 == 201, f"回滚后正常注册应成功:{code2} {detail2}"


async def test_concurrent_different_ids_both_succeed(concurrency_seed):
    """不同 id 并发注册:互不阻断,双双 201(advisory 锁各键各锁)。"""
    sid_a = f"{_PREFIX}race-a"
    sid_b = f"{_PREFIX}race-b"
    results = await asyncio.gather(
        _post_create(concurrency_seed, sid_a),
        _post_create(concurrency_seed, sid_b),
    )
    codes = [code for code, _ in results]
    assert codes == [201, 201], f"不同 id 并发注册不得互扰:{results}"
    assert len(await _source_rows(sid_a)) == 1
    assert len(await _source_rows(sid_b)) == 1


# --------------------------------------------------------------------------- #
# 身份谓词边界:通配符 / 前缀 / 大小写
# --------------------------------------------------------------------------- #


async def test_wildcard_chars_in_id_never_overblock(concurrency_seed):
    """id 含 %/_ (LIKE 通配符)时,对「形似但身份不同」的孤儿零误伤
    (startswith autoescape → 通配符按字面处理)。"""
    await _seed_orphan_version(f"{_PREFIX}wld")  # 真实孤儿身份 = {prefix}wld/doc1
    for sid in (f"{_PREFIX}wld%", f"{_PREFIX}wld_", f"{_PREFIX}wldx"):
        code, detail = await _post_create(concurrency_seed, sid)
        assert code == 201, (
            f"通配符/形似 id {sid} 不得被误伤(身份谓词必须字面精确):{code} {detail}"
        )


async def test_wildcard_named_orphan_still_blocked(concurrency_seed):
    """孤儿自身含通配符字符 → 注册该字面 id 仍必须 409(不漏拦)。"""
    sid = f"{_PREFIX}wlq%"
    await _seed_orphan_version(sid)
    code, detail = await _post_create(concurrency_seed, sid)
    assert code == 409, f"含通配符字面 id 的孤儿必须被拦:{code} {detail}"
    assert _ORPHAN_ANCHOR in str(detail)


async def test_sibling_prefix_identity_not_confused(concurrency_seed):
    """前缀兄弟:孤儿 g2g3cc-pfx/doc1 与注册 id g2g3cc-pf 身份不同 → 201;
    注册 id g2g3cc-pfx(恰为孤儿源)→ 409。"""
    await _seed_orphan_version(f"{_PREFIX}pfx")
    code, detail = await _post_create(concurrency_seed, f"{_PREFIX}pf")
    assert code == 201, f"前缀兄弟身份不得混淆误伤:{code} {detail}"
    code2, detail2 = await _post_create(concurrency_seed, f"{_PREFIX}pfx")
    assert code2 == 409 and _ORPHAN_ANCHOR in str(detail2)


async def test_case_distinct_identity_boundary(concurrency_seed):
    """大小写边界(如实钉住既有语义):身份谓词大小写敏感(PG = / like 均
    case-sensitive)→ 大写变体 id 不命中小写孤儿身份,注册放行。若产品层
    要求大小写不敏感唯一,属后续产品决策,不在本 guard 语义内。"""
    await _seed_orphan_version(f"{_PREFIX}case")
    upper = f"{_PREFIX}CASE"
    code, detail = await _post_create(concurrency_seed, upper)
    assert code == 201, (
        f"大小写敏感边界被破坏(谓词意外不敏感):{code} {detail}"
    )
    code2, _ = await _post_create(concurrency_seed, f"{_PREFIX}case")
    assert code2 == 409, "精确同字面孤儿 id 必须仍被拦"
