"""商店设备身份元数据迁移(Issue #19 Store Identity Contract)。

把 WooCommerce 商店源 chunk 的 ``product`` 元数据迁移到确定性派生的设备身份:
派生规则与连接器 ingest **共用同一函数**
(:func:`backend.connectors.woocommerce._device_identity_from_text`,
taxonomy 别名扫描,kind=product 设备 slug,零 LLM、禁止猜测):

- 只重标「派生出设备 slug 且当前标签不同」的 chunk —— 无歧义设备产品页;
- 配件页 / 通用商业页不猜(V1 不重标,维持现标签);
- 原位属性更新,不触向量、零 re-embed(与 #5 元数据迁移同机制)。

**默认 dry-run**;``--apply`` 才写入。

用法:
    # dry-run(默认):报告 old→new 映射与样本
    python scripts/migrate_store_device_metadata.py --source-ids woocommerce-mall

    # 原位应用
    python scripts/migrate_store_device_metadata.py --source-ids woocommerce-mall --apply

Gate 顺序:连接器修复(ingest 侧)部署 → 本脚本 dry-run → 人工核对映射
→ --apply → 复跑 dry-run 应零残余候选。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import weaviate

from backend.config import load_settings
from backend.connectors.woocommerce import _device_identity_from_text

logger = logging.getLogger("migrate-store-device-metadata")


def _scan(
    client: Any,
    *,
    class_name: str,
    source_ids: set[str],
) -> tuple[Counter, list[tuple[str, str, str]], int]:
    """遍历范围内 chunk,产出 (old→new 映射, 变更清单, 扫描数)。

    只把「派生为设备 slug 且当前标签不同」的 chunk 记为候选;派生失败
    (无设备命中)或已一致 → 不动。
    """
    collection = client.collections.get(class_name)
    mapping: Counter = Counter()
    updates: list[tuple[str, str, str]] = []  # (uuid, old_label, new_slug)
    scanned = 0
    for obj in collection.iterator(
        include_vector=False,
        return_properties=["source_id", "product", "title", "url"],
    ):
        props = obj.properties or {}
        source_id = str(props.get("source_id", ""))
        if source_id.split("/", 1)[0] not in source_ids:
            continue
        scanned += 1
        old_label = str(props.get("product", ""))
        identity_text = f"{props.get('title', '')} {props.get('url', '')}"
        derived = _device_identity_from_text(identity_text)
        if derived is None or derived == old_label:
            continue
        mapping[old_label, derived] += 1
        updates.append((str(obj.uuid), old_label, derived))
    return mapping, updates, scanned


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Store device-identity metadata migration (Issue #19; dry-run default)"
    )
    parser.add_argument(
        "--source-ids",
        required=True,
        help="逗号分隔的 WooCommerce 数据源 id 列表(如 woocommerce-mall)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="原位应用迁移(缺省 = dry-run,零写入)",
    )
    parser.add_argument("--class-name", default=None, help="Weaviate collection(默认读配置)")
    parser.add_argument("--weaviate-url", default=None, help="覆盖 WEAVIATE_URL")
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
    mode = "APPLY(in-place property update)" if args.apply else "DRY-RUN(零写入)"
    logger.info(
        "store device metadata migration | mode=%s | sources=%s | class=%s",
        mode,
        source_ids,
        class_name,
    )

    client = weaviate.connect_to_local(host=host, port=port)
    try:
        mapping, updates, scanned = _scan(client, class_name=class_name, source_ids=set(source_ids))
        payload = {
            "mode": "apply" if args.apply else "dry-run",
            "sources": source_ids,
            "scanned": scanned,
            "candidates": len(updates),
            "mapping": {f"{old} -> {new}": n for (old, new), n in sorted(mapping.items())},
            "samples": [{"uuid": u, "old": o, "new": n} for u, o, n in updates[:20]],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if args.json_out:
            Path(args.json_out).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        if not args.apply:
            logger.info(
                "DRY RUN 完成:candidates=%d;未产生任何变更(执行请加 --apply)",
                len(updates),
            )
            return 0

        collection = client.collections.get(class_name)
        applied = 0
        for uuid, _old, new_slug in updates:
            collection.data.update(uuid=uuid, properties={"product": new_slug})
            applied += 1
        logger.info("APPLY 完成:updated=%d chunks(零 re-embed,向量未触碰)", applied)
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
