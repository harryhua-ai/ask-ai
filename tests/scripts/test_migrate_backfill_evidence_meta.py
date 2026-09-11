"""INC-2a 回填工具测试:确定性/幂等/dry-run 无 mutation/向量与正文零触碰(契约 §8/A6/A7)。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.evidence_meta import EVIDENCE_PROPERTIES
from backend.pipeline.ingest import _build_props
from scripts.migrate_add_evidence_meta_props import ensure_evidence_props
from scripts.migrate_backfill_evidence_meta import (
    BackfillCounters,
    apply_changes,
    plan_backfill,
    plan_object,
)


def _rec(uuid: str, source_id: str, source_type: str, visibility=None, **evidence):
    rec = {
        "uuid": uuid,
        "source_id": source_id,
        "source_type": source_type,
        "channel_visibility": list(visibility) if visibility else None,
    }
    rec.update(evidence)
    return rec


KNOWN = frozenset({"gh-docs", "kb-support", "store", "site"})

# --------------------------------------------------------------------------- #
# 纯核心:plan_backfill
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_plan_backfill_counters_and_changes():
    records = [
        _rec("u1", "gh-docs/readme", "github"),  # 待写:UUUD
        _rec("u2", "kb-support/case-1", "filesystem"),  # 待写:UUUD
        _rec("u3", "store/p-1", "woocommerce"),  # 待写:UUUD
        _rec(
            "u4",
            "gh-docs/old",
            "github",
            evidence_authority_class="unknown",
            evidence_temporality="unknown",
            evidence_sensitivity="unknown",
            evidence_citation_eligibility="citable-numbered",
            evidence_origin="UUUD",
        ),  # 已正确
        _rec("u5", "ghost/1", "github"),  # 孤儿:只上报
    ]
    counters, changes = plan_backfill(iter(records), KNOWN)
    assert counters.total_inspected == 5
    assert counters.eligible == 4
    assert counters.orphans == 1
    assert counters.changed == 3
    assert counters.unchanged == 1
    assert counters.failures == 0
    assert [u for u, _ in changes] == ["u1", "u2", "u3"]
    # 修订 SAFETY-01:authority 全 unknown;sensitivity 无标记即 unknown;
    # citation 镜像组合语义(PUBLIC → citable;filesystem → background)
    assert changes[0][1]["evidence_sensitivity"] == "unknown"
    assert changes[0][1]["evidence_citation_eligibility"] == "citable-numbered"
    assert changes[1][1]["evidence_authority_class"] == "unknown"
    assert changes[1][1]["evidence_citation_eligibility"] == "background-declared"
    assert changes[2][1]["evidence_authority_class"] == "unknown"
    # 孤儿绝不进写集
    assert all(u != "u5" for u, _ in changes)


@pytest.mark.unit
def test_plan_backfill_idempotent_second_run_zero_changes():
    """首次 apply 后的存储状态再次规划 → changed=0(幂等,契约 A7)。"""
    records = [
        _rec("u1", "gh-docs/readme", "github"),
        _rec("u2", "kb-support/case-1", "filesystem"),
    ]
    counters, changes = plan_backfill(iter(records), KNOWN)
    assert counters.changed == 2
    # 模拟 apply:把目标值写回记录
    for uuid, target in changes:
        for rec in records:
            if rec["uuid"] == uuid:
                rec.update(target)
    counters2, changes2 = plan_backfill(iter(records), KNOWN)
    assert counters2.total_inspected == 2
    assert counters2.changed == 0
    assert counters2.unchanged == 2
    assert changes2 == []


@pytest.mark.unit
def test_plan_backfill_does_not_mutate_input_records():
    """规划纯度:dry-run 核心(规划)不修改任何输入记录。"""
    records = [_rec("u1", "gh-docs/readme", "github")]
    snapshot = dict(records[0])
    plan_backfill(iter(records), KNOWN)
    assert records[0] == snapshot


@pytest.mark.unit
def test_unknown_type_counted_unclassifiable_but_written():
    """未知类型对象:显式 unknown 仍写入(不静默留下空值),计数单独上报。"""
    records = [_rec("u1", "gh-docs/x", "mystery-connector")]
    counters, changes = plan_backfill(iter(records), KNOWN)
    # 修订后:authority+sensitivity 双 unknown ⇒ 不可分类计数;
    # citation 镜像组合语义(非 PUBLIC → background-declared)恒有值
    assert counters.unknown_unclassifiable == 1
    assert counters.changed == 1
    assert changes[0][1]["evidence_authority_class"] == "unknown"
    assert changes[0][1]["evidence_sensitivity"] == "unknown"
    assert changes[0][1]["evidence_citation_eligibility"] == "background-declared"
    assert changes[0][1]["evidence_origin"] == "UUUD"


@pytest.mark.unit
def test_plan_zero_drift_with_ingestion_path():
    """零漂移:回填规划与摄取 _build_props 同输入同输出(契约 §6 双写路径)。"""
    from backend.connectors.base import RawDocument

    doc = RawDocument(
        source_id="kb-support/case-1",
        source_type="filesystem",
        product="knowledge",
        title="c",
        content="x",
        url="",
        metadata={},
        content_hash="h",
        channel_visibility=("widget", "api"),
    )
    chunk = type(
        "C",
        (),
        {
            "text": "x",
            "chunk_index": 0,
            "doc_section": "",
            "chunk_type": "",
            "channel_visibility": ("widget", "api"),
            "product": "knowledge",
            "symbol_name": "",
            "symbol_signature": "",
            "symbol_node_type": "",
            "symbol_tokens": "",
        },
    )()
    from_ingest = {k: v for k, v in _build_props(chunk, doc).items() if k in EVIDENCE_PROPERTIES}
    from_backfill = plan_object(
        {
            "source_id": doc.source_id,
            "source_type": doc.source_type,
            "product": doc.product,
            "channel_visibility": list(doc.channel_visibility),
        }
    )
    assert from_ingest == from_backfill


# --------------------------------------------------------------------------- #
# apply_changes:有界写(只 evidence_*,无 text/vector)
# --------------------------------------------------------------------------- #


class _FakeCollection:
    def __init__(self):
        self.updates = []

    class data:  # noqa: N801 - 模拟 weaviate 命名
        @staticmethod
        def update(uuid, properties):
            pass


def test_apply_changes_writes_only_evidence_properties():
    """写集有界:只含 5 个 evidence 属性;不触碰 text,不传 vector(契约 §8)。"""
    calls: list[dict] = []

    class _Data:
        @staticmethod
        def update(uuid, properties):
            calls.append({"uuid": uuid, "properties": properties})

    class _Col:
        data = _Data

    counters = BackfillCounters()
    changes = [
        (
            "u1",
            {
                "evidence_authority_class": "unknown",
                "evidence_temporality": "unknown",
                "evidence_sensitivity": "public",
                "evidence_citation_eligibility": "citable-numbered",
                "evidence_origin": "UUDD",
            },
        ),
        ("u2", {k: "unknown" for k in EVIDENCE_PROPERTIES} | {"evidence_origin": "UUUU"}),
    ]
    written = apply_changes(_Col(), changes, counters, progress_every=0)
    assert written == 2 and counters.failures == 0
    for call in calls:
        assert set(call["properties"]) == set(EVIDENCE_PROPERTIES)
        assert "text" not in call["properties"]
        assert "vector" not in call["properties"]


def test_apply_changes_counts_failures_without_raising():
    """单对象写失败计数不中断(重启安全:重跑幂等补齐)。"""

    class _Data:
        calls = 0

        @staticmethod
        def update(uuid, properties):
            if uuid == "u-bad":
                raise RuntimeError("boom")

    class _Col:
        data = _Data

    counters = BackfillCounters()
    changes = [
        ("u-bad", dict.fromkeys(EVIDENCE_PROPERTIES, "unknown")),
        ("u-ok", dict.fromkeys(EVIDENCE_PROPERTIES, "unknown")),
    ]
    written = apply_changes(_Col(), changes, counters, progress_every=0)
    assert written == 1
    assert counters.failures == 1


# --------------------------------------------------------------------------- #
# schema 增量:ensure_evidence_props 幂等
# --------------------------------------------------------------------------- #


def test_ensure_evidence_props_idempotent():
    added1 = ensure_evidence_props(_FakeConfigCol(existing=set()))
    added2 = ensure_evidence_props(_FakeConfigCol(existing=set(added1)))
    assert sorted(added1) == sorted(EVIDENCE_PROPERTIES)
    assert added2 == []


class _FakeConfigHandle:
    def __init__(self, col):
        self._col = col

    def get(self):
        class _Cfg:
            properties = [type("P", (), {"name": n})() for n in self._col._existing]

        return _Cfg()

    def add_property(self, prop):
        self._col._existing.add(prop.name)
        self._col.added.append(prop.name)


class _FakeConfigCol:
    """模拟 collection.config(记录 add_property;get 反映已加集合)。"""

    def __init__(self, existing: set):
        self._existing = set(existing)
        self.added: list[str] = []

    @property
    def config(self):
        return _FakeConfigHandle(self)
