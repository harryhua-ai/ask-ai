"""Corpus Repair CLI(Issue #13 Stage A;DRY RUN DEFAULT,--apply 显式执行)。

为 Production Repair Gate 提供可审计入口。本轮仅本地/测试使用;对生产执行
属于生产写操作,必须持独立授权(PROD_MUTATION_AUTHORIZATION_REQUIRED),
且与在线同步窗口互斥。

用法(dry-run,默认;产出计划并可持续化审计):
    python scripts/repair_corpus.py --source ne301-local
    python scripts/repair_corpus.py --source ne301-local --output /tmp/plan.json

执行(显式;逐项幂等,只触碰计划内对象):
    python scripts/repair_corpus.py --source ne301-local --apply

源确认退休(需权威成员证据;由 connector 权威枚举取得):
    python scripts/repair_corpus.py --source ne301-local --check-source

注意:本工具不加载 BGE(重建分支为零 embedding;refill/补灌属 Stage B)。
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import weaviate  # noqa: E402

from backend.config import load_settings  # noqa: E402
from backend.connectors.db_adapter import to_source_config  # noqa: E402
from backend.connectors.registry import ConnectorRegistry  # noqa: E402
from backend.db.models import DataSource  # noqa: E402
from backend.db.session import (  # noqa: E402
    get_engine,
    get_session_factory,
    get_sync_session_factory,
)
from backend.pipeline.ingest import IngestionPipeline  # noqa: E402
from backend.services.corpus_repair import CorpusRepairTool  # noqa: E402


class _NoEmbedEmbedder:
    """修复工具永不 embed:任何试图 embed 的路径都应显式失败(防误扩权)。"""

    def embed(self, texts, *args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError(
            "corpus repair 不执行 embedding(Stage B 范畴);" "若看到此错误说明工具被错误用于灌入路径"
        )


def _parse_weaviate_endpoint(weaviate_url: str) -> tuple[str, int]:
    from urllib.parse import urlparse

    if "://" not in weaviate_url:
        weaviate_url = f"http://{weaviate_url}"
    parsed = urlparse(weaviate_url)
    return parsed.hostname or "localhost", parsed.port or 8080


async def _load_source(session_factory, source_id: str):
    async with session_factory() as session:
        from sqlalchemy import select

        row = (
            await session.execute(select(DataSource).where(DataSource.id == source_id))
        ).scalar_one_or_none()
    return to_source_config(row) if row else None


async def main_async(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="repair_corpus")
    parser.add_argument("--source", required=True, help="数据源 ID(严格前缀圈定)")
    parser.add_argument("--apply", action="store_true", help="显式执行(缺省=dry-run)")
    parser.add_argument(
        "--check-source",
        action="store_true",
        help="经 connector 权威枚举取得成员集(启用源确认退休类条目)",
    )
    parser.add_argument("--output", default=None, help="计划/结果 JSON 持久化路径(审计)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    settings = load_settings(
        config_dir=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config"
        )
    )
    engine = get_engine(settings.postgres_dsn)
    weaviate_client = None
    try:
        host, port = _parse_weaviate_endpoint(settings.weaviate_url)
        weaviate_client = weaviate.connect_to_local(host=host, port=port)
        session_factory = get_session_factory(engine)
        sync_session_factory = get_sync_session_factory(settings.postgres_dsn)
        pipeline = IngestionPipeline(
            _NoEmbedEmbedder(),
            weaviate_client,
            class_name=settings.weaviate_class_name,
            session_factory=sync_session_factory,
        )
        tool = CorpusRepairTool(async_session_factory=session_factory, pipeline=pipeline)

        membership = None
        if args.check_source:
            cfg = await _load_source(session_factory, args.source)
            if cfg is None:
                print(f"数据源 {args.source} 不存在", file=sys.stderr)
                return 2
            connector = ConnectorRegistry.create(cfg)
            docs = list(connector.fetch_all())
            getter = getattr(connector, "authoritative_source_ids", None)
            membership = (
                set(getter()) if callable(getter) and getter() else {d.source_id for d in docs}
            )

        plan = await tool.plan(args.source, membership=membership)
        payload = {"mode": "apply" if args.apply else "dry-run", **plan.to_dict()}
        print(json.dumps(payload, ensure_ascii=False, indent=2))

        if args.output:
            Path(args.output).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"[repair_corpus] 计划已写入 {args.output}", file=sys.stderr)

        if not args.apply:
            print(
                f"[repair_corpus] DRY RUN 完成:{len(plan.entries)} 条目,"
                f"{sum(e.chunk_count for e in plan.entries)} chunks;未产生任何变更"
                "(执行请加 --apply)",
                file=sys.stderr,
            )
            return 0

        result = await tool.apply(plan)
        print(
            json.dumps({"mode": "apply-result", **result.to_dict()}, ensure_ascii=False, indent=2)
        )
        if args.output:
            Path(args.output).write_text(
                json.dumps(
                    {"plan": payload, "result": result.to_dict()}, ensure_ascii=False, indent=2
                ),
                encoding="utf-8",
            )
        return 1 if result.failed else 0
    finally:
        if weaviate_client is not None:
            weaviate_client.close()
        await engine.dispose()


def main() -> None:
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
