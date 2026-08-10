"""Trace 数据模型测试。"""

from sqlalchemy import inspect

from backend.db.models import Conversation, Trace


def test_trace_model_columns():
    """Trace 模型有所需字段,且 conversation_id 外键到 conversations。"""
    mapper = inspect(Trace)
    cols = {c.key for c in mapper.columns}
    expected = {
        "id",
        "conversation_id",
        "prev_trace_id",
        "turn_index",
        "type",
        "stages",
        "total_ms",
        "intent",
        "confidence",
        "config_snapshot",
        "created_at",
    }
    assert expected.issubset(cols), f"缺少字段: {expected - cols}"


def test_trace_conversation_relationship():
    """Conversation.traces 反向关系存在,1:N。"""
    mapper = inspect(Conversation)
    assert "traces" in mapper.relationships, "Conversation 缺 traces relationship"


def test_trace_self_reference():
    """Trace.prev_trace 自引用关系存在。"""
    mapper = inspect(Trace)
    assert "prev_trace" in mapper.relationships, "Trace 缺 prev_trace relationship"
