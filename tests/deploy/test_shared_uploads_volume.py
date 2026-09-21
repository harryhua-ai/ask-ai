"""Issue #100 AC1:上传数据源 = 一份持久共享上传权威(部署拓扑契约)。

生产事故(2026-09-21):上传端点写入 ``/app/data/uploads/...`` 只落在
backend 容器可写层 —— 无任何持久卷;sync-executor/sync-cron 是**不同容器**,
同一相对路径解析后目录不存在 ⇒ 上传语料对同步执行面不可见,且 backend
容器重建即丢失(权威知识丢失风险)。

契约(#100 AC1):backend 写入的上传权威字节必须持久(容器重建存活)且
对 backend、sync-executor、scheduled sync(sync-cron)与一次性 sync 作业
同一可见。实现 = 共享命名卷挂载到统一容器路径 ``/app/data/uploads``,
四个 backend 类服务(共用 x-backend-base anchor)必须全部携带。

验证方式:静态解析 prod compose(deployment/compose configuration
verification,#100 validation 指定通道);生产挂载动作属部署授权范畴,
不在本 Issue 生产变更范围内(契约:无生产 mutation)。
"""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PROD_COMPOSE = REPO / "deploy" / "prod" / "docker-compose.yml"

UPLOAD_MOUNT_CONTAINER_PATH = "/app/data/uploads"
# 挂载同一共享卷的全部 backend 类服务(prod compose x-backend-base 覆盖面)
BACKEND_CLASS_SERVICES = ("backend", "sync", "sync-executor", "sync-cron")

yaml = pytest.importorskip("yaml")


def _prod_compose() -> dict:
    return yaml.safe_load(PROD_COMPOSE.read_text(encoding="utf-8"))


def _service_upload_mounts(compose: dict) -> dict[str, list[str]]:
    """各服务的 uploads 挂载声明(短/长语法均归一为容器路径列表)。"""
    result: dict[str, list[str]] = {}
    for name in BACKEND_CLASS_SERVICES:
        service = compose.get("services", {}).get(name)
        if service is None:
            result[name] = []
            continue
        mounts: list[str] = []
        for vol in service.get("volumes", []) or []:
            if isinstance(vol, dict):
                target = str(vol.get("target", ""))
            else:
                parts = str(vol).split(":")
                target = parts[1] if len(parts) >= 2 else ""
            if target.rstrip("/") == UPLOAD_MOUNT_CONTAINER_PATH:
                mounts.append(target)
        result[name] = mounts
    return result


def test_upload_root_constant_is_single_authority_under_shared_subtree():
    """写侧权威:上传落盘根 = 统一常量,且位于共享卷子树 ``/app/data/uploads``。"""
    from backend.api.admin.data_sources import UPLOADS_CORPUS_ROOT

    assert UPLOADS_CORPUS_ROOT == Path("data/uploads/data-sources")
    # 镜像 CWD = /app;共享卷挂 /app/data/uploads ⇒ 上传权威整体在共享卷内
    assert UPLOADS_CORPUS_ROOT.as_posix().startswith("data/uploads")


def test_prod_compose_mounts_shared_uploads_volume_on_every_backend_service():
    """AC1 主链:四个 backend 类服务必须挂**同一** uploads 共享卷。"""
    compose = _prod_compose()
    top = compose.get("volumes", {}) or {}
    uploads_volumes = [
        name for name, attrs in top.items() if "uploads" in str(name)
    ]
    assert uploads_volumes, (
        "prod compose 必须声明 uploads 持久共享卷(现状缺失 = 上传只落 backend "
        "容器可写层,重建即丢失且对 sync 执行面不可见)"
    )

    mounts = _service_upload_mounts(compose)
    for name in BACKEND_CLASS_SERVICES:
        assert mounts.get(name), (
            f"服务 {name} 必须挂载共享 uploads 卷到 {UPLOAD_MOUNT_CONTAINER_PATH}"
            f"(现状未挂载 ⇒ 执行面看不到上传语料,#100 AC1)"
        )


def test_prod_compose_all_services_share_one_uploads_volume():
    """同一权威:各服务挂的必须是**同一个**卷(多卷 = 多份权威 = 契约破坏)。"""
    compose = _prod_compose()
    volume_names = set()
    for name in BACKEND_CLASS_SERVICES:
        service = compose["services"][name]
        for vol in service.get("volumes", []) or []:
            raw = vol if isinstance(vol, str) else f"{vol.get('source', '')}:{vol.get('target', '')}"
            parts = raw.split(":")
            if len(parts) >= 2 and parts[1].rstrip("/") == UPLOAD_MOUNT_CONTAINER_PATH:
                volume_names.add(parts[0])
    assert len(volume_names) == 1, (
        f"uploads 权威必须单一共享卷,发现多个:{sorted(volume_names)}"
    )
