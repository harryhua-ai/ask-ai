"""嵌入与重排模型抽象基类。

定义 Embedder / Reranker Protocol 以及 detect_device 设备自动检测工具。
设备优先级:cuda > mps > cpu。
"""

from typing import Protocol, runtime_checkable

import numpy as np


def detect_device(preference: str = "auto") -> str:
    """根据偏好返回推理设备名称。

    优先级:显式偏好 > cuda > mps > cpu。当 preference 不为 "auto" 时,
    直接返回该值(允许调用方强制指定设备,便于测试与调试)。

    Args:
        preference: 设备偏好字符串。"auto" 表示自动检测,
            其他值(如 "cpu"、"cuda"、"mps")将原样返回。

    Returns:
        设备名称字符串,可为 "cuda"、"mps"、"cpu" 或调用方传入的任意值。
    """
    if preference != "auto":
        return preference
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


@runtime_checkable
class Embedder(Protocol):
    """嵌入模型协议。

    所有具体嵌入模型必须实现该协议,以支持批量文本到固定维度向量的转换。
    """

    @property
    def dimension(self) -> int: ...

    def embed(self, texts: list[str]) -> list[np.ndarray]: ...


@runtime_checkable
class Reranker(Protocol):
    """重排模型协议。

    所有具体重排模型必须实现该协议,以支持基于 query 对候选文档打分。
    """

    def rerank(self, query: str, documents: list[str]) -> list[float]: ...
