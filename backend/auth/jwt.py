"""JWT token 签发与校验 + bcrypt 密码哈希。"""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"
TOKEN_TTL_HOURS = 24


def hash_password(plain: str) -> str:
    """bcrypt 哈希明文密码。"""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与 bcrypt 哈希是否匹配。"""
    return _pwd_context.verify(plain, hashed)


def create_access_token(user_id: str, role: str, secret: str) -> str:
    """签发 JWT，payload 包含 sub(user_id) / role / exp。"""
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "exp": datetime.now(UTC) + timedelta(hours=TOKEN_TTL_HOURS),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(token: str, secret: str) -> dict[str, Any]:
    """解码并校验 JWT，过期/篡改抛 jwt.PyJWTError。"""
    return jwt.decode(token, secret, algorithms=[ALGORITHM])
