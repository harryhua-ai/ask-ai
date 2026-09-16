"""生命周期 GC sweep CLI / 常驻调度(P1 地基 + v1.6.4 Track A #25 运营化)。

资格与红线见 backend/services/lifecycle_gc.py(RETIRED+7 天冻结;
墓碑窗不设隐式默认 —— 未配置 LIFECYCLE_GC_TOMBSTONE_DAYS 时墓碑物理 GC 关闭;
已废除的 30 天默认禁止回用)。

v1.6.4 Track A(A-5,#25):GC **自动调度触发**落地(sync-cron 同款
while-loop 模式),默认 report-only;物理 apply 受 config gate 约束 ——
``--apply`` 必须同时满足 ``LIFECYCLE_GC_APPLY=true`` 才执行,否则显式拒绝
(首次生产 apply 是受控操作员动作:dry-run 输出经 ``--report-json`` 归档后
再显式开门)。发现确认退休行按 retired_at + 7d **自动**取得资格(A-2);
普通墓碑仍 opt-in(墓碑窗配置,A-5 分层)。

用法:
    python scripts/gc_lifecycle.py            # 单轮 dry-run:只报告资格
    python scripts/gc_lifecycle.py --apply    # 物理清除(需 LIFECYCLE_GC_APPLY=true)
    python scripts/gc_lifecycle.py --loop [--interval 3600]
                                              # 常驻调度(sync-cron 模式,默认 dry-run)
    python scripts/gc_lifecycle.py --report-json out.json
                                              # GCReport JSON 归档(dry-run 输出存证)
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time

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


def resolve_apply(requested: bool, settings) -> tuple[bool, str]:
    """A-5 config gate:物理 apply = CLI 意图 ∧ 配置开门(二者缺一即 dry-run)。

    Returns:
        (apply, note) — note 为人读裁决说明(拒绝时含开门方法)。
    """
    if not requested:
        return False, "dry-run default(A-5:reporting by default)"
    if not settings.lifecycle_gc_apply:
        return (
            False,
            "apply 被拒绝:LIFECYCLE_GC_APPLY 未开启(物理清除是 config-gated "
            "受控操作;先归档 dry-run 输出,再显式设置 LIFECYCLE_GC_APPLY=true)",
        )
    return True, "config-gated apply(LIFECYCLE_GC_APPLY=true)"


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
    parser = argparse.ArgumentParser(description="生命周期 GC sweep(dry-run 默认)")
    parser.add_argument("--apply", action="store_true", help="请求物理清除(仍需 LIFECYCLE_GC_APPLY=true)")
    parser.add_argument(
        "--loop",
        action="store_true",
        help="常驻调度模式(sync-cron 同款 while-loop;默认单轮后退出)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=3600,
        help="loop 模式轮间隔秒数(默认 3600)",
    )
    parser.add_argument(
        "--report-json",
        type=str,
        default=None,
        help="GCReport JSON 归档路径(dry-run 输出存证;首次生产 apply 的前置)",
    )
    args = parser.parse_args()

    settings = load_settings()
    apply, gate_note = resolve_apply(args.apply, settings)
    if args.apply and not apply:
        # 显式意图被 config gate 拒绝:退出码 2(脚本化调用可感知),
        # loop 模式下降级为 dry-run 继续(报告职能不中断)。
        logging.getLogger(__name__).warning("%s", gate_note)
        if not args.loop:
            print(json.dumps({"applied": False, "gate": gate_note}, ensure_ascii=False))
            sys.exit(2)

    def _archive(report_dict: dict) -> None:
        if args.report_json:
            with open(args.report_json, "w", encoding="utf-8") as fh:
                json.dump(report_dict, fh, ensure_ascii=False, indent=2)
            logging.getLogger(__name__).info("GCReport 已归档: %s", args.report_json)

    async def once() -> dict:
        report = await run(apply=apply)
        _archive(report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return report

    if not args.loop:
        asyncio.run(once())
        return
    logging.getLogger(__name__).info(
        "GC 调度循环启动(interval=%ds, apply=%s)", args.interval, apply
    )
    while True:
        try:
            asyncio.run(once())
        except Exception as exc:  # noqa: BLE001 - 单轮失败不终止调度(sync-cron 模式)
            logging.getLogger(__name__).error("GC sweep 轮失败(下一轮重试): %s", exc)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
