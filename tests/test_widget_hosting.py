"""T1a Phase1-T2:/widget 静态托管契约测试。

- widget/dist 存在时挂载 /widget,widget.js 可 200 获取;
- 响应头 Cache-Control: public, max-age=300(契约冻结:更新 5 分钟内生效);
- /widget/ 目录本身禁止目录列表(404,不得 html=True);
- dist 不存在时不挂载(镜像 admin 模式,本地/CI 无产物不炸)。
"""

from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import backend.main as backend_main

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def widget_app(tmp_path: Path):
    """临时 dist 目录 + 挂载后的独立 FastAPI 应用。"""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "widget.js").write_text("console.log('ask-ai widget');", encoding="utf-8")
    app = FastAPI()
    backend_main._mount_widget_static(app, dist)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_widget_js_served_with_cache_header(widget_app):
    resp = await widget_app.get("/widget/widget.js")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=300"
    assert "ask-ai widget" in resp.text


async def test_widget_dir_root_no_directory_listing(widget_app):
    resp = await widget_app.get("/widget/")
    assert resp.status_code == 404
    assert "widget.js" not in resp.text


async def test_widget_missing_file_404(widget_app):
    resp = await widget_app.get("/widget/nope.js")
    assert resp.status_code == 404


async def test_widget_not_mounted_when_dist_missing(tmp_path: Path):
    app = FastAPI()
    backend_main._mount_widget_static(app, tmp_path / "does-not-exist")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/widget/widget.js")
    assert resp.status_code == 404
