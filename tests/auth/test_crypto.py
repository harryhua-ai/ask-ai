"""Fernet 加解密测试。"""

from backend.auth.crypto import decrypt_api_key, encrypt_api_key

KEY = "my-encryption-key"


def test_encrypt_decrypt_roundtrip():
    original = "sk-abc123secret"
    encrypted = encrypt_api_key(original, KEY)
    assert encrypted != original
    assert decrypt_api_key(encrypted, KEY) == original


def test_decrypt_invalid_raises():
    import pytest
    from cryptography.fernet import InvalidToken

    with pytest.raises((ValueError, InvalidToken)):
        decrypt_api_key("not-valid-fernet-data", KEY)


def test_empty_key_raises():
    import pytest

    with pytest.raises(ValueError, match="ENCRYPTION_KEY"):
        encrypt_api_key("sk-test", "")
