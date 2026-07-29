"""语言检测工具测试。

单元测试覆盖中英文检测、边界情况和失败回落逻辑。
"""

import pytest

from backend.utils.language import detect_language

# --------------------------------------------------------------------------- #
# 单元测试:正常语言检测
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_detect_chinese() -> None:
    """包含足够中文特征词的文本应识别为 zh-cn。"""
    assert detect_language("NE503 的功耗是多少") == "zh-cn"


@pytest.mark.unit
def test_detect_english() -> None:
    """英文句子应识别为 en。"""
    assert detect_language("What is the power consumption of NE503") == "en"


# --------------------------------------------------------------------------- #
# 单元测试:边界情况与失败回落
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_detect_language_fallback_on_empty() -> None:
    """空字符串或纯空白符号应回落到 en。"""
    assert detect_language("") == "en"
    assert detect_language("   ") == "en"
    assert detect_language("\n\t") == "en"


@pytest.mark.unit
def test_detect_language_fallback_on_pure_symbols() -> None:
    """纯标点/符号文本应回落到 en。"""
    assert detect_language("!@#$%^&*()") == "en"


@pytest.mark.unit
def test_detect_language_fallback_on_garbage() -> None:
    """无意义数字串应回落到 en。"""
    assert detect_language("12345!!!") == "en"
