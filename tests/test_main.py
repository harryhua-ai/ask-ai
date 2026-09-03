"""FastAPI 最小入口与配置兼容性测试。"""

from pathlib import Path
from typing import IO

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config import load_yaml_config


@pytest.mark.unit
async def test_health_returns_ok() -> None:
    """健康检查:status 兼容既有消费者 + 发布身份字段 truthful(#10)。

    使用 ASGITransport(不触发 lifespan),避免依赖 Postgres / Weaviate。
    测试环境 APP_MODE≠prod 且无 RELEASE.json → dev 兜底身份(0.0.0-dev)。
    """
    from backend.main import app
    from backend.release import get_release_identity

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    rid = get_release_identity()
    # 既有消费者契约:status 字段保持
    assert body["status"] == "ok"
    # #10 扩展字段 = 运行时 release authority(非前端/环境可变值)
    assert body["version"] == rid.version
    assert body["git_sha"] == rid.git_sha
    assert body["app_mode"] == rid.app_mode


@pytest.mark.unit
def test_load_yaml_config_uses_utf8(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """YAML 配置应在不同系统默认编码下始终按 UTF-8 读取。"""
    config_path = tmp_path / "system_prompt.yaml"
    config_path.write_text("title: 中文助手\n", encoding="utf-8")
    original_open = Path.open

    def checked_open(path: Path, *args: object, **kwargs: object) -> IO[str]:
        assert kwargs.get("encoding") == "utf-8"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", checked_open)

    assert load_yaml_config(config_path) == {"title": "中文助手"}
