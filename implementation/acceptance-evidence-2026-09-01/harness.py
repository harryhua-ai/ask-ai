"""CamThink V1 验收 harness:按 corpus.jsonl 逐场景调 /api/ask SSE,留存原始证据。

- target=prod  → https://wiki-data.camthink.ai (生产,基线代码等价面,15 源)
- target=local → http://localhost:8000 (main=76b2199 本地,仅官网爬取库)
- channel 按场景(widget/admin);widget 附件走 /api/upload + session_id
- 每交互间隔 prod 4.2s(限流 20/min 余量)/ local 1.2s;429 退避 35s 重试一次
- 原始证据写 raw/{scenario_id}.json:请求、逐轮 answer/sources/intent/declined/trace(裁剪)

用法: python3 harness.py [--only-prefix A,B] [--limit N]
"""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import requests

HERE = Path(__file__).parent
CORPUS = HERE / "corpus.jsonl"
RAW = HERE / "raw"
TARGETS = {"prod": "https://wiki-data.camthink.ai", "local": "http://localhost:8000"}
DELAY = {"prod": 4.2, "local": 1.2}
REJECT_MARKS = ("我只能回答与 CamThink 产品相关的问题", "关于商务合作或价格咨询", "暂未在官方资料中找到相关信息")
MAX_HISTORY_MSGS = 10  # 对齐 widget 前端(最近 5 轮)


def trim_trace(tp: dict | None) -> dict | None:
    """trace 留阶段得分与候选预览,丢大文本。"""
    if not tp:
        return None
    out = {"type": tp.get("type")}
    stages = {}
    for name, st in (tp.get("stages") or {}).items():
        if not isinstance(st, dict):
            stages[name] = st
            continue
        slim = {k: v for k, v in st.items() if not isinstance(v, (list, dict)) or k in ("candidates",)}
        cands = st.get("candidates")
        if isinstance(cands, list):
            slim["candidates"] = [
                {k: (f"{v[:300]}…" if k in ("text", "content", "chunk", "preview") and isinstance(v, str) else v)
                 for k, v in c.items() if k != "embedding"}
                for c in cands[:6] if isinstance(c, dict)
            ]
        stages[name] = slim
    out["stages"] = stages
    return out


def upload_attachment(api: str, path: Path, session_id: str) -> dict:
    try:
        with open(path, "rb") as f:
            r = requests.post(f"{api}/api/upload", data={"session_id": session_id},
                              files={"files": (path.name, f, "text/plain")}, timeout=60)
        data = r.json()
        atts = [a for a in data.get("attachments", []) if a.get("ok")]
        if not atts:
            return {"error": f"upload failed: {r.status_code} {str(data)[:300]}"}
        return {"id": atts[0]["id"], "filename": atts[0].get("filename", path.name)}
    except Exception as exc:
        return {"error": f"upload exception: {exc}"}


def ask_once(api: str, payload: dict, timeout: int = 150) -> dict:
    t0 = time.time()
    rec: dict = {"http_status": None, "sources": [], "answer": "", "declined": None,
                 "done": None, "conversation_id": None, "error": None}
    try:
        with requests.post(f"{api}/api/ask", json=payload, stream=True, timeout=timeout) as r:
            rec["http_status"] = r.status_code
            if r.status_code == 429:
                rec["error"] = "rate_limited"
                return rec
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
                        rec["sources"] = data.get("sources", [])
                        rec["conversation_id"] = data.get("conversation_id")
                    elif event == "token":
                        rec["answer"] += data.get("content", "")
                    elif event == "declined":
                        rec["declined"] = data
                    elif event == "done":
                        rec["done"] = data
    except Exception as exc:
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    rec["wall_s"] = round(time.time() - t0, 1)
    rec["is_reject_text"] = any(m in rec["answer"] for m in REJECT_MARKS)
    rec["answered"] = bool(rec["answer"]) and not rec["declined"] and not rec["is_reject_text"]
    return rec


def run_scenario(api: str, scen: dict, delay: float) -> dict:
    out = {"id": scen["id"], "family": scen["family"], "channel": scen["channel"],
           "target": scen["target"], "expected_intent": scen.get("expected_intent"),
           "product": scen.get("product"), "note": scen.get("note", ""),
           "bank_ground_truth": scen.get("bank_ground_truth"), "turns": []}
    session_id = str(uuid.uuid4())
    attachment_ids, upload_info = [], None
    if scen.get("attachment"):
        tmp = HERE / "raw" / f"_upl_{scen['id']}_{scen['attachment']['filename']}"
        tmp.write_text(scen["attachment"]["content"], encoding="utf-8")
        upload_info = upload_attachment(api, tmp, session_id)
        tmp.unlink(missing_ok=True)
        if "id" in upload_info:
            attachment_ids = [upload_info["id"]]
        time.sleep(min(delay, 6.0))  # upload 限流 10/min
    out["upload"] = upload_info

    history: list[dict] = []
    for i, turn in enumerate(scen["turns"], 1):
        payload = {"message": turn["text"], "channel": scen["channel"],
                   "conversation_history": history[-MAX_HISTORY_MSGS:]}
        if attachment_ids:
            payload["attachments"] = attachment_ids
            payload["session_id"] = session_id
        rec = ask_once(api, payload)
        if rec.get("error") == "rate_limited":
            time.sleep(35)
            rec = ask_once(api, payload)
        rec["message"] = turn["text"]
        out["turns"].append(rec)
        flag = "REJ" if rec.get("is_reject_text") else ("ok" if rec.get("answered") else "?")
        print(f"  [{scen['id']} t{i}] {rec['http_status']}/{flag} src={len(rec['sources'])} "
              f"{rec['wall_s']}s {'ERR:'+rec['error'] if rec.get('error') else repr(rec['answer'][:60])}",
              flush=True)
        if rec["answer"]:
            history.append({"role": "user", "content": turn["text"]})
            history.append({"role": "assistant", "content": rec["answer"]})
        time.sleep(delay)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-prefix", default="", help="逗号分隔场景 id 前缀,空=全部")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    RAW.mkdir(exist_ok=True)
    scens = [json.loads(l) for l in CORPUS.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.only_prefix:
        prefixes = args.only_prefix.split(",")
        scens = [s for s in scens if any(s["id"].startswith(p) for p in prefixes)]
    if args.limit:
        scens = scens[:args.limit]
    print(f"{len(scens)} scenarios; corpus interactions="
          f"{sum(len(s['turns']) for s in scens)}", flush=True)
    for n, scen in enumerate(scens, 1):
        api = TARGETS[scen["target"]]
        print(f"[{n}/{len(scens)}] {scen['id']} ({scen['target']}/{scen['channel']})",
              flush=True)
        out = run_scenario(api, scen, DELAY[scen["target"]])
        (RAW / f"{scen['id']}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
