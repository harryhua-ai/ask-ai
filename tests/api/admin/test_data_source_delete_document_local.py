"""Admin Source Delete 文档局部安全性测试(阶段1 / G2)。

冻结禁令:Admin 源删除路径禁止 TEXT source_id equal/like 作为删除原语。
删除只能:
  1) 按账本确定性 UUID(uuid5(source_id, 0..chunk_count-1))点删;
  2) 迭代器实扫边界内对象,按**对象 UUID** 点删;
并必须在结束时验证残留 = 0。

核心断言:删除 Source A 不得波及 A-sibling / A-xxx / 相似前缀源。
"""

import re
import uuid as uuid_mod
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.pipeline.ingest import _deterministic_uuid

pytestmark = pytest.mark.unit

_PREFIX_A = "src-a"
_SIBLINGS = ("src-a-sibling", "src-a-xxx", "src-ab")


class _FakeItem:
    def __init__(
        self,
        obj_uuid: str,
        sid: str | None = None,
        properties: dict | None = None,
    ):
        self.uuid = obj_uuid
        self.properties = properties if properties is not None else {"source_id": sid}


_UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


class _FakeData:
    """delete_many/delete_by_id 模拟真实删除语义(维护存活对象表)。"""

    def __init__(self, objects: dict[str, _FakeItem]):
        self.objects = objects
        self.by_id_delete_calls: list[str] = []
        self.delete_many_filters: list = []

    def delete_many(self, where=None):
        # 真实 Filter 的 repr 携带 uuid 值列表(value=[...]):据此模拟删除,
        # 并让测试能断言「过滤器只夹带本源 UUID」。
        assert where is not None
        self.delete_many_filters.append(where)
        requested = re.findall(_UUID_RE, str(where))
        matched = sum(1 for u in requested if u in self.objects)
        for u in requested:
            self.objects.pop(u, None)
        return SimpleNamespace(failed=0, matches=matched, successful=matched)

    def delete_by_id(self, obj_uuid: str):
        self.by_id_delete_calls.append(obj_uuid)
        self.objects.pop(obj_uuid, None)


def _fake_client(objects: dict[str, _FakeItem]):
    collection = MagicMock()
    collection.data = _FakeData(objects)
    collection.readback_filters: list = []

    def iterator(return_properties=None):
        return iter(list(collection.data.objects.values()))

    collection.iterator.side_effect = iterator

    def fetch_objects(filters=None, limit=None):
        # 模拟 #168 读回原语:按过滤器携带的 UUID 返回实物存活对象
        collection.readback_filters.append(filters)
        requested = re.findall(_UUID_RE, str(filters))
        found = [objects[u] for u in requested if u in objects]
        return SimpleNamespace(objects=found)

    collection.query = SimpleNamespace(fetch_objects=fetch_objects)
    client = MagicMock()
    client.collections.get.return_value = collection
    client.close = lambda: None
    return client, collection


def _build_objects():
    """构造 Source A + 三个相似前缀源的账本与对象。"""
    ledger = [(_PREFIX_A + "/doc1", 3), (_PREFIX_A + "/doc2", 2)]
    objects: dict[str, _FakeItem] = {}
    sibling_obj_uuids: list[str] = []
    for sid, cc in ledger:
        for i in range(cc):
            u = _deterministic_uuid(sid, i)
            objects[u] = _FakeItem(u, sid)
    for sib in _SIBLINGS:
        for i in range(2):
            u = _deterministic_uuid(f"{sib}/doc", i)
            objects[u] = _FakeItem(u, f"{sib}/doc")
            sibling_obj_uuids.append(u)
    # A 源的账本外孤儿(A 边界内,应被兜底段删除)
    orphan_u = str(uuid_mod.uuid4())
    objects[orphan_u] = _FakeItem(orphan_u, _PREFIX_A + "/ghost")
    return ledger, objects, sibling_obj_uuids, orphan_u


def test_delete_source_a_document_local_and_siblings_survive():
    from backend.services import source_deletion as sd

    ledger, objects, sibling_uuids, orphan_u = _build_objects()
    client, collection = _fake_client(objects)

    with patch.object(sd.weaviate, "connect_to_local", lambda host, port, **k: client):
        stats = sd.purge_source_corpus_sync("http://localhost:8080", "Document", _PREFIX_A, ledger)

    own_uuids = {_deterministic_uuid(sid, i) for sid, cc in ledger for i in range(cc)}
    # Phase 1:每个账本 UUID 都被 by_id 过滤器点名,且不夹带任何兄弟源 UUID
    carried: set[str] = set()
    for f in collection.data.delete_many_filters:
        found = set(
            re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", str(f))
        )
        assert found <= own_uuids, f"过滤器夹带非本源 UUID: {found - own_uuids}"
        carried |= found
    assert carried == own_uuids
    # Phase 1 生效:账本对象已被删除(不在存活表);孤儿由兜底段按对象 UUID 删
    assert not (own_uuids & set(collection.data.objects))
    assert orphan_u in collection.data.by_id_delete_calls
    # 相似前缀源的每个对象都必须幸存(核心红线)
    for u in sibling_uuids:
        assert u in collection.data.objects, f"sibling object {u} 被误删"
    assert stats["ledger_docs"] == len(ledger)
    assert stats["orphans"] == 1
    assert stats["residue"] == 0


def test_purge_verifies_residue_zero_and_raises_on_leftover():
    """验证段:残留 > 0 必须 raise(调用方转 502,不假报成功)。"""
    from backend.services import source_deletion as sd

    ledger = [(_PREFIX_A + "/doc1", 1)]
    client, collection = _fake_client(
        {_deterministic_uuid(_PREFIX_A + "/doc1", 0): _FakeItem("x", _PREFIX_A + "/doc1")}
    )
    # 模拟「删除不生效」:iterator 永远返回残留
    collection.iterator.side_effect = lambda return_properties=None: iter(
        [_FakeItem("x", _PREFIX_A + "/doc1")]
    )
    with (
        patch.object(sd.weaviate, "connect_to_local", lambda host, port, **k: client),
        pytest.raises(RuntimeError, match="残留"),
    ):
        sd.purge_source_corpus_sync("http://localhost:8080", "Document", _PREFIX_A, ledger)


def test_purge_rejects_partial_delete_many_receipt_even_when_scan_is_empty():
    """A partial/failed batch receipt is not success, even if later iteration is empty."""
    from backend.services import source_deletion as sd

    ledger, objects, _sibling_uuids, _orphan_u = _build_objects()
    client, collection = _fake_client(objects)
    original_delete_many = collection.data.delete_many

    def _partial_receipt(where=None):
        original_delete_many(where)
        return SimpleNamespace(failed=1, matches=5, successful=4)

    collection.data.delete_many = _partial_receipt
    with (
        patch.object(sd.weaviate, "connect_to_local", lambda host, port, **k: client),
        pytest.raises(RuntimeError, match="failed|receipt"),
    ):
        sd.purge_source_corpus_sync("http://localhost:8080", "Document", _PREFIX_A, ledger)


def test_no_text_property_filter_primitive_in_delete_path():
    """静态禁令:Admin 删除路径源码不得再出现 TEXT 属性过滤删除(G2/AC8)。"""
    import inspect

    from backend.services import source_deletion as sd

    src = inspect.getsource(sd.purge_source_corpus_sync)
    for banned in (
        'by_property("source_id").equal',
        "by_property('source_id').equal",
        'by_property("source_id").like',
        "like(",
    ):
        assert banned not in src, f"删除路径出现禁止原语: {banned}"


# --------------------------------------------------------------------------- #
# R2 阻塞③:确定性 UUID 读回(属性扫描的盲区必须由读回关闭)
# --------------------------------------------------------------------------- #


def test_purge_readback_confirms_every_named_uuid_absent():
    """成功 purge 必须按确定性 UUID 逐一读回确认零在场(账本 + 孤儿全覆盖)。"""
    from backend.services import source_deletion as sd

    ledger, objects, sibling_uuids, orphan_u = _build_objects()
    client, collection = _fake_client(objects)

    with patch.object(sd.weaviate, "connect_to_local", lambda host, port, **k: client):
        stats = sd.purge_source_corpus_sync("http://localhost:8080", "Document", _PREFIX_A, ledger)

    own_uuids = {_deterministic_uuid(sid, i) for sid, cc in ledger for i in range(cc)}
    requested: set[str] = set()
    for f in collection.readback_filters:
        requested |= set(re.findall(_UUID_RE, str(f)))
    # 每个被点名删除的 UUID 都必须被读回;读回请求不得夹带兄弟源 UUID
    assert own_uuids <= requested, f"账本 UUID 未全部读回: {own_uuids - requested}"
    assert orphan_u in requested, "孤儿段点删的 UUID 未读回"
    assert requested.isdisjoint(set(sibling_uuids)), "读回请求夹带兄弟源 UUID"
    assert stats["residue"] == 0
    assert stats["readback_confirmed"] == len(own_uuids) + 1


@pytest.mark.parametrize(
    "survivor_properties",
    [{"source_id": "unrelated/doc"}, {"other": "x"}],
    ids=["wrong-source_id", "missing-source_id"],
)
def test_purge_fails_when_named_uuid_survives_with_wrong_metadata(survivor_properties):
    """UUID 在场但 source_id 元数据缺失/错误:属性扫描看不见,读回必须抓住。

    负例前提:说谎后端(delete_many 回执全成功但实物未消失)+ 残留扫描
    盲区(元数据不匹配前缀)→ 旧实现会假报成功;读回段必须 fail-closed。
    """
    from backend.services import source_deletion as sd

    ledger = [(_PREFIX_A + "/doc1", 1)]
    survivor_u = _deterministic_uuid(_PREFIX_A + "/doc1", 0)
    objects = {survivor_u: _FakeItem(survivor_u, properties=survivor_properties)}
    client, collection = _fake_client(objects)

    def _lying_delete_many(where=None):
        # 回执声称全部成功,但实物不消失(元数据错误场景的极端化)
        collection.data.delete_many_filters.append(where)
        return SimpleNamespace(failed=0, matches=1, successful=1)

    collection.data.delete_many = _lying_delete_many
    with (
        patch.object(sd.weaviate, "connect_to_local", lambda host, port, **k: client),
        pytest.raises(RuntimeError, match="读回"),
    ):
        sd.purge_source_corpus_sync("http://localhost:8080", "Document", _PREFIX_A, ledger)
    assert survivor_u in objects, "负例前提被破坏:实物应仍在场"


def test_purge_fails_closed_on_unreadable_readback_response():
    """读回响应结构不可读(objects 非列表)必须失败关闭,不得视为零在场。"""
    from backend.services import source_deletion as sd

    ledger = [(_PREFIX_A + "/doc1", 1)]
    objects = {
        _deterministic_uuid(_PREFIX_A + "/doc1", 0): _FakeItem(
            _deterministic_uuid(_PREFIX_A + "/doc1", 0), _PREFIX_A + "/doc1"
        )
    }
    client, collection = _fake_client(objects)
    collection.query = SimpleNamespace(
        fetch_objects=lambda filters=None, limit=None: SimpleNamespace(objects=None)
    )
    with (
        patch.object(sd.weaviate, "connect_to_local", lambda host, port, **k: client),
        pytest.raises((TypeError, RuntimeError), match="unreadable"),
    ):
        sd.purge_source_corpus_sync("http://localhost:8080", "Document", _PREFIX_A, ledger)


@pytest.mark.integration
def test_real_weaviate_delete_document_local():
    """真实 Weaviate 验证(无本地实例则 skip;与 P0-A 套件同门控)。"""
    import os

    import weaviate

    port = int(os.environ.get("P0A_WEAVIATE_PORT", "21100"))
    try:
        client = weaviate.connect_to_local(host="localhost", port=port)
    except Exception:
        pytest.skip("local Weaviate 1.28 不可达(P0A_WEAVIATE_PORT)")
    try:
        from backend.services import source_deletion as sd

        coll_name = f"DelSafety{uuid_mod.uuid4().hex[:8]}"
        from weaviate.classes.config import Configure, DataType, Property

        client.collections.delete(coll_name)
        coll = client.collections.create(
            name=coll_name,
            vectorizer_config=Configure.Vectorizer.none(),
            properties=[
                Property(name="source_id", data_type=DataType.TEXT),
                Property(name="chunk_index", data_type=DataType.INT),
            ],
        )
        objs = []
        for sid, n in (("src-a/d1", 2), ("src-a-sibling/d1", 2)):
            for i in range(n):
                u = _deterministic_uuid(sid, i)
                objs.append(
                    weaviate.classes.data.DataObject(
                        properties={"source_id": sid, "chunk_index": i},
                        uuid=u,
                        vector=[0.0],
                    )
                )
        coll.data.insert_many(objs)

        ledger = [("src-a/d1", 2)]
        stats = sd.purge_source_corpus_sync("http://localhost:8080", coll_name, "src-a", ledger)
        residue_a = sum(
            1
            for it in coll.iterator(return_properties=["source_id"])
            if str(it.properties.get("source_id", "")).startswith("src-a/")
        )
        residue_sib = sum(
            1
            for it in coll.iterator(return_properties=["source_id"])
            if str(it.properties.get("source_id", "")).startswith("src-a-sibling/")
        )
        assert stats["residue"] == 0 and residue_a == 0
        assert residue_sib == 2, "兄弟源对象必须幸存"
        client.collections.delete(coll_name)
    finally:
        client.close()
