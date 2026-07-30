# Phase 2B — 管理后台 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Ask AI RAG 系统构建一个完整的 React 管理后台，包含 JWT 认证/RBAC、数据源 CRUD、同步监控、Customization 管理、LLM 供应商管理、对话审查六大模块。

**Architecture:** 后端在现有 FastAPI 应用上新增 `/api/admin/*` 路由组（JWT 认证 + RBAC 依赖注入），YAML 配置迁移到 Postgres 表（data_sources / customizations / llm_providers 等），启动时从 DB 加载配置注入 RAGOrchestrator。前端为全新 React 19 SPA（Vite + Tailwind + shadcn/ui），开发时通过 Vite proxy 转发 API 请求，生产环境由 FastAPI StaticFiles 托管。

**Tech Stack:** React 19 / TypeScript 5.7 / Vite 6 / Tailwind CSS 4 / shadcn/ui (Radix) / TanStack Query v5 / react-router v7 / react-hook-form / zod / PyJWT / passlib[bcrypt] / cryptography (Fernet)

## Global Constraints

- Python 3.12+, type annotations required on all function signatures
- PEP 8, black formatting (line-length=100), isort, ruff linting
- pytest for backend tests, vitest for admin frontend tests
- Immutable data patterns on backend (frozen dataclasses)
- React 19 + TypeScript strict mode on frontend
- Admin API 全部在 `/api/admin/*` 前缀下，JWT Bearer 认证
- 三种角色：`admin`（全部权限）/ `editor`（数据源、Customization、LLM、对话审查）/ `viewer`（只读）
- 所有 API key 入库必须用 Fernet 对称加密（密钥从 `ENCRYPTION_KEY` 环境变量读取）
- 用户密码用 bcrypt 哈希存储（passlib），永不明文
- JWT secret 从 `JWT_SECRET` 环境变量读取，token 有效期 24h
- 前端开发服务器端口 5174（widget 占用 5173），通过 Vite proxy 转发 `/api` 到 `http://localhost:8000`
- 前端生产构建输出到 `admin/dist/`，由 FastAPI `StaticFiles` 在 `/admin/` 路径下托管
- 所有代码注释和 UI 文案使用中文（简体）
- 文件大小：200-400 行为佳，800 行为上限
- 安全铁律：secret 永不进 LLM 上下文；LLM 输出渲染前必须 XSS 清洗；外部输入在系统边界校验

---

## File Structure

### 新建文件

```
ask-ai/
├── admin/                              # 管理后台 React SPA（全新）
│   ├── package.json
│   ├── tsconfig.json
│   ├── tsconfig.node.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── postcss.config.js
│   ├── index.html
│   ├── components.json                 # shadcn/ui 配置
│   ├── src/
│   │   ├── main.tsx                    # React 入口
│   │   ├── App.tsx                     # 路由根 + QueryClientProvider + AuthProvider
│   │   ├── index.css                   # Tailwind 全局样式 + CSS 变量
│   │   ├── lib/
│   │   │   ├── api.ts                  # fetch wrapper + JWT 拦截 + 错误处理
│   │   │   └── utils.ts                # cn() 等工具函数（shadcn 依赖）
│   │   ├── types/
│   │   │   └── api.ts                  # API 响应/请求 TS 类型（对齐后端 Pydantic）
│   │   ├── hooks/
│   │   │   ├── useAuth.ts              # 认证状态 hook
│   │   │   └── useApi.ts               # TanStack Query 封装 hooks
│   │   ├── components/
│   │   │   ├── ui/                     # shadcn/ui 组件（button, input, table, dialog 等）
│   │   │   ├── Layout.tsx              # 侧边栏 + 顶栏布局 shell
│   │   │   ├── Sidebar.tsx             # 导航侧边栏
│   │   │   ├── ProtectedRoute.tsx      # 路由守卫（未登录重定向）
│   │   │   ├── StatusBadge.tsx         # 状态徽章（成功/失败/运行中）
│   │   │   └── Pagination.tsx          # 分页组件
│   │   └── pages/
│   │       ├── Login.tsx               # 登录页
│   │       ├── Dashboard.tsx           # 首页概览
│   │       ├── Users.tsx               # 用户管理
│   │       ├── DataSources.tsx         # 数据源管理
│   │       ├── SyncLogs.tsx            # 同步监控
│   │       ├── Customizations.tsx      # Customization 管理
│   │       ├── LLMProviders.tsx        # LLM 供应商管理
│   │       └── Conversations.tsx       # 对话审查
│   └── tests/
│       └── setup.ts                    # vitest 测试配置
├── backend/
│   ├── auth/                           # 认证模块（全新）
│   │   ├── __init__.py
│   │   ├── jwt.py                      # JWT 签发/校验 + 密码哈希
│   │   ├── dependencies.py             # FastAPI 认证/RBAC 依赖
│   │   └── crypto.py                   # Fernet API key 加解密
│   ├── api/
│   │   └── admin/                      # Admin API 路由组（全新）
│   │       ├── __init__.py
│   │       ├── router.py               # 汇总所有 admin 子路由
│   │       ├── auth.py                 # 登录/me/改密码
│   │       ├── users.py                # 用户 CRUD
│   │       ├── data_sources.py         # 数据源 CRUD + 手动同步
│   │       ├── sync_logs.py            # 同步日志查询
│   │       ├── customizations.py       # Customization CRUD + 渠道绑定
│   │       ├── llm_providers.py        # LLM 供应商 CRUD + 路由 + 连通性测试
│   │       ├── conversations.py        # 对话查询 + Intent 标注
│   │       └── schemas.py              # Admin Pydantic 模型
│   └── services/                       # 业务服务层（全新）
│       ├── __init__.py
│       ├── config_loader.py            # 从 DB 加载配置（data_sources/llm/customizations）
│       └── intent_tagger.py            # LLM Intent 自动标注
├── scripts/
│   ├── migrate_yaml_to_db.py           # YAML → Postgres 一次性迁移脚本
│   └── create_admin_user.py            # 创建初始管理员用户
└── tests/
    ├── auth/
    │   ├── __init__.py
    │   ├── test_jwt.py
    │   └── test_crypto.py
    └── api/
        └── admin/
            ├── __init__.py
            ├── test_auth.py
            ├── test_users.py
            ├── test_data_sources.py
            ├── test_sync_logs.py
            ├── test_customizations.py
            ├── test_llm_providers.py
            └── test_conversations.py
```

### 修改的现有文件

| 文件 | 改动 |
|---|---|
| `backend/db/models.py` | `User` 模型增加 `password_hash` 列 |
| `backend/main.py` | lifespan 中加载 admin 路由；从 DB 加载 LLM/customization 配置（fallback YAML）；挂载 admin StaticFiles |
| `backend/config.py` | `Settings` 增加 `jwt_secret` / `encryption_key` 字段 |
| `backend/pipeline/rag.py` | `RAGOrchestrator.__init__` 增加 `channel_customizations: dict[str, str]` 参数，按渠道选 system_prompt |
| `pyproject.toml` | 增加 `PyJWT`、`passlib[bcrypt]`、`cryptography` 依赖 |
| `scripts/sync.py` | 无改动（已有 `triggered_by` 参数）；手动同步通过 admin API 端点复用 `_sync_one` |

---

## Task 1: Backend — User 模型增加 password_hash 列

**Files:**
- Modify: `backend/db/models.py`
- Modify: `backend/config.py`
- Create: `scripts/create_admin_user.py`
- Test: `tests/db/test_models.py`

**Interfaces:**
- Consumes: 现有 `User` 模型 (`backend/db/models.py:179`)
- Produces: `User.password_hash` 列；`Settings.jwt_secret` / `Settings.encryption_key` 字段；`create_admin_user.py` 脚本入口

**Steps:**

- [ ] 在 `backend/db/models.py` 的 `User` 类中添加 `password_hash` 列

```python
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    password_hash: Mapped[str | None] = mapped_column(String(255))  # 新增：bcrypt 哈希
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

- [ ] 在 `backend/config.py` 的 `Settings` 中添加 `jwt_secret` 和 `encryption_key` 字段

```python
@dataclass(frozen=True)
class Settings:
    # ... 现有字段不变 ...
    jwt_secret: str
    encryption_key: str

    # 在 load_settings 中添加：
    # jwt_secret=_env("JWT_SECRET", "dev-secret-change-in-production"),
    # encryption_key=_env("ENCRYPTION_KEY", ""),
```

- [ ] 在 `pyproject.toml` 的 `dependencies` 中添加 `PyJWT>=2.8`、`passlib[bcrypt]>=1.7`、`cryptography>=43.0`

- [ ] 在 `tests/db/test_models.py` 中添加测试验证 `password_hash` 列存在

```python
def test_user_model_has_password_hash():
    """User 模型必须包含 password_hash 列。"""
    from backend.db.models import User
    assert hasattr(User, "password_hash")
    col = User.__table__.columns["password_hash"]
    assert col.type.length == 255
    assert col.nullable is True  # 初始可为空，由迁移脚本填充
```

- [ ] 创建 `scripts/create_admin_user.py`：通过 CLI 创建初始管理员

```python
"""创建初始管理员用户。

用法：python scripts/create_admin_user.py admin@camthink.ai --name "Admin" --role admin
交互式输入密码，bcrypt 哈希后写入 users 表。
"""
import argparse
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from passlib.context import CryptContext
from sqlalchemy import select

from backend.config import load_settings
from backend.db.models import User
from backend.db.session import get_engine, get_session_factory, init_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def create_admin(email: str, name: str, role: str) -> None:
    password = getpass.getpass("密码: ")
    password_hash = pwd_context.hash(password)
    settings = load_settings()
    engine = get_engine(settings.postgres_dsn)
    await init_db(engine)
    factory = get_session_factory(engine)
    async with factory() as session:
        existing = await session.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            print(f"用户 {email} 已存在")
            return
        user = User(email=email, name=name, role=role, password_hash=password_hash)
        session.add(user)
        await session.commit()
        print(f"管理员 {email} 创建成功")
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="创建管理员用户")
    parser.add_argument("email")
    parser.add_argument("--name", default="Admin")
    parser.add_argument("--role", default="admin", choices=["admin", "editor", "viewer"])
    args = parser.parse_args()
    asyncio.run(create_admin(args.email, args.name, args.role))


if __name__ == "__main__":
    main()
```

- [ ] 运行测试验证，commit

```bash
pytest tests/db/test_models.py -v
```

---

## Task 2: Backend — JWT 认证与密码哈希模块

**Files:**
- Create: `backend/auth/__init__.py`
- Create: `backend/auth/jwt.py`
- Create: `backend/auth/crypto.py`
- Create: `backend/auth/dependencies.py`
- Test: `tests/auth/__init__.py`
- Test: `tests/auth/test_jwt.py`
- Test: `tests/auth/test_crypto.py`

**Interfaces:**
- Consumes: `Settings.jwt_secret`（Task 1）；`Settings.encryption_key`
- Produces: `hash_password(plain) -> str`；`verify_password(plain, hash) -> bool`；`create_access_token(user_id, role) -> str`；`decode_access_token(token) -> dict`；`get_current_user(request) -> User`（FastAPI 依赖）；`encrypt_api_key(key) -> str`；`decrypt_api_key(encrypted) -> str`

**Steps:**

- [ ] 创建 `backend/auth/__init__.py`（空导出）

```python
"""管理后台认证与加密模块。"""
```

- [ ] 创建 `backend/auth/jwt.py`：JWT 签发/校验 + bcrypt 密码哈希

```python
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
```

- [ ] 创建 `backend/auth/crypto.py`：Fernet 对称加密（用于 API key 入库）

```python
"""API key 对称加密/解密（Fernet）。"""

import base64
import hashlib
import os

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
```

- [ ] 创建 `backend/auth/dependencies.py`：FastAPI 认证依赖

```python
"""FastAPI 认证与 RBAC 依赖。"""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.auth.jwt import decode_access_token
from backend.db.models import User

_security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
) -> User:
    """从 JWT Bearer token 解析当前用户。无 token / 过期 / 用户不存在 → 401。"""
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未提供认证令牌")
    settings = request.app.state.settings
    try:
        payload = decode_access_token(creds.credentials, settings.jwt_secret)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌无效或已过期")
    user_id = uuid.UUID(payload["sub"])
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        user = await session.execute(select(User).where(User.id == user_id))
        user = user.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已禁用")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: str):
    """RBAC 角色校验依赖工厂。用法：Depends(require_role("admin", "editor"))。"""

    async def _check(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
        return user

    return _check
```

- [ ] 创建 `tests/auth/test_jwt.py`

```python
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
    with pytest.raises(Exception):
        decode_access_token("invalid.token.here", SECRET)
```

- [ ] 创建 `tests/auth/test_crypto.py`

```python
"""Fernet 加解密测试。"""

from backend.auth.crypto import decrypt_api_key, encrypt_api_key

KEY = "my-encryption-key"


def test_encrypt_decrypt_roundtrip():
    original = "sk-abc123secret"
    encrypted = encrypt_api_key(original, KEY)
    assert encrypted != original
    assert decrypt_api_key(encrypted, KEY) == original


def test_decrypt_invalid_raises():
    from cryptography.fernet import InvalidToken
    import pytest
    with pytest.raises((ValueError, InvalidToken)):
        decrypt_api_key("not-valid-fernet-data", KEY)


def test_empty_key_raises():
    import pytest
    with pytest.raises(ValueError, match="ENCRYPTION_KEY"):
        encrypt_api_key("sk-test", "")
```

- [ ] 运行测试验证，commit

```bash
pytest tests/auth/ -v
```

---

## Task 3: Backend — Admin 认证端点（登录/me/改密码）

**Files:**
- Create: `backend/api/admin/__init__.py`
- Create: `backend/api/admin/router.py`
- Create: `backend/api/admin/auth.py`
- Create: `backend/api/admin/schemas.py`
- Modify: `backend/main.py`（挂载 admin 路由 + `app.state.settings` / `app.state.llm` / `app.state.embedder`）
- Test: `tests/api/admin/__init__.py`
- Test: `tests/api/admin/conftest.py`
- Test: `tests/api/admin/test_auth.py`

**Interfaces:**
- Consumes: `hash_password` / `verify_password` / `create_access_token`（Task 2）；`get_current_user`（Task 2）
- Produces: `POST /api/admin/auth/login`；`GET /api/admin/auth/me`；`PUT /api/admin/auth/password`；`admin_router`（汇总所有 admin 子路由）

**Steps:**

- [ ] 创建 `backend/api/admin/schemas.py` 中的认证相关 Pydantic 模型

```python
"""Admin API Pydantic 模型。"""

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: str
    email: str
    name: str | None
    role: str
    is_active: bool


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class UserCreate(BaseModel):
    email: EmailStr
    name: str | None = None
    role: str = Field(default="viewer", pattern="^(admin|editor|viewer)$")
    password: str = Field(..., min_length=8, max_length=128)


class UserUpdate(BaseModel):
    name: str | None = None
    role: str | None = Field(default=None, pattern="^(admin|editor|viewer)$")
    is_active: bool | None = None
```

- [ ] 创建 `backend/api/admin/auth.py`

```python
"""Admin 认证端点：登录 / me / 改密码。"""

from typing import Annotated
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    UserOut,
)
from backend.auth.dependencies import CurrentUser
from backend.auth.jwt import create_access_token, verify_password, hash_password
from backend.db.models import User

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request) -> LoginResponse:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    settings = request.app.state.settings
    async with factory() as session:
        result = await session.execute(select(User).where(User.email == req.email))
        user = result.scalar_one_or_none()
    if user is None or user.password_hash is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误")
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账户已禁用")
    token = create_access_token(str(user.id), user.role, settings.jwt_secret)
    async with factory() as session:
        await session.execute(
            update(User).where(User.id == user.id).values(last_login_at=datetime.now(UTC))
        )
        await session.commit()
    return LoginResponse(
        access_token=token,
        user=UserOut(
            id=str(user.id), email=user.email, name=user.name, role=user.role, is_active=user.is_active
        ),
    )


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut(
        id=str(user.id), email=user.email, name=user.name, role=user.role, is_active=user.is_active
    )


@router.put("/password")
async def change_password(
    req: ChangePasswordRequest, user: CurrentUser, request: Request
) -> dict[str, str]:
    if user.password_hash and not verify_password(req.old_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="原密码错误")
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(password_hash=hash_password(req.new_password))
        )
        await session.commit()
    return {"status": "ok"}
```

- [ ] 创建 `backend/api/admin/router.py` 汇总路由

```python
"""Admin API 路由汇总。"""

from fastapi import APIRouter

from backend.api.admin.auth import router as auth_router

admin_router = APIRouter(prefix="/api/admin")
admin_router.include_router(auth_router)
```

- [ ] 创建 `backend/api/admin/__init__.py`

```python
"""Admin API 层。"""

from backend.api.admin.router import admin_router

__all__ = ["admin_router"]
```

- [ ] 修改 `backend/main.py`：在 `lifespan` 中保存 settings / llm / embedder；挂载 admin 路由

```python
# 在 lifespan 函数体开头添加：
app.state.settings = settings

# 在 router_llm = _build_llm_router(...) 之后添加（供 admin intent 标注等服务使用）：
app.state.llm = router_llm

# 在 embedder = BGEEmbedder(...) 之后添加（供 admin 手动同步复用）：
app.state.embedder = embedder
app.state.weaviate_class_name = settings.weaviate_class_name

# 在 app.include_router(api_router) 之后添加：
from backend.api.admin.router import admin_router
app.include_router(admin_router)
```

- [ ] 创建 `tests/api/admin/conftest.py`：admin API 测试公共 fixture

ASGITransport 不触发 FastAPI lifespan，因此需要 session 级 autouse fixture
手动初始化 `app.state.settings` 和 `app.state.session_factory`。所有
admin API 测试（Task 3 及后续 Task 4/10/12/14/16/18/19）自动继承此 fixture。

```python
"""Admin API 测试公共 fixture。

ASGITransport 不触发 FastAPI lifespan，因此手动初始化 app.state
中测试所需的属性（settings / session_factory）。
session 级 autouse，在所有 admin API 测试前执行一次。
"""

import pytest

from backend.config import load_settings
from backend.db.session import get_engine, get_session_factory, init_db


@pytest.fixture(scope="session", autouse=True)
async def _setup_app_state():
    """手动初始化 app.state，绕过 ASGITransport 不触发 lifespan 的问题。"""
    from backend.main import app

    settings = load_settings()
    app.state.settings = settings

    engine = get_engine(settings.postgres_dsn)
    await init_db(engine)
    app.state.session_factory = get_session_factory(engine)
    yield
    await engine.dispose()
```

- [ ] 创建 `tests/api/admin/test_auth.py`

```python
"""Admin 认证端点测试。"""

import pytest
from httpx import ASGITransport, AsyncClient
from backend.main import app
from backend.auth.jwt import hash_password
from backend.db.models import User
import uuid


@pytest.fixture
async def admin_user():
    """在 app.state.session_factory 中插入一个管理员用户。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        user = User(
            id=user_id,
            email="admin@test.com",
            name="Admin",
            role="admin",
            password_hash=hash_password("testpass123"),
        )
        session.add(user)
        await session.commit()
    yield user_id
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


@pytest.mark.asyncio
async def test_login_success(admin_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/auth/login",
            json={"email": "admin@test.com", "password": "testpass123"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "admin@test.com"


@pytest.mark.asyncio
async def test_login_wrong_password(admin_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/auth/login",
            json={"email": "admin@test.com", "password": "wrong"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_without_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/auth/me")
    assert resp.status_code == 401
```

- [ ] 运行测试验证，commit

```bash
pytest tests/api/admin/test_auth.py -v
```

---

## Task 4: Backend — 用户 CRUD API

**Files:**
- Create: `backend/api/admin/users.py`
- Modify: `backend/api/admin/router.py`
- Modify: `backend/api/admin/schemas.py`（已有 UserCreate/UserUpdate）
- Test: `tests/api/admin/test_users.py`

**Interfaces:**
- Consumes: `CurrentUser` / `require_role`（Task 2）；`UserCreate` / `UserUpdate`（Task 3）
- Produces: `GET /api/admin/users`；`POST /api/admin/users`；`PATCH /api/admin/users/:id`；`DELETE /api/admin/users/:id`

**Steps:**

- [ ] 创建 `backend/api/admin/users.py`

```python
"""用户管理 CRUD 端点（仅 admin）。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import UserCreate, UserOut, UserUpdate
from backend.auth.dependencies import CurrentUser, require_role
from backend.auth.jwt import hash_password
from backend.db.models import User

router = APIRouter(prefix="/users", tags=["用户管理"])
AdminDep = Annotated[CurrentUser, Depends(require_role("admin"))]


@router.get("", response_model=list[UserOut])
async def list_users(
    _: AdminDep,
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> list[UserOut]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(
            select(User).offset((page - 1) * size).limit(size).order_by(User.created_at.desc())
        )
        users = result.scalars().all()
    return [
        UserOut(id=str(u.id), email=u.email, name=u.name, role=u.role, is_active=u.is_active)
        for u in users
    ]


@router.post("", response_model=UserOut, status_code=201)
async def create_user(req: UserCreate, _: AdminDep, request: Request) -> UserOut:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        existing = await session.execute(select(User).where(User.email == req.email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="邮箱已存在")
        user = User(
            email=req.email,
            name=req.name,
            role=req.role,
            password_hash=hash_password(req.password),
        )
        session.add(user)
        await session.commit()
    return UserOut(
        id=str(user.id), email=user.email, name=user.name, role=user.role, is_active=True
    )


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: UUID, req: UserUpdate, _: AdminDep, request: Request
) -> UserOut:
    values = req.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(status_code=400, detail="无更新字段")
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(
            update(User).where(User.id == user_id).values(**values).returning(User)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        await session.commit()
    return UserOut(
        id=str(user.id), email=user.email, name=user.name, role=user.role, is_active=user.is_active
    )


@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: UUID, current: AdminDep, request: Request) -> None:
    if current.id == user_id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        await session.delete(user)
        await session.commit()
```

- [ ] 在 `backend/api/admin/router.py` 中注册 users 路由

```python
from backend.api.admin.users import router as users_router
admin_router.include_router(users_router)
```

- [ ] 创建 `tests/api/admin/test_users.py` 测试 CRUD

```python
"""用户管理端点测试。"""

import pytest
from httpx import ASGITransport, AsyncClient
from backend.main import app
from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import User
import uuid


@pytest.fixture
async def auth_token():
    """创建管理员用户并返回 JWT token。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(User(
            id=user_id, email="admin@test.com", role="admin",
            password_hash=hash_password("pass123"),
        ))
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield token
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


@pytest.mark.asyncio
async def test_list_users_requires_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/users")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_and_list_user(auth_token):
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {auth_token}"}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/users",
            json={"email": "new@test.com", "password": "newpass123", "role": "viewer"},
            headers=headers,
        )
        assert resp.status_code == 201
        resp = await client.get("/api/admin/users", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1
```

- [ ] 运行测试验证，commit

```bash
pytest tests/api/admin/test_users.py -v
```

---

## Task 5: Frontend — Admin React 脚手架

**Files:**
- Create: `admin/package.json`
- Create: `admin/vite.config.ts`
- Create: `admin/tsconfig.json`
- Create: `admin/tsconfig.node.json`
- Create: `admin/tailwind.config.ts`
- Create: `admin/postcss.config.js`
- Create: `admin/index.html`
- Create: `admin/src/main.tsx`
- Create: `admin/src/index.css`
- Create: `admin/src/lib/utils.ts`
- Create: `admin/src/types/api.ts`

**Interfaces:**
- Consumes: 无（全新项目）
- Produces: `admin/` 目录可运行的 Vite + React + TypeScript 项目；`api.ts` 类型定义；`apiFetch()` HTTP 客户端

**Steps:**

- [ ] 创建 `admin/package.json`

```json
{
  "name": "ask-ai-admin",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite --port 5174",
    "build": "tsc -b && vite build",
    "preview": "vite preview --port 5174",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "react-router-dom": "^7.0.0",
    "@tanstack/react-query": "^5.60.0",
    "react-hook-form": "^7.54.0",
    "@hookform/resolvers": "^3.9.0",
    "zod": "^3.24.0",
    "clsx": "^2.1.0",
    "tailwind-merge": "^2.6.0",
    "class-variance-authority": "^0.7.0",
    "lucide-react": "^0.468.0",
    "@radix-ui/react-dialog": "^1.1.0",
    "@radix-ui/react-dropdown-menu": "^2.1.0",
    "@radix-ui/react-label": "^2.1.0",
    "@radix-ui/react-select": "^2.1.0",
    "@radix-ui/react-slot": "^1.1.0",
    "@radix-ui/react-toast": "^1.2.0"
  },
  "devDependencies": {
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.0",
    "typescript": "^5.7",
    "vite": "^6.0.0",
    "vitest": "^4.1.0",
    "jsdom": "^30.0.0",
    "tailwindcss": "^3.4.0",
    "postcss": "^8.4.0",
    "autoprefixer": "^10.4.0",
    "@testing-library/react": "^16.1.0",
    "@testing-library/jest-dom": "^6.6.0"
  }
}
```

- [ ] 创建 `admin/vite.config.ts`（proxy /api → FastAPI）

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5174,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
  },
});
```

- [ ] 创建 `admin/tsconfig.json`

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] 创建 `admin/tailwind.config.ts` + `admin/postcss.config.js`

```typescript
// tailwind.config.ts
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: "#000000", foreground: "#ffffff" },
      },
    },
  },
  plugins: [],
} satisfies Config;
```

```javascript
// postcss.config.js
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} },
};
```

- [ ] 创建 `admin/src/index.css`（Tailwind + shadcn CSS 变量）

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --background: 0 0% 100%;
  --foreground: 0 0% 3.9%;
  --card: 0 0% 100%;
  --primary: 0 0% 9%;
  --primary-foreground: 0 0% 98%;
  --muted: 0 0% 96.1%;
  --muted-foreground: 0 0% 45.1%;
  --border: 0 0% 89.8%;
  --destructive: 0 84.2% 60.2%;
  --destructive-foreground: 0 0% 98%;
  --radius: 0.5rem;
}

@layer base {
  * { border-color: hsl(var(--border)); }
  body {
    background-color: hsl(var(--background));
    color: hsl(var(--foreground));
    font-family: Manrope, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
}
```

- [ ] 创建 `admin/src/lib/utils.ts`（shadcn cn() 函数）

```typescript
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

- [ ] 创建 `admin/src/lib/api.ts`（fetch wrapper + JWT 拦截）

```typescript
const TOKEN_KEY = "ask-ai-admin-token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string>) || {}),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const resp = await fetch(`/api/admin${path}`, { ...options, headers });
  if (resp.status === 401) {
    clearToken();
    window.location.href = "/login";
    throw new ApiError(401, "未登录或登录已过期");
  }
  if (!resp.ok) {
    let detail = "请求失败";
    try {
      const body = await resp.json();
      detail = body.detail || detail;
    } catch { /* ignore parse error */ }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}
```

- [ ] 创建 `admin/src/types/api.ts`（对齐后端 Pydantic 模型）

```typescript
export interface User {
  id: string;
  email: string;
  name: string | null;
  role: "admin" | "editor" | "viewer";
  is_active: boolean;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface DataSource {
  id: string;
  type: string;
  product: string;
  enabled: boolean;
  config: Record<string, unknown>;
  sync_interval: string;
  created_at: string;
  updated_at: string;
}

export interface SyncLog {
  id: string;
  source_id: string;
  source_type: string;
  status: "success" | "failed" | "partial";
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  items_new: number;
  items_updated: number;
  items_deleted: number;
  error_detail: string | null;
  triggered_by: string;
}

export interface Customization {
  id: string;
  name: string;
  system_prompt: string;
  style_tone: string | null;
  guardrails: string | null;
  language: string;
  assistant_name: string;
  is_active: boolean;
  version: string;
}

export interface LLMProvider {
  id: string;
  type: string;
  enabled: boolean;
  config: Record<string, unknown>;
}

export interface LLMRouting {
  task: string;
  chain: string[];
}

export interface Conversation {
  id: string;
  question: string;
  answer: string | null;
  channel: string;
  language: string | null;
  sources: unknown[];
  is_answered: boolean;
  feedback: string | null;
  response_time_ms: number | null;
  created_at: string;
  intent_tag: string | null;
}
```

- [ ] 创建 `admin/index.html` + `admin/src/main.tsx`

```html
<!-- index.html -->
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Ask AI 管理后台</title>
</head>
<body>
  <div id="root"></div>
  <script type="module" src="/src/main.tsx"></script>
</body>
</html>
```

```typescript
// src/main.tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
```

- [ ] 运行 `cd admin && npm install && npm run dev` 验证脚手架启动，commit

---

## Task 6: Frontend — 登录页 + Auth Context

**Files:**
- Create: `admin/src/hooks/useAuth.ts`
- Create: `admin/src/components/ProtectedRoute.tsx`
- Create: `admin/src/pages/Login.tsx`
- Create: `admin/src/components/ui/button.tsx`（shadcn button）
- Create: `admin/src/components/ui/input.tsx`（shadcn input）
- Create: `admin/src/components/ui/label.tsx`（shadcn label）
- Modify: `admin/src/App.tsx`

**Interfaces:**
- Consumes: `apiFetch` / `setToken` / `getToken` / `clearToken`（Task 5）；`LoginResponse` 类型
- Produces: `useAuth()` hook（`{ user, login, logout, isLoading }`）；`<ProtectedRoute>` 组件；`/login` 路由

**Steps:**

- [ ] 创建 shadcn/ui 基础组件（button / input / label）

```typescript
// src/components/ui/button.tsx
import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        outline: "border border-input bg-background hover:bg-accent",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: { default: "h-10 px-4 py-2", sm: "h-9 px-3", lg: "h-11 px-8", icon: "h-10 w-10" },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return <Comp className={cn(buttonVariants({ variant, size }), className)} ref={ref} {...props} />;
  },
);
Button.displayName = "Button";
```

```typescript
// src/components/ui/input.tsx
import * as React from "react";
import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      className={cn(
        "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm",
        "ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none",
        className,
      )}
      ref={ref}
      {...props}
    />
  ),
);
Input.displayName = "Input";
```

```typescript
// src/components/ui/label.tsx
import * as React from "react";
import * as LabelPrimitive from "@radix-ui/react-label";
import { cn } from "@/lib/utils";

export const Label = React.forwardRef<
  React.ElementRef<typeof LabelPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>
>(({ className, ...props }, ref) => (
  <LabelPrimitive.Root
    ref={ref}
    className={cn("text-sm font-medium leading-none peer-disabled:cursor-not-allowed", className)}
    {...props}
  />
));
Label.displayName = LabelPrimitive.Root.displayName;
```

- [ ] 创建 `admin/src/hooks/useAuth.ts`

```typescript
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { apiFetch, getToken, setToken, clearToken } from "@/lib/api";
import type { LoginResponse, User } from "@/types/api";

interface AuthContextValue {
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      setIsLoading(false);
      return;
    }
    apiFetch<User>("/auth/me")
      .then(setUser)
      .catch(() => clearToken())
      .finally(() => setIsLoading(false));
  }, []);

  const login = async (email: string, password: string) => {
    const data = await apiFetch<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setToken(data.access_token);
    setUser(data.user);
  };

  const logout = () => {
    clearToken();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, isLoading }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return ctx;
}
```

- [ ] 创建 `admin/src/pages/Login.tsx`

```typescript
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted">
      <div className="w-full max-w-md rounded-lg border bg-card p-8 shadow-lg">
        <h1 className="mb-6 text-2xl font-bold">Ask AI 管理后台</h1>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email">邮箱</Label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">密码</Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? "登录中..." : "登录"}
          </Button>
        </form>
      </div>
    </div>
  );
}
```

- [ ] 创建 `admin/src/components/ProtectedRoute.tsx`

```typescript
import { type ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  if (isLoading) return <div className="flex min-h-screen items-center justify-center">加载中...</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}
```

- [ ] 创建 `admin/src/App.tsx`（基础路由骨架）

```typescript
import { Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/hooks/useAuth";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import Login from "@/pages/Login";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <Navigate to="/data-sources" replace />
            </ProtectedRoute>
          }
        />
      </Routes>
    </AuthProvider>
  );
}
```

- [ ] 运行 dev server 验证登录页渲染，commit

---

## Task 7: Frontend — 管理后台布局 Shell（侧边栏 + 顶栏）

**Files:**
- Create: `admin/src/components/Layout.tsx`
- Create: `admin/src/components/Sidebar.tsx`
- Create: `admin/src/components/ui/table.tsx`（shadcn table，后续 CRUD 页面复用）
- Create: `admin/src/components/ui/badge.tsx`（shadcn badge）
- Create: `admin/src/components/ui/dialog.tsx`（shadcn dialog）
- Create: `admin/src/components/ui/textarea.tsx`（shadcn textarea）
- Create: `admin/src/components/ui/select.tsx`（shadcn select）
- Modify: `admin/src/App.tsx`（添加 Layout 路由）

**Interfaces:**
- Consumes: `useAuth()`（Task 6）
- Produces: `<Layout>` 组件（含侧边栏导航 + 顶栏用户菜单）；shadcn table/badge/dialog/textarea/select 组件

**Steps:**

- [ ] 创建 `admin/src/components/Sidebar.tsx`

```typescript
import { NavLink } from "react-router-dom";
import {
  Database, Activity, Palette, Cpu, MessageSquare, Users, LayoutDashboard,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/useAuth";

const NAV_ITEMS = [
  { to: "/", icon: LayoutDashboard, label: "概览", roles: ["admin", "editor", "viewer"] },
  { to: "/data-sources", icon: Database, label: "数据源", roles: ["admin", "editor", "viewer"] },
  { to: "/sync-logs", icon: Activity, label: "同步监控", roles: ["admin", "editor", "viewer"] },
  { to: "/customizations", icon: Palette, label: "Customization", roles: ["admin", "editor", "viewer"] },
  { to: "/llm-providers", icon: Cpu, label: "LLM 供应商", roles: ["admin", "editor", "viewer"] },
  { to: "/conversations", icon: MessageSquare, label: "对话审查", roles: ["admin", "editor", "viewer"] },
  { to: "/users", icon: Users, label: "用户管理", roles: ["admin"] },
];

export function Sidebar() {
  const { user } = useAuth();
  const items = NAV_ITEMS.filter((item) => user && item.roles.includes(user.role));
  return (
    <aside className="flex w-60 flex-col border-r bg-card">
      <div className="flex h-14 items-center border-b px-6">
        <span className="text-lg font-bold">Ask AI</span>
      </div>
      <nav className="flex-1 space-y-1 p-3">
        {items.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive ? "bg-primary text-primary-foreground" : "hover:bg-muted",
              )
            }
          >
            <Icon className="h-4 w-4" />
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
```

- [ ] 创建 `admin/src/components/Layout.tsx`

```typescript
import { type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar } from "@/components/Sidebar";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";

export function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-14 items-center justify-between border-b bg-card px-6">
          <span className="text-sm text-muted-foreground">
            欢迎，{user?.name || user?.email}
          </span>
          <div className="flex items-center gap-3">
            <span className="rounded bg-muted px-2 py-0.5 text-xs">{user?.role}</span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => { logout(); navigate("/login"); }}
            >
              退出
            </Button>
          </div>
        </header>
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </div>
    </div>
  );
}
```

- [ ] 创建 shadcn table / badge / dialog / textarea / select 组件

```typescript
// src/components/ui/table.tsx
import * as React from "react";
import { cn } from "@/lib/utils";

export const Table = React.forwardRef<HTMLTableElement, React.HTMLAttributes<HTMLTableElement>>(
  ({ className, ...props }, ref) => (
    <div className="relative w-full overflow-auto">
      <table ref={ref} className={cn("w-full caption-bottom text-sm", className)} {...props} />
    </div>
  ),
);
Table.displayName = "Table";

export const TableHeader = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => <thead ref={ref} className={cn("[&_tr]:border-b", className)} {...props} />,
);
TableHeader.displayName = "TableHeader";

export const TableBody = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => <tbody ref={ref} className={cn("[&_tr:last-child]:border-0", className)} {...props} />,
);
TableBody.displayName = "TableBody";

export const TableRow = React.forwardRef<HTMLTableRowElement, React.HTMLAttributes<HTMLTableRowElement>>(
  ({ className, ...props }, ref) => (
    <tr ref={ref} className={cn("border-b transition-colors hover:bg-muted/50", className)} {...props} />
  ),
);
TableRow.displayName = "TableRow";

export const TableHead = React.forwardRef<HTMLTableCellElement, React.ThHTMLAttributes<HTMLTableCellElement>>(
  ({ className, ...props }, ref) => (
    <th ref={ref} className={cn("h-12 px-4 text-left align-middle font-medium text-muted-foreground", className)} {...props} />
  ),
);
TableHead.displayName = "TableHead";

export const TableCell = React.forwardRef<HTMLTableCellElement, React.TdHTMLAttributes<HTMLTableCellElement>>(
  ({ className, ...props }, ref) => (
    <td ref={ref} className={cn("p-4 align-middle", className)} {...props} />
  ),
);
TableCell.displayName = "TableCell";
```

```typescript
// src/components/ui/badge.tsx
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground",
        success: "bg-green-100 text-green-800",
        destructive: "bg-destructive text-destructive-foreground",
        warning: "bg-yellow-100 text-yellow-800",
        outline: "border border-input",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}
```

```typescript
// src/components/ui/textarea.tsx
import * as React from "react";
import { cn } from "@/lib/utils";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm",
        "ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none",
        className,
      )}
      {...props}
    />
  ),
);
Textarea.displayName = "Textarea";
```

- [ ] 修改 `admin/src/App.tsx` 添加 Layout 包裹

```typescript
import { Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/hooks/useAuth";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Layout } from "@/components/Layout";
import Login from "@/pages/Login";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <Layout>
                <Routes>
                  <Route path="/" element={<Navigate to="/data-sources" replace />} />
                  <Route path="/data-sources" element={<div>数据源管理（待实现）</div>} />
                  <Route path="/sync-logs" element={<div>同步监控（待实现）</div>} />
                  <Route path="/customizations" element={<div>Customization（待实现）</div>} />
                  <Route path="/llm-providers" element={<div>LLM 供应商（待实现）</div>} />
                  <Route path="/conversations" element={<div>对话审查（待实现）</div>} />
                  <Route path="/users" element={<div>用户管理（待实现）</div>} />
                </Routes>
              </Layout>
            </ProtectedRoute>
          }
        />
      </Routes>
    </AuthProvider>
  );
}
```

- [ ] 运行 dev server 验证侧边栏导航正常切换，commit

---

## Task 8: Frontend — 用户管理页面

**Files:**
- Create: `admin/src/pages/Users.tsx`
- Create: `admin/src/components/Pagination.tsx`
- Modify: `admin/src/App.tsx`（替换 Users 占位路由）
- Create: `admin/src/hooks/useUsers.ts`

**Interfaces:**
- Consumes: `apiFetch`（Task 5）；shadcn table/badge/dialog（Task 7）；`GET/POST/PATCH/DELETE /api/admin/users`（Task 4）
- Produces: `/users` 路由页面

**Steps:**

- [ ] 创建 `admin/src/hooks/useUsers.ts`

```typescript
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { User } from "@/types/api";

export function useUsers(page: number = 1, size: number = 20) {
  return useQuery({
    queryKey: ["users", page, size],
    queryFn: () => apiFetch<User[]>(`/users?page=${page}&size=${size}`),
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { email: string; password: string; role: string; name?: string }) =>
      apiFetch<User>("/users", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string; name?: string; role?: string; is_active?: boolean }) =>
      apiFetch<User>(`/users/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/users/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}
```

- [ ] 创建 `admin/src/pages/Users.tsx`

```typescript
import { useState } from "react";
import { useUsers, useCreateUser, useDeleteUser } from "@/hooks/useUsers";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { useAuth } from "@/hooks/useAuth";

export default function Users() {
  const { user: currentUser } = useAuth();
  const [page, setPage] = useState(1);
  const { data: users, isLoading } = useUsers(page);
  const createUser = useCreateUser();
  const deleteUser = useDeleteUser();
  const [showCreate, setShowCreate] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("viewer");

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    await createUser.mutateAsync({ email, password, role });
    setShowCreate(false);
    setEmail(""); setPassword(""); setRole("viewer");
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">用户管理</h1>
        <Button onClick={() => setShowCreate(!showCreate)}>新增用户</Button>
      </div>
      {showCreate && (
        <form onSubmit={handleCreate} className="flex items-end gap-3 rounded-lg border bg-card p-4">
          <div className="space-y-1">
            <Label>邮箱</Label>
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="space-y-1">
            <Label>密码</Label>
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
          </div>
          <div className="space-y-1">
            <Label>角色</Label>
            <select className="h-10 rounded-md border px-3" value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="admin">admin</option>
              <option value="editor">editor</option>
              <option value="viewer">viewer</option>
            </select>
          </div>
          <Button type="submit" disabled={createUser.isPending}>创建</Button>
        </form>
      )}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>邮箱</TableHead>
            <TableHead>姓名</TableHead>
            <TableHead>角色</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableRow><TableCell colSpan={5} className="text-center">加载中...</TableCell></TableRow>
          ) : users?.map((u) => (
            <TableRow key={u.id}>
              <TableCell>{u.email}</TableCell>
              <TableCell>{u.name || "-"}</TableCell>
              <TableCell><Badge variant={u.role === "admin" ? "default" : "outline"}>{u.role}</Badge></TableCell>
              <TableCell><Badge variant={u.is_active ? "success" : "destructive"}>{u.is_active ? "启用" : "禁用"}</Badge></TableCell>
              <TableCell>
                {u.id !== currentUser?.id && (
                  <Button variant="destructive" size="sm" onClick={() => deleteUser.mutate(u.id)}>删除</Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={() => setPage(page - 1)} disabled={page <= 1}>上一页</Button>
        <span className="text-sm">第 {page} 页</span>
        <Button variant="outline" size="sm" onClick={() => setPage(page + 1)}>下一页</Button>
      </div>
    </div>
  );
}
```

- [ ] 在 `admin/src/App.tsx` 中替换 Users 路由

```typescript
import Users from "@/pages/Users";
// ...
<Route path="/users" element={<Users />} />
```

- [ ] 验证用户列表页可显示、新增、删除用户，commit

---

## Task 9: Backend — YAML → Postgres 迁移脚本

**Files:**
- Create: `scripts/migrate_yaml_to_db.py`
- Create: `backend/services/__init__.py`
- Create: `backend/services/config_loader.py`
- Test: `tests/services/__init__.py`
- Test: `tests/services/test_config_loader.py`

**Interfaces:**
- Consumes: `load_yaml_config`（`backend/config.py`）；现有 YAML 文件（data_sources/llm_providers/system_prompt）
- Produces: `migrate_yaml_to_db.py` CLI 入口；`config_loader.load_configs_from_db(session_factory) -> (llm_router_config, customizations_map)` 函数

**Steps:**

- [ ] 创建 `backend/services/__init__.py`

```python
"""业务服务层。"""
```

- [ ] 创建 `backend/services/config_loader.py`：从 DB 加载 LLM 供应商和 Customization 配置

```python
"""从 Postgres 加载运行时配置（LLM 供应商、Customization）。

启动时调用，优先从 DB 读取；DB 为空时回退到 YAML（Phase 1 兼容）。
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import Customization, CustomizationBinding, LLMProviderModel, LLMRouting


async def load_llm_config_from_db(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[list[dict], dict[str, list[str]]] | None:
    """从 DB 加载 LLM 供应商和路由配置。

    Returns:
        (providers_list, routing_dict) 或 None（DB 为空时）。
        providers_list 格式与 llm_providers.yaml 的 providers 字段一致。
    """
    async with factory() as session:
        providers = (await session.execute(select(LLMProviderModel).where(LLMProviderModel.enabled))).scalars().all()
        if not providers:
            return None
        routing_rows = (await session.execute(select(LLMRouting))).scalars().all()

    providers_list = [
        {"id": p.id, "type": p.type, "enabled": p.enabled, "config": p.config}
        for p in providers
    ]
    routing = {r.task: list(r.chain) for r in routing_rows}
    return providers_list, routing


async def load_customizations_from_db(
    factory: async_sessionmaker[AsyncSession],
) -> dict[str, dict[str, Any]] | None:
    """从 DB 加载 Customization 配置，按 channel 绑定组织。

    Returns:
        {channel: {system_prompt, style_tone, guardrails, assistant_name, language, id}}
        或 None（DB 为空时）。
    """
    async with factory() as session:
        bindings = (await session.execute(select(CustomizationBinding))).scalars().all()
        if not bindings:
            return None
        result: dict[str, dict[str, Any]] = {}
        for b in bindings:
            cust = await session.execute(
                select(Customization).where(Customization.id == b.customization_id)
            )
            cust = cust.scalar_one_or_none()
            if cust and cust.is_active:
                full_prompt = cust.system_prompt
                if cust.style_tone:
                    full_prompt += f"\n\n## 风格语气\n{cust.style_tone}"
                if cust.guardrails:
                    full_prompt += f"\n\n## 边界规则\n{cust.guardrails}"
                result[b.channel] = {
                    "id": cust.id,
                    "system_prompt": full_prompt,
                    "assistant_name": cust.assistant_name,
                    "language": cust.language,
                }
    return result


def load_data_sources_from_yaml(yaml_data: dict) -> list[dict]:
    """从 YAML 字典读取数据源列表（用于迁移）。

    返回格式与 data_sources 表行结构一致。
    """
    sources = []
    for src in yaml_data.get("sources", []):
        sources.append({
            "id": src["id"],
            "type": src["type"],
            "product": src["product"],
            "enabled": src.get("enabled", True),
            "config": src.get("config", {}),
            "sync_interval": src.get("sync_interval", "24h"),
        })
    return sources
```

- [ ] 创建 `scripts/migrate_yaml_to_db.py`：一次性迁移 YAML → Postgres

```python
"""YAML 配置 → Postgres 一次性迁移脚本。

将 config/ 目录下的 data_sources.yaml、llm_providers.yaml、system_prompt.yaml
中的配置迁移到对应的 Postgres 表。

用法：python scripts/migrate_yaml_to_db.py
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from sqlalchemy import select

from backend.auth.crypto import encrypt_api_key
from backend.config import load_settings, load_yaml_config
from backend.db.models import (
    Customization, CustomizationBinding, DataSource,
    LLMProviderModel, LLMRouting,
)
from backend.db.session import get_engine, get_session_factory, init_db
from backend.services.config_loader import load_data_sources_from_yaml

load_dotenv()
logger = logging.getLogger(__name__)


async def migrate_data_sources(factory) -> None:
    yaml_data = load_yaml_config(Path("config/data_sources.yaml"))
    sources = load_data_sources_from_yaml(yaml_data)
    async with factory() as session:
        for s in sources:
            existing = await session.execute(select(DataSource).where(DataSource.id == s["id"]))
            if existing.scalar_one_or_none():
                continue
            session.add(DataSource(**s))
        await session.commit()
    logger.info("迁移 %d 个数据源", len(sources))


async def migrate_llm_providers(factory, encryption_key: str) -> None:
    yaml_data = load_yaml_config(Path("config/llm_providers.yaml"))
    sensitive_keys = {"api_key", "secret", "token", "password"}
    async with factory() as session:
        for prov in yaml_data.get("providers", []):
            existing = await session.execute(select(LLMProviderModel).where(LLMProviderModel.id == prov["id"]))
            if existing.scalar_one_or_none():
                continue
            cfg = dict(prov.get("config", {}))
            for k in sensitive_keys:
                if k in cfg and cfg[k]:
                    cfg[k] = encrypt_api_key(str(cfg[k]), encryption_key)
            session.add(LLMProviderModel(
                id=prov["id"], type=prov["type"], enabled=prov.get("enabled", True),
                config=cfg,
            ))
        for task, cfg in yaml_data.get("routing", {}).items():
            chain = cfg.get("chain", []) if isinstance(cfg, dict) else cfg
            existing = await session.execute(select(LLMRouting).where(LLMRouting.task == task))
            if existing.scalar_one_or_none():
                continue
            session.add(LLMRouting(task=task, chain=chain))
        await session.commit()
    logger.info("迁移 LLM 供应商和路由配置")


async def migrate_customizations(factory) -> None:
    yaml_data = load_yaml_config(Path("config/system_prompt.yaml"))
    cust_id = "default"
    async with factory() as session:
        existing = await session.execute(select(Customization).where(Customization.id == cust_id))
        if existing.scalar_one_or_none():
            return
        session.add(Customization(
            id=cust_id,
            name="默认配置",
            system_prompt=yaml_data["system_prompt"],
            style_tone=yaml_data.get("response_style"),
            guardrails=yaml_data.get("guardrails"),
            language=yaml_data.get("language", "auto"),
            assistant_name=yaml_data.get("assistant_name", "CamThink 助手"),
        ))
        session.add(CustomizationBinding(channel="widget", customization_id=cust_id))
        await session.commit()
    logger.info("迁移默认 Customization 配置")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    settings = load_settings()
    engine = get_engine(settings.postgres_dsn)
    await init_db(engine)
    factory = get_session_factory(engine)
    await migrate_data_sources(factory)
    await migrate_llm_providers(factory, settings.encryption_key)
    await migrate_customizations(factory)
    await engine.dispose()
    logger.info("迁移完成")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] 创建 `tests/services/test_config_loader.py`

```python
"""config_loader 测试。"""

import pytest
from backend.services.config_loader import load_data_sources_from_yaml


def test_load_data_sources_from_yaml():
    yaml_data = {
        "sources": [
            {"id": "test", "type": "github", "product": "test", "config": {"owner": "o"}},
        ]
    }
    sources = load_data_sources_from_yaml(yaml_data)
    assert len(sources) == 1
    assert sources[0]["id"] == "test"
    assert sources[0]["sync_interval"] == "24h"
```

- [ ] 运行迁移脚本 + 测试验证，commit

```bash
python scripts/migrate_yaml_to_db.py
pytest tests/services/ -v
```

---

## Task 10: Backend — 数据源 CRUD API + 手动同步

**Files:**
- Create: `backend/api/admin/data_sources.py`
- Modify: `backend/api/admin/router.py`
- Modify: `backend/api/admin/schemas.py`
- Test: `tests/api/admin/test_data_sources.py`

**Interfaces:**
- Consumes: `require_role`（Task 2）；`DataSource` 模型；`scripts/sync.py` 的 `_sync_one` 函数（已有 `triggered_by` 参数，无需修改）
- Produces: `GET /api/admin/data-sources`；`POST /api/admin/data-sources`；`PATCH /api/admin/data-sources/:id`；`DELETE /api/admin/data-sources/:id`；`POST /api/admin/data-sources/:id/sync`

**Steps:**

- [ ] 在 `backend/api/admin/schemas.py` 中添加数据源相关 schema

```python
class DataSourceOut(BaseModel):
    id: str
    type: str
    product: str
    enabled: bool
    config: dict
    sync_interval: str
    created_at: str
    updated_at: str


class DataSourceCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., pattern="^(github|filesystem|web_crawl|sdk)$")
    product: str = Field(..., min_length=1, max_length=50)
    enabled: bool = True
    config: dict = Field(default_factory=dict)
    sync_interval: str = Field(default="24h", pattern="^\\d+[hm]$")


class DataSourceUpdate(BaseModel):
    type: str | None = Field(default=None, pattern="^(github|filesystem|web_crawl|sdk)$")
    product: str | None = None
    enabled: bool | None = None
    config: dict | None = None
    sync_interval: str | None = Field(default=None, pattern="^\\d+[hm]$")
```

- [ ] 创建 `backend/api/admin/data_sources.py`

```python
"""数据源 CRUD + 手动同步端点。"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import DataSourceCreate, DataSourceOut, DataSourceUpdate
from backend.auth.dependencies import CurrentUser, require_role
from backend.connectors.registry import ConnectorRegistry, SourceConfig
from backend.db.models import DataSource, SyncLog

router = APIRouter(prefix="/data-sources", tags=["数据源管理"])
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]


def _to_out(ds: DataSource) -> DataSourceOut:
    return DataSourceOut(
        id=ds.id, type=ds.type, product=ds.product, enabled=ds.enabled,
        config=ds.config, sync_interval=ds.sync_interval,
        created_at=ds.created_at.isoformat() if ds.created_at else "",
        updated_at=ds.updated_at.isoformat() if ds.updated_at else "",
    )


@router.get("", response_model=list[DataSourceOut])
async def list_data_sources(
    _: Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))],
    request: Request,
) -> list[DataSourceOut]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(select(DataSource).order_by(DataSource.id))
        sources = result.scalars().all()
    return [_to_out(s) for s in sources]


@router.post("", response_model=DataSourceOut, status_code=201)
async def create_data_source(req: DataSourceCreate, _: EditorDep, request: Request) -> DataSourceOut:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        existing = await session.execute(select(DataSource).where(DataSource.id == req.id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="数据源 ID 已存在")
        ds = DataSource(**req.model_dump())
        session.add(ds)
        await session.commit()
        await session.refresh(ds)
    return _to_out(ds)


@router.patch("/{source_id}", response_model=DataSourceOut)
async def update_data_source(
    source_id: str, req: DataSourceUpdate, _: EditorDep, request: Request
) -> DataSourceOut:
    values = req.model_dump(exclude_none=True)
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        ds = await session.execute(select(DataSource).where(DataSource.id == source_id))
        ds = ds.scalar_one_or_none()
        if ds is None:
            raise HTTPException(status_code=404, detail="数据源不存在")
        for k, v in values.items():
            setattr(ds, k, v)
        await session.commit()
        await session.refresh(ds)
    return _to_out(ds)


@router.delete("/{source_id}", status_code=204)
async def delete_data_source(source_id: str, _: EditorDep, request: Request) -> None:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        ds = await session.execute(select(DataSource).where(DataSource.id == source_id))
        ds = ds.scalar_one_or_none()
        if ds is None:
            raise HTTPException(status_code=404, detail="数据源不存在")
        await session.delete(ds)
        await session.commit()


@router.post("/{source_id}/sync")
async def trigger_sync(source_id: str, _: EditorDep, request: Request) -> dict[str, str]:
    """手动触发指定数据源同步（异步执行，立即返回）。"""
    import asyncio
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        ds = await session.execute(select(DataSource).where(DataSource.id == source_id))
        ds = ds.scalar_one_or_none()
        if ds is None:
            raise HTTPException(status_code=404, detail="数据源不存在")
        if not ds.enabled:
            raise HTTPException(status_code=400, detail="数据源已禁用")
        cfg = SourceConfig(
            id=ds.id, type=ds.type, product=ds.product,
            enabled=ds.enabled, config=ds.config, sync_interval=ds.sync_interval,
        )

    async def _run() -> None:
        from scripts.sync import _sync_one
        from backend.pipeline.ingest import IngestionPipeline

        pipeline = IngestionPipeline(
            request.app.state.embedder,
            request.app.state.weaviate_client,
            class_name=request.app.state.weaviate_class_name,
        )
        await _sync_one(cfg, pipeline, factory, triggered_by="manual")

    asyncio.create_task(_run())
    return {"status": "syncing", "source_id": source_id}
```

- [ ] 在 `backend/api/admin/router.py` 中注册

```python
from backend.api.admin.data_sources import router as data_sources_router
admin_router.include_router(data_sources_router)
```

- [ ] 创建 `tests/api/admin/test_data_sources.py`

```python
"""数据源管理端点测试。"""

import pytest
from httpx import ASGITransport, AsyncClient
from backend.main import app
from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import User, DataSource
import uuid


@pytest.fixture
async def auth_headers():
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(User(id=user_id, email="admin@test.com", role="admin",
                         password_hash=hash_password("pass")))
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    async with factory() as session:
        await session.execute(DataSource.__table__.delete())
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


@pytest.mark.asyncio
async def test_create_and_list_data_source(auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/admin/data-sources", json={
            "id": "test-source", "type": "github", "product": "test",
            "config": {"owner": "camthink-ai", "repo": "test"},
        }, headers=auth_headers)
        assert resp.status_code == 201
        resp = await client.get("/api/admin/data-sources", headers=auth_headers)
        assert resp.status_code == 200
        assert any(s["id"] == "test-source" for s in resp.json())
```

- [ ] 运行测试验证，commit

```bash
pytest tests/api/admin/test_data_sources.py -v
```

---

## Task 11: Frontend — 数据源管理页面

**Files:**
- Create: `admin/src/hooks/useDataSources.ts`
- Create: `admin/src/pages/DataSources.tsx`
- Modify: `admin/src/App.tsx`

**Interfaces:**
- Consumes: `GET/POST/PATCH/DELETE /api/admin/data-sources`（Task 10）；shadcn 组件
- Produces: `/data-sources` 路由页面

**Steps:**

- [ ] 创建 `admin/src/hooks/useDataSources.ts`

```typescript
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { DataSource } from "@/types/api";

export function useDataSources() {
  return useQuery({
    queryKey: ["data-sources"],
    queryFn: () => apiFetch<DataSource[]>("/data-sources"),
  });
}

export function useCreateDataSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<DataSource> & { id: string; type: string; product: string }) =>
      apiFetch<DataSource>("/data-sources", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["data-sources"] }),
  });
}

export function useUpdateDataSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & Partial<DataSource>) =>
      apiFetch<DataSource>(`/data-sources/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["data-sources"] }),
  });
}

export function useToggleDataSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      apiFetch<DataSource>(`/data-sources/${id}`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["data-sources"] }),
  });
}

export function useTriggerSync() {
  return useMutation({
    mutationFn: (id: string) => apiFetch<{ status: string }>(`/data-sources/${id}/sync`, { method: "POST" }),
  });
}
```

- [ ] 创建 `admin/src/pages/DataSources.tsx`

```typescript
import { useState } from "react";
import { useDataSources, useCreateDataSource, useToggleDataSource, useTriggerSync } from "@/hooks/useDataSources";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";

export default function DataSources() {
  const { data: sources, isLoading } = useDataSources();
  const createDs = useCreateDataSource();
  const toggleDs = useToggleDataSource();
  const triggerSync = useTriggerSync();
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ id: "", type: "github", product: "", config_text: '{"owner":"","repo":"","branch":"main"}' });

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    await createDs.mutateAsync({
      id: form.id, type: form.type, product: form.product,
      config: JSON.parse(form.config_text),
    });
    setShowCreate(false);
    setForm({ id: "", type: "github", product: "", config_text: '{"owner":"","repo":"","branch":"main"}' });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">数据源管理</h1>
        <Button onClick={() => setShowCreate(!showCreate)}>新增数据源</Button>
      </div>
      {showCreate && (
        <form onSubmit={handleCreate} className="space-y-3 rounded-lg border bg-card p-4">
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1">
              <Label>ID</Label>
              <Input value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} required />
            </div>
            <div className="space-y-1">
              <Label>类型</Label>
              <select className="h-10 w-full rounded-md border px-3" value={form.type}
                onChange={(e) => setForm({ ...form, type: e.target.value })}>
                <option value="github">github</option>
                <option value="filesystem">filesystem</option>
                <option value="web_crawl">web_crawl</option>
                <option value="sdk">sdk</option>
              </select>
            </div>
            <div className="space-y-1">
              <Label>产品线</Label>
              <Input value={form.product} onChange={(e) => setForm({ ...form, product: e.target.value })} required />
            </div>
          </div>
          <div className="space-y-1">
            <Label>配置 (JSON)</Label>
            <Textarea className="font-mono" rows={5} value={form.config_text}
              onChange={(e) => setForm({ ...form, config_text: e.target.value })} />
          </div>
          <Button type="submit" disabled={createDs.isPending}>创建</Button>
        </form>
      )}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>ID</TableHead>
            <TableHead>类型</TableHead>
            <TableHead>产品线</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>同步间隔</TableHead>
            <TableHead>操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableRow><TableCell colSpan={6} className="text-center">加载中...</TableCell></TableRow>
          ) : sources?.map((ds) => (
            <TableRow key={ds.id}>
              <TableCell className="font-mono text-sm">{ds.id}</TableCell>
              <TableCell>{ds.type}</TableCell>
              <TableCell>{ds.product}</TableCell>
              <TableCell>
                <Badge variant={ds.enabled ? "success" : "destructive"}
                  className="cursor-pointer"
                  onClick={() => toggleDs.mutate({ id: ds.id, enabled: !ds.enabled })}>
                  {ds.enabled ? "启用" : "禁用"}
                </Badge>
              </TableCell>
              <TableCell>{ds.sync_interval}</TableCell>
              <TableCell className="space-x-2">
                <Button size="sm" variant="outline"
                  disabled={triggerSync.isPending || !ds.enabled}
                  onClick={() => triggerSync.mutate(ds.id)}>
                  同步
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
```

- [ ] 在 `App.tsx` 中替换 DataSources 占位路由，commit

---

## Task 12: Backend — 同步日志查询 API

**Files:**
- Create: `backend/api/admin/sync_logs.py`
- Modify: `backend/api/admin/router.py`
- Modify: `backend/api/admin/schemas.py`
- Test: `tests/api/admin/test_sync_logs.py`

**Interfaces:**
- Consumes: `SyncLog` 模型；`require_role`
- Produces: `GET /api/admin/sync-logs`（带过滤 + 分页）

**Steps:**

- [ ] 在 `schemas.py` 中添加 SyncLogOut 和分页响应

```python
class SyncLogOut(BaseModel):
    id: str
    source_id: str
    source_type: str
    status: str
    started_at: str
    finished_at: str | None
    duration_ms: int | None
    items_new: int
    items_updated: int
    items_deleted: int
    error_detail: str | None
    triggered_by: str


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    size: int
```

- [ ] 创建 `backend/api/admin/sync_logs.py`

```python
"""同步日志查询端点（只读）。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import SyncLogOut
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import SyncLog

router = APIRouter(prefix="/sync-logs", tags=["同步监控"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]


@router.get("")
async def list_sync_logs(
    _: ViewerDep,
    request: Request,
    source_id: str | None = Query(default=None),
    status: str | None = Query(default=None, pattern="^(success|failed|partial)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        q = select(SyncLog)
        count_q = select(func.count()).select_from(SyncLog)
        if source_id:
            q = q.where(SyncLog.source_id == source_id)
            count_q = count_q.where(SyncLog.source_id == source_id)
        if status:
            q = q.where(SyncLog.status == status)
            count_q = count_q.where(SyncLog.status == status)
        total = (await session.execute(count_q)).scalar() or 0
        result = await session.execute(
            q.order_by(SyncLog.started_at.desc()).offset((page - 1) * size).limit(size)
        )
        logs = result.scalars().all()

    items = [
        SyncLogOut(
            id=str(log.id), source_id=log.source_id, source_type=log.source_type,
            status=log.status, started_at=log.started_at.isoformat() if log.started_at else "",
            finished_at=log.finished_at.isoformat() if log.finished_at else None,
            duration_ms=log.duration_ms, items_new=log.items_new,
            items_updated=log.items_updated, items_deleted=log.items_deleted,
            error_detail=log.error_detail, triggered_by=log.triggered_by,
        )
        for log in logs
    ]
    return {"items": items, "total": total, "page": page, "size": size}
```

- [ ] 在 `router.py` 中注册 sync_logs 路由

```python
from backend.api.admin.sync_logs import router as sync_logs_router
admin_router.include_router(sync_logs_router)
```

- [ ] 创建 `tests/api/admin/test_sync_logs.py`

```python
"""同步日志端点测试。"""

import pytest, uuid
from datetime import UTC, datetime
from httpx import ASGITransport, AsyncClient
from backend.main import app
from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import User, SyncLog


@pytest.fixture
async def auth_headers():
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(User(id=user_id, email="admin@test.com", role="admin",
                         password_hash=hash_password("pass")))
        session.add(SyncLog(source_id="test", source_type="github", status="success"))
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    async with factory() as session:
        await session.execute(SyncLog.__table__.delete().where(SyncLog.source_id == "test"))
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


@pytest.mark.asyncio
async def test_list_sync_logs(auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/sync-logs", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any(log["source_id"] == "test" for log in data["items"])
```

- [ ] 运行测试验证，commit

---

## Task 13: Frontend — 同步监控仪表盘

**Files:**
- Create: `admin/src/hooks/useSyncLogs.ts`
- Create: `admin/src/pages/SyncLogs.tsx`
- Modify: `admin/src/App.tsx`

**Interfaces:**
- Consumes: `GET /api/admin/sync-logs`（Task 12）
- Produces: `/sync-logs` 路由页面

**Steps:**

- [ ] 创建 `admin/src/hooks/useSyncLogs.ts`

```typescript
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { SyncLog } from "@/types/api";

interface PaginatedSyncLogs {
  items: SyncLog[];
  total: number;
  page: number;
  size: number;
}

export function useSyncLogs(params: { sourceId?: string; status?: string; page?: number } = {}) {
  const searchParams = new URLSearchParams();
  if (params.sourceId) searchParams.set("source_id", params.sourceId);
  if (params.status) searchParams.set("status", params.status);
  searchParams.set("page", String(params.page || 1));
  return useQuery({
    queryKey: ["sync-logs", params],
    queryFn: () => apiFetch<PaginatedSyncLogs>(`/sync-logs?${searchParams}`),
    refetchInterval: 10000, // 10 秒自动刷新
  });
}
```

- [ ] 创建 `admin/src/pages/SyncLogs.tsx`

```typescript
import { useState } from "react";
import { useSyncLogs } from "@/hooks/useSyncLogs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";

export default function SyncLogs() {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const { data, isLoading } = useSyncLogs({ status: statusFilter || undefined, page });

  const statusVariant = (status: string) =>
    status === "success" ? "success" : status === "failed" ? "destructive" : "warning";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">同步监控</h1>
        <div className="flex items-center gap-2">
          <select className="h-9 rounded-md border px-3 text-sm"
            value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}>
            <option value="">全部状态</option>
            <option value="success">成功</option>
            <option value="failed">失败</option>
            <option value="partial">部分成功</option>
          </select>
        </div>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>数据源</TableHead>
            <TableHead>类型</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>开始时间</TableHead>
            <TableHead>耗时</TableHead>
            <TableHead>新增/更新/删除</TableHead>
            <TableHead>触发方式</TableHead>
            <TableHead>错误详情</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableRow><TableCell colSpan={8} className="text-center">加载中...</TableCell></TableRow>
          ) : data?.items.map((log) => (
            <TableRow key={log.id}>
              <TableCell className="font-mono text-sm">{log.source_id}</TableCell>
              <TableCell>{log.source_type}</TableCell>
              <TableCell><Badge variant={statusVariant(log.status)}>{log.status}</Badge></TableCell>
              <TableCell className="text-sm">{new Date(log.started_at).toLocaleString("zh-CN")}</TableCell>
              <TableCell>{log.duration_ms ? `${(log.duration_ms / 1000).toFixed(1)}s` : "-"}</TableCell>
              <TableCell className="text-sm">
                <span className="text-green-600">+{log.items_new}</span> /{" "}
                <span className="text-blue-600">~{log.items_updated}</span> /{" "}
                <span className="text-red-600">-{log.items_deleted}</span>
              </TableCell>
              <TableCell><Badge variant="outline">{log.triggered_by}</Badge></TableCell>
              <TableCell className="max-w-xs truncate text-sm text-destructive" title={log.error_detail || ""}>
                {log.error_detail || "-"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {data && (
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button>
          <span className="text-sm">第 {page} 页（共 {Math.ceil(data.total / data.size)} 页，{data.total} 条）</span>
          <Button variant="outline" size="sm" disabled={page * data.size >= data.total} onClick={() => setPage(page + 1)}>下一页</Button>
        </div>
      )}
    </div>
  );
}
```

- [ ] 在 `App.tsx` 中替换 SyncLogs 占位路由，commit

---

## Task 14: Backend — Customization CRUD + 渠道绑定 API

**Files:**
- Create: `backend/api/admin/customizations.py`
- Modify: `backend/api/admin/router.py`
- Modify: `backend/api/admin/schemas.py`
- Modify: `backend/pipeline/rag.py`（支持 channel_customizations）
- Modify: `backend/main.py`（lifespan 从 DB 加载 customization）
- Test: `tests/api/admin/test_customizations.py`

**Interfaces:**
- Consumes: `Customization` / `CustomizationBinding` 模型；`config_loader.load_customizations_from_db`
- Produces: `GET/POST/PATCH/DELETE /api/admin/customizations`；`GET/PUT /api/admin/customization-bindings`；`RAGOrchestrator` 支持按渠道选 system_prompt

**Steps:**

- [ ] 在 `schemas.py` 中添加 Customization schema

```python
class CustomizationOut(BaseModel):
    id: str
    name: str
    system_prompt: str
    style_tone: str | None
    guardrails: str | None
    language: str
    assistant_name: str
    is_active: bool
    version: str


class CustomizationCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    system_prompt: str = Field(..., min_length=1)
    style_tone: str | None = None
    guardrails: str | None = None
    language: str = "auto"
    assistant_name: str = "CamThink 助手"


class CustomizationUpdate(BaseModel):
    name: str | None = None
    system_prompt: str | None = None
    style_tone: str | None = None
    guardrails: str | None = None
    language: str | None = None
    assistant_name: str | None = None
    is_active: bool | None = None


class BindingOut(BaseModel):
    channel: str
    customization_id: str


class BindingUpdate(BaseModel):
    customization_id: str
```

- [ ] 创建 `backend/api/admin/customizations.py`

```python
"""Customization CRUD + 渠道绑定端点。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import (
    BindingOut, BindingUpdate, CustomizationCreate, CustomizationOut, CustomizationUpdate,
)
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import Customization, CustomizationBinding

router = APIRouter(tags=["Customization 管理"])
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]

VALID_CHANNELS = {"widget", "discord", "whatsapp", "mcp"}


@router.get("/customizations", response_model=list[CustomizationOut])
async def list_customizations(_: ViewerDep, request: Request) -> list[CustomizationOut]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(select(Customization).order_by(Customization.id))
        custs = result.scalars().all()
    return [CustomizationOut(**{c: getattr(cust, c) for c in CustomizationOut.model_fields}) for cust in custs]


@router.post("/customizations", response_model=CustomizationOut, status_code=201)
async def create_customization(req: CustomizationCreate, _: EditorDep, request: Request) -> CustomizationOut:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        existing = await session.execute(select(Customization).where(Customization.id == req.id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="配置 ID 已存在")
        cust = Customization(**req.model_dump())
        session.add(cust)
        await session.commit()
        await session.refresh(cust)
    return CustomizationOut(**{c: getattr(cust, c) for c in CustomizationOut.model_fields})


@router.patch("/customizations/{cust_id}", response_model=CustomizationOut)
async def update_customization(
    cust_id: str, req: CustomizationUpdate, _: EditorDep, request: Request
) -> CustomizationOut:
    values = req.model_dump(exclude_none=True)
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        cust = await session.execute(select(Customization).where(Customization.id == cust_id))
        cust = cust.scalar_one_or_none()
        if cust is None:
            raise HTTPException(status_code=404, detail="配置不存在")
        for k, v in values.items():
            setattr(cust, k, v)
        await session.commit()
        await session.refresh(cust)
    return CustomizationOut(**{c: getattr(cust, c) for c in CustomizationOut.model_fields})


@router.delete("/customizations/{cust_id}", status_code=204)
async def delete_customization(cust_id: str, _: EditorDep, request: Request) -> None:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        cust = await session.execute(select(Customization).where(Customization.id == cust_id))
        cust = cust.scalar_one_or_none()
        if cust is None:
            raise HTTPException(status_code=404, detail="配置不存在")
        await session.delete(cust)
        await session.commit()


@router.get("/customization-bindings", response_model=list[BindingOut])
async def list_bindings(_: ViewerDep, request: Request) -> list[BindingOut]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(select(CustomizationBinding))
        bindings = result.scalars().all()
    return [BindingOut(channel=b.channel, customization_id=b.customization_id) for b in bindings]


@router.put("/customization-bindings/{channel}")
async def update_binding(
    channel: str, req: BindingUpdate, _: EditorDep, request: Request
) -> dict[str, str]:
    if channel not in VALID_CHANNELS:
        raise HTTPException(status_code=400, detail=f"无效渠道，允许：{VALID_CHANNELS}")
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        cust = await session.execute(select(Customization).where(Customization.id == req.customization_id))
        if cust.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="配置不存在")
        binding = await session.execute(
            select(CustomizationBinding).where(CustomizationBinding.channel == channel)
        )
        binding = binding.scalar_one_or_none()
        if binding:
            binding.customization_id = req.customization_id
        else:
            session.add(CustomizationBinding(channel=channel, customization_id=req.customization_id))
        await session.commit()
    return {"status": "ok"}
```

- [ ] 修改 `backend/pipeline/rag.py` 支持按渠道选 system_prompt

```python
# RAGOrchestrator.__init__ 中新增参数：
def __init__(
    self,
    searcher: Any,
    reranker: Any,
    llm: Any,
    system_prompt: str,
    alpha: float = 0.5,
    recall_limit: int = 30,
    top_k: int = 10,
    conversation_max_turns: int = 5,
    pruner: Any = None,
    min_results_to_answer: int = 3,
    channel_customizations: dict[str, str] | None = None,  # 新增
) -> None:
    # ... 现有初始化不变 ...
    self._channel_customizations = channel_customizations or {}

# _build_messages 方法中，根据 channel 选择 system_prompt：
def _build_messages(self, query: str, context: str, language: str, history: list[dict] | None, channel: str = "widget") -> list[dict]:
    system_prompt = self._channel_customizations.get(channel, self._system_prompt)
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    # ... 后续不变 ...

# answer() 方法中（约 rag.py:283），将 _build_messages 调用改为传入 channel：
# 修改前：messages = self._build_messages(query, context, language, conversation_history)
# 修改后：
messages = self._build_messages(query, context, language, conversation_history, channel)

# stream_answer() 方法中（约 rag.py:365），同样传入 channel：
# 修改前：messages = self._build_messages(query, context, language, conversation_history)
# 修改后：
messages = self._build_messages(query, context, language, conversation_history, channel)
```

- [ ] 修改 `backend/main.py` lifespan 从 DB 加载 customization（fallback YAML）

```python
# 在 lifespan 中，加载 system_prompt 之后添加：
from backend.services.config_loader import load_customizations_from_db, load_llm_config_from_db

# 先尝试从 DB 加载 customization
channel_custs = await load_customizations_from_db(app.state.session_factory)
if channel_custs:
    system_prompt = channel_custs.get("widget", {}).get("system_prompt", prompt_config["system_prompt"])
    channel_customizations = {ch: c["system_prompt"] for ch, c in channel_custs.items()}
else:
    system_prompt = prompt_config["system_prompt"]
    channel_customizations = None

# 传给 RAGOrchestrator：
app.state.rag = RAGOrchestrator(
    searcher=searcher,
    reranker=rerank_pipeline,
    llm=router_llm,
    system_prompt=system_prompt,
    channel_customizations=channel_customizations,
)
```

- [ ] 在 `router.py` 中注册 customizations 路由

```python
from backend.api.admin.customizations import router as customizations_router
admin_router.include_router(customizations_router)
```

- [ ] 创建 `tests/api/admin/test_customizations.py` 并运行测试，commit

---

## Task 15: Frontend — Customization 管理页面

**Files:**
- Create: `admin/src/hooks/useCustomizations.ts`
- Create: `admin/src/pages/Customizations.tsx`
- Modify: `admin/src/App.tsx`

**Interfaces:**
- Consumes: `GET/POST/PATCH/DELETE /api/admin/customizations`；`GET/PUT /api/admin/customization-bindings`
- Produces: `/customizations` 路由页面（多套配置编辑 + 渠道绑定 + 预览）

**Steps:**

- [ ] 创建 `admin/src/hooks/useCustomizations.ts`

```typescript
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { Customization } from "@/types/api";

interface Binding { channel: string; customization_id: string }

export function useCustomizations() {
  return useQuery({
    queryKey: ["customizations"],
    queryFn: () => apiFetch<Customization[]>("/customizations"),
  });
}

export function useBindings() {
  return useQuery({
    queryKey: ["bindings"],
    queryFn: () => apiFetch<Binding[]>("/customization-bindings"),
  });
}

export function useCreateCustomization() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { id: string; name: string; system_prompt: string; style_tone?: string; guardrails?: string }) =>
      apiFetch<Customization>("/customizations", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["customizations"] }),
  });
}

export function useUpdateCustomization() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & Partial<Customization>) =>
      apiFetch<Customization>(`/customizations/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["customizations"] }),
  });
}

export function useUpdateBinding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ channel, customization_id }: { channel: string; customization_id: string }) =>
      apiFetch(`/customization-bindings/${channel}`, { method: "PUT", body: JSON.stringify({ customization_id }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bindings"] }),
  });
}
```

- [ ] 创建 `admin/src/pages/Customizations.tsx`

```typescript
import { useState } from "react";
import { useCustomizations, useBindings, useCreateCustomization, useUpdateCustomization, useUpdateBinding } from "@/hooks/useCustomizations";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";

const CHANNELS = ["widget", "discord", "whatsapp", "mcp"];

export default function Customizations() {
  const { data: customizations, isLoading } = useCustomizations();
  const { data: bindings } = useBindings();
  const updateCust = useUpdateCustomization();
  const updateBinding = useUpdateBinding();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<Partial<Customization>>({});

  const bindingMap = new Map((bindings || []).map((b) => [b.channel, b.customization_id]));

  const startEdit = (cust: Customization) => {
    setEditingId(cust.id);
    setEditForm({ system_prompt: cust.system_prompt, style_tone: cust.style_tone, guardrails: cust.guardrails, assistant_name: cust.assistant_name });
  };

  const handleSave = async () => {
    if (!editingId) return;
    await updateCust.mutateAsync({ id: editingId, ...editForm });
    setEditingId(null);
  };

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Customization 管理</h1>

      {/* 渠道绑定矩阵 */}
      <div className="rounded-lg border bg-card p-4">
        <h2 className="mb-3 text-lg font-semibold">渠道绑定</h2>
        <div className="grid grid-cols-4 gap-3">
          {CHANNELS.map((ch) => (
            <div key={ch} className="space-y-1">
              <Label className="text-xs uppercase text-muted-foreground">{ch}</Label>
              <select
                className="h-9 w-full rounded-md border px-2 text-sm"
                value={bindingMap.get(ch) || ""}
                onChange={(e) => updateBinding.mutate({ channel: ch, customization_id: e.target.value })}
              >
                <option value="">未绑定</option>
                {customizations?.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
          ))}
        </div>
      </div>

      {/* Customization 列表 */}
      <div className="space-y-3">
        {isLoading ? (
          <div className="text-center">加载中...</div>
        ) : customizations?.map((cust) => (
          <div key={cust.id} className="rounded-lg border bg-card p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <h3 className="font-semibold">{cust.name}</h3>
                <Badge variant="outline">{cust.id}</Badge>
                <Badge variant={cust.is_active ? "success" : "destructive"}>{cust.is_active ? "启用" : "停用"}</Badge>
              </div>
              <Button variant="outline" size="sm" onClick={() => editingId === cust.id ? setEditingId(null) : startEdit(cust)}>
                {editingId === cust.id ? "取消" : "编辑"}
              </Button>
            </div>
            {editingId === cust.id ? (
              <div className="space-y-3">
                <div className="space-y-1">
                  <Label>System Prompt</Label>
                  <Textarea className="font-mono text-sm" rows={8}
                    value={editForm.system_prompt || ""}
                    onChange={(e) => setEditForm({ ...editForm, system_prompt: e.target.value })} />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <Label>风格语气</Label>
                    <Textarea rows={3} value={editForm.style_tone || ""}
                      onChange={(e) => setEditForm({ ...editForm, style_tone: e.target.value })} />
                  </div>
                  <div className="space-y-1">
                    <Label>边界规则</Label>
                    <Textarea rows={3} value={editForm.guardrails || ""}
                      onChange={(e) => setEditForm({ ...editForm, guardrails: e.target.value })} />
                  </div>
                </div>
                <Button onClick={handleSave} disabled={updateCust.isPending}>保存</Button>
              </div>
            ) : (
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">{cust.assistant_name} · {cust.language}</p>
                <pre className="max-h-32 overflow-auto rounded bg-muted p-2 text-xs">{cust.system_prompt.slice(0, 500)}...</pre>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] 在 `App.tsx` 中替换 Customizations 占位路由，commit

---

## Task 16: Backend — LLM 供应商 CRUD + 路由 + 连通性测试

**Files:**
- Create: `backend/api/admin/llm_providers.py`
- Modify: `backend/api/admin/router.py`
- Modify: `backend/api/admin/schemas.py`
- Modify: `backend/main.py`（lifespan 从 DB 加载 LLM 配置，fallback YAML）
- Test: `tests/api/admin/test_llm_providers.py`

**Interfaces:**
- Consumes: `LLMProviderModel` / `LLMRouting` 模型；`config_loader.load_llm_config_from_db`；`LLMRegistry`；`encrypt_api_key` / `decrypt_api_key`
- Produces: `GET/POST/PATCH/DELETE /api/admin/llm-providers`；`GET/PUT /api/admin/llm-routing`；`POST /api/admin/llm-providers/:id/test`

**Steps:**

- [ ] 在 `schemas.py` 中添加 LLM schema

```python
class LLMProviderOut(BaseModel):
    id: str
    type: str
    enabled: bool
    config: dict  # api_key 已脱敏


class LLMProviderCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=50)
    type: str = Field(..., pattern="^(openai_compatible|anthropic|openai)$")
    enabled: bool = True
    config: dict  # 包含明文 api_key


class LLMProviderUpdate(BaseModel):
    type: str | None = None
    enabled: bool | None = None
    config: dict | None = None


class LLMRoutingOut(BaseModel):
    task: str
    chain: list[str]


class LLMRoutingUpdate(BaseModel):
    chain: list[str]


class ConnectivityTestResult(BaseModel):
    provider_id: str
    success: bool
    latency_ms: int | None
    error: str | None
```

- [ ] 创建 `backend/api/admin/llm_providers.py`

```python
"""LLM 供应商 CRUD + 路由 + 连通性测试端点。"""

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import (
    ConnectivityTestResult, LLMProviderCreate, LLMProviderOut,
    LLMProviderUpdate, LLMRoutingOut, LLMRoutingUpdate,
)
from backend.auth.crypto import decrypt_api_key, encrypt_api_key
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import LLMProviderModel, LLMRouting
from backend.llm.registry import LLMRegistry

router = APIRouter(tags=["LLM 供应商管理"])
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]

SENSITIVE_KEYS = {"api_key", "secret", "token", "password"}


def _mask_config(config: dict, encryption_key: str | None = None) -> dict:
    """脱敏 config 中的 api_key 等敏感字段。"""
    masked = {}
    for k, v in config.items():
        if k in SENSITIVE_KEYS:
            masked[k] = "********" if v else ""
        else:
            masked[k] = v
    return masked


def _encrypt_sensitive(config: dict, encryption_key: str) -> dict:
    """加密 config 中的 api_key 等敏感字段。"""
    encrypted = {}
    for k, v in config.items():
        if k in SENSITIVE_KEYS and v and v != "********":
            encrypted[k] = encrypt_api_key(str(v), encryption_key)
        else:
            encrypted[k] = v
    return encrypted


@router.get("/llm-providers", response_model=list[LLMProviderOut])
async def list_providers(_: ViewerDep, request: Request) -> list[LLMProviderOut]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(select(LLMProviderModel).order_by(LLMProviderModel.id))
        providers = result.scalars().all()
    return [
        LLMProviderOut(id=p.id, type=p.type, enabled=p.enabled, config=_mask_config(p.config))
        for p in providers
    ]


@router.post("/llm-providers", response_model=LLMProviderOut, status_code=201)
async def create_provider(req: LLMProviderCreate, _: EditorDep, request: Request) -> LLMProviderOut:
    settings = request.app.state.settings
    encrypted_config = _encrypt_sensitive(req.config, settings.encryption_key)
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        existing = await session.execute(select(LLMProviderModel).where(LLMProviderModel.id == req.id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="供应商 ID 已存在")
        provider = LLMProviderModel(
            id=req.id, type=req.type, enabled=req.enabled, config=encrypted_config,
        )
        session.add(provider)
        await session.commit()
    return LLMProviderOut(id=req.id, type=req.type, enabled=req.enabled, config=_mask_config(req.config))


@router.patch("/llm-providers/{provider_id}", response_model=LLMProviderOut)
async def update_provider(
    provider_id: str, req: LLMProviderUpdate, _: EditorDep, request: Request
) -> LLMProviderOut:
    settings = request.app.state.settings
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        provider = await session.execute(select(LLMProviderModel).where(LLMProviderModel.id == provider_id))
        provider = provider.scalar_one_or_none()
        if provider is None:
            raise HTTPException(status_code=404, detail="供应商不存在")
        if req.type:
            provider.type = req.type
        if req.enabled is not None:
            provider.enabled = req.enabled
        if req.config:
            merged = {**provider.config, **req.config}
            provider.config = _encrypt_sensitive(merged, settings.encryption_key)
        await session.commit()
        await session.refresh(provider)
    return LLMProviderOut(id=provider.id, type=provider.type, enabled=provider.enabled, config=_mask_config(provider.config))


@router.delete("/llm-providers/{provider_id}", status_code=204)
async def delete_provider(provider_id: str, _: EditorDep, request: Request) -> None:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        provider = await session.execute(select(LLMProviderModel).where(LLMProviderModel.id == provider_id))
        provider = provider.scalar_one_or_none()
        if provider is None:
            raise HTTPException(status_code=404, detail="供应商不存在")
        await session.delete(provider)
        await session.commit()


@router.get("/llm-routing", response_model=list[LLMRoutingOut])
async def list_routing(_: ViewerDep, request: Request) -> list[LLMRoutingOut]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(select(LLMRouting))
        routes = result.scalars().all()
    return [LLMRoutingOut(task=r.task, chain=list(r.chain)) for r in routes]


@router.put("/llm-routing/{task}")
async def update_routing(
    task: str, req: LLMRoutingUpdate, _: EditorDep, request: Request
) -> dict[str, str]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        route = await session.execute(select(LLMRouting).where(LLMRouting.task == task))
        route = route.scalar_one_or_none()
        if route:
            route.chain = req.chain
        else:
            session.add(LLMRouting(task=task, chain=req.chain))
        await session.commit()
    return {"status": "ok"}


@router.post("/llm-providers/{provider_id}/test", response_model=ConnectivityTestResult)
async def test_provider(
    provider_id: str, _: EditorDep, request: Request
) -> ConnectivityTestResult:
    settings = request.app.state.settings
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        provider = await session.execute(select(LLMProviderModel).where(LLMProviderModel.id == provider_id))
        provider = provider.scalar_one_or_none()
        if provider is None:
            raise HTTPException(status_code=404, detail="供应商不存在")

    config = dict(provider.config)
    if "api_key" in config and config["api_key"]:
        try:
            config["api_key"] = decrypt_api_key(config["api_key"], settings.encryption_key)
        except ValueError:
            pass  # 可能是明文（旧数据）

    try:
        start = time.monotonic()
        llm = LLMRegistry.create(
            provider.type,
            provider_id=provider.id,
            api_base=config.get("api_base", ""),
            api_key=config.get("api_key", ""),
            model=config.get("model", ""),
            max_tokens=config.get("max_tokens", 100),
            temperature=config.get("temperature", 0.1),
        )
        ok = await llm.health_check()
        latency = int((time.monotonic() - start) * 1000)
        return ConnectivityTestResult(provider_id=provider_id, success=ok, latency_ms=latency, error=None)
    except Exception as exc:
        return ConnectivityTestResult(provider_id=provider_id, success=False, latency_ms=None, error=str(exc))
```

- [ ] 修改 `backend/main.py` lifespan 从 DB 加载 LLM 配置

```python
# 替换 _build_llm_router 调用：
from backend.services.config_loader import load_llm_config_from_db

db_config = await load_llm_config_from_db(app.state.session_factory)
if db_config:
    providers_list, routing_dict = db_config
    providers = {}
    settings_enc = settings.encryption_key
    for prov in providers_list:
        cfg = dict(prov["config"])
        if "api_key" in cfg and cfg["api_key"]:
            try:
                cfg["api_key"] = decrypt_api_key(cfg["api_key"], settings_enc)
            except ValueError:
                pass
        provider = LLMRegistry.create(
            prov["type"],
            provider_id=prov["id"],
            api_base=cfg.get("api_base", ""),
            api_key=cfg.get("api_key", ""),
            model=cfg.get("model", ""),
            max_tokens=cfg.get("max_tokens", 4096),
            temperature=cfg.get("temperature", 0.3),
        )
        providers[prov["id"]] = provider
    router_llm = LLMRouter(providers, routing_dict)
else:
    router_llm = _build_llm_router(settings.config_dir)
```

- [ ] 在 `router.py` 中注册 llm_providers 路由；创建测试并运行，commit

---

## Task 17: Frontend — LLM 供应商管理页面

**Files:**
- Create: `admin/src/hooks/useLLMProviders.ts`
- Create: `admin/src/pages/LLMProviders.tsx`
- Modify: `admin/src/App.tsx`

**Interfaces:**
- Consumes: `GET/POST/PATCH/DELETE /api/admin/llm-providers`；`GET/PUT /api/admin/llm-routing`；`POST /api/admin/llm-providers/:id/test`
- Produces: `/llm-providers` 路由页面

**Steps:**

- [ ] 创建 `admin/src/hooks/useLLMProviders.ts`

```typescript
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { LLMProvider, LLMRouting } from "@/types/api";

export function useLLMProviders() {
  return useQuery({
    queryKey: ["llm-providers"],
    queryFn: () => apiFetch<LLMProvider[]>("/llm-providers"),
  });
}

export function useLLMRouting() {
  return useQuery({
    queryKey: ["llm-routing"],
    queryFn: () => apiFetch<LLMRouting[]>("/llm-routing"),
  });
}

export function useCreateProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { id: string; type: string; config: Record<string, unknown> }) =>
      apiFetch<LLMProvider>("/llm-providers", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["llm-providers"] }),
  });
}

export function useToggleProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      apiFetch<LLMProvider>(`/llm-providers/${id}`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["llm-providers"] }),
  });
}

export function useTestProvider() {
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<{ provider_id: string; success: boolean; latency_ms: number | null; error: string | null }>(
        `/llm-providers/${id}/test`, { method: "POST" }),
  });
}

export function useUpdateRouting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ task, chain }: { task: string; chain: string[] }) =>
      apiFetch(`/llm-routing/${task}`, { method: "PUT", body: JSON.stringify({ chain }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["llm-routing"] }),
  });
}
```

- [ ] 创建 `admin/src/pages/LLMProviders.tsx`

```typescript
import { useState } from "react";
import { useLLMProviders, useLLMRouting, useCreateProvider, useToggleProvider, useTestProvider, useUpdateRouting } from "@/hooks/useLLMProviders";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";

export default function LLMProviders() {
  const { data: providers, isLoading } = useLLMProviders();
  const { data: routing } = useLLMRouting();
  const createProvider = useCreateProvider();
  const toggleProvider = useToggleProvider();
  const testProvider = useTestProvider();
  const updateRouting = useUpdateRouting();

  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ id: "", type: "openai_compatible", config_text: '{"api_base":"","api_key":"","model":"","max_tokens":4096,"temperature":0.3}' });
  const [testResults, setTestResults] = useState<Record<string, { success: boolean; latency?: number; error?: string }>>({});

  const handleTest = async (id: string) => {
    const result = await testProvider.mutateAsync(id);
    setTestResults((prev) => ({ ...prev, [id]: result }));
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">LLM 供应商管理</h1>
        <Button onClick={() => setShowCreate(!showCreate)}>新增供应商</Button>
      </div>

      {/* 路由配置 */}
      <div className="rounded-lg border bg-card p-4">
        <h2 className="mb-3 text-lg font-semibold">路由配置</h2>
        {routing?.map((r) => (
          <div key={r.task} className="mb-2 flex items-center gap-2">
            <Badge variant="outline" className="min-w-[160px]">{r.task}</Badge>
            <Input
              className="flex-1"
              defaultValue={r.chain.join(", ")}
              onBlur={(e) => {
                const chain = e.target.value.split(",").map((s) => s.trim()).filter(Boolean);
                if (chain.join(",") !== r.chain.join(",")) {
                  updateRouting.mutate({ task: r.task, chain });
                }
              }}
            />
          </div>
        ))}
      </div>

      {/* 新增供应商表单 */}
      {showCreate && (
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            await createProvider.mutateAsync({
              id: form.id, type: form.type, config: JSON.parse(form.config_text),
            });
            setShowCreate(false);
          }}
          className="space-y-3 rounded-lg border bg-card p-4"
        >
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>ID</Label>
              <Input value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} required />
            </div>
            <div className="space-y-1">
              <Label>类型</Label>
              <select className="h-10 w-full rounded-md border px-3" value={form.type}
                onChange={(e) => setForm({ ...form, type: e.target.value })}>
                <option value="openai_compatible">openai_compatible</option>
                <option value="anthropic">anthropic</option>
                <option value="openai">openai</option>
              </select>
            </div>
          </div>
          <div className="space-y-1">
            <Label>配置 (JSON，含 api_key)</Label>
            <Textarea className="font-mono text-sm" rows={5} value={form.config_text}
              onChange={(e) => setForm({ ...form, config_text: e.target.value })} />
          </div>
          <Button type="submit" disabled={createProvider.isPending}>创建</Button>
        </form>
      )}

      {/* 供应商列表 */}
      <div className="space-y-2">
        {isLoading ? (
          <div className="text-center">加载中...</div>
        ) : providers?.map((p) => {
          const result = testResults[p.id];
          return (
            <div key={p.id} className="flex items-center justify-between rounded-lg border bg-card p-4">
              <div className="flex items-center gap-3">
                <span className="font-mono font-medium">{p.id}</span>
                <Badge variant="outline">{p.type}</Badge>
                <Badge
                  variant={p.enabled ? "success" : "destructive"}
                  className="cursor-pointer"
                  onClick={() => toggleProvider.mutate({ id: p.id, enabled: !p.enabled })}
                >
                  {p.enabled ? "启用" : "禁用"}
                </Badge>
                <span className="text-sm text-muted-foreground">model: {String(p.config.model || "-")}</span>
              </div>
              <div className="flex items-center gap-3">
                {result && (
                  <Badge variant={result.success ? "success" : "destructive"}>
                    {result.success ? `${result.latency}ms` : "失败"}
                  </Badge>
                )}
                <Button size="sm" variant="outline" disabled={testProvider.isPending}
                  onClick={() => handleTest(p.id)}>
                  测试连通性
                </Button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] 在 `App.tsx` 中替换 LLMProviders 占位路由，commit

---

## Task 18: Backend — 对话查询 API（多维过滤 + 分页）

**Files:**
- Create: `backend/api/admin/conversations.py`
- Modify: `backend/api/admin/router.py`
- Modify: `backend/api/admin/schemas.py`
- Test: `tests/api/admin/test_conversations.py`

**Interfaces:**
- Consumes: `Conversation` / `SourceClick` 模型；`require_role`
- Produces: `GET /api/admin/conversations`（多维过滤 + 分页）；`GET /api/admin/conversations/:id`（详情含点击）

**Steps:**

- [ ] 在 `schemas.py` 中添加 ConversationOut

```python
class ConversationOut(BaseModel):
    id: str
    question: str
    answer: str | None
    channel: str
    language: str | None
    sources: list
    is_answered: bool
    feedback: str | None
    response_time_ms: int | None
    created_at: str
    intent_tag: str | None
```

- [ ] 创建 `backend/api/admin/conversations.py`

```python
"""对话审查端点（多维过滤 + 分页 + 详情）。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import ConversationOut
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import Conversation, SourceClick

router = APIRouter(prefix="/conversations", tags=["对话审查"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]


@router.get("")
async def list_conversations(
    _: ViewerDep,
    request: Request,
    channel: str | None = Query(default=None),
    is_answered: bool | None = Query(default=None),
    feedback: str | None = Query(default=None, pattern="^(up|down)$"),
    intent_tag: str | None = Query(default=None),
    date_from: str | None = Query(default=None, description="ISO 日期，如 2026-01-01"),
    date_to: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        q = select(Conversation)
        count_q = select(func.count()).select_from(Conversation)
        if channel:
            q = q.where(Conversation.channel == channel)
            count_q = count_q.where(Conversation.channel == channel)
        if is_answered is not None:
            q = q.where(Conversation.is_answered == is_answered)
            count_q = count_q.where(Conversation.is_answered == is_answered)
        if feedback:
            q = q.where(Conversation.feedback == feedback)
            count_q = count_q.where(Conversation.feedback == feedback)
        if intent_tag:
            q = q.where(Conversation.intent_tag == intent_tag)
            count_q = count_q.where(Conversation.intent_tag == intent_tag)
        if date_from:
            q = q.where(Conversation.created_at >= date_from)
            count_q = count_q.where(Conversation.created_at >= date_from)
        if date_to:
            q = q.where(Conversation.created_at <= date_to)
            count_q = count_q.where(Conversation.created_at <= date_to)

        total = (await session.execute(count_q)).scalar() or 0
        result = await session.execute(
            q.order_by(Conversation.created_at.desc()).offset((page - 1) * size).limit(size)
        )
        convs = result.scalars().all()

    items = [
        ConversationOut(
            id=str(c.id), question=c.question, answer=c.answer, channel=c.channel,
            language=c.language, sources=list(c.sources or []), is_answered=c.is_answered,
            feedback=c.feedback, response_time_ms=c.response_time_ms,
            created_at=c.created_at.isoformat() if c.created_at else "",
            intent_tag=c.intent_tag,
        )
        for c in convs
    ]
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: UUID, _: ViewerDep, request: Request
) -> dict:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        conv = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
        conv = conv.scalar_one_or_none()
        if conv is None:
            raise HTTPException(status_code=404, detail="对话不存在")
        clicks = await session.execute(
            select(SourceClick).where(SourceClick.conversation_id == conversation_id)
        )
        clicks = clicks.scalars().all()
    return {
        "id": str(conv.id), "question": conv.question, "answer": conv.answer,
        "channel": conv.channel, "language": conv.language, "sources": conv.sources or [],
        "is_answered": conv.is_answered, "feedback": conv.feedback,
        "response_time_ms": conv.response_time_ms,
        "created_at": conv.created_at.isoformat() if conv.created_at else "",
        "intent_tag": conv.intent_tag,
        "clicks": [
            {"url": c.source_url, "type": c.source_type, "product": c.product,
             "clicked_at": c.clicked_at.isoformat() if c.clicked_at else ""}
            for c in clicks
        ],
    }
```

- [ ] 在 `router.py` 中注册 conversations 路由

```python
from backend.api.admin.conversations import router as conversations_router
admin_router.include_router(conversations_router)
```

- [ ] 创建 `tests/api/admin/test_conversations.py`

```python
"""对话审查端点测试。"""

import pytest, uuid
from httpx import ASGITransport, AsyncClient
from backend.main import app
from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import User, Conversation


@pytest.fixture
async def auth_headers():
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(User(id=user_id, email="admin@test.com", role="admin",
                         password_hash=hash_password("pass")))
        session.add(Conversation(question="test question", channel="widget", is_answered=True))
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    async with factory() as session:
        await session.execute(Conversation.__table__.delete().where(Conversation.question == "test question"))
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


@pytest.mark.asyncio
async def test_list_conversations_filtered(auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/conversations?channel=widget&is_answered=true",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert all(c["channel"] == "widget" for c in data["items"])
```

- [ ] 运行测试验证，commit

---

## Task 19: Backend — Intent 自动标注

**Files:**
- Create: `backend/services/intent_tagger.py`
- Modify: `backend/api/admin/conversations.py`（新增标注端点）
- Test: `tests/services/test_intent_tagger.py`

**Interfaces:**
- Consumes: `Conversation` 模型；`LLMRouter` / `LLMProvider`（从 `app.state.llm` 获取）
- Produces: `POST /api/admin/conversations/:id/tag`；`POST /api/admin/conversations/batch-tag`

**Steps:**

- [ ] 创建 `backend/services/intent_tagger.py`

```python
"""LLM Intent 自动标注服务。

用现有的 LLM 基础设施对对话问题做意图分类。
"""

import json
import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import Conversation

logger = logging.getLogger(__name__)

INTENT_CATEGORIES = [
    "product_spec",      # 产品规格咨询
    "tech_support",      # 技术支持/故障排查
    "getting_started",   # 入门/快速开始
    "pricing",           # 价格/购买
    "comparison",        # 产品对比
    "api_reference",     # API/SDK 参考
    "documentation",     # 文档查询
    "other",             # 其他
]

INTENT_PROMPT = f"""请分析以下用户问题，从这些意图类别中选择最合适的一个：
{chr(10).join(f"- {c}" for c in INTENT_CATEGORIES)}

只返回类别名称（不解释、不加引号）。

用户问题：{{question}}"""


async def tag_single(
    conversation_id: str,
    question: str,
    llm: Any,
) -> str:
    """对单个问题做意图标注。

    Args:
        conversation_id: 对话 ID（用于日志）。
        question: 用户问题文本。
        llm: LLMProvider 或 LLMRouter 实例。

    Returns:
        意图标签字符串。
    """
    messages = [
        {"role": "system", "content": "你是一个意图分类器，只输出类别名称。"},
        {"role": "user", "content": INTENT_PROMPT.format(question=question)},
    ]
    try:
        resp = await llm.generate(messages, task="query_decomposition", max_tokens=20, temperature=0.0)
        tag = resp.content.strip().lower().replace(" ", "_")
        if tag not in INTENT_CATEGORIES:
            tag = "other"
        return tag
    except Exception:
        logger.exception("Intent 标注失败 conversation_id=%s", conversation_id)
        return "other"


async def tag_batch(
    factory: async_sessionmaker[AsyncSession],
    llm: Any,
    batch_size: int = 50,
) -> int:
    """批量标注未标注的对话。

    Args:
        factory: 异步会话工厂。
        llm: LLM 实例。
        batch_size: 每批处理数量。

    Returns:
        成功标注的对话数。
    """
    async with factory() as session:
        result = await session.execute(
            select(Conversation)
            .where(Conversation.intent_tag.is_(None))
            .limit(batch_size)
        )
        untagged = result.scalars().all()

    count = 0
    for conv in untagged:
        tag = await tag_single(str(conv.id), conv.question, llm)
        async with factory() as session:
            await session.execute(
                update(Conversation).where(Conversation.id == conv.id).values(intent_tag=tag)
            )
            await session.commit()
        count += 1
    logger.info("批量标注完成：%d 条对话", count)
    return count
```

- [ ] 在 `conversations.py` 中添加标注端点

```python
from backend.services.intent_tagger import tag_batch, tag_single

@router.post("/{conversation_id}/tag")
async def tag_conversation(
    conversation_id: UUID, _: Annotated[CurrentUser, Depends(require_role("admin", "editor"))],
    request: Request,
) -> dict[str, str]:
    """手动标注单个对话的 intent。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    llm = request.app.state.llm
    async with factory() as session:
        conv = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
        conv = conv.scalar_one_or_none()
        if conv is None:
            raise HTTPException(status_code=404, detail="对话不存在")
    tag = await tag_single(str(conversation_id), conv.question, llm)
    async with factory() as session:
        await session.execute(
            update(Conversation).where(Conversation.id == conversation_id).values(intent_tag=tag)
        )
        await session.commit()
    return {"intent_tag": tag}


@router.post("/batch-tag")
async def batch_tag_conversations(
    _: Annotated[CurrentUser, Depends(require_role("admin", "editor"))],
    request: Request, batch_size: int = Query(default=50, ge=1, le=500),
) -> dict:
    """批量标注未标注的对话。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    llm = request.app.state.llm
    count = await tag_batch(factory, llm, batch_size)
    return {"tagged_count": count}
```

- [ ] 创建 `tests/services/test_intent_tagger.py`

```python
"""Intent 标注服务测试。"""

import pytest
from unittest.mock import AsyncMock
from backend.services.intent_tagger import tag_single, INTENT_CATEGORIES


@pytest.mark.asyncio
async def test_tag_single_returns_valid_category():
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=type("R", (), {"content": "tech_support"})())
    tag = await tag_single("conv-1", "如何配置 NE503 的网络？", llm)
    assert tag in INTENT_CATEGORIES
    assert tag == "tech_support"


@pytest.mark.asyncio
async def test_tag_single_fallback_on_error():
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=Exception("LLM 不可用"))
    tag = await tag_single("conv-2", "test question", llm)
    assert tag == "other"
```

- [ ] 运行测试验证，commit

---

## Task 20: Frontend — 对话审查页面

**Files:**
- Create: `admin/src/hooks/useConversations.ts`
- Create: `admin/src/pages/Conversations.tsx`
- Modify: `admin/src/App.tsx`

**Interfaces:**
- Consumes: `GET /api/admin/conversations`（Task 18）；`POST /api/admin/conversations/:id/tag`（Task 19）
- Produces: `/conversations` 路由页面（列表 + 多维过滤 + 详情侧栏 + intent 标签）

**Steps:**

- [ ] 创建 `admin/src/hooks/useConversations.ts`

```typescript
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { Conversation } from "@/types/api";

interface ConversationFilters {
  channel?: string;
  is_answered?: boolean;
  feedback?: string;
  intent_tag?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
}

interface PaginatedConversations {
  items: Conversation[];
  total: number;
  page: number;
  size: number;
}

export function useConversations(filters: ConversationFilters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== "") params.set(k, String(v));
  });
  return useQuery({
    queryKey: ["conversations", filters],
    queryFn: () => apiFetch<PaginatedConversations>(`/conversations?${params}`),
  });
}

export function useConversationDetail(id: string | null) {
  return useQuery({
    queryKey: ["conversation", id],
    queryFn: () => apiFetch<{ id: string; question: string; answer: string; clicks: unknown[] }>(`/conversations/${id}`),
    enabled: !!id,
  });
}

export function useTagConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<{ intent_tag: string }>(`/conversations/${id}/tag`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["conversations"] }),
  });
}

export function useBatchTag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<{ tagged_count: number }>("/conversations/batch-tag", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["conversations"] }),
  });
}
```

- [ ] 创建 `admin/src/pages/Conversations.tsx`

```typescript
import { useState } from "react";
import { useConversations, useConversationDetail, useTagConversation, useBatchTag } from "@/hooks/useConversations";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";

const INTENT_LABELS: Record<string, string> = {
  product_spec: "产品规格", tech_support: "技术支持", getting_started: "入门指南",
  pricing: "价格咨询", comparison: "产品对比", api_reference: "API 参考",
  documentation: "文档查询", other: "其他",
};

export default function Conversations() {
  const [filters, setFilters] = useState<{ channel?: string; is_answered?: boolean; feedback?: string; page: number }>({ page: 1 });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { data, isLoading } = useConversations(filters);
  const { data: detail } = useConversationDetail(selectedId);
  const tagMutation = useTagConversation();
  const batchTag = useBatchTag();

  return (
    <div className="flex h-full gap-4">
      {/* 主列表 */}
      <div className="flex-1 space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">对话审查</h1>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => batchTag.mutate()} disabled={batchTag.isPending}>
              批量标注 Intent
            </Button>
          </div>
        </div>

        {/* 过滤栏 */}
        <div className="flex flex-wrap gap-3">
          <select className="h-9 rounded-md border px-3 text-sm"
            value={filters.channel || ""}
            onChange={(e) => setFilters({ ...filters, channel: e.target.value || undefined, page: 1 })}>
            <option value="">全部渠道</option>
            <option value="widget">widget</option>
            <option value="discord">discord</option>
          </select>
          <select className="h-9 rounded-md border px-3 text-sm"
            value={filters.is_answered === undefined ? "" : String(filters.is_answered)}
            onChange={(e) => setFilters({ ...filters, is_answered: e.target.value === "" ? undefined : e.target.value === "true", page: 1 })}>
            <option value="">全部状态</option>
            <option value="true">已回答</option>
            <option value="false">未回答</option>
          </select>
          <select className="h-9 rounded-md border px-3 text-sm"
            value={filters.feedback || ""}
            onChange={(e) => setFilters({ ...filters, feedback: e.target.value || undefined, page: 1 })}>
            <option value="">全部反馈</option>
            <option value="up">赞</option>
            <option value="down">踩</option>
          </select>
        </div>

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>问题</TableHead>
              <TableHead>渠道</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>反馈</TableHead>
              <TableHead>Intent</TableHead>
              <TableHead>耗时</TableHead>
              <TableHead>时间</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow><TableCell colSpan={7} className="text-center">加载中...</TableCell></TableRow>
            ) : data?.items.map((conv) => (
              <TableRow key={conv.id} className="cursor-pointer" onClick={() => setSelectedId(conv.id)}>
                <TableCell className="max-w-xs truncate">{conv.question}</TableCell>
                <TableCell><Badge variant="outline">{conv.channel}</Badge></TableCell>
                <TableCell><Badge variant={conv.is_answered ? "success" : "warning"}>{conv.is_answered ? "已回答" : "拒答"}</Badge></TableCell>
                <TableCell>
                  {conv.feedback === "up" && <span className="text-green-600">赞</span>}
                  {conv.feedback === "down" && <span className="text-red-600">踩</span>}
                  {!conv.feedback && "-"}
                </TableCell>
                <TableCell>
                  {conv.intent_tag ? (
                    <Badge variant="outline">{INTENT_LABELS[conv.intent_tag] || conv.intent_tag}</Badge>
                  ) : (
                    <span className="text-muted-foreground">-</span>
                  )}
                </TableCell>
                <TableCell>{conv.response_time_ms ? `${(conv.response_time_ms / 1000).toFixed(1)}s` : "-"}</TableCell>
                <TableCell className="text-sm text-muted-foreground">{new Date(conv.created_at).toLocaleString("zh-CN")}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>

        {data && (
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" disabled={filters.page <= 1}
              onClick={() => setFilters({ ...filters, page: filters.page - 1 })}>上一页</Button>
            <span className="text-sm">第 {filters.page} 页（共 {Math.ceil(data.total / data.size)} 页，{data.total} 条）</span>
            <Button variant="outline" size="sm" disabled={filters.page * data.size >= data.total}
              onClick={() => setFilters({ ...filters, page: filters.page + 1 })}>下一页</Button>
          </div>
        )}
      </div>

      {/* 详情侧栏 */}
      {selectedId && detail && (
        <div className="w-96 space-y-3 rounded-lg border bg-card p-4 overflow-auto">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">对话详情</h2>
            <Button variant="ghost" size="sm" onClick={() => setSelectedId(null)}>关闭</Button>
          </div>
          <div>
            <h3 className="text-sm font-medium text-muted-foreground">问题</h3>
            <p className="mt-1 text-sm">{detail.question}</p>
          </div>
          <div>
            <h3 className="text-sm font-medium text-muted-foreground">回答</h3>
            <p className="mt-1 whitespace-pre-wrap text-sm">{detail.answer || "(无回答)"}</p>
          </div>
          {detail.clicks && (detail.clicks as unknown[]).length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground">来源点击 ({(detail.clicks as unknown[]).length})</h3>
              <ul className="mt-1 space-y-1">
                {(detail.clicks as Array<{ url: string; type: string }>).map((c, i) => (
                  <li key={i} className="text-xs">
                    <Badge variant="outline">{c.type}</Badge>{" "}
                    <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">{c.url}</a>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <Button
            variant="outline" size="sm"
            onClick={() => tagMutation.mutate(selectedId)}
            disabled={tagMutation.isPending}
          >
            标注 Intent
          </Button>
          {tagMutation.data && (
            <Badge variant="success">{INTENT_LABELS[tagMutation.data.intent_tag] || tagMutation.data.intent_tag}</Badge>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] 在 `App.tsx` 中替换 Conversations 占位路由，commit

---

## Task 21: 生产部署 — FastAPI 挂载 Admin StaticFiles

**Files:**
- Modify: `backend/main.py`

**Interfaces:**
- Consumes: `admin/dist/` 构建产物（Task 5-20 前端构建结果）
- Produces: FastAPI 在 `/admin/` 路径下托管 admin SPA

**Steps:**

- [ ] 在 `backend/main.py` 中添加 StaticFiles 挂载

```python
from fastapi.staticfiles import StaticFiles
from pathlib import Path

# 在 app.include_router(admin_router) 之后添加：
_admin_dist = Path(__file__).resolve().parent.parent / "admin" / "dist"
if _admin_dist.exists():
    app.mount("/admin", StaticFiles(directory=str(_admin_dist), html=True), name="admin")
```

- [ ] 在 admin 前端添加 basename 路由配置

```typescript
// admin/src/main.tsx 修改 BrowserRouter：
<BrowserRouter basename="/admin">
```

- [ ] 构建前端并验证

```bash
cd admin && npm run build
# 验证 http://localhost:8000/admin/ 返回 index.html
```

- [ ] commit

---

## 风险与注意事项

### 1. users 表 password_hash 列迁移
Phase 1 的 `init_db` 使用 `Base.metadata.create_all`，不会自动为已有表添加新列。如果 Postgres 中 `users` 表已存在（Phase 1 已建表），需要手动执行 `ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)` 或用 `scripts/create_admin_user.py`（内部先执行该 DDL）。在开发环境重置 DB 时可删除表后重新 `create_all`。

### 2. API key 加密兼容性
迁移脚本 `migrate_yaml_to_db.py` 在写入 DB 时直接加密 api_key（调用 `encrypt_api_key`）。`config_loader.py` 的 `load_llm_config_from_db` 有 fallback 解密逻辑（解密失败则当明文处理），保证兼容旧数据。

### 3. LLM 配置热重载
`main.py` lifespan 在启动时从 DB 加载 LLM/customization 配置注入 `RAGOrchestrator`，修改配置后需重启服务生效。如需热重载，Phase 3 可在 admin API 中重建 `app.state.rag` 实例。

### 4. 手动同步的异步执行
`POST /api/admin/data-sources/:id/sync` 使用 `asyncio.create_task` 在后台执行，立即返回。同步状态通过 sync_log 轮询获取（前端 10 秒自动刷新）。在生产环境多 worker 下，`create_task` 仅在当前 worker 生效，但同步任务只需执行一次即可。

### 5. 与 Phase 1 代码的衔接
- `backend/main.py`：lifespan 中增加从 DB 加载配置的逻辑（DB 空 → fallback YAML）
- `backend/pipeline/rag.py`：`RAGOrchestrator` 新增 `channel_customizations` 参数（向后兼容，默认 None）
- `backend/db/models.py`：`User` 模型增加 `password_hash` 列
- `backend/config.py`：`Settings` 增加 `jwt_secret` / `encryption_key`
- `scripts/sync.py`：无改动（已有 `triggered_by` 参数），数据源管理页面的手动同步直接复用 `_sync_one` 函数

### 6. CORS 配置
开发环境通过 Vite proxy（`/api → http://localhost:8000`）避免 CORS 问题。生产环境 admin SPA 由 FastAPI 同源托管，无 CORS 问题。
