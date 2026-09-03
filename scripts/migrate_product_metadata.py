"""产品元数据迁移 CLI(Issue #5 契约 §4)。

把存量 Weaviate chunk 的 ``product`` 元数据迁移到 taxonomy canonical 值。
**默认 dry-run**;``--apply`` 才写入。原位属性更新,不触向量、不 re-embed。

用法:
    # dry-run(默认):只报告 old→new 映射 / unknown 明细
    python scripts/migrate_product_metadata.py --source-ids wiki-documents-local,website-camthink

    # 原位应用(仅对变化 chunk 写 product 属性)
    python scripts/migrate_product_metadata.py --source-ids wiki-documents-local --apply

Gate 顺序(实现报告 §生产验收):taxonomy 部署 → 本脚本 dry-run → apply →
服务发布 → 11 例冒烟 → 93 场景回归。**禁止**在未跑 dry-run 并人工核对
unknown 明细前直接 --apply。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import weaviate

from backend.config import load_settings
from backend.product_taxonomy import get_taxonomy
from backend.services.product_migration import (
    apply_migration,
    format_report,
    plan_migration,
)

logger = logging.getLogger("migrate-product-metadata")


def main() -> int:
    parser = argparse.ArgumentParser(description="Weaviate product metadata migration (taxonomy canonical)")
    parser.add_argument(
        "--source-ids",
        required=True,
        help="逗号分隔的 data_sources.id 列表(source-scoped;如 wiki-documents-local)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="原位应用迁移(缺省 = dry-run,零写入)",
    )
    parser.add_argument("--class-name", default=None, help="Weaviate collection(默认读配置)")
    parser.add_argument("--weaviate-url", default=None, help="覆盖 WEAVIATE_URL(如 http://localhost:8080)")
    parser.add_argument("--json", dest="json_out", default=None, help="报告 JSON 输出路径")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    class_name = args.class_name or settings.weaviate_class_name
    weaviate_url = args.weaviate_url or settings.weaviate_url
    source_ids = [s.strip() for s in args.source_ids.split(",") if s.strip()]
    if not source_ids:
        parser.error("--source-ids 不能为空")

    from scripts.sync import _parse_weaviate_endpoint

    host, port = _parse_weaviate_endpoint(weaviate_url)
    taxonomy = get_taxonomy()
    mode = "APPLY(in-place property update)" if args.apply else "DRY-RUN(零写入)"
    logger.info("product metadata migration | mode=%s | sources=%s | class=%s", mode, source_ids, class_name)

    client = weaviate.connect_to_local(host=host, port=port)
    try:
        if args.apply:
            report = apply_migration(
                client, class_name=class_name, source_ids=source_ids, taxonomy=taxonomy
            )
        else:
            report = plan_migration(
                client, class_name=class_name, source_ids=source_ids, taxonomy=taxonomy
            )
    finally:
        client.close()

    print(format_report(report))
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("JSON 报告已写入 %s", args.json_out)
    if report.total_unknown:
        logger.warning(
            "存在 %d 个 unknown chunk(未命中规则且标签不可 canonicalize)——"
            "已逐条计数并列样本;按契约不得猜测归属,请人工核对后再决定",
            report.total_unknown,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
