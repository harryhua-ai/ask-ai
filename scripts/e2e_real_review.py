"""把 e2e_real.py 的结果生成核验文档(answer vs 源文档答案并排,供人工正确性核验)。

用法:
    python scripts/e2e_real_review.py e2e_real_results.json [--out review.md]
"""
import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("results", help="e2e_real.py 输出的 JSON")
    ap.add_argument("--out", default="e2e_real_review.md")
    args = ap.parse_args()

    results = json.loads(Path(args.results).read_text(encoding="utf-8"))
    lines = [f"# 真实案例 e2e 核验文档({len(results)} 例)\n",
             "对比 **AI 答案** 和 **源文档答案(根因+建议)**,人工评判正确性。\n\n"]
    for i, r in enumerate(results, 1):
        st = "答" if r.get("is_answered") else ("拒答" if r.get("is_reject") else "失败")
        lines.append(f"---\n\n## [{i}/{len(results)}] {st} — {r['title']}\n")
        lines.append(f"`{r['file']}` | sources={r.get('n_sources',0)}\n\n")
        lines.append(f"### 真实问题(案例文档提取)\n{r['problem']}\n\n")
        lines.append(f"### AI 答案\n{r.get('answer','')}\n\n")
        lines.append(f"### 源文档答案(根因+排查+建议)\n{r.get('source_answer','(无)')}\n\n")
    Path(args.out).write_text("".join(lines), encoding="utf-8")
    print(f"核验文档 → {args.out}({len(results)} 例)")
    return 0


if __name__ == "__main__":
    sys.exit(main())