"""语言检测工具。

基于 langdetect 库检测文本语言,失败时安全回落到英文。
"""

from langdetect import DetectorFactory, detect

# 设置随机种子以确保检测结果稳定
# langdetect 内部使用概率算法,未设种子时同一文本可能返回不同结果。
DetectorFactory.seed = 42


def detect_language(text: str) -> str:
    """检测文本所属语言,返回语言代码。

    使用 langdetect 进行语言检测,返回 ISO 639-1 风格的语言代码
    (如 ``zh-cn``、``en``、``ja``)。当检测失败(例如文本为空、纯符号、
    过短或无法识别)时,安全回落到 ``en``,避免阻塞用户输入预处理链路。

    Note:
        此处有意捕获 ``Exception`` 而非更具体的 ``LangDetectException``。
        原因:langdetect 在不同版本中可能抛出多种异常(包括上游依赖
        的异常),用户输入预处理是请求链路的最前端,任何未捕获异常
        都会导致整条链路中断。保守兜底为 ``en`` 是可接受的产品行为
        (后续 LLM 仍可处理多语言文本,仅影响路由选择)。

    Args:
        text: 待检测的文本。

    Returns:
        语言代码字符串(如 ``zh-cn``、``en``);检测失败时返回 ``en``。
    """
    try:
        return detect(text)
    except Exception:  # noqa: BLE001 - 故意兜底:见上方 docstring Note 说明
        # langdetect 对空字符串、纯符号或无法识别的文本会抛出异常,
        # 此处统一回落到英文,保证输入预处理链路不中断。
        return "en"
