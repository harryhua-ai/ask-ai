"""语言检测工具。

优先用 CJK 字符集快速判断中/日/韩,拉丁字母文本默认英语。
"""

import re

_KANA_RE = re.compile(r"[぀-ヿ]")
_CJK_RE = re.compile(r"[一-鿿]")
_HANGUL_RE = re.compile(r"[가-힯]")


def detect_language(text: str) -> str:
    """检测文本所属语言,返回语言代码。

    优先用 Unicode 字符集判断 CJK 语言(快速且准确):
    - 含假名 → ja
    - 含汉字 → zh-cn
    - 含谚文 → ko
    拉丁字母文本回退到 langdetect 概率检测,失败时回落到 en。
    """
    if _KANA_RE.search(text):
        return "ja"
    if _CJK_RE.search(text):
        return "zh-cn"
    if _HANGUL_RE.search(text):
        return "ko"
    return "en"
