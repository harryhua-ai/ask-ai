"""INC-2a 证据语义确定性分类单元测试。

契约要求(§4/§5/§15):
- 相同持久化输入 → 恒等输出(确定性/可复算);
- 歧义/不可判定 → 显式 unknown(不得推断 stronger class);
- personal-data 永不由规则赋值(内容审查属 INC-2b);
- 溯源码 A/T/S/C ∈ {E,D,U},internal 显式标记 → sensitivity=E。
"""

import itertools

import pytest

from backend.evidence_meta import (
    AUTHORITY_CLASSES,
    CITATION_ELIGIBILITY,
    SENSITIVITY_CLASSES,
    TEMPORALITY_STATES,
    derive_evidence_meta,
)

PUBLIC_TYPES = ["github", "local_git", "website", "web_crawl", "woocommerce"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "source_type,visibility,expected",
    [
        # filesystem = 内部支持案例库:case-example / internal / background-declared
        (
            "filesystem",
            ("widget", "api"),
            ("case-example", "unknown", "internal", "background-declared", "DUDD"),
        ),
        # woocommerce = 官方商城目录(含价格账本):official-pricing / public / citable
        (
            "woocommerce",
            ("widget", "api"),
            ("official-pricing", "unknown", "public", "citable-numbered", "DUDD"),
        ),
        # 公开文档源:权威类不唯一蕴含 → unknown(契约 §5,不推断 stronger class)
        ("github", ("widget", "api"), ("unknown", "unknown", "public", "citable-numbered", "UUDD")),
        (
            "website",
            ("widget", "api"),
            ("unknown", "unknown", "public", "citable-numbered", "UUDD"),
        ),
        (
            "web_crawl",
            ("widget", "api"),
            ("unknown", "unknown", "public", "citable-numbered", "UUDD"),
        ),
        (
            "local_git",
            ("widget", "api"),
            ("unknown", "unknown", "public", "citable-numbered", "UUDD"),
        ),
        # 显式 internal 标记(EXPLICIT):sensitivity 溯源为 E
        (
            "github",
            ("internal",),
            ("unknown", "unknown", "internal", "background-declared", "UUED"),
        ),
        (
            "web_crawl",
            ("internal", "api"),
            ("unknown", "unknown", "internal", "background-declared", "UUED"),
        ),
        # 未知类型:全 unknown(UUUU)
        (
            "future-connector",
            ("widget", "api"),
            ("unknown", "unknown", "unknown", "unknown", "UUUU"),
        ),
        # 缺失 channel_visibility(存量兼容)按公开默认解释
        ("github", None, ("unknown", "unknown", "public", "citable-numbered", "UUDD")),
    ],
)
def test_deterministic_mapping_table(source_type, visibility, expected):
    meta = derive_evidence_meta(source_type, visibility)
    got = (
        meta.authority_class,
        meta.temporality,
        meta.sensitivity,
        meta.citation_eligibility,
        meta.origin,
    )
    assert got == expected


@pytest.mark.unit
def test_same_input_same_output():
    """确定性:相同存储输入恒等输出(含 dataclass 相等与 hash 稳定)。"""
    a = derive_evidence_meta("filesystem", ("widget", "api"))
    b = derive_evidence_meta("filesystem", ("widget", "api"))
    assert a == b and hash(a) == hash(b)


@pytest.mark.unit
def test_vocabulary_membership_all_rules():
    """词表封闭:任意 source_type × visibility 组合的输出都在冻结词表内。"""
    types = [*PUBLIC_TYPES, "filesystem", "future-connector", ""]
    visibilities = [None, (), ("widget", "api"), ("internal",), ("admin",)]
    for st, cv in itertools.product(types, visibilities):
        meta = derive_evidence_meta(st, cv)
        assert meta.authority_class in AUTHORITY_CLASSES
        assert meta.temporality in TEMPORALITY_STATES
        assert meta.sensitivity in SENSITIVITY_CLASSES
        assert meta.citation_eligibility in CITATION_ELIGIBILITY
        assert len(meta.origin) == 4
        assert set(meta.origin) <= {"E", "D", "U"}


@pytest.mark.unit
def test_personal_data_and_user_provided_never_assigned():
    """personal-data/user-provided 只能来自 INC-2b 内容审查/用户提供通道,
    确定性规则永不赋值(契约 §3/§10)。"""
    types = [*PUBLIC_TYPES, "filesystem", "future-connector", ""]
    visibilities = [None, (), ("widget",), ("internal",), ("widget", "internal")]
    for st, cv in itertools.product(types, visibilities):
        meta = derive_evidence_meta(st, cv)
        assert meta.sensitivity not in {"personal-data", "user-provided"}


@pytest.mark.unit
def test_temporality_always_unknown_no_date_fabrication():
    """摄取/同步时间戳不得冒充 source-valid 日期(契约 §3):INC-2a 恒 unknown。"""
    for st in [*PUBLIC_TYPES, "filesystem"]:
        assert derive_evidence_meta(st, None).temporality == "unknown"
        assert derive_evidence_meta(st, ("internal",)).temporality == "unknown"
