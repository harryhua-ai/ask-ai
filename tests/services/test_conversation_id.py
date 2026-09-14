"""Conversation ID 策略的纯生成回归。"""

import uuid

import pytest

from backend.services.conversation_id import (
    generate_conversation_id,
    policy_view,
    validate_strategy,
)


def test_uuid4_generation_keeps_existing_uuid_semantics():
    value = generate_conversation_id("uuid4")
    assert isinstance(value, uuid.UUID)
    assert value.version == 4
    assert value.variant == uuid.RFC_4122


def test_uuid7_generation_has_rfc9562_version_and_variant():
    value = generate_conversation_id("uuid7")
    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_policy_view_and_validation_are_fail_loud():
    assert validate_strategy(" UUID7 ") == "uuid7"
    view = policy_view("uuid7")
    assert view.strategy == "uuid7"
    assert view.example
    with pytest.raises(ValueError):
        generate_conversation_id("free-form-template")
