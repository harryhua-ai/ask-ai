"""语言检测与归一化工具。

优先用 CJK 字符集快速判断中/日/韩,拉丁字母文本默认英语。
多语言闭环(ML Closure)新增:语言代码归一化 + 答案语言解析。
"""

import re

_KANA_RE = re.compile(r"[぀-ヿ]")
_CJK_RE = re.compile(r"[一-鿿]")
_HANGUL_RE = re.compile(r"[가-힯]")

# CJK 族(文本可确定性检出的「显式用户语言信号」)
_CJK_FAMILIES = frozenset({"zh", "ja", "ko"})

_LANG_CODE_RE = re.compile(r"^[a-z]{2,3}(-[a-z0-9]+)*$")


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


def normalize_language(code: str | None) -> str | None:
    """语言代码归一化(ML 冻结语义:en/zh 规范形)。

    - ``zh-CN`` / ``zh_TW`` / ``zh-Hans`` / ``zh`` → ``zh``;
      ``en-US`` / ``en-GB`` / ``en`` → ``en``;
    - 其他 BCP-47 形状取小写主子标签(如 ``fr-FR`` → ``fr``),交由管线
      作为答案语言语境(G-L1:请求 language 提示被消费);
    - 空 / 非语言形状 → ``None``(fail-open,交回文本检测)。
    """
    if not code:
        return None
    cleaned = code.strip().lower().replace("_", "-")
    if not cleaned:
        return None
    primary = cleaned.split("-", 1)[0]
    if primary in ("zh", "en"):
        return primary
    if _LANG_CODE_RE.fullmatch(cleaned):
        return primary
    return None


def _language_family(code: str) -> str:
    """语言代码 → 主族标签(zh-cn/zh → zh)。"""
    return normalize_language(code) or code.strip().lower()


def resolve_answer_language(query: str, language_hint: str | None) -> str:
    """答案语言解析(ML 闭环冻结语义,ANSWER_LANGUAGE)。

    优先级:
    1. 无 hint → 文本检测(基线行为逐字保留,含 ``zh-cn`` 原值);
    2. 有 hint → hint 为**默认答案语境**(宿主页面/站点默认语言随 ask 传播);
       但文本检出 CJK(用户显式语言表达,可确定性识别)且与 hint 不同族时,
       **显式用户语言覆盖宿主默认**;
    3. hint 命中时返回规范化值(``zh`` / ``en`` / 其他主子标签)。

    已知边界(诚实声明):拉丁文本间的区分(如英语 vs 西语)不在 CJK 确定性
    检测能力内,统一视为「未定」交 hint 裁决;hint 缺失时按基线回落 en。
    """
    detected = detect_language(query)
    normalized_hint = normalize_language(language_hint)
    if normalized_hint is None:
        return detected
    detected_family = _language_family(detected)
    if detected_family in _CJK_FAMILIES and detected_family != normalized_hint:
        return detected_family
    return normalized_hint
