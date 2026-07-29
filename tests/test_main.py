"""FastAPI 最小入口与配置兼容性测试。"""

from pathlib import Path
from typing import IO

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config import load_yaml_config


@pytest.mark.unit
async def test_health_returns_ok() -> None:
    """健康检查应返回可供编排系统识别的固定响应。

    使用 ASGITransport(不触发 lifespan),避免依赖 Postgres / Weaviate。
    """
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
