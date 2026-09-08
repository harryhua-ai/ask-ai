"""LLM 调用遥测采集(INC-1 答案管线可观测基线)。

请求级 ContextVar 采集器:编排器在请求入口 :func:`start_capture`,此后
``LLMRouter`` 的每次 generate/stream 尝试向当前上下文追加结构化事件;
编排器在写 Trace 时用 :func:`current_calls` 读取。

设计约束:
- **只记元数据**——task/provider/model/latency/tokens/thinking/success/skip,
  绝不记录 prompt 原文、内部证据原文或任何用户/客户内容(信任边界,INC-1 契约)。
- ContextVar 而非共享单例列表:并发请求各自独立;``asyncio.create_task``
  在创建时复制上下文(同一 list 对象引用),并行的 lead 资格判定调用事件
  因此落入同一请求的采集器,无需改任何调用方签名。
- 事件为纯标量 dict(可直接 JSON 序列化进 Trace.stages)。
"""

from __future__ import annotations

import contextvars
from typing import Any

# 单请求事件上限(防御性:正常 ≤ 每角色 1-2 条 + skip 标记,远低于此界)
_MAX_EVENTS = 64

_calls: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "llm_call_telemetry", default=None
)
# 流式 usage 由 provider 在收到 usage chunk 时写入,router 收尾时一次性读取
_stream_usage: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "llm_stream_usage", default=None
)


def start_capture() -> list[dict[str, Any]]:
    """开启本请求的调用事件采集,返回采集列表(编排器无需直接使用)。"""
    calls: list[dict[str, Any]] = []
    _calls.set(calls)
    _stream_usage.set(None)
    return calls


def current_calls() -> list[dict[str, Any]]:
    """当前上下文已采集事件的浅拷贝;未开启捕获时返回空列表。"""
    return list(_calls.get() or [])


def record_call(event: dict[str, Any]) -> None:
    """追加一次 LLM 调用尝试事件(router 专用;未开启捕获时静默丢弃)。"""
    calls = _calls.get()
    if calls is None or len(calls) >= _MAX_EVENTS:
        return
    calls.append({k: v for k, v in event.items() if v is not None})


def record_skipped(task: str, reason: str) -> None:
    """记录条件跳过状态(短路/门控未命中),不记录任何内容性数据。"""
    calls = _calls.get()
    if calls is None or len(calls) >= _MAX_EVENTS:
        return
    calls.append({"task": task, "skipped": True, "reason": reason})


def record_stream_usage(tokens_input: Any, tokens_output: Any) -> None:
    """provider 流式收到 usage chunk 时写入(该 chunk 无内容,不进答案)。"""
    _stream_usage.set({"tokens_input": tokens_input, "tokens_output": tokens_output})


def pop_stream_usage() -> dict[str, Any] | None:
    """router 收尾读取本次流式 usage(一次性;未报告时返回 None)。"""
    usage = _stream_usage.get()
    _stream_usage.set(None)
    return usage
