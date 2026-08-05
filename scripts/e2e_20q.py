"""e2e 20 问回归测试:从 TS_record 取 20 个真实客户问题,调 /api/ask SSE,收集 sources + answer。

用法:
    python scripts/e2e_20q.py [--limit N] [--out results.json]

输出:每问 {question, sources, answer, is_answered},汇总精准/拒答/部分/失败统计。
不评判对错(人工看 answer),只收集 RAG 管线输出 + 来源召回。
"""
import argparse
import json
import re
import sys
from pathlib import Path

import requests

DEFAULT_API = "http://localhost:8000/api/ask"
TS_RECORD = Path.home() / "Documents/GitHub/Knowledge/知识库/support/TS_record.md"


def extract_questions(limit: int = 20) -> list[str]:
    """从 TS_record 表格取前 N 个问题简述(第 4 列)。"""
    text = TS_RECORD.read_text(encoding="utf-8")
    qs = []
    for line in text.splitlines():
        # 表格行:| 日期 | 客户 | 型号 | 问题简述 | 详细 | 处理人 | 状态 |
        m = re.match(r"^\|\s*\d{4}-\d{2}-\d{2}\s*\|.*?\|.*?\|\s*(.+?)\s*\|", line)
        if m:
            q = m.group(1).strip()
            # 去掉 markdown 链接,保留问题文本
            q = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", q)
            qs.append(q)
    return qs[:limit]


def ask(question: str, api: str = DEFAULT_API, timeout: int = 90) -> dict:
    """调 /api/ask SSE,收集 sources + answer。"""
    sources, answer, is_answered = [], [], True
    try:
        with requests.post(
            api, json={"message": question, "channel": "widget"},
            stream=True, timeout=timeout,
        ) as r:
            r.raise_for_status()
            event = None
            for line in r.iter_lines(decode_unicode=True):
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    try:
                        data = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if event == "sources":
                        sources = data.get("sources", [])
                    elif event == "token":
                        answer.append(data.get("content", ""))
                    elif event == "declined":
                        is_answered = False
            full = "".join(answer)
            # 拒答话术(off_topic / business / 无依据)算拒答,非精准答
            reject_phrases = (
                "我只能回答与 CamThink 产品相关的问题",  # off_topic
                "关于商务合作或价格咨询",  # business_inquiry
                "暂未在官方资料中找到相关信息",  # 无依据
            )
            is_reject = any(p in full for p in reject_phrases)
            return {"question": question, "sources": sources, "answer": full,
                    "is_answered": bool(full) and not is_reject and bool(sources),
                    "is_reject": is_reject,
                    "n_sources": len(sources)}
    except Exception as exc:
        return {"question": question, "sources": [], "answer": "",
                "is_answered": False, "error": str(exc)[:200]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--out", default="e2e_20q_results.json")
    ap.add_argument("--api", default=DEFAULT_API,
                   help=f"API 端点(默认 {DEFAULT_API};远程用 https://wiki-data.camthink.ai/api/ask)")
    args = ap.parse_args()

    qs = extract_questions(args.limit)
    print(f"取 {len(qs)} 个问题\nAPI: {args.api}\n" + "=" * 60)
    results = []
    for i, q in enumerate(qs, 1):
        print(f"\n[{i}/{len(qs)}] {q[:60]}")
        res = ask(q, api=args.api)
        results.append(res)
        status = "答" if res.get("is_answered") else "拒答"
        ns = res.get("n_sources", 0)
        ans = res.get("answer", "")[:80]
        err = res.get("error", "")
        print(f"  → {status} | sources={ns} | {ans}{'... ERROR:'+err if err else ''}")
    print("\n" + "=" * 60)

    n_answered = sum(1 for r in results if r.get("is_answered"))
    n_refused = sum(1 for r in results if r.get("is_reject"))
    n_err = sum(1 for r in results if r.get("error"))
    print(f"精准答(有 sources + 非拒答):{n_answered}/{len(results)}")
    print(f"拒答(off_topic/business/无依据):{n_refused}/{len(results)}")
    print(f"失败(error):{n_err}/{len(results)}")

    Path(args.out).write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n详细结果 → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())