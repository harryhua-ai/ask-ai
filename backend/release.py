"""Release identity(Issue #10 版本与发布治理)。

权威版本模型(冻结):

    git tag / exact commit
      → CI 生成不可变 RELEASE.json(镜像构建期)
      → 镜像内 COPY(/app/RELEASE.json)
      → backend 启动一次性加载为本进程级 release identity
      → /health 与 GET /api/admin/system/release 直呈

- **无 DB 版本权威、无可变 env 版本权威、无前端版本常量**;
  OCI revision label 是独立交叉核对证据,不是应用权威。
- **fail-closed**:`APP_MODE=prod` 下 manifest 缺失 → 启动即失败
  (生产镜像不得假冒正式版本);**任何模式下,存在但非法的 manifest
  一律 raise** —— 坏文件 ≠ 缺失,绝不静默降级成假版本。
- 开发兜底仅限:非 prod 且文件缺失。``version="0.0.0-dev"``、
  ``source="fallback"``,git_sha 取本地 ``git rev-parse``(尽力而为),
  绝不产出看似正式的版本号。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# 与 CI/部署契约对齐的 manifest 默认落点:镜像 WORKDIR=/app(仓库根)。
# ASKAI_RELEASE_FILE 可显式覆盖(测试/非常规布局)。
_RELEASE_FILE = Path(
    os.environ.get(
        "ASKAI_RELEASE_FILE",
        str(Path(__file__).resolve().parent.parent / "RELEASE.json"),
    )
)

# 官方 SemVer( semver.org #tab-regex );输入允许 build tag 的可选 v 前缀,
# 存储归一为无前缀。
_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)
# CI 传 full 40 位 sha;宽容 7..40 位十六进制(git 短 sha 亦可核验)
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")

_REQUIRED_FIELDS = ("version", "git_sha", "built_at", "image")


class ReleaseIdentityError(RuntimeError):
    """RELEASE.json 缺失(prod fail-closed)或非法(任何模式)。"""


@dataclass(frozen=True)
class ReleaseIdentity:
    """进程级不可变发布身份。"""

    version: str
    git_sha: str
    built_at: str | None
    app_mode: str  # "production" | "development"
    image: str | None
    ci_run_id: str | None
    source: str  # "manifest" | "fallback"


def _normalize_version(raw: str, field: str = "version") -> str:
    value = (raw or "").strip()
    if value.startswith(("v", "V")) and _SEMVER_RE.match(value[1:]):
        value = value[1:]
    if not _SEMVER_RE.match(value):
        raise ReleaseIdentityError(f"RELEASE.json {field} 非法 SemVer: {raw!r}")
    return value


def _normalize_sha(raw: str) -> str:
    value = (raw or "").strip().lower()
    if not _SHA_RE.match(value):
        raise ReleaseIdentityError(f"RELEASE.json git_sha 非法(期望 git commit hex): {raw!r}")
    return value


def _current_app_mode() -> str:
    """APP_MODE env(prod/其它)→ 归一 production/development。"""
    return "production" if os.environ.get("APP_MODE", "dev") == "prod" else "development"


def load_release_identity(path: Path, *, app_mode: str) -> ReleaseIdentity:
    """读取并校验 RELEASE.json(纯函数,供测试/工具复用)。

    Raises:
        ReleaseIdentityError: prod 且文件缺失;或文件存在但缺失必需字段/
            非法 JSON/非法 SemVer/非法 git_sha(任何模式)。
    """
    if not path.is_file():
        if app_mode == "production":
            raise ReleaseIdentityError(
                f"RELEASE.json 缺失({path}):生产镜像必须内嵌构建期生成的"
                "发布清单(fail-closed),禁止无版本身份的正式部署"
            )
        return ReleaseIdentity(
            version="0.0.0-dev",
            git_sha=_local_git_sha(),
            built_at=None,
            app_mode=app_mode,
            image=None,
            ci_run_id=None,
            source="fallback",
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ReleaseIdentityError(f"RELEASE.json 不是合法 JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ReleaseIdentityError("RELEASE.json 顶层必须是 JSON object")

    missing = [k for k in _REQUIRED_FIELDS if not str(raw.get(k) or "").strip()]
    if missing:
        raise ReleaseIdentityError(f"RELEASE.json 缺失必需字段: {', '.join(missing)}")

    version = _normalize_version(str(raw["version"]))
    git_sha = _normalize_sha(str(raw["git_sha"]))
    ci_run_id = str(raw.get("ci_run_id") or "").strip() or None
    return ReleaseIdentity(
        version=version,
        git_sha=git_sha,
        built_at=str(raw["built_at"]).strip(),
        app_mode=app_mode,
        image=str(raw["image"]).strip(),
        ci_run_id=ci_run_id,
        source="manifest",
    )


def _local_git_sha() -> str:
    """本地开发兜底:尽力取当前 commit;不在 git 仓内则显式 unknown。"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return _normalize_sha(out.stdout.strip())
    except Exception:  # noqa: BLE001 - 兜底路径永不抛错
        return "unknown"


@lru_cache(maxsize=1)
def _cached_identity(cache_key: str, app_mode: str) -> ReleaseIdentity:
    """进程级一次性加载(cache_key 绑定文件路径;身份加载后不可变)。"""
    return load_release_identity(Path(cache_key), app_mode=app_mode)


def get_release_identity() -> ReleaseIdentity:
    """本进程 release identity(启动时首次调用后缓存;prod 缺失即抛)。"""
    return _cached_identity(str(_RELEASE_FILE), _current_app_mode())


def reset_release_identity_cache() -> None:
    """测试专用:清空进程级缓存(生产代码不得调用)。"""
    _cached_identity.cache_clear()
