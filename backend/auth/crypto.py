"""API key 对称加密/解密（Fernet）。"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def _get_fernet(encryption_key: str) -> Fernet:
    """从任意长度密钥派生标准 Fernet key（32 base64-url-safe bytes）。"""
    if not encryption_key:
        raise ValueError("ENCRYPTION_KEY 未配置，无法加密 API key")
    derived = hashlib.sha256(encryption_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_api_key(plaintext: str, encryption_key: str) -> str:
    """加密 API key，返回 base64 字符串。"""
    f = _get_fernet(encryption_key)
    return f.encrypt(plaintext.encode()).decode()


def decrypt_api_key(ciphertext: str, encryption_key: str) -> str:
    """解密 API key。无效密文抛 ValueError。"""
    f = _get_fernet(encryption_key)
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("API key 解密失败") from exc
