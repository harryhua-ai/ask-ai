"""合并任务理解(INC-3:Task Understanding Consolidation)。

将既有三段串行预处理合并为**一次**结构化 LLM 调用:

    classify_intent → extract_query → rewrite_query
    ⇒ understand_task(单次,task="task_understanding")

冻结语义(契约 §2/§3/§5/§7):
- legacy 意图枚举不变(commercial/product/support/off_topic),对外消费者兼容;
- 新增**交互模式**维度(与 legacy category 概念正交):
  standard / clarification_required / capability_orientation / off_topic;
  交互模式(而非 legacy category)决定路由:正常作答 / 澄清 / 能力导向 / 无关边界;
- ``clarification_required``(#26):大概率属域内但缺关键信息且上下文无法安全补全
  → 澄清而非拒答,绝不猜测产品;缺失产品名本身绝不足以判 off_topic;
- ``capability_orientation``(#27):询问助手本身的能力/范围/用法是合法交互,
  语义类覆盖中英文,**禁止短语补丁**;legacy category 映射 product;
- category=off_topic 仅用于确证无关。

失败契约(§7,逐维 fail-open,永不产生误拒):
- 整体失败/JSON 不可解析 → category=product, confidence=0.0, reason=有界诊断,
  interaction_mode=standard, extracted=rewritten=原 query, fallback_used=True;
- 单字段缺失/非法 → 逐字段安全缺省(category 非法→product;mode 缺失→由
  category 推导(off_topic→off_topic,否则 standard);confidence 非法→None;
  extracted 缺失→原 query;rewritten 缺失→extracted),fallback_used=True;
- 无合格历史( None 或 len<2,与既有 rewrite guard 同判据)→ 强制
  ``rewritten == extracted``(确定性,不依赖模型自觉);
- mode=off_topic ⇒ category=off_topic;category=off_topic ⇒ mode=off_topic
  (双向一致性修复,杜绝「standard 路由 + off_topic 枚举」的脏组合)。

边界:产品身份权威仍在 Product Resolver(先于本调用,契约 §4),本模块不输出
任何产品目标;语言权威仍是确定性 ``detect_language``;查询以用户原语言输出。
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

INTERACTION_MODES = (
    "standard",
    "clarification_required",
    "capability_orientation",
    "off_topic",
)

MODE_STANDARD = "standard"
MODE_CLARIFICATION = "clarification_required"
MODE_CAPABILITY = "capability_orientation"
MODE_OFF_TOPIC = "off_topic"

# legacy 枚举唯一权威定义点(intent.py);合并理解不新增第五个 legacy 值
from backend.pipeline.intent import VALID_CATEGORIES  # noqa: E402

_UNDERSTANDING_PROMPT = """你是 CamThink 智能应答的任务理解助手。请基于用户输入与对话历史,一次性完成四件事:意图分类、核心检索问题提取、自包含查询改写、交互模式判定。

## 第一步:交互模式判定(决定路由,先于分类)
- capability_orientation: 用户在询问**助手本身**——它能做什么/能帮什么忙/服务范围/怎么使用它。中英文语义等价表达都算(如「你会干什么」「你可以帮我什么」「怎么用你」「What can you do?」「How can you help me?」)。这是合法交互,**不是闲聊,也不是 off_topic**。
- clarification_required: 请求大概率属于产品/商务/支持域(有明确的产品/技术/采购诉求),但缺少继续所需的关键信息(典型:没说产品型号),且对话历史也补不上。此时**绝不猜产品,也绝不当无关处理**。例:「What is included in the box?」(无上下文)→ clarification_required。
- off_topic: **仅当有充分证据**表明请求与产品域完全无关:天气、通用闲聊、纯无关技术问题、纯竞品闲聊。**仅缺少产品名称不足以判 off_topic**。
- standard: 其余正常的产品/商务/支持请求,直接进入检索作答。

## 第二步:意图分类(4 类,供下游系统使用)
- commercial: 纯价格/采购/报价/渠道/库存/促销/商务合作(不涉及技术方案)
- product: 产品功能/参数/规格/选型/方案/竞品对比/适配/演示能力咨询(含"能否做 XX""怎么选型""有没有 XX 能力")
- support: 故障排查/报错/集成/二次开发/代码/调试/寄存器/固件
- off_topic: 仅限确证无关(见上)
一致性规则:interaction_mode=capability_orientation → category=product;clarification_required → category 取最贴近的产品/商务/支持类(区分不了则 product);off_topic 模式 → category=off_topic。

## 第三步:核心检索问题提取(extracted_query)
- 保留核心技术意图(产品型号、错误信息、功能需求),去除寒暄/签名/无关噪音
- 输入已简洁明确则原样返回
- 用用户的原始语言输出

## 第四步:自包含查询改写(rewritten_query)
{history_rules}

只输出 JSON(不要 markdown 代码块、不要解释):
{{"category": "commercial|product|support|off_topic", "reason": "简短理由", "confidence": 0.0到1.0, "interaction_mode": "standard|clarification_required|capability_orientation|off_topic", "extracted_query": "核心检索问题", "rewritten_query": "自包含查询"}}

## 对话历史(最近 3 轮)
{history}

## 用户输入
{query}
"""

_HISTORY_PRESENT_RULES = """- 结合对话历史,把当前问题改写为**自包含**的独立查询(没有历史也能理解)
- 保留用户原始意图与已确立的主体,不添加无关信息,不虚构产品身份
- 问题已经自包含时,rewritten_query 与 extracted_query 一致
- 用用户的原始语言输出"""

_HISTORY_ABSENT_RULES = (
    """- 本轮无有效对话历史:**rewritten_query 必须与 extracted_query 完全一致**"""
)

_NO_HISTORY_BLOCK = "(无有效历史)"

_MAX_UNDERSTAND_QUERIES = 2000
_REASON_BOUND = 300


@dataclass(frozen=True)
class TaskUnderstanding:
    """合并理解结果(单次 LLM 调用的结构化产物)。

    Attributes:
        category: legacy 意图枚举(4 值,外部消费者兼容映射的依据)。
        reason: 有界诊断理由(供 trace;不持久化思维链)。
        confidence: 0..1 或 None;仅诊断用,**不单独构成 off_topic 证据**。
        interaction_mode: 交互模式(路由权威)。
        extracted_query: 核心检索问题(符号/boost 桶/比较检索消费者)。
        rewritten_query: 自包含查询(主 hybrid/重排消费者);无合格历史时
            确定性等于 extracted_query。
        fallback_used: 是否发生了整体或逐字段回退(可观测,契约 §7)。
        parse_ok: 结构化 JSON 是否解析成功。
    """

    category: str = "product"
    reason: str = ""
    confidence: float | None = None
    interaction_mode: str = MODE_STANDARD
    extracted_query: str = ""
    rewritten_query: str = ""
    fallback_used: bool = False
    parse_ok: bool = True


def _history_block(history: list[dict] | None) -> str:
    lines = []
    for m in history[-6:]:
        role = "用户" if m.get("role") == "user" else "助手"
        content = m.get("content", "")
        if isinstance(content, str):
            lines.append(f"{role}: {content[:300]}")
    return "\n".join(lines) or _NO_HISTORY_BLOCK


def _total_fallback(query: str) -> TaskUnderstanding:
    """整体失败回退(契约 §7):检索保持可用,永不产生 off_topic 拒答。"""
    return TaskUnderstanding(
        category="product",
        reason="task understanding failed (fail-open: empty/malformed structured response)",
        confidence=0.0,
        interaction_mode=MODE_STANDARD,
        extracted_query=query,
        rewritten_query=query,
        fallback_used=True,
        parse_ok=False,
    )


async def understand_task(
    query: str,
    history: list[dict] | None,
    llm: Any,
) -> TaskUnderstanding:
    """一次结构化调用完成意图分类 + 查询提取 + 上下文改写 + 交互模式判定。

    Args:
        query: 用户当前查询原文。
        history: OpenAI 风格对话历史(可为 None);与既有 rewrite guard 同判据
            (None 或长度 <2 视为无合格历史)。
        llm: LLMProvider / LLMRouter 实例(task="task_understanding")。

    Returns:
        :class:`TaskUnderstanding`。任何失败都 fail-open:检索保持可用,
        绝不把畸形/失败转成 off_topic(契约 §7)。
    """
    qualifying_history = bool(history) and len(history) >= 2
    prompt = _UNDERSTANDING_PROMPT.format(
        history_rules=_HISTORY_PRESENT_RULES if qualifying_history else _HISTORY_ABSENT_RULES,
        history=_history_block(history) if qualifying_history else _NO_HISTORY_BLOCK,
        query=query[:_MAX_UNDERSTAND_QUERIES],
    )
    # 调用 + 解析整体包在 fail-open 内:任何异常(网络/畸形/非字符串内容)
    # 都落到整体回退,绝不向主管线抛错,也绝不转成 off_topic(契约 §7)
    try:
        response = await llm.generate(
            [{"role": "user", "content": prompt}],
            task="task_understanding",
            max_tokens=512,
            temperature=0.0,
            # 结构化预处理任务禁用思考(与 intent/extract/rewrite 同理,Issue #23)
            thinking="disabled",
        )
        raw = (response.content or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("understanding payload is not an object")
    except Exception:  # noqa: BLE001
        logger.warning("合并任务理解失败/不可解析,fail-open standard", exc_info=True)
        return _total_fallback(query)

    fallback_used = False

    # category:非法/缺失 → product(镜像 intent.py 既有 fail-open)
    category = data.get("category", "product")
    if category not in VALID_CATEGORIES:
        category = "product"
        fallback_used = True

    # confidence:非法/越界 → None
    raw_conf = data.get("confidence")
    try:
        confidence = float(raw_conf) if raw_conf is not None else None
        if confidence is not None and not (0.0 <= confidence <= 1.0):
            confidence = None
            fallback_used = True
    except (TypeError, ValueError):
        confidence = None
        fallback_used = True

    # interaction_mode:缺失 → 由 category 推导(off_topic→off_topic,否则
    # standard);非法 → 同推导。绝不因字段畸形进入 off_topic。
    mode = data.get("interaction_mode")
    if mode not in INTERACTION_MODES:
        mode = MODE_OFF_TOPIC if category == "off_topic" else MODE_STANDARD
        fallback_used = True

    # reason:缺失容错;有界(不持久化思维链)
    reason = data.get("reason", "")
    if not isinstance(reason, str):
        reason = ""
        fallback_used = True
    reason = reason[:_REASON_BOUND]

    # extracted:缺失/空 → 原 query
    extracted = data.get("extracted_query")
    if not isinstance(extracted, str) or not extracted.strip():
        extracted = query
        fallback_used = True
    extracted = extracted.strip().strip('"').strip("'")

    # rewritten:缺失/空 → extracted;无合格历史 → 强制 == extracted(契约 A2)
    rewritten = data.get("rewritten_query")
    if not isinstance(rewritten, str) or not rewritten.strip():
        rewritten = extracted
        fallback_used = True
    rewritten = rewritten.strip().strip('"').strip("'")
    if not qualifying_history:
        if rewritten != extracted:
            rewritten = extracted
            fallback_used = True

    # 双向一致性修复:mode 与 legacy category 的 off_topic 语义对齐,
    # 杜绝「standard 路由 + off_topic 枚举」(或反向)的脏组合
    if mode == MODE_OFF_TOPIC and category != "off_topic":
        category = "off_topic"
        fallback_used = True
    elif category == "off_topic" and mode != MODE_OFF_TOPIC:
        mode = MODE_OFF_TOPIC
        fallback_used = True

    return TaskUnderstanding(
        category=category,
        reason=reason,
        confidence=confidence,
        interaction_mode=mode,
        extracted_query=extracted,
        rewritten_query=rewritten,
        fallback_used=fallback_used,
        parse_ok=True,
    )
