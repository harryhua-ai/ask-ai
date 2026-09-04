"""内部嵌入服务认证(sync 执行面 → backend 单一驻留运行时)。

- 令牌 = HMAC-SHA256(JWT_SECRET, "internal-api:v1") 十六进制摘要;
  无需新增环境配置(两侧同源 .env 均有 JWT_SECRET),常量时间比较;
- 该通道只暴露「共享嵌入运行时」这一项能力,不授予任何其他权限;
  site/来源授权语义零触碰。
"""

from __future__ import annotations

import hashlib
import hmac

_INTERNAL_TOKEN_CONTEXT = b"internal-api:v1"


def internal_api_token(jwt_secret: str) -> str:
    """由 JWT_SECRET 派生内部嵌入通道令牌(两侧一致计算,无新配置)。"""
    return hmac.new(
        jwt_secret.encode("utf-8"),
        _INTERNAL_TOKEN_CONTEXT,
        hashlib.sha256,
    ).hexdigest()


def verify_internal_token(jwt_secret: str, presented: str | None) -> bool:
    """常量时间校验;缺失/不匹配一律 False(fail-closed)。"""
    if not presented:
        return False
    return hmac.compare_digest(presented, internal_api_token(jwt_secret))
