"""INC-2a 证据语义确定性分类单元测试(修订 INC-2A-CLASSIFICATION-SAFETY-01 后)。

契约要求(§4/§5/§15 + 修订令 10 项):
- 相同持久化输入 → 恒等输出(确定性/可复算);
- 歧义/不可判定 → 显式 unknown(不得推断 stronger class);
- sensitivity 唯一判定 = 显式 internal 标记(EXPLICIT);缺失标记绝不推出 public;
- filesystem 不得仅凭 source_type 成为 case-example;authority 歧义恒 unknown;
- citation eligibility 严格镜像组合语义且独立于 sensitivity;
- personal-data 永不由规则赋值(内容审查属 INC-2b)。
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
        # 修订后:authority 全量 unknown;sensitivity 仅显式 internal 标记;
        # citation 严格镜像组合语义(PUBLIC 白名单 → citable;其余 → background)
        (
            "filesystem",
            ("widget", "api"),
            ("unknown", "unknown", "unknown", "background-declared", "UUUD"),
        ),
        (
            "woocommerce",
            ("widget", "api"),
            ("unknown", "unknown", "unknown", "citable-numbered", "UUUD"),
        ),
        (
            "github",
            ("widget", "api"),
            ("unknown", "unknown", "unknown", "citable-numbered", "UUUD"),
        ),
        (
            "website",
            ("widget", "api"),
            ("unknown", "unknown", "unknown", "citable-numbered", "UUUD"),
        ),
        (
            "web_crawl",
            ("widget", "api"),
            ("unknown", "unknown", "unknown", "citable-numbered", "UUUD"),
        ),
        (
            "local_git",
            ("widget", "api"),
            ("unknown", "unknown", "unknown", "citable-numbered", "UUUD"),
        ),
        # 显式 internal 标记:唯一 sensitivity 判定(EXPLICIT,溯源 s 位=E);
        # citation 仍按 source_type 镜像(与 sensitivity 独立)
        ("github", ("internal",), ("unknown", "unknown", "internal", "citable-numbered", "UUED")),
        (
            "web_crawl",
            ("internal", "api"),
            ("unknown", "unknown", "internal", "citable-numbered", "UUED"),
        ),
        (
            "filesystem",
            ("internal",),
            ("unknown", "unknown", "internal", "background-declared", "UUED"),
        ),
        # 未知类型:authority/sensitivity unknown;citation 镜像组合(非 PUBLIC → background)
        (
            "future-connector",
            ("widget", "api"),
            ("unknown", "unknown", "unknown", "background-declared", "UUUD"),
        ),
        # 缺失 channel_visibility(存量兼容)按公开默认解释,不产生 sensitivity
        ("github", None, ("unknown", "unknown", "unknown", "citable-numbered", "UUUD")),
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


# --------------------------------------------------------------------------- #
# 修订令要求的逐项证明
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.parametrize("source_type", ["github", "website", "web_crawl", "local_git"])
def test_amendment_1_2_public_types_without_marker_sensitivity_unknown(source_type):
    """修订令 1/2:公开文档类型无 internal 标记 → sensitivity=unknown(非 public)。"""
    meta = derive_evidence_meta(source_type, ("widget", "api"))
    assert meta.sensitivity == "unknown"
    assert meta.origin[2] == "U"


@pytest.mark.unit
def test_amendment_3_explicit_internal_marker_is_internal_explicit():
    """修订令 3:显式 internal 标记 → internal,溯源 EXPLICIT。"""
    meta = derive_evidence_meta("github", ("internal",))
    assert meta.sensitivity == "internal"
    assert meta.origin[2] == "E"


@pytest.mark.unit
@pytest.mark.parametrize("source_type", [*PUBLIC_TYPES, "filesystem", "future-connector", ""])
@pytest.mark.parametrize("visibility", [None, (), ("widget", "api"), ("admin",)])
def test_amendment_4_absence_of_marker_never_produces_public(source_type, visibility):
    """修订令 4:internal 标记缺省本身永不产生 public(全类型 × 全缺省形态)。"""
    meta = derive_evidence_meta(source_type, visibility)
    assert meta.sensitivity != "public"
    if "internal" not in (visibility or ()):
        assert meta.sensitivity == "unknown"


@pytest.mark.unit
def test_amendment_5_filesystem_not_case_example_from_source_type_alone():
    """修订令 5:filesystem 仅凭 source_type 不得成为 case-example。"""
    meta = derive_evidence_meta("filesystem", ("widget", "api"))
    assert meta.authority_class == "unknown"
    assert meta.origin[0] == "U"
    # 既有组合语义保留在 citation 维度:非 PUBLIC → background-declared
    assert meta.citation_eligibility == "background-declared"


@pytest.mark.unit
@pytest.mark.parametrize("source_type", [*PUBLIC_TYPES, "filesystem", "future-connector"])
def test_amendment_6_ambiguous_authority_remains_unknown(source_type):
    """修订令 6:无正面事实的 authority 恒 unknown(woocommerce 同撤)。"""
    for visibility in (None, ("widget", "api"), ("internal",)):
        assert derive_evidence_meta(source_type, visibility).authority_class == "unknown"


@pytest.mark.unit
def test_amendment_7_citation_independent_from_sensitivity():
    """修订令 7:citation 只随 source_type 镜像组合语义,不随 sensitivity 变。"""
    plain = derive_evidence_meta("github", ("widget", "api"))
    marked = derive_evidence_meta("github", ("internal",))
    assert plain.sensitivity != marked.sensitivity
    assert plain.citation_eligibility == marked.citation_eligibility == "citable-numbered"
    fs_plain = derive_evidence_meta("filesystem", ("widget", "api"))
    fs_marked = derive_evidence_meta("filesystem", ("internal",))
    assert fs_plain.sensitivity != fs_marked.sensitivity
    assert fs_plain.citation_eligibility == fs_marked.citation_eligibility == "background-declared"


@pytest.mark.unit
def test_determinism_same_input_same_output():
    """修订令 8:确定性——相同存储输入恒等输出。"""
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
        assert derive_evidence_meta(st, cv).sensitivity not in {"personal-data", "user-provided"}


@pytest.mark.unit
def test_temporality_always_unknown_no_date_fabrication():
    """摄取/同步时间戳不得冒充 source-valid 日期(契约 §3):INC-2a 恒 unknown。"""
    for st in [*PUBLIC_TYPES, "filesystem"]:
        assert derive_evidence_meta(st, None).temporality == "unknown"
        assert derive_evidence_meta(st, ("internal",)).temporality == "unknown"
