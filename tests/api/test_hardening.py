"""FastAPI 生产配置加固集成测试(S5: 全局异常 handler / 安全响应头)。

Test 策略:
    - ``test_unhandled_exception_hides_stack``: 临时给 app 加 ``/__raise`` 路由,
      触发未捕获异常,验证响应不包含堆栈细节。
    - ``test_security_headers_present``: 验证每个响应都带 ``X-Content-Type-Options`` /
      ``X-Frame-Options`` 等安全头。
"""

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app


@pytest.fixture
def raise_route() -> Any:
    """临时给 app 注册 ``/__raise`` 路由,测试后从 router 中移除以避免污染其它测试。"""

    @app.get("/__raise")
    async def _raise() -> None:
        raise RuntimeError("secret internal detail")

    yield _raise

    # 清理:移除刚加的路由
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != "/__raise"]


@pytest.mark.integration
async def test_unhandled_exception_hides_stack(raise_route: Any) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/__raise")
    assert resp.status_code == 500
    assert "secret internal detail" not in resp.text
    assert "detail" in resp.json()


@pytest.mark.integration
async def test_security_headers_present() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
