"""PII 脱敏工具测试。

单元测试覆盖邮箱地址、中国手机号的脱敏逻辑,包括:
- 标准 11 位手机号
- 国际前缀(+86 / 86)
- 带分隔符的号码(138-1234-5678、138.1234.5678)
- 多 PII 混合文本
- 文本结构保留
- 无 PII 文本原样返回
"""

import pytest

from backend.utils.pii import mask_pii

# --------------------------------------------------------------------------- #
# 单元测试:邮箱脱敏
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_mask_email() -> None:
    """单个邮箱地址应被替换为 [邮箱已脱敏]。"""
    assert mask_pii("联系我 test@example.com") == "联系我 [邮箱已脱敏]"


@pytest.mark.unit
def test_mask_email_with_subaddress() -> None:
    """带子地址符(+)的邮箱应被完整脱敏。"""
    assert mask_pii("联系 user+tag@sub.example.com") == "联系 [邮箱已脱敏]"


# --------------------------------------------------------------------------- #
# 单元测试:手机号脱敏
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_mask_phone() -> None:
    """11 位中国手机号应被替换为 [电话已脱敏]。"""
    assert mask_pii("电话 13800138000") == "电话 [电话已脱敏]"


@pytest.mark.unit
def test_mask_international_phone() -> None:
    """+86 前缀和带分隔符的号码均应被脱敏。"""
    # +86 国际前缀(无分隔符)
    assert mask_pii("电话 +8613812345678") == "电话 [电话已脱敏]"
    # 86 前缀(无 +)
    assert mask_pii("电话 8613812345678") == "电话 [电话已脱敏]"
    # 带连字符分隔
    assert mask_pii("电话 138-1234-5678") == "电话 [电话已脱敏]"
    # 带点分隔
    assert mask_pii("电话 138.1234.5678") == "电话 [电话已脱敏]"


# --------------------------------------------------------------------------- #
# 单元测试:无 PII 文本
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_no_pii_unchanged() -> None:
    """无 PII 的文本应保持不变。"""
    assert mask_pii("NE503 功耗 2.5W") == "NE503 功耗 2.5W"


@pytest.mark.unit
def test_mask_pii_preserves_other_content() -> None:
    """脱敏只替换 PII,保留文本结构和其余内容。"""
    text = "用户 alice@example.com 询问订单 #12345,手机 13812345678 已验证。"
    masked = mask_pii(text)
    # 邮箱和手机号被替换
    assert "[邮箱已脱敏]" in masked
    assert "[电话已脱敏]" in masked
    # 其他文本内容保持不变
    assert "用户" in masked
    assert "询问订单 #12345" in masked
    assert "已验证。" in masked
    # 整体结构(空格、标点)未被破坏,仅 PII 部分被替换
    assert masked == "用户 [邮箱已脱敏] 询问订单 #12345,手机 [电话已脱敏] 已验证。"


# --------------------------------------------------------------------------- #
# 单元测试:多 PII 混合
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_mask_multiple_pii_in_one_text() -> None:
    """一段文本中含多个 email/手机号,应全部脱敏。"""
    text = "联系 a@x.com 或 b@y.com;电话 13812345678 / 13987654321。"
    masked = mask_pii(text)
    assert masked == ("联系 [邮箱已脱敏] 或 [邮箱已脱敏];" "电话 [电话已脱敏] / [电话已脱敏]。")


# --------------------------------------------------------------------------- #
# 单元测试:纯函数与边界情况
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_mask_pii_returns_new_string() -> None:
    """mask_pii 是纯函数,不应修改输入字符串。"""
    original = "联系 test@example.com 电话 13800138000"
    result = mask_pii(original)
    # str 在 Python 中不可变,这里验证调用前后原变量保持不变
    assert original == "联系 test@example.com 电话 13800138000"
    assert result == "联系 [邮箱已脱敏] 电话 [电话已脱敏]"


@pytest.mark.unit
def test_mask_pii_empty_string() -> None:
    """空字符串输入应返回空字符串。"""
    assert mask_pii("") == ""


@pytest.mark.unit
def test_mask_pii_no_false_positive_on_short_digits() -> None:
    """短数字串(如 2.5W、订单号 #12345)不应被误判为手机号。"""
    assert mask_pii("功耗 2.5W 订单 #12345") == "功耗 2.5W 订单 #12345"
