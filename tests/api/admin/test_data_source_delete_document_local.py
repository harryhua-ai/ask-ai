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
from unittest.mock import MagicMock, patch

import pytest

from backend.pipeline.ingest import _deterministic_uuid

pytestmark = pytest.mark.unit

_PREFIX_A = "src-a"
_SIBLINGS = ("src-a-sibling", "src-a-xxx", "src-ab")


class _FakeItem:
    def __init__(self, obj_uuid: str, sid: str):
        self.uuid = obj_uuid
        self.properties = {"source_id": sid}


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
        for u in re.findall(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", str(where)
        ):
            self.objects.pop(u, None)

    def delete_by_id(self, obj_uuid: str):
        self.by_id_delete_calls.append(obj_uuid)
        self.objects.pop(obj_uuid, None)


def _fake_client(objects: dict[str, _FakeItem]):
    collection = MagicMock()
    collection.data = _FakeData(objects)

    def iterator(return_properties=None):
        return iter(list(collection.data.objects.values()))

    collection.iterator.side_effect = iterator
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
    with patch.object(sd.weaviate, "connect_to_local", lambda host, port, **k: client):
        with pytest.raises(RuntimeError, match="残留"):
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
