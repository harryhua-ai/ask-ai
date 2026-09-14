"""Conversation ID generation policy Admin contract tests."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import Conversation, ConversationIdPolicy, User
from backend.main import app
from backend.services.conversation_id import ConversationIdPolicyError, new_conversation_id

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def clean_policy():
    async with app.state.session_factory() as session:
        original = (
            await session.execute(
                select(ConversationIdPolicy).where(ConversationIdPolicy.key == "default")
            )
        ).scalar_one_or_none()
        original_strategy = original.strategy if original else None
    yield
    async with app.state.session_factory() as session:
        await session.execute(ConversationIdPolicy.__table__.delete())
        if original_strategy:
            session.add(ConversationIdPolicy(key="default", strategy=original_strategy))
        await session.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers():
    user_id = uuid.uuid4()
    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email=f"conversation-policy-{user_id.hex[:8]}@test.com",
                role="admin",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    yield {
        "Authorization": f"Bearer {create_access_token(
            str(user_id), "admin", app.state.settings.jwt_secret
        )}"
    }
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


async def test_conversation_id_policy_can_be_read_and_saved(auth_headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        before = await client.get(
            "/api/admin/system/conversation-id-policy", headers=auth_headers
        )
        saved = await client.put(
            "/api/admin/system/conversation-id-policy",
            json={"strategy": "uuid7"},
            headers=auth_headers,
        )
        after = await client.get(
            "/api/admin/system/conversation-id-policy", headers=auth_headers
        )
    assert before.status_code == 200
    assert saved.status_code == 200
    assert saved.json()["strategy"] == "uuid7"
    assert after.status_code == 200
    assert after.json()["strategy"] == "uuid7"
    assert after.json()["affects_new_conversations_only"] is True


async def test_conversation_id_policy_rejects_invalid_strategy(auth_headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            "/api/admin/system/conversation-id-policy",
            json={"strategy": "free-form-template"},
            headers=auth_headers,
        )
    assert response.status_code == 422


async def test_new_conversation_id_uses_active_policy_and_authoritative_missing_default():
    factory = app.state.session_factory
    async with factory() as session:
        row = await session.get(ConversationIdPolicy, "default")
        if row is None:
            row = ConversationIdPolicy(key="default", strategy="uuid7")
            session.add(row)
        else:
            row.strategy = "uuid7"
        await session.commit()
    try:
        uuid7 = await new_conversation_id(factory)
        assert uuid7.version == 7
    finally:
        async with factory() as session:
            await session.execute(
                ConversationIdPolicy.__table__.delete().where(
                    ConversationIdPolicy.key == "default"
                )
            )
            await session.commit()
    uuid4 = await new_conversation_id(factory)
    assert uuid4.version == 4


async def test_invalid_persisted_strategy_fails_closed_without_generating_id():
    factory = app.state.session_factory
    async with factory() as session:
        row = await session.get(ConversationIdPolicy, "default")
        if row is None:
            row = ConversationIdPolicy(key="default", strategy="invalid")
            session.add(row)
        else:
            row.strategy = "invalid"
        await session.commit()

    try:
        with patch("backend.services.conversation_id.generate_conversation_id") as generate, pytest.raises(
            ConversationIdPolicyError
        ):
            await new_conversation_id(factory)
        generate.assert_not_called()
    finally:
        async with factory() as session:
            await session.execute(
                ConversationIdPolicy.__table__.delete().where(
                    ConversationIdPolicy.key == "default"
                )
            )
            await session.commit()


async def test_policy_store_read_failure_fails_closed_without_generating_id():
    session = AsyncMock()
    session.execute.side_effect = RuntimeError("policy store unavailable")
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("backend.services.conversation_id.generate_conversation_id") as generate, pytest.raises(
        ConversationIdPolicyError
    ):
        await new_conversation_id(factory)
    generate.assert_not_called()


async def test_policy_failure_does_not_rewrite_existing_conversation_id():
    factory = app.state.session_factory
    existing_id = uuid.uuid4()
    async with factory() as session:
        session.add(Conversation(id=existing_id, question="existing", answer="answer"))
        row = await session.get(ConversationIdPolicy, "default")
        if row is None:
            session.add(ConversationIdPolicy(key="default", strategy="invalid"))
        else:
            row.strategy = "invalid"
        await session.commit()

    try:
        with pytest.raises(ConversationIdPolicyError):
            await new_conversation_id(factory)
        async with factory() as session:
            current = await session.get(Conversation, existing_id)
            assert current is not None
            assert current.id == existing_id
            assert current.question == "existing"
            assert current.answer == "answer"
    finally:
        async with factory() as session:
            await session.execute(Conversation.__table__.delete().where(Conversation.id == existing_id))
            await session.execute(
                ConversationIdPolicy.__table__.delete().where(
                    ConversationIdPolicy.key == "default"
                )
            )
            await session.commit()
