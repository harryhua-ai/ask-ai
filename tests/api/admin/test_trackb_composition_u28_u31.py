"""#28×#31 Track B composition 不变量(组合树 integration/v1.6.3-r5-trackb-comp)。

两个 accepted 候选的语义缝(#28 B1 = 变体商业真值摄取/投影;#31 B2 =
evidence-authority 恢复:第一方案例证据/官方方案保留/禁上下文域官方缺席
指令)。本套件锁定跨候选组合不变量与 #28 冻结集成义务:

- INV-B1(单一权威词表):Weaviate COMMERCE_PROPS 键、Admin
  DocumentCommerceTruth 字段、连接器 metadata 键三方同名 —— 不存在第二套
  authority representation(B2-1 继续 DEFERRED 的组合面前提);
- INV-B2(端点装配 + honest absence,义务 3/4):woo 文档且账本行携带
  commerce 标识 → DocumentCommerceTruth 逐字段投影(date_modified →
  commerce_synced_at 新鲜度戳);woo 存量行(pre-migration/pre-resync,
  metadata 无 commerce 键)与非 woo 文档 → commerce=None 显式缺席;
  同一响应上 #55 的 citation/versions 真值共存(组合树加性面);
- INV-B3(摄取面诚实缺席):``_commerce_props`` 对非 woo 文档返回 {}
  (零商业 props),woo 缺键按 COMMERCE_PROPS 缺省 —— 与检索面
  return_properties 的空值判「非变体」语义一致。

真实 Postgres(TEST_DATABASE_URL);与 test_document_inspector_truth 同构。
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
from backend.pipeline.ingest import COMMERCE_PROPS

pytestmark = pytest.mark.asyncio(loop_scope="session")

SRC = f"ub28-{uuid.uuid4().hex[:10]}"
ORDINAL = uuid.uuid4().int % 900_000_000 + 100_000_000
NOW = datetime.now(UTC)
DETAIL_URL = f"/api/admin/data-sources/{SRC}/documents/detail"

DOC_WOO_LIVE = f"{SRC}/woo/product-101/variation-1"
DOC_WOO_LEGACY = f"{SRC}/woo/product-102/variation-1"  # pre-resync 存量行
DOC_GITHUB = f"{SRC}/main/README.md"

WOO_META = {
    "commerce_type": "variation",
    "product_id": 101,
    "variation_id": 7,
    "variation_identity_key": "101:7",
    "sku": "NE101-V7",
    "price": "89.00",
    "regular_price": "112.00",
    "sale_price": "89.00",
    "on_sale": True,
    "stock_status": "instock",
    "purchasable": True,
    "variation_attributes": [" connectivity=4g ", "lens=6mm"],
    "permalink": "https://store.example.com/product/ne101/var-7",
    "date_modified": "2026-09-16T08:00:00",
}


@pytest_asyncio.fixture(loop_scope="session")
async def tb_seed():
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        gen = IndexGeneration(ordinal=ORDINAL, source_id=SRC, status="ready")
        session.add(gen)
        await session.flush()
        session.add(
            DataSource(
                id=SRC,
                type="woocommerce",
                product="ne101",
                config={"base_url": "https://store.example.com"},
                sync_interval="24h",
                enabled=True,
            )
        )
        for doc_id, source_type, meta in (
            (DOC_WOO_LIVE, "woocommerce", WOO_META),
            (DOC_WOO_LEGACY, "woocommerce", {}),
            (DOC_GITHUB, "github", {}),
        ):
            v = DocumentVersion(
                source_id=doc_id,
                version_seq=1,
                content_hash="a" * 64,
                metadata_hash="b" * 64,
                generation_id=gen.id,
                generation_ordinal=ORDINAL,
                status="active",
                title=doc_id.rsplit("/", 1)[-1],
                url=f"https://store.example.com/{doc_id.rsplit('/', 1)[-1]}",
                chunk_count=0,
                valid_from=NOW - timedelta(days=1),
            )
            session.add(v)
            await session.flush()
            doc = Document(
                source_id=doc_id,
                content_hash="c" * 64,
                source_type=source_type,
                product="ne101",
                title=doc_id.rsplit("/", 1)[-1],
                url=f"https://store.example.com/{doc_id.rsplit('/', 1)[-1]}",
                branch="",
                chunk_count=0,
                lifecycle="active",
                current_version_id=v.id,
                metadata_=meta,
            )
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
                    select(DocumentVersion.id).where(
                        DocumentVersion.source_id.like(f"{SRC}/%")
                    )
                )
            )
        )
        await session.execute(
            DocumentVersion.__table__.delete().where(
                DocumentVersion.source_id.like(f"{SRC}/%")
            )
        )
        await session.execute(
            Document.__table__.delete().where(Document.source_id.like(f"{SRC}/%"))
        )
        await session.execute(
            IndexGeneration.__table__.delete().where(IndexGeneration.source_id == SRC)
        )
        await session.execute(
            DataSource.__table__.delete().where(DataSource.id == SRC)
        )
        await session.execute(
            User.__table__.delete().where(User.id == user_id)
        )
        await session.commit()


async def _truth(headers, doc_source_id: str) -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            DETAIL_URL, params={"doc_source_id": doc_source_id}, headers=headers
        )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_b28_commerce_truth_projected_for_woo_document(tb_seed):
    """义务 3:woo 在账行 → 逐字段商业真值(单一词表;date_modified →
    commerce_synced_at 新鲜度戳)。"""
    body = await _truth(tb_seed["headers"], DOC_WOO_LIVE)
    c = body["commerce"]
    assert c is not None
    assert c["commerce_type"] == "variation"
    assert c["variation_identity_key"] == "101:7"
    assert c["sku"] == "NE101-V7"
    assert c["price"] == "89.00"
    assert c["regular_price"] == "112.00"
    assert c["sale_price"] == "89.00"
    assert c["on_sale"] is True
    assert c["stock_status"] == "instock"
    assert c["purchasable"] is True
    assert c["variation_attributes"] == [" connectivity=4g ", "lens=6mm"]
    assert c["permalink"].startswith("https://store.example.com/")
    assert c["commerce_synced_at"] == "2026-09-16T08:00:00"


async def test_b28_honest_absence_for_legacy_and_non_woo(tb_seed):
    """义务 4:pre-resync 存量 woo 行(键缺失)与非 woo 文档 → commerce=None
    显式缺席(绝不以空值伪装 0 价/缺货);#55 真值面同响应共存。"""
    legacy = await _truth(tb_seed["headers"], DOC_WOO_LEGACY)
    assert legacy["commerce"] is None, "pre-resync 存量行诚实缺席"
    assert legacy["versions"] is not None  # #55 面共存(组合树加性)
    assert legacy["citation"] is not None

    gh = await _truth(tb_seed["headers"], DOC_GITHUB)
    assert gh["commerce"] is None, "非 woo 文档恒无商业真值"
    assert gh["citation"] is not None


async def test_b28_single_authority_vocabulary_across_surfaces():
    """INV-B1:COMMERCE_PROPS(Weaviate/检索投影)与 Admin
    DocumentCommerceTruth 字段同名 —— 零第二套 authority representation。"""
    from backend.api.admin.schemas import DocumentCommerceTruth

    admin_fields = set(DocumentCommerceTruth.model_fields.keys())
    prop_keys = set(COMMERCE_PROPS.keys())
    assert prop_keys <= admin_fields, (
        f"检索投影键缺 Admin 对应字段: {prop_keys - admin_fields}"
    )
    assert admin_fields - prop_keys == {"commerce_synced_at"} or not (
        admin_fields - prop_keys
    ), "Admin 新增字段必须说明映射(commerce_synced_at ← date_modified)"


async def test_b28_ingest_projection_non_woo_empty_and_defaults(tb_seed):
    """INV-B3:``_commerce_props`` 非 woo → {}(零商业 props);woo 缺键用
    COMMERCE_PROPS 缺省 —— 检索面空值判「非变体」的诚实缺席语义。"""
    from backend.pipeline.ingest import _commerce_props

    class _Raw:
        def __init__(self, source_type, metadata):
            self.source_type = source_type
            self.metadata = metadata

    assert _commerce_props(_Raw("github", {"price": "1.00"})) == {}
    woo_empty = _commerce_props(_Raw("woocommerce", {}))
    assert woo_empty["variation_identity_key"] == ""
    assert woo_empty["price"] == ""
    assert "stock_quantity" not in woo_empty  # None 整键省略,不写 0 伪装
