"""系统信息端点(Issue #10 版本与发布治理;Issue #7 系统运行时可观测)。

只读;#10 值全部来自进程启动时一次性加载的 release identity
(backend.release,RELEASE.json 权威),无环境变量 dump、无密钥。
#7 系统运行时快照(GET /runtime)由 backend.services.host_runtime 只读采集
(真实采集 + 显式不可得语义,每项 as_of),同样 GET-only、零操作控制。
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from backend.auth.dependencies import CurrentUser, require_role
from backend.release import get_release_identity
from backend.services.host_runtime import collect_system_runtime

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


@router.get("/runtime")
async def get_system_runtime(
    _: Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))],
    request: Request,
) -> dict[str, Any]:
    """系统运行时只读快照(Issue #7)。

    一次返回四组事实,每项观测 = {available, value, reason, as_of}:

    - ``host``:hostname / OS / 内核 / uptime;
    - ``resources``:CPU(核数/利用率/loadavg)、内存/swap、磁盘(部署卷);
    - ``accelerator``:GPU(利用率/显存/温度)+ 驱动/CUDA 版本;无 GPU 环境
      available=False + 原因(非错误、非空壳);
    - ``service``:release 身份(复用 #10 权威)+ health + model-runtime
      快照(devices/policies/runtime_plan/capacity,未就绪 → 显式 unavailable)。

    全程只读采集(stdlib + nvidia-smi 只读查询),平台不可得项显示显式
    不可得 + 原因,绝不虚构值;无 env/secrets 暴露;无任何操作控制。
    """
    return collect_system_runtime(
        model_runtime=getattr(request.app.state, "model_runtime", None)
    )
