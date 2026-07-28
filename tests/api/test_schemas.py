"""AskRequest schema 边界单元测试(S3: conversation_history 强制边界)。"""

import pytest
from pydantic import ValidationError

from backend.api.schemas import AskRequest


@pytest.mark.unit
def test_normal_history_passes() -> None:
    req = AskRequest(
        message="hi",
        conversation_history=[
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
        ],
    )
    assert len(req.conversation_history) == 2


@pytest.mark.unit
def test_history_over_10_items_rejected() -> None:
    with pytest.raises(ValidationError):
        AskRequest(message="hi", conversation_history=[{"role": "user", "content": "x"}] * 11)


@pytest.mark.unit
def test_history_oversize_content_rejected() -> None:
    with pytest.raises(ValidationError):
        AskRequest(message="hi", conversation_history=[{"role": "user", "content": "x" * 5000}])


@pytest.mark.unit
def test_invalid_channel_rejected() -> None:
    with pytest.raises(ValidationError):
        AskRequest(message="hi", channel="evil")


@pytest.mark.unit
def test_history_strips_extra_keys() -> None:
    req = AskRequest(
        message="hi",
        conversation_history=[{"role": "user", "content": "a", "injected": "malware"}],
    )
    assert "injected" not in req.conversation_history[0]
