"""e2e 跨语言意图测试:从 support 案例库抽真实问题 → 英文 → 按意图分类 → 打 API。

3 个意图(commercial / product / support)各 100 个英文问题:
- support:从 support 案例库的技术工单抽(故障/排查类),翻译成英文查询
- product:从方案/咨询/选型类案例抽,翻译成英文
- commercial:从 support 库能提的真实售前问题 + 基于 WooCommerce 产品合成英文购买问题
  (support 库 commercial 不足,synthetic 补足到 100)

用法:
    python scripts/e2e_intent_en.py --api https://wiki-data.camthink.ai/api/ask
    python scripts/e2e_intent_en.py --api http://localhost:8000/api/ask

输出:每意图 {精准答 / 拒答 / 失败} 统计 + sources 召回率 + 详细 JSON。

**跨语言召回核验**:问题是英文,知识库是中文(support 案例)+ 英文(woocommerce/wiki)。
精准答 = 有 sources 且非拒答;重点看是否召回了对应的中文 support 案例(跨语言命中)。
"""
import argparse
import json
import re
import sys
from pathlib import Path

import requests

DEFAULT_API = "http://localhost:8000/api/ask"
SUPPORT = Path.home() / "Documents/GitHub/Knowledge/知识库/support"
CASE_DIRS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2025.2", "experience"]

REJECT_PHRASES = (
    "我只能回答与 CamThink 产品相关的问题",
    "关于商务合作或价格咨询",
    "暂未在官方资料中找到相关信息",
)

# ---------------------------------------------------------------------------
# 问题来源:从 support 案例提取真实问题 + 按意图分类(中文) + 英文翻译
# ---------------------------------------------------------------------------

# 意图分类关键词(基于案例标题/内容判断该案例属于哪个意图)
SUPPORT_KEYWORDS = ("故障", "失败", "不亮", "不上", "报错", "排查", "崩溃", "掉线",
                    "刷写", "烧录", "注册被拒", "登录失败", "异常", "重启", "变砖",
                    "不工作", "无法", "升级", "flashing", "debug", "fix", "error",
                    "reset", "recovery", "unbrick")
PRODUCT_KEYWORDS = ("方案", "选型", "咨询", "评估", "可行性", "meeting", "prep",
                    "规格", "FOV", "功能", "定制", "集成", "兼容", "能力",
                    "deployment", "integration", "feasibility", "spec")
COMMERCIAL_KEYWORDS = ("询价", "报价", "经销商", "分销", "合作", "订单", "购买",
                       "price", "quote", "distributor", "order", "purchase")


def classify_intent(title: str, problem: str) -> str:
    """根据标题 + 问题描述粗分类为 commercial/product/support。"""
    text = (title + " " + problem).lower()
    if any(k.lower() in text for k in COMMERCIAL_KEYWORDS):
        return "commercial"
    if any(k.lower() in text for k in SUPPORT_KEYWORDS):
        return "support"
    if any(k.lower() in text for k in PRODUCT_KEYWORDS):
        return "product"
    return "support"  # 默认 support(support 库主体)


def extract_problem(path: Path) -> str:
    """提取 ## 问题描述 段(到下一个 ## 为止),去客户信息块。"""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^## 问题描述\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not m:
        return ""
    body = m.group(1).strip()
    # 去客户信息块
    body = re.sub(r"\*\*客户信息?:\*\*.*?(?=\n\n|\Z)", "", body, flags=re.DOTALL).strip()
    # 压缩空白
    body = re.sub(r"\s+", " ", body)
    return body[:300]  # 截断,避免太长


def to_english_query(problem: str, title: str, intent: str) -> str:
    """把中文问题转成英文查询(规则化,非 LLM)。

    保持核心实体(型号 NE301/NE101/NE503、技术词)和问题意图。
    """
    # 型号保留
    models = re.findall(r"NE\d{3}|NG\d{4}|NeoMind", title + " " + problem)
    model = models[0] if models else "CamThink camera"

    # 按意图构造英文模板
    t = (title + " " + problem).lower()
    if intent == "support":
        if "烧录" in t or "flashing" in t or "刷写" in t:
            return f"How to flash firmware on {model}, external flash erase failure and DIP switch setup"
        if "补光灯" in t:
            return f"{model} fill light not turning on during photo capture, how to fix"
        if "4g" in t or "蜂窝" in t or "sim" in t or "网络" in t:
            return f"{model} cellular network registration denied or SIM not connecting"
        if "供电" in t or "电源" in t or "power" in t:
            return f"What is the power supply requirement for {model}, voltage range"
        if "重置" in t or "reset" in t or "恢复" in t:
            return f"{model} factory reset recovery, WiFi AP not broadcasting after reset"
        if "登录" in t or "password" in t or "权限" in t:
            return f"{model} login failed with default password, unauthorized access"
        return f"{model} troubleshooting: {problem[:80]}"
    if intent == "commercial":
        if "询价" in t or "报价" in t or "price" in t:
            return f"What is the price of {model}, how to order and shipping options"
        if "经销商" in t or "分销" in t or "distributor" in t:
            return f"How to become CamThink distributor for {model} in our region"
        return f"How to purchase {model}, minimum order quantity and lead time"
    # product
    if "fov" in t or "镜头" in t or "lens" in t:
        return f"What is the field of view and lens spec for {model}"
    if "方案" in t or "deployment" in t or "方案评估" in t:
        return f"What is the recommended deployment architecture for {model} in industrial monitoring"
    if "pir" in t:
        return f"Does {model} support PIR sensor for motion-triggered wake-up"
    if "双摄" in t or "dual" in t or "多摄" in t:
        return f"Can {model} support dual camera input, hardware feasibility"
    if "存储" in t or "storage" in t or "sd" in t:
        return f"What are the local storage options for {model}, SD card support"
    if "ai" in t or "检测" in t or "detection" in t:
        return f"What AI detection models are supported on {model}, custom model training"
    return f"{model} product consultation: {problem[:80]}"


# ---------------------------------------------------------------------------
# 合成问题(commercial / product 数据不足时补足)
# ---------------------------------------------------------------------------

WOOCOMMERCE_PRODUCTS = [
    ("Multi-Sensor Expansion Development Kit for NE301", "commercial"),
    ("NeoEyes NE503 4K PoE Edge AI Camera", "commercial"),
    ("10W Solar Panel & 7Ah Outdoor Battery Kit", "commercial"),
    ("Sensor Expansion Board for NE101 and NE301", "commercial"),
    ("Single-Point dToF Ranging Module 20m Range", "commercial"),
    ("Thermal IR Array Sensor MLX90642 32x24", "commercial"),
]

PRODUCT_QUERIES = [
    ("What is the operating temperature range of NE301 edge camera", "product"),
    ("Does NE101 support WiFi HaLow connectivity", "product"),
    ("What sensor does NE503 use, resolution and frame rate", "product"),
    ("How to deploy NG4500 as edge AI gateway with multiple cameras", "product"),
    ("NE301 power consumption in sleep mode, battery life estimation", "product"),
    ("What AI models are pre-installed on NE503", "product"),
    ("Does NE101 support ONVIF protocol for video streaming", "product"),
    ("RTSP stream URL format for NE503 camera", "product"),
    ("How to train custom YOLOv8 model for NE301 using AI Tool Stack", "product"),
    ("What is the detection range of NE301 people counting", "product"),
    ("NE101 cellular module support, 4G LTE Cat 1 compatibility", "product"),
    ("Container deployment on NE503, Docker support", "product"),
    ("What is the IP rating of NE301 outdoor enclosure", "product"),
    ("NeoMind platform features for device management", "product"),
    ("NE301 night vision capability, IR illumination range", "product"),
]


def synthetic_questions(intent: str, count: int) -> list[str]:
    """合成英文问题(商业/产品数据不足时补足)。"""
    pool: list[str] = []
    if intent == "commercial":
        for name, _ in WOOCOMMERCE_PRODUCTS:
            pool.append(f"How to order {name}, price and availability")
            pool.append(f"What are the specifications of {name}")
            pool.append(f"Is {name} in stock, shipping options to Europe")
        # 泛化商业问题
        for m in ["NE301", "NE101", "NE503", "NG4500"]:
            pool.append(f"Price quote for {m} camera, bulk order discount")
            pool.append(f"How to become CamThink distributor for {m}")
            pool.append(f"Lead time for {m} sample order")
            pool.append(f"Warranty policy for {m}")
    elif intent == "product":
        for q, _ in PRODUCT_QUERIES:
            pool.append(q)
        # 变体
        for m in ["NE301", "NE101", "NE503"]:
            pool.extend([
                f"What interfaces does {m} expose for integration",
                f"Mounting options for {m} outdoor deployment",
                f"Firmware update procedure for {m}",
                f"Data output format from {m} inference",
            ])
    # 去重 + 截取
    seen, result = set(), []
    for q in pool:
        if q not in seen:
            seen.add(q)
            result.append(q)
    return result[:count]


# ---------------------------------------------------------------------------
# 数据收集:真实问题(分类 + 英文)+ 合成补足
# ---------------------------------------------------------------------------

def load_real_questions() -> dict[str, list[dict]]:
    """从 support 库提真实问题,按意图分类 + 英文翻译。返回 {intent: [{q, file, source_problem}]}。"""
    by_intent: dict[str, list[dict]] = {"commercial": [], "product": [], "support": []}
    for d in CASE_DIRS:
        dirp = SUPPORT / d
        if not dirp.is_dir():
            continue
        for f in sorted(dirp.glob("*.md")):
            title = f.stem
            problem = extract_problem(f)
            if not problem or len(problem) < 15:
                continue
            intent = classify_intent(title, problem)
            q = to_english_query(problem, title, intent)
            by_intent[intent].append({
                "question": q, "file": str(f.relative_to(SUPPORT)),
                "source_problem": problem[:100], "source": "real",
            })
    return by_intent


def build_questions(per_intent: int = 100) -> dict[str, list[dict]]:
    """真实优先 + 合成补足到 per_intent。"""
    real = load_real_questions()
    result: dict[str, list[dict]] = {}
    for intent in ("commercial", "product", "support"):
        reals = real.get(intent, [])
        questions = list(reals)
        if len(questions) < per_intent:
            need = per_intent - len(questions)
            syn = synthetic_questions(intent, need + 20)  # 多取防去重后不够
            seen = {q["question"] for q in questions}
            for q in syn:
                if len(questions) >= per_intent:
                    break
                if q not in seen:
                    questions.append({"question": q, "file": "", "source_problem": "",
                                      "source": "synthetic"})
                    seen.add(q)
        questions = questions[:per_intent]
        result[intent] = questions
    return result


# ---------------------------------------------------------------------------
# 打 API + 统计
# ---------------------------------------------------------------------------

def ask(question: str, api: str, timeout: int = 90, max_retries: int = 3) -> dict:
    """打 API,429 限流时指数退避重试。"""
    import time as _time
    for attempt in range(max_retries + 1):
        sources, answer = [], []
        try:
            with requests.post(api, json={"message": question, "channel": "widget"},
                               stream=True, timeout=timeout) as r:
                if r.status_code == 429 and attempt < max_retries:
                    # 指数退避:3s → 6s → 12s
                    backoff = 3 * (2 ** attempt)
                    _time.sleep(backoff)
                    continue
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
                has_cn_support = any(s.get("type") == "filesystem" for s in sources)
                return {"answer": full, "sources": sources,
                        "is_answered": bool(full) and not is_reject and bool(sources),
                        "is_reject": is_reject, "n_sources": len(sources),
                        "has_cn_support": has_cn_support}
        except requests.exceptions.HTTPError as exc:
            if "429" in str(exc) and attempt < max_retries:
                _time.sleep(3 * (2 ** attempt))
                continue
            return {"answer": "", "sources": [], "is_answered": False,
                    "is_reject": False, "n_sources": 0, "has_cn_support": False,
                    "error": str(exc)[:200]}
        except Exception as exc:
            return {"answer": "", "sources": [], "is_answered": False,
                    "is_reject": False, "n_sources": 0, "has_cn_support": False,
                    "error": str(exc)[:200]}
    return {"answer": "", "sources": [], "is_answered": False,
            "is_reject": False, "n_sources": 0, "has_cn_support": False,
            "error": "429 after retries"}


def run_intent(intent: str, questions: list[dict], api: str) -> list[dict]:
    import time as _time
    results = []
    n = len(questions)
    for i, q in enumerate(questions, 1):
        print(f"  [{intent} {i}/{n}] {q['question'][:60]}", flush=True)
        res = ask(q["question"], api)
        res.update({"intent": intent, "question": q["question"],
                    "file": q.get("file", ""), "source": q.get("source", ""),
                    "source_problem": q.get("source_problem", "")})
        results.append(res)
        st = "答" if res.get("is_answered") else ("拒" if res.get("is_reject") else "ERR")
        cn = "🇨🇳" if res.get("has_cn_support") else "  "
        print(f"    → {st} {cn} src={res.get('n_sources', 0)} | {res.get('answer','')[:50]}", flush=True)
        _time.sleep(3.5)  # 节流:20/min 限流,留余量
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=DEFAULT_API)
    ap.add_argument("--per-intent", type=int, default=100)
    ap.add_argument("--out", default="e2e_intent_en_results.json")
    args = ap.parse_args()

    print(f"构建问题集(每意图 {args.per_intent} 个,真实优先 + 合成补足)...")
    questions = build_questions(args.per_intent)
    for intent in ("commercial", "product", "support"):
        reals = sum(1 for q in questions[intent] if q["source"] == "real")
        print(f"  {intent}: {len(questions[intent])} 题(真实 {reals} + 合成 {len(questions[intent])-reals})")

    print(f"\nAPI: {args.api}\n" + "=" * 70)
    all_results = []
    for intent in ("commercial", "product", "support"):
        print(f"\n=== {intent.upper()} ===")
        all_results.extend(run_intent(intent, questions[intent], args.api))

    # 汇总
    print("\n" + "=" * 70)
    print(f"{'意图':<12} {'精准答':<10} {'拒答':<10} {'失败':<8} {'🇨🇳命中support':<16} {'平均sources'}")
    for intent in ("commercial", "product", "support"):
        rs = [r for r in all_results if r["intent"] == intent]
        n = len(rs)
        ans = sum(1 for r in rs if r.get("is_answered"))
        rej = sum(1 for r in rs if r.get("is_reject"))
        err = sum(1 for r in rs if r.get("error"))
        cn = sum(1 for r in rs if r.get("has_cn_support"))
        avg_src = sum(r.get("n_sources", 0) for r in rs) / n if n else 0
        print(f"{intent:<12} {ans}/{n:<8} {rej}/{n:<8} {err:<8} {cn}/{n:<14} {avg_src:.1f}")

    Path(args.out).write_text(
        json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n详细 → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
