"""证据语义元数据(INC-2a 冻结契约:Evidence Metadata Schema + Deterministic Backfill)。

为知识 chunk 建立机器可读的证据语义(authority / temporality / sensitivity /
citation eligibility),供后续 S5 证据选择与 S6 信任边界使用。本模块只做
**确定性元数据分类**,不做任何内容脱敏(INC-2b 域),也不在运行期参与任何
检索/排序/组合决策(行为冻结于 INC-2a §11)。

冻结词表(目标架构 §6 + INC-2a 契约 §3):

- authority_class: authoritative-doc / official-pricing / case-example /
  community / marketing / unknown
- temporality: current / historical-as-of / undated / unknown
- sensitivity: public / internal / personal-data / user-provided / unknown
- citation_eligibility: citable-numbered / background-declared / context-only /
  unknown

分类只允许使用**已持久化的结构事实**(契约 §4):chunk 自身的
``source_type`` 与 ``channel_visibility``。禁止 LLM 分类、正文审查、
源内容/git/sitemap 抓取、日期编造。无法安全判定的维度一律显式
``unknown``——不确证的 stronger class 不得推断(契约 §5)。

溯源(契约 §7):``evidence_origin`` 为 4 字符定长码,固定位置依序
A/T/S/C(authority/temporality/sensitivity/citation eligibility),字符
``E``=EXPLICIT(来自源显式配置标记)、``D``=DERIVED(确定性系统映射)、
``U``=UNKNOWN(安全默认)。bounded、可解释、无逐 chunk 长解释。

设计不变量:摄取路径(``_build_props``)与回填工具使用**同一个纯函数**
``derive_evidence_meta``,输入同为对象自身持久化的 ``source_type`` 与
``channel_visibility``——两条写路径构造上不可能漂移,亦无运行期 DB join
(契约 §6.6 / §14)。
"""

from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# 冻结词表(显式 unknown 安全域)
# --------------------------------------------------------------------------- #

AUTHORITY_CLASSES = frozenset(
    {"authoritative-doc", "official-pricing", "case-example", "community", "marketing", "unknown"}
)
TEMPORALITY_STATES = frozenset({"current", "historical-as-of", "undated", "unknown"})
SENSITIVITY_CLASSES = frozenset({"public", "internal", "personal-data", "user-provided", "unknown"})
CITATION_ELIGIBILITY = frozenset(
    {"citable-numbered", "background-declared", "context-only", "unknown"}
)

AUTHORITY_UNKNOWN = "unknown"
TEMPORALITY_UNKNOWN = "unknown"
SENSITIVITY_UNKNOWN = "unknown"
CITATION_UNKNOWN = "unknown"

# Weaviate property 名(与检索投影/回填工具共用,防字符串漂移)
PROP_AUTHORITY = "evidence_authority_class"
PROP_TEMPORALITY = "evidence_temporality"
PROP_SENSITIVITY = "evidence_sensitivity"
PROP_CITATION = "evidence_citation_eligibility"
PROP_ORIGIN = "evidence_origin"
EVIDENCE_PROPERTIES: tuple[str, ...] = (
    PROP_AUTHORITY,
    PROP_TEMPORALITY,
    PROP_SENSITIVITY,
    PROP_CITATION,
    PROP_ORIGIN,
)

# 溯源字符(位置固定:A/T/S/C)
ORIGIN_EXPLICIT = "E"
ORIGIN_DERIVED = "D"
ORIGIN_UNKNOWN = "U"

# "internal" 是既有显式源配置标记惯例:migrate_channel_visibility 契约中
# 管理员以 channel_visibility: ["internal"] 标记内部源;该值永不匹配
# widget/api 探测渠道(检索期整源排除),此处读作 sensitivity=internal 的
# EXPLICIT 依据。
_INTERNAL_MARKER = "internal"


@dataclass(frozen=True)
class EvidenceMeta:
    """单 chunk 证据语义(不可变)。

    Attributes:
        authority_class: 权威类别(冻结词表)。
        temporality: 时效态(current / historical-as-of / undated / unknown);
            INC-2a 恒为 unknown——摄取时间戳不是 source-valid 日期(契约 §3)。
        sensitivity: 敏感度(public / internal / …);personal-data 只能由
            INC-2b 内容审查产生,本映射永不赋值。
        citation_eligibility: 引用资格语义(表达未来阶段的资格,不改当前行为)。
        origin: 4 字符溯源码(A/T/S/C ∈ {E,D,U})。
    """

    authority_class: str = AUTHORITY_UNKNOWN
    temporality: str = TEMPORALITY_UNKNOWN
    sensitivity: str = SENSITIVITY_UNKNOWN
    citation_eligibility: str = CITATION_UNKNOWN
    origin: str = "UUUU"


def _origin_code(a: str, t: str, s: str, c: str) -> str:
    return f"{a}{t}{s}{c}"


def derive_evidence_meta(
    source_type: str,
    channel_visibility: "tuple[str, ...] | list[str] | None" = None,
) -> EvidenceMeta:
    """从 chunk 自身持久化结构事实确定性推导证据语义。

    Args:
        source_type: chunk 的 ``source_type`` property(连接器类型)。
        channel_visibility: chunk 的 ``channel_visibility`` property
            (Weaviate 读回 list / 内存 tuple;None/缺失按公开默认解释,
            与 ``_to_search_result`` 既有兼容语义一致)。

    Returns:
        :class:`EvidenceMeta`。相同输入恒等输出(确定性、可复算、可测试)。

    规则(全部源自既有系统语义,逐条可解释):

    - authority:``filesystem`` → case-example(本系统 filesystem 源即内部
      支持案例库,架构 case-example 类);``woocommerce`` → official-pricing
      (本系统 woocommerce 源即官方商城目录,含价格账本);其余一律 unknown
      ——github/website 等不唯一蕴含单一权威类(契约 §5 明示),不推断
      stronger class。
    - sensitivity:源显式 ``internal`` 标记 → internal(EXPLICIT);
      ``filesystem`` → internal(DERIVED,既有背景通道语义);公开源类型
      → public(DERIVED,既有展示白名单语义);否则 unknown。``personal-data``
      永不由本映射赋值(内容审查属 INC-2b)。
    - citation_eligibility:internal 标记或 filesystem → background-declared
      (与既有背景通道一致);公开源类型(且非内部)→ citable-numbered
      (与既有组合白名单一致);否则 unknown。只表达语义,**不改当前引用行为**
      (契约 §3/§11)。
    - temporality:恒 unknown——无任何持久化 source-valid 日期;摄取/同步
      时间戳不得冒充(契约 §3/§9)。
    """
    visibility = tuple(channel_visibility) if isinstance(channel_visibility, (list, tuple)) else ()
    internal_marker = _INTERNAL_MARKER in visibility

    # 展示白名单是组合期既有语义的唯一权威定义点(citation.py)
    from backend.pipeline.citation import PUBLIC_SOURCE_TYPES

    is_public_type = source_type in PUBLIC_SOURCE_TYPES

    # authority
    if source_type == "filesystem":
        authority, auth_origin = "case-example", ORIGIN_DERIVED
    elif source_type == "woocommerce":
        authority, auth_origin = "official-pricing", ORIGIN_DERIVED
    else:
        authority, auth_origin = AUTHORITY_UNKNOWN, ORIGIN_UNKNOWN

    # sensitivity
    if internal_marker:
        sensitivity, sens_origin = "internal", ORIGIN_EXPLICIT
    elif source_type == "filesystem":
        sensitivity, sens_origin = "internal", ORIGIN_DERIVED
    elif is_public_type:
        sensitivity, sens_origin = "public", ORIGIN_DERIVED
    else:
        sensitivity, sens_origin = SENSITIVITY_UNKNOWN, ORIGIN_UNKNOWN

    # citation eligibility(语义表达;不改任何现行行为)
    if internal_marker or source_type == "filesystem":
        citation, cite_origin = "background-declared", ORIGIN_DERIVED
    elif is_public_type:
        citation, cite_origin = "citable-numbered", ORIGIN_DERIVED
    else:
        citation, cite_origin = CITATION_UNKNOWN, ORIGIN_UNKNOWN

    # temporality:INC-2a 恒 unknown(契约 §9 SOURCE_DATA_REQUIRED 不物化)
    temporality, temp_origin = TEMPORALITY_UNKNOWN, ORIGIN_UNKNOWN

    return EvidenceMeta(
        authority_class=authority,
        temporality=temporality,
        sensitivity=sensitivity,
        citation_eligibility=citation,
        origin=_origin_code(auth_origin, temp_origin, sens_origin, cite_origin),
    )
