"""ASK-AI Answer Intelligence Benchmark v1 — 可执行基线 runner(#32)。

v1 冻结基线(v1.1.2 cdbcad3, 2026-09-07)与复测(v1.2.1 26de2b6, 2026-09-08)
均由一次性会话工具执行,可执行 runner 未入库(评审缺口)。本脚本将执行面
固化为仓库资产,执行契约与既有工件对齐:

- 输入:``docs/evaluation/benchmark_v1/freeze_v1/executable_corpus_v1.json``
  (唯一可执行模型输入;不含真值/评分,数据最小化已脱敏);
- 传输:SSE widget channel,message 逐字投递;connect 15s / read 180s;
  每 run 间隔 3.5s(与 v1 复测 runner 契约一致);
- 输出:JSONL(每行一个 run:case_id/run_seq/question/answer/sources/
  declined/error/时间戳/endpoint),供 LLM-assisted 评审打分与聚合;
- 判分:不在本脚本内(EVAL_V1 evaluator contract 见 freeze_v1/;
  v1 方法论 = LLM judge + 人工校准,判分模型身份逐 run 记录)。

用法:
    python scripts/benchmark_v1/run_benchmark.py \
        --endpoint https://wiki-data.camthink.ai/api/ask \
        --runs-per-case 3 --out /tmp/baseline_raw.jsonl
    # 子集(种子复测):
    python scripts/benchmark_v1/run_benchmark.py --case-id cg-r03 --case-id cg-r05 ...

身份门(与既有基线纪律一致):跑批前先 GET /health 核验 target 身份并写入
manifest;本脚本不核验版本(由调用方记录),但每行 JSONL 均带 endpoint。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = (
    REPO_ROOT / "docs/evaluation/benchmark_v1/freeze_v1/executable_corpus_v1.json"
)
DEFAULT_ENDPOINT = "https://wiki-data.camthink.ai/api/ask"
CONNECT_TIMEOUT = 15
READ_TIMEOUT = 180
INTER_RUN_SLEEP = 3.5


def ask_once(endpoint: str, question: str) -> dict:
    """单次 /api/ask SSE 调用;返回 answer/sources/declined/error 摘要。"""
    answer: list[str] = []
    sources: list = []
    declined: dict | None = None
    started = datetime.now(UTC).isoformat()
    try:
        with requests.post(
            endpoint,
            json={"message": question, "channel": "widget"},
            stream=True,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        ) as resp:
            resp.raise_for_status()
            event = None
            for line in resp.iter_lines(decode_unicode=True):
                if isinstance(line, str) and line.startswith("event:"):
                    event = line[6:].strip()
                elif isinstance(line, str) and line.startswith("data:"):
                    try:
                        data = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if event == "token":
                        answer.append(data.get("content", ""))
                    elif event == "sources":
                        sources = data.get("sources", [])
                    elif event == "declined":
                        declined = data
    except Exception as exc:  # noqa: BLE001 - 传输失败如实记录为该 run 的 error
        return {
            "answer": "",
            "sources": [],
            "declined": None,
            "error": f"{type(exc).__name__}: {exc}"[:200],
            "ttft_ms": None,
            "duration_ms": None,
            "started_at": started,
        }
    return {
        "answer": "".join(answer),
        "sources": sources,
        "declined": declined,
        "error": None,
        "ttft_ms": None,  # v1 复测披露的 TTFT 缺口:本 runner 不测首延迟(非判分输入)
        "duration_ms": int((datetime.now(UTC) - datetime.fromisoformat(started)).total_seconds() * 1000),
        "started_at": started,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--runs-per-case", type=int, default=3)
    parser.add_argument("--case-id", action="append", default=[], help="仅跑指定 case(可重复)")
    parser.add_argument("--limit", type=int, default=0, help="仅前 N 个 case(0=全部)")
    parser.add_argument("--out", required=True, help="输出 JSONL 路径(追加模式)")
    args = parser.parse_args(argv)

    corpus = json.loads(Path(args.corpus).read_text())
    cases = corpus["cases"]
    if args.case_id:
        wanted = set(args.case_id)
        cases = [c for c in cases if c["case_id"] in wanted]
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        print("no cases selected", file=sys.stderr)
        return 1

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    total = len(cases) * args.runs_per_case
    done = 0
    with out_path.open("a") as sink:
        for case in cases:
            for run_seq in range(1, args.runs_per_case + 1):
                result = ask_once(args.endpoint, case["question"])
                record = {
                    "case_id": case["case_id"],
                    "run_seq": run_seq,
                    "question": case["question"],
                    "language": case.get("language"),
                    "endpoint": args.endpoint,
                    "executed_at": datetime.now(UTC).isoformat(),
                    **result,
                }
                sink.write(json.dumps(record, ensure_ascii=False) + "\n")
                sink.flush()
                done += 1
                print(f"[{done}/{total}] {case['case_id']}#{run_seq} "
                      f"answer_len={len(result['answer'])} err={result['error']}")
                if done < total:
                    time.sleep(INTER_RUN_SLEEP)
    print(f"done: {done} runs → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
