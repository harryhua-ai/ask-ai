"""生命周期 GC sweep CLI(P1 地基;dry-run 默认,--apply 显式执行)。

资格与红线见 backend/services/lifecycle_gc.py(RETIRED+7 天冻结;
墓碑窗不设隐式默认 —— 未配置 LIFECYCLE_GC_TOMBSTONE_DAYS 时墓碑物理 GC 关闭;
已废除的 30 天默认禁止回用;运营 rollout 归 P5)。

用法:
    python scripts/gc_lifecycle.py            # dry-run:只报告资格
    python scripts/gc_lifecycle.py --apply    # 执行物理清除
"""

import argparse
import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

import weaviate

from backend.config import load_settings
from backend.db.session import get_engine, get_session_factory, get_sync_session_factory
from backend.pipeline.ingest import IngestionPipeline
from backend.services.lifecycle_gc import sweep


def _parse_weaviate_endpoint(weaviate_url: str) -> tuple[str, int]:
    from urllib.parse import urlparse

    if "://" not in weaviate_url:
        weaviate_url = f"http://{weaviate_url}"
    parsed = urlparse(weaviate_url)
    return parsed.hostname or "localhost", parsed.port or 8080


async def run(apply: bool) -> dict:
    settings = load_settings()
    engine = get_engine(settings.postgres_dsn)
    host, port = _parse_weaviate_endpoint(settings.weaviate_url)
    client = weaviate.connect_to_local(host=host, port=port)
    try:
        pipeline = IngestionPipeline(
            embedder=None,  # GC 不嵌入;集合句柄惰性获取
            weaviate_client=client,
            class_name=settings.weaviate_class_name,
            session_factory=get_sync_session_factory(settings.postgres_dsn),
        )
        report = await sweep(
            get_session_factory(engine),
            pipeline,
            tombstone_days=settings.lifecycle_gc_tombstone_days,
            apply=apply,
        )
        return report.as_dict()
    finally:
        client.close()
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="P1 生命周期 GC sweep(dry-run 默认)")
    parser.add_argument("--apply", action="store_true", help="执行物理清除(默认 dry-run)")
    args = parser.parse_args()
    report = asyncio.run(run(apply=args.apply))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
