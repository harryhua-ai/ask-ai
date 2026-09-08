"""主张—证据验证 v1(INC-6:Claim–Evidence Validation)。

把既有确定性引用强制层(剔标记,不改正文)升级为**诚实的结果分类层**:
每个引用标记的 claim-window 得到显式四态真值 + 有界 reason code,并把引用
确定性归因到 INC-5 实际达生成的证据角色(角色集,不择一)。

冻结结果模型(契约 §4):

- ``SUPPORTED``     该标记的全部可判定检查通过(语法/来源资格/上下文成员/
  产品域/数值必要条件)。**仅确定性支持**——不蕴含语义成立、权威正确、
  时效正确或整体事实正确。
- ``UNSUPPORTED``   既有确定性强制规则拒绝(dangling / 数值无据 / 产品不合格)。
  行为保持:剔标记、保留主张文本。
- ``UNVALIDATABLE`` 存在真实主张窗口,但当前确定性体系没有可成立的必要条件
  检验(如窗口无显著数值,或该编号无源文本可校验)。**不得计为 SUPPORTED**。
- ``NOT_APPLICABLE`` 无主张可验证(空/纯空白窗口;背景语义;非 RAG 载荷)。
  **不得计入/聚合为 SUPPORTED / VALIDATED**;v1 不改变空窗标记的既有可见行为。

角色归因(契约 §2/§3,全部来自既有运行期对象,零 INC-5 改动):

    citation_no → stats.citable 全部稳定身份 → 与 INC-5 slots[].matched 求交
    → 完整角色集(single_role / multi_role / unattributed)

- citation_no 是**源级**编号:一个编号可对应多身份,全部保留,不择一;
- 一个身份可命中多角色(方案块={SOLUTION_GUIDE, PRODUCT_SPEC};
  Store 块={STORE_OFFICIAL, PRODUCT_SPEC}),完整返回,不坍缩;
- 未命中任何槽位=空角色集(unattributed)——合法状态,绝不伪造;
- 背景(filesystem)证据永不进入 citable,不产生编号归因。

流式边界(契约 §7):分类发生在既有标记解析时点(数据生成前已完备),
零缓冲;需要标记之后文本或整段语义的规则不在 v1。

本模块零 LLM、零 IO,全部纯函数。
"""

from backend.pipeline.evidence_selection import CoverageReport

# --------------------------------------------------------------------------- #
# 冻结词表(结果 / reason / 归因形态)
# --------------------------------------------------------------------------- #

OUTCOME_SUPPORTED = "SUPPORTED"
OUTCOME_UNSUPPORTED = "UNSUPPORTED"
OUTCOME_UNVALIDATABLE = "UNVALIDATABLE"
OUTCOME_NOT_APPLICABLE = "NOT_APPLICABLE"
VALIDATION_OUTCOMES = (
    OUTCOME_SUPPORTED,
    OUTCOME_UNSUPPORTED,
    OUTCOME_UNVALIDATABLE,
    OUTCOME_NOT_APPLICABLE,
)

REASON_ALL_CHECKS_PASSED = "all_checks_passed"
REASON_DANGLING_MARKER = "dangling_marker"
REASON_NUMERIC_UNSUPPORTED = "numeric_unsupported"
REASON_PRODUCT_INELIGIBLE = "product_ineligible"
REASON_NO_DETERMINISTIC_NECESSARY_CONDITION = "no_deterministic_necessary_condition"
REASON_VACUOUS_WINDOW = "vacuous_window"
# 以下两项为载荷级分类(无标记事件的自然场景):纯背景语义 / 非 RAG 载荷
# (smalltalk、override、拒答)。v1 中由文档语义承载,暂无事件生产点。
REASON_BACKGROUND_ONLY = "background_only"
REASON_NON_RAG_PAYLOAD = "non_rag_payload"

ATTRIBUTION_SINGLE_ROLE = "single_role"
ATTRIBUTION_MULTI_ROLE = "multi_role"
ATTRIBUTION_UNATTRIBUTED = "unattributed"

# --------------------------------------------------------------------------- #
# 角色归因(citation_no → 身份集 → 完整角色集)
# --------------------------------------------------------------------------- #


def build_role_attribution(citable_entries, coverage: CoverageReport | None = None) -> dict:
    """把终局可引用身份按 citation_no 聚合,并与 INC-5 槽位匹配求交得角色集。

    Args:
        citable_entries: ``cite_ctx.stats["citable"]`` ——
            ``[{source_id, chunk_index, citation_no}, ...]``。
        coverage: INC-5 :class:`CoverageReport`(``None`` = 无证据计划,
            全部身份 unattributed,不伪造角色)。

    Returns:
        ``{"<citation_no>": {"identities": [{source_id, chunk_index}...],
        "identities_truncated": bool, "roles": [role...],
        "attribution": single_role|multi_role|unattributed}}``。
        键为**字符串**编号(answer/stream 双路径 JSON 语义稳定);有界:
        身份 ≤8/编号(超出以 truncated 标记);角色集去重排序。
    """
    identity_roles: dict[tuple, set] = {}
    if coverage is not None:
        for slot in coverage.slots:
            for key in slot.matched:
                identity_roles.setdefault(key, set()).add(slot.role)

    attr: dict = {}
    for entry in citable_entries or ():
        no = str(entry.get("citation_no"))
        key = (entry.get("source_id"), entry.get("chunk_index"))
        info = attr.setdefault(
            no, {"identities": [], "roles": set(), "identities_truncated": False}
        )
        if len(info["identities"]) < 8:
            info["identities"].append({"source_id": key[0], "chunk_index": key[1]})
        else:
            info["identities_truncated"] = True
        info["roles"].update(identity_roles.get(key, ()))

    out: dict = {}
    for no, info in attr.items():
        roles = sorted(info["roles"])
        if not roles:
            attribution = ATTRIBUTION_UNATTRIBUTED
        elif len(roles) == 1:
            attribution = ATTRIBUTION_SINGLE_ROLE
        else:
            attribution = ATTRIBUTION_MULTI_ROLE
        out[no] = {
            "identities": info["identities"],
            "identities_truncated": info["identities_truncated"],
            "roles": roles,
            "attribution": attribution,
        }
    return out


# --------------------------------------------------------------------------- #
# trace 装配(有界:计数 + 事件 ≤32 + 归因;零 chunk 正文)
# --------------------------------------------------------------------------- #


def build_claim_validation(
    validation_stats: dict,
    citable_entries,
    coverage: CoverageReport | None = None,
) -> dict:
    """从流式/终验过滤器的 stats 与 INC-5 覆盖装配 ``claim_validation`` 阶段。

    Args:
        validation_stats: ``CitationStreamFilter.stats`` / ``validate_citations``
            的 stats(含既有计数器 + ``outcome_counts`` + ``validation_events``)。
        citable_entries / coverage: 同 :func:`build_role_attribution`。

    不变量:``outcome_counts["UNSUPPORTED"]`` 恒等于 dangling + numeric +
    product 三类剔除之和;N/A 与 UNVALIDATABLE 不出现在 SUPPORTED 中。
    """
    return {
        "outcome_counts": dict(validation_stats.get("outcome_counts") or {}),
        "validation_events": list(validation_stats.get("validation_events") or ()),
        "role_attribution": build_role_attribution(citable_entries, coverage),
    }
