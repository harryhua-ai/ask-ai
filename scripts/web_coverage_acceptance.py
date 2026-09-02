"""WEB-G010 自然覆盖验收:对真实 https://www.camthink.ai 只读跑连接器(不触库)。

输出 JSON 证据:discovered/accepted/rejected(+reasons)/extracted/failed/
documents 双轮全量清单 + 逐 path 的 content_hash diff(幂等性精确定位,
WEB-G007)。只读 GET、UA 标识、500ms 限速、robots 遵从。

用法:PYTHONPATH=. python scripts/web_coverage_acceptance.py <out.json>
"""

import json
import sys
from datetime import UTC, datetime

import backend.connectors.web_crawl  # noqa: F401 - 触发 @register 装饰器
from backend.connectors.registry import ConnectorRegistry, SourceConfig


def run_once(source_id: str) -> dict:
    cfg = SourceConfig(
        id=source_id,
        type="web_crawl",
        product="website",
        enabled=True,
        config={
            "base_url": "https://www.camthink.ai",
            "crawl_delay_ms": 500,  # 红线:礼貌限速
        },
        sync_interval="24h",
    )
    conn = ConnectorRegistry.create(cfg)
    docs = list(conn.fetch_all())
    return {
        "stats": dict(conn.run_stats or {}),
        # path → (hash 短码, md_chars, title):幂等 diff 的最小充分集
        "by_path": {
            d.metadata["path"]: [d.content_hash[:12], len(d.content), d.title[:60]]
            for d in docs
        },
    }


def main(out_path: str) -> None:
    t0 = datetime.now(UTC).isoformat()
    r1 = run_once("web-acceptance-r1")
    r2 = run_once("web-acceptance-r2")

    p1, p2 = r1["by_path"], r2["by_path"]
    changed = sorted(k for k in p1.keys() & p2.keys() if p1[k][0] != p2[k][0])
    added = sorted(p2.keys() - p1.keys())
    removed = sorted(p1.keys() - p2.keys())
    same = sorted(k for k in p1.keys() & p2.keys() if p1[k][0] == p2[k][0])

    evidence = {
        "target": "https://www.camthink.ai",
        "ran_at": t0,
        "run1": {"stats": r1["stats"], "documents": p1},
        "run2_stats": r2["stats"],
        "run2_documents": p2,
        "idempotency": {
            "run1_doc_count": len(p1),
            "run2_doc_count": len(p2),
            "same_path_set": set(p1) == set(p2),
            "same_hash_count": sum(1 for k in same),
            "changed_paths": changed,
            "added_paths": added,
            "removed_paths": removed,
            # 合同 G007 口径:文档集不倍增 + 语料稳定(变更篇数即实况披露)
            "multiplied": len(p2) > len(p1),
            "corpus_stable": len(changed) == 0 and set(p1) == set(p2),
        },
    }
    with open(out_path, "w") as f:
        json.dump(evidence, f, ensure_ascii=False, indent=1)
    print(json.dumps({
        "run1_stats": r1["stats"],
        "run2_stats": r2["stats"],
        "run1_docs": len(p1),
        "run2_docs": len(p2),
        "same_path_set": evidence["idempotency"]["same_path_set"],
        "changed": len(changed),
        "changed_paths": changed[:10],
        "out": out_path,
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
