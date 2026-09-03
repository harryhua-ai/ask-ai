"""系统信息端点(Issue #10 版本与发布治理)。

只读;值全部来自进程启动时一次性加载的 release identity
(backend.release,RELEASE.json 权威),无环境变量 dump、无密钥。
Issue #7 硬件可观测性后续可在同一 router 下追加端点,不影响本契约。
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from backend.auth.dependencies import CurrentUser, require_role
from backend.release import get_release_identity

router = APIRouter(prefix="/system", tags=["系统信息"])


@router.get("/release")
async def get_release(
    _: Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))],
) -> dict[str, Any]:
    """当前运行镜像的发布身份(与 /health 同一权威来源)。

    - ``version``:SemVer 发布版本(镜像构建 tag,无 v 前缀)
    - ``git_sha``:精确源码 commit
    - ``built_at``:CI 构建时间(权威构建钟,非浏览器时间)
    - ``app_mode``:production / development
    - ``image``:构建产物镜像引用
    - ``ci_run_id``:CI 运行 id(可用时返回;可据此拼 Actions 链接)
    - ``source``:manifest(正式) | fallback(开发兜底)
    """
    rid = get_release_identity()
    return {
        "version": rid.version,
        "git_sha": rid.git_sha,
        "built_at": rid.built_at,
        "app_mode": rid.app_mode,
        "image": rid.image,
        "ci_run_id": rid.ci_run_id,
        "source": rid.source,
    }
