"""JWT 与密码哈希测试。"""

import pytest

from backend.auth.jwt import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

SECRET = "test-secret"


def test_hash_and_verify_password():
    h = hash_password("mypass123")
    assert h != "mypass123"
    assert verify_password("mypass123", h) is True
    assert verify_password("wrong", h) is False


def test_create_and_decode_token():
    token = create_access_token("user-uuid-123", "admin", SECRET)
    payload = decode_access_token(token, SECRET)
    assert payload["sub"] == "user-uuid-123"
    assert payload["role"] == "admin"
    assert "exp" in payload


def test_decode_invalid_token():
    import jwt

    with pytest.raises(jwt.PyJWTError):
        decode_access_token("invalid.token.here", SECRET)
