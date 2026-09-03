"""结构化产品边界消息键(Issue #5 契约 §8)。"""


from backend.utils.user_messages import (
    MESSAGE_KEYS,
    NO_EVIDENCE_KEY,
    PRODUCT_AMBIGUOUS_KEY,
    PRODUCT_EVIDENCE_INSUFFICIENT_KEY,
    PRODUCT_NOT_SUPPORTED_KEY,
    localized_message,
)


def test_new_product_keys_registered():
    assert PRODUCT_AMBIGUOUS_KEY == "product_ambiguous"
    assert PRODUCT_EVIDENCE_INSUFFICIENT_KEY == "product_evidence_insufficient"
    assert PRODUCT_NOT_SUPPORTED_KEY == "product_not_supported"
    assert {
        PRODUCT_AMBIGUOUS_KEY,
        PRODUCT_EVIDENCE_INSUFFICIENT_KEY,
        PRODUCT_NOT_SUPPORTED_KEY,
    } <= MESSAGE_KEYS


def test_no_evidence_key_unchanged():
    """既有 no-evidence 拒答行为保持兼容(文案逐字不变)。"""
    assert localized_message(NO_EVIDENCE_KEY, "zh") == "暂未在官方资料中找到相关信息。"
    assert (
        localized_message(NO_EVIDENCE_KEY, "en")
        == "I couldn't find relevant information in the official sources."
    )


def test_insufficient_message_interpolates_product_name():
    zh = localized_message(PRODUCT_EVIDENCE_INSUFFICIENT_KEY, "zh", product="NeoEye NE503")
    assert "NeoEye NE503" in zh
    en = localized_message(
        PRODUCT_EVIDENCE_INSUFFICIENT_KEY, "en", product="NeoEye NE503"
    )
    assert "NeoEye NE503" in en


def test_ambiguous_and_not_supported_localized():
    assert localized_message(PRODUCT_AMBIGUOUS_KEY, "zh")
    assert localized_message(PRODUCT_AMBIGUOUS_KEY, "en")
    assert localized_message(PRODUCT_NOT_SUPPORTED_KEY, "zh")
    assert localized_message(PRODUCT_NOT_SUPPORTED_KEY, "en")


def test_unknown_key_falls_back_service_unavailable():
    """未知键语义不变:回落 service_unavailable(fail-safe,非 raise)。"""
    from backend.utils.user_messages import SERVICE_UNAVAILABLE_KEY

    assert localized_message("definitely-not-a-key", "zh") == localized_message(
        SERVICE_UNAVAILABLE_KEY, "zh"
    )
