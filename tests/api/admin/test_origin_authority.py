"""I-UX-001 矫正(#6)动态 CORS 调和 —— 真实 HTTP 边界。

覆盖(冻结契约 §2.1/§3.11):
- DB 授权 origin 的浏览器预检/实际请求获得 CORS 头;
- 非授权 origin 无 CORS 头(浏览器执行层 fail closed);
- env 静态集合仍生效(本地开发/Admin 工具不变);
- Admin 侧 origins 变更经 TTL 缓存(≤5s)收敛到 CORS 执行层,无需重建镜像。
- (seed 权威域 / presentation 解析的隔离单测见
  tests/services/test_site_experiences.py。)
"""

import asyncio
import os
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.services.site_experiences import seed_default_sites

pytestmark = pytest.mark.asyncio(loop_scope="session")

REPO_ROOT = Path(__file__).resolve().parents[3]


async def _seed_db():
    await seed_default_sites(app.state.session_factory, REPO_ROOT / "config" / "sites.yaml")


@pytest_asyncio.fixture(loop_scope="session")
async def seeded_sites():
    await _seed_db()
    yield None
    # 恢复 YAML 基线 origins(删除行 + 重seed = 新建行路径,恢复 YAML 初始授权)
    from backend.db.models import SiteExperience

    factory = app.state.session_factory
    async with factory() as session:
        rows = (await session.execute(sqlalchemy_select(SiteExperience))).scalars().all()
        for row in rows:
            await session.delete(row)
        await session.commit()
    await _seed_db()


from sqlalchemy import select as sqlalchemy_select


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _env_cors_origin() -> str:
    raw = os.environ.get(
        "CORS_ALLOW_ORIGINS", "http://localhost:3000,http://localhost:1313,http://localhost:5173"
    )
    return raw.split(",")[0].strip()


class TestDynamicCors:
    async def test_db_authorized_origin_gets_preflight_headers(self, seeded_sites):
        async with await _client() as client:
            resp = await client.options(
                "/api/ask",
                headers={
                    "Origin": "https://www.camthink.ai",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "https://www.camthink.ai"
        assert "POST" in resp.headers.get("access-control-allow-methods", "")

    async def test_unauthorized_origin_gets_no_cors_headers(self, seeded_sites):
        async with await _client() as client:
            resp = await client.options(
                "/api/ask",
                headers={
                    "Origin": "https://evil.example.com",
                    "Access-Control-Request-Method": "POST",
                },
            )
        assert "access-control-allow-origin" not in resp.headers

    async def test_simple_request_from_authorized_origin_gets_allow_origin(self, seeded_sites):
        async with await _client() as client:
            resp = await client.get(
                "/health",
                headers={"Origin": "https://www.camthink.ai"},
            )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "https://www.camthink.ai"
        assert resp.headers.get("vary") == "Origin"

    async def test_env_static_origins_still_allowed(self, seeded_sites):
        origin = _env_cors_origin()
        async with await _client() as client:
            resp = await client.options(
                "/api/ask",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                },
            )
        assert resp.headers.get("access-control-allow-origin") == origin

    async def test_admin_origin_mutation_converges_without_redeploy(self, seeded_sites):
        """Admin 写 DB origins → TTL 过后 CORS 执行层收敛(无需重建镜像)。"""
        from backend.db.models import SiteExperience

        factory = app.state.session_factory
        async with factory() as session:
            row = await session.get(SiteExperience, "camthink-website")
            row.allowed_origins = ["https://cors-converge.example.com"]
            await session.commit()
        # TTL 缓存可能残留旧集合 —— 等待超过 TTL(5s)后必收敛
        await asyncio.sleep(5.2)
        async with await _client() as client:
            resp = await client.options(
                "/api/ask",
                headers={
                    "Origin": "https://cors-converge.example.com",
                    "Access-Control-Request-Method": "POST",
                },
            )
        assert resp.headers.get("access-control-allow-origin") == "https://cors-converge.example.com"
