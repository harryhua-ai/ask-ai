"""lead_qualify 纯逻辑单元测试。

覆盖:LLM 输出解析(fail-open)、邀请决策矩阵(LEAD-G001/G002/G005 与
One-Proactive-Ask)、状态推进(只升不降/handed_off 终态)、联系方式
确定性检测与脱敏、明确销售请求短语。
"""

import uuid

from backend.pipeline.lead_qualify import (
    LEAD_ACK_INSTRUCTION,
    LEAD_INVITE_INSTRUCTION,
    LEAD_NONE,
    LEAD_POTENTIAL,
    LEAD_QUALIFIED,
    LEAD_STATUS_CONTACT_CAPTURED,
    LEAD_STATUS_HANDED_OFF,
    LEAD_STATUS_POTENTIAL,
    LEAD_STATUS_QUALIFIED,
    LeadFields,
    LeadQualification,
    build_qualification_prompt,
    compute_status,
    decide_invite,
    detect_contact,
    explicit_sales_hint,
    mask_contact_value,
    parse_qualification,
)

# --------------------------------------------------------------------------- #
# parse_qualification
# --------------------------------------------------------------------------- #


def test_parse_valid_json() -> None:
    out = parse_qualification(
        '{"lead_level": "qualified", "explicit_sales_request": false,'
        ' "stronger_signal": true, "fields": {"company": "Acme", "quantity": "500 units"},'
        ' "summary": "Acme 要 500 台"}'
    )
    assert out.level == LEAD_QUALIFIED
    assert out.stronger_signal is True
    assert out.ran is True
    assert out.fields.company == "Acme"
    assert out.fields.quantity == "500 units"
    assert out.summary == "Acme 要 500 台"


def test_parse_fenced_json() -> None:
    out = parse_qualification('```json\n{"lead_level": "potential"}\n```')
    assert out.level == LEAD_POTENTIAL
    assert out.ran is True


def test_parse_invalid_json_fails_open() -> None:
    out = parse_qualification("抱歉,我无法输出 JSON")
    assert out.level == LEAD_NONE
    assert out.ran is False


def test_parse_invalid_level_fails_to_none() -> None:
    out = parse_qualification('{"lead_level": "hot"}')
    assert out.level == LEAD_NONE
    assert out.ran is True


def test_parse_truncates_long_fields() -> None:
    out = parse_qualification(
        '{"lead_level": "potential", "fields": {"use_case": "' + "长" * 600 + '"}}'
    )
    assert len(out.fields.use_case) == 500


def test_parse_non_string_fields_ignored() -> None:
    out = parse_qualification('{"lead_level": "potential", "fields": {"company": 123}}')
    assert out.fields.company == ""


# --------------------------------------------------------------------------- #
# decide_invite(One-Proactive-Ask)
# --------------------------------------------------------------------------- #


def _qual(level=LEAD_NONE, **kw) -> LeadQualification:
    return LeadQualification(level=level, ran=True, **kw)


def test_invite_no_invite_for_price_inquiry() -> None:
    """LEAD-G001:普通产品/价格咨询(potential)不邀请。"""
    assert decide_invite(_qual(LEAD_POTENTIAL), prompt_count=0, contact_present=False) is False


def test_invite_qualified_first_time() -> None:
    """LEAD-G002/G003:首次 qualified 邀请一次。"""
    assert decide_invite(_qual(LEAD_QUALIFIED), prompt_count=0, contact_present=False) is True


def test_invite_qualified_second_time_needs_stronger_signal() -> None:
    """已邀请过、无更强信号:不再邀请(G005 不重复骚扰)。"""
    assert decide_invite(_qual(LEAD_QUALIFIED), prompt_count=1, contact_present=False) is False
    assert (
        decide_invite(
            _qual(LEAD_QUALIFIED, stronger_signal=True), prompt_count=1, contact_present=False
        )
        is True
    )


def test_invite_capped_at_two_proactive_asks() -> None:
    assert (
        decide_invite(
            _qual(LEAD_QUALIFIED, stronger_signal=True), prompt_count=2, contact_present=False
        )
        is False
    )


def test_invite_never_when_contact_present() -> None:
    assert (
        decide_invite(
            _qual(LEAD_QUALIFIED, explicit_sales_request=True), prompt_count=0, contact_present=True
        )
        is False
    )


def test_invite_explicit_sales_request_overrides_everything() -> None:
    """用户明确要求销售联系:即使已邀请过也允许回应。"""
    assert (
        decide_invite(
            _qual(LEAD_NONE, explicit_sales_request=True), prompt_count=2, contact_present=False
        )
        is True
    )


def test_invite_deterministic_hint_counts_as_explicit() -> None:
    assert (
        decide_invite(_qual(LEAD_NONE), prompt_count=0, contact_present=False, explicit_hint=True)
        is True
    )


# --------------------------------------------------------------------------- #
# compute_status
# --------------------------------------------------------------------------- #


def test_status_none_level_keeps_existing() -> None:
    assert compute_status(LEAD_STATUS_QUALIFIED, _qual(LEAD_NONE), contact_now=False) == (
        LEAD_STATUS_QUALIFIED
    )


def test_status_upgrade_potential_to_qualified() -> None:
    assert compute_status(LEAD_STATUS_POTENTIAL, _qual(LEAD_QUALIFIED), contact_now=False) == (
        LEAD_STATUS_QUALIFIED
    )


def test_status_contact_now_upgrades() -> None:
    assert compute_status(LEAD_STATUS_POTENTIAL, _qual(LEAD_NONE), contact_now=True) == (
        LEAD_STATUS_CONTACT_CAPTURED
    )


def test_status_never_downgrades_from_contact_captured() -> None:
    assert (
        compute_status(LEAD_STATUS_CONTACT_CAPTURED, _qual(LEAD_NONE), contact_now=False)
        == LEAD_STATUS_CONTACT_CAPTURED
    )


def test_status_handed_off_is_terminal() -> None:
    assert (
        compute_status(LEAD_STATUS_HANDED_OFF, _qual(LEAD_QUALIFIED), contact_now=True)
        == LEAD_STATUS_HANDED_OFF
    )


def test_status_first_creation_potential_floor() -> None:
    assert compute_status(None, _qual(LEAD_NONE), contact_now=False) == LEAD_STATUS_POTENTIAL


# --------------------------------------------------------------------------- #
# detect_contact / mask_contact_value(LEAD-G004)
# --------------------------------------------------------------------------- #


def test_detect_email() -> None:
    hit = detect_contact("请发报价到我邮箱 john@example.com 谢谢")
    assert hit is not None and hit.type == "email"
    assert hit.value == "john@example.com"
    assert "@" in hit.masked and "john@example.com" not in hit.masked


def test_detect_bare_email_only() -> None:
    """LEAD-G004:只给一个邮箱也要能 capture。"""
    hit = detect_contact("john@example.com")
    assert hit is not None and hit.type == "email"


def test_detect_cn_mobile() -> None:
    hit = detect_contact("我的手机号 13812345678")
    assert hit is not None and hit.type == "phone"
    assert hit.value == "13812345678"


def test_detect_international_phone() -> None:
    hit = detect_contact("call me at +44 20 7946 0958")
    assert hit is not None and hit.type == "phone"
    assert hit.value == "+44 20 7946 0958"


def test_detect_landline_with_keyword() -> None:
    hit = detect_contact("联系电话 0755-8666-9158")
    assert hit is not None and hit.type == "phone"


def test_date_is_not_phone() -> None:
    assert detect_contact("项目启动日期是 2026-09-02") is None


def test_detect_wechat_id() -> None:
    hit = detect_contact("加我微信: harry_lead01")
    assert hit is not None and hit.type == "wechat"
    assert hit.value == "harry_lead01"


def test_detect_whatsapp_keyword() -> None:
    hit = detect_contact("my whatsapp is +86 138 1234 5678")
    assert hit is not None and hit.type == "whatsapp"


def test_detect_none() -> None:
    assert detect_contact("NE503 有什么接口?") is None
    assert detect_contact("") is None


def test_mask_contact_value_email() -> None:
    assert mask_contact_value("john@example.com") == "j***@example.com"


def test_mask_contact_value_phone() -> None:
    masked = mask_contact_value("13812345678")
    assert masked.startswith("138") and masked.endswith("78") and "1234" not in masked


# --------------------------------------------------------------------------- #
# explicit_sales_hint
# --------------------------------------------------------------------------- #


def test_hint_zh() -> None:
    assert explicit_sales_hint("请让销售人员联系我") is True
    assert explicit_sales_hint("我需要正式报价") is True
    assert explicit_sales_hint("转人工") is True


def test_hint_en() -> None:
    assert explicit_sales_hint("Please have your sales team contact me") is True
    assert explicit_sales_hint("I'd like to request a quotation") is True


def test_hint_negative() -> None:
    assert explicit_sales_hint("NE503 有什么接口?") is False
    assert explicit_sales_hint("NE503 多少钱?") is False
    assert explicit_sales_hint("what is the price of NE301?") is False


# --------------------------------------------------------------------------- #
# prompt 构造与内嵌指令
# --------------------------------------------------------------------------- #


def test_build_qualification_prompt_contains_rules_and_context() -> None:
    msgs = build_qualification_prompt(
        "我们要做一个项目,需要 500 台,请报价",
        [{"role": "user", "content": "NE503 多少钱"}, {"role": "assistant", "content": "价格是…"}],
        {"company": "Acme"},
    )
    assert msgs[0]["role"] == "system"
    body = msgs[1]["content"]
    assert "500 台" in body
    assert "NE503 多少钱" in body
    assert "Acme" in body


def test_embedded_instructions_do_not_promise_sales_contact() -> None:
    """契约 §8:两条内嵌指令都不得包含可被模型借用的承诺语义。"""
    for instr in (LEAD_INVITE_INSTRUCTION, LEAD_ACK_INSTRUCTION):
        assert "不要承诺" in instr or "绝对不要承诺" in instr


def test_lead_fields_non_empty_filter() -> None:
    f = LeadFields(company="Acme", quantity="500")
    assert f.non_empty() == {"company": "Acme", "quantity": "500"}


def test_lead_turn_context_gate() -> None:
    from backend.pipeline.lead_qualify import ContactHit, LeadTurnContext

    ctx = LeadTurnContext(session_id="s1")
    assert ctx.should_qualify("product") is True
    assert ctx.should_qualify("support") is False
    assert ctx.should_qualify("off_topic") is False

    ctx2 = LeadTurnContext(session_id="s1", has_lead=True)
    assert ctx2.should_qualify("support") is True

    ctx3 = LeadTurnContext(
        session_id="s1", contact=ContactHit(type="email", value="a@b.com", masked="a***@b.com")
    )
    assert ctx3.capture_mode is True
    assert ctx3.should_qualify("support") is True
    assert uuid.UUID(str(ctx3.lead_id)) if ctx3.lead_id else True  # 类型冒烟
