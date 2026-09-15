"""INC-WEB-EMBED-413 REMEDIATION:sync_requests 补 kind 列(幂等加性迁移)。

修复面 REBUILD_REQUIRED 裁决经既有 sync_requests 交接缝请求权威源重建:
kind = "rebuild" → 执行面透传 ``--reindex``(既有 P1-E 全量生成重建路径,
经 ``_enforce_char_limit`` 的已验收摄取路径)。NULL = 既有增量同步语义,
存量行零回填。纯加列,幂等,生产执行窗口任意。
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import load_settings
from backend.db.session import ensure_sync_request_kind_column, get_engine


async def migrate(engine) -> None:
    await ensure_sync_request_kind_column(engine)
    print("OK: sync_requests.kind 就绪(幂等迁移完成)")


async def _main() -> None:
    settings = load_settings()
    engine = get_engine(settings.postgres_dsn)
    try:
        await migrate(engine)
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
