"""真实 e2e 测试:从 support 详细案例提取客户真实问题,调 /api/ask,
对比 answer 和源文档的根因分析/建议措施,供人工正确性核验。

用法:
    python scripts/e2e_real.py [--limit N] [--out results.json]

与 e2e_20q.py 区别:
- 输入:案例文档的 ## 问题描述 段(客户真实完整需求,非 TS_record 摘要)
- 核验:输出 answer + 源文档的 ## 根因分析 / ## 建议措施(人工对比正确性)
"""
import argparse
import json
import re
import sys
from pathlib import Path

import requests

API = "http://localhost:8000/api/ask"
SUPPORT = Path.home() / "Documents/GitHub/Knowledge/知识库/support"
CASE_DIRS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2025.2", "experience"]

REJECT_PHRASES = (
    "我只能回答与 CamThink 产品相关的问题",
    "关于商务合作或价格咨询",
    "暂未在官方资料中找到相关信息",
)


def extract_section(text: str, heading: str) -> str:
    """提取 ## heading 段落内容(到下一个 ## 为止),去掉客户信息块。"""
    m = re.search(rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)",
                  text, re.MULTILINE | re.DOTALL)
    if not m:
        return ""
    body = m.group(1).strip()
    # 去掉 **客户信息:** 块(避免泄露 PII 到输入)
    body = re.sub(r"\*\*客户信息?:\*\*.*?(?=\n\n|\Z)", "", body, flags=re.DOTALL).strip()
    return body


def load_cases(limit: int) -> list[dict]:
    """遍历 support 案例目录,提取 真实问题 + 源答案(根因+建议)。"""
    cases = []
    for d in CASE_DIRS:
        dirp = SUPPORT / d
        if not dirp.is_dir():
            continue
        for f in sorted(dirp.glob("*.md")):
            text = f.read_text(encoding="utf-8")
            problem = extract_section(text, "问题描述")
            if not problem:
                continue
            root_cause = extract_section(text, "根因分析")
            suggestion = extract_section(text, "建议措施")
            troubleshoot = extract_section(text, "排查思路")
            cases.append({
                "file": str(f.relative_to(SUPPORT)),
                "title": f.stem,
                "problem": problem,
                "source_answer": (root_cause + "\n\n" + troubleshoot + "\n\n" + suggestion).strip(),
            })
            if len(cases) >= limit:
                return cases
    return cases


def ask(question: str, timeout: int = 90) -> dict:
    sources, answer = [], []
    try:
        with requests.post(
            API, json={"message": question, "channel": "widget"},
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
            full = "".join(answer)
            is_reject = any(p in full for p in REJECT_PHRASES)
            return {"answer": full, "sources": sources,
                    "is_answered": bool(full) and not is_reject and bool(sources),
                    "is_reject": is_reject, "n_sources": len(sources)}
    except Exception as exc:
        return {"answer": "", "sources": [], "is_answered": False,
                "is_reject": False, "n_sources": 0, "error": str(exc)[:200]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--out", default="e2e_real_results.json")
    args = ap.parse_args()

    cases = load_cases(args.limit)
    print(f"加载 {len(cases)} 个真实案例\n" + "=" * 70)
    results = []
    for i, c in enumerate(cases, 1):
        print(f"\n[{i}/{len(cases)}] {c['file']}")
        res = ask(c["problem"])
        res.update({"file": c["file"], "title": c["title"],
                   "problem": c["problem"], "source_answer": c["source_answer"]})
        results.append(res)
        st = "答" if res.get("is_answered") else ("拒" if res.get("is_reject") else "ERR")
        print(f"  → {st} | src={res.get('n_sources',0)} | {res.get('answer','')[:60]}")

    Path(args.out).write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    n_ans = sum(1 for r in results if r.get("is_answered"))
    n_rej = sum(1 for r in results if r.get("is_reject"))
    n_err = sum(1 for r in results if r.get("error"))
    print("\n" + "=" * 70)
    print(f"答:{n_ans}/{len(results)} | 拒答:{n_rej} | 失败:{n_err}")
    print(f"详细(含源答案核验)→ {args.out}")
    print(f"\n查看核验文档:python scripts/e2e_real_review.py {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())