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
    sync_interval: str = Field(default="24h", pattern=r"^\d+[hm]$")


class DataSourceUpdate(BaseModel):
    type: str | None = Field(default=None, pattern="^(github|filesystem|web_crawl|sdk)$")
    product: str | None = None
    enabled: bool | None = None
    config: dict | None = None
    sync_interval: str | None = Field(default=None, pattern=r"^\d+[hm]$")
