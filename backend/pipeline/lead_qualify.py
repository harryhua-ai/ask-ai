"""Lead 资格判定(Lead Qualification)纯逻辑层。

产品契约(CAMTHINK V1 Sales Lead Capture & Handoff,冻结 WHAT):
- commercial intent != lead:普通产品/价格咨询不索要联系方式(LEAD-G001);
- 明确强信号(quotation / bulk / project / distributor / purchase timeline /
  explicit sales contact request)→ QUALIFIED(LEAD-G002);
- 仅 QUALIFIED 或用户明确要求销售联系时才邀请留联系方式,且先回答当前问题
  再自然邀请(LEAD-G003);
- One-Proactive-Ask:默认每会话主动邀请至多一次;用户忽略/拒绝后正常回答,
  只有「用户明确要求销售联系」或「出现实质更强的采购信号」才允许再邀请(契约 §7);
- Contact Captured ≠ Sales Contacted:不得无依据承诺销售会联系(契约 §8);
- 联系方式等 PII 只落 PostgreSQL sales_leads(授权 Admin 可见),
  绝不进入 Knowledge Corpus / Weaviate / RAG(契约 §14,HARD)。

本模块只含纯逻辑(常量/数据类/prompt 构造/LLM 输出解析/决策函数/联系方式
检测),不触 DB、不触 FastAPI;DB 读写见 backend/services/lead_service.py。
"""

import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from dataclasses import fields as dc_fields

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 常量:资格级别 / 线索状态
# --------------------------------------------------------------------------- #

LEAD_NONE = "none"
LEAD_POTENTIAL = "potential"
LEAD_QUALIFIED = "qualified"

_LEVEL_ORDER = {LEAD_NONE: 0, LEAD_POTENTIAL: 1, LEAD_QUALIFIED: 2}

# 产品生命周期语义:Potential → Qualified → Contact Captured → Handed Off(契约 §10)
LEAD_STATUS_POTENTIAL = "potential"
LEAD_STATUS_QUALIFIED = "qualified"
LEAD_STATUS_CONTACT_CAPTURED = "contact_captured"
LEAD_STATUS_HANDED_OFF = "handed_off"

LEAD_STATUSES = (
    LEAD_STATUS_POTENTIAL,
    LEAD_STATUS_QUALIFIED,
    LEAD_STATUS_CONTACT_CAPTURED,
    LEAD_STATUS_HANDED_OFF,
)

_STATUS_ORDER = {
    LEAD_STATUS_POTENTIAL: 0,
    LEAD_STATUS_QUALIFIED: 1,
    LEAD_STATUS_CONTACT_CAPTURED: 2,
    LEAD_STATUS_HANDED_OFF: 3,
}

CONTACT_TYPES = ("email", "phone", "whatsapp", "wechat", "other")

# 再邀请上限:首次 + 至多一次「实质更强信号」再邀请(契约 §7「合理再次提示」的有界化)
MAX_PROACTIVE_ASKS = 2

# --------------------------------------------------------------------------- #
# 联系方式检测(确定性正则,对原始用户消息执行,早于 mask_pii)
# --------------------------------------------------------------------------- #

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# 微信号:微信/wechat/vx 后跟 6-20 位字母开头 ID
_WECHAT_ID_RE = re.compile(
    r"(?:微信|wechat|weixin|vx|v信)[号:：\s]*([A-Za-z][-_A-Za-z0-9]{5,19})", re.IGNORECASE
)

# 电话号码:≥9 位数字(容忍 + 前缀与 -/空格/括号分隔);<9 位排除日期/编号噪声
_PHONE_RE = re.compile(r"(?<![\d@.\-])(?:\+\d[\d\s().-]{8,17}\d|\d[\d\s().-]{7,17}\d)(?![\d@.\-])")

_WHATSAPP_KW_RE = re.compile(r"whats\s*app|whatsapp", re.IGNORECASE)
_WECHAT_KW_RE = re.compile(r"微信|wechat|weixin", re.IGNORECASE)
_PHONE_KW_RE = re.compile(r"电话|手机号|联系电话|phone|tel|mobile|call me", re.IGNORECASE)


def mask_contact_value(value: str) -> str:
    """联系方式脱敏展示值(列表/trace/日志用;原文只进 sales_leads 表)。

    邮箱保留首字符与域名(``j***@example.com``);电话保留前 3 后 2
    (``138******78``);其余统一打码到 25% 长度。
    """
    value = (value or "").strip()
    if not value:
        return ""
    if "@" in value:
        local, _, domain = value.partition("@")
        head = local[:1] if local else "*"
        return f"{head}***@{domain}"
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 7:
        return f"{digits[:3]}******{digits[-2:]}"
    keep = max(1, len(value) // 4)
    return value[:keep] + "*" * max(3, len(value) - keep)


@dataclass(frozen=True)
class ContactHit:
    """从原始用户消息中确定性检出的联系方式。

    ``value`` 为原文(仅允许写入 PostgreSQL sales_leads,由授权 Admin 访问);
    ``masked`` 为脱敏展示值(trace / 列表 / 日志一律用它)。
    """

    type: str  # email | phone | whatsapp | wechat | other
    value: str
    masked: str


def detect_contact(text: str) -> ContactHit | None:
    """从文本中检出一种联系方式(存在即满足 LEAD-G004,不要求多种)。

    优先级:邮箱 > 显式关键词(whatsapp/wechat/phone)> 通用号码形状。
    纯函数;无命中返回 None。
    """
    if not text:
        return None

    m = _EMAIL_RE.search(text)
    if m:
        return ContactHit(type="email", value=m.group(0), masked=mask_contact_value(m.group(0)))

    m = _WECHAT_ID_RE.search(text)
    if m:
        val = m.group(1)
        default_type = "wechat" if not _WHATSAPP_KW_RE.search(text) else "whatsapp"
        return ContactHit(type=default_type, value=val, masked=mask_contact_value(val))

    phone_m = _PHONE_RE.search(text)
    if phone_m:
        raw = phone_m.group(0).strip()
        digits = re.sub(r"\D", "", raw)
        # 9-15 位数字才算号码:滤掉 8 位日期(20260902)、订单号碎片等
        if 9 <= len(digits) <= 15:
            if _WHATSAPP_KW_RE.search(text):
                ctype = "whatsapp"
            elif _WECHAT_KW_RE.search(text):
                ctype = "wechat"
            elif _PHONE_KW_RE.search(text):
                ctype = "phone"
            else:
                ctype = "phone"
            return ContactHit(type=ctype, value=raw, masked=mask_contact_value(raw))
    return None


# --------------------------------------------------------------------------- #
# 明确「要求销售联系」确定性短语(qualifier LLM 的安全网)
# --------------------------------------------------------------------------- #

_EXPLICIT_SALES_RE = re.compile(
    r"联系(你们的|你们|贵司)?销售"
    r"|销售(人员|团队)?(联系|跟进|回电)"
    r"|找(一下)?(你们)?销售"
    r"|让销售"
    r"|转(接)?人工"
    r"|需要?(一份)?(正式)?报价"
    r"|要(一份)?报价单"
    r"|requesting? (a |an )?(formal |official )?quot"
    r"|request.{0,12}quot"
    r"|\bquotation\b"
    r"|price quote"
    r"|contact (your |us |the )?sales"
    r"|talk to (a |your |the )?sales"
    r"|sales (team|rep|representative|person) (contact|reach out|get)"
    r"|get in touch with (your )?sales"
    r"|have (your |a )?sales",
    re.IGNORECASE,
)


def explicit_sales_hint(text: str) -> bool:
    """确定性判断用户消息是否明确要求销售联系/正式报价(安全网,LLM 之外)。"""
    if not text:
        return False
    return bool(_EXPLICIT_SALES_RE.search(text))


# --------------------------------------------------------------------------- #
# 资格判定 LLM 输入/输出
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LeadFields:
    """从对话中结构化提取的商业信息(用户自愿提供,允许全空)。"""

    name: str = ""
    company: str = ""
    region: str = ""
    product_interest: str = ""
    quantity: str = ""
    use_case: str = ""
    purchase_intent: str = ""
    timeline: str = ""

    def non_empty(self) -> dict[str, str]:
        return {k: v for k, v in asdict(self).items() if v}


_FIELD_KEYS = {f.name for f in dc_fields(LeadFields)}


@dataclass(frozen=True)
class LeadQualification:
    """单轮 lead 资格判定结果(LLM 输出解析产物,fail-open 时为默认值)。"""

    level: str = LEAD_NONE
    explicit_sales_request: bool = False
    stronger_signal: bool = False
    fields: LeadFields = field(default_factory=LeadFields)
    summary: str = ""
    ran: bool = False  # 便于上层区分「判定过但 none」与「判定失败/未判定」


_QUALIFIER_SYSTEM_PROMPT = """你是 B2B 硬件公司 CamThink 的销售线索资格判定器。根据「当前用户消息」和「近期对话」,判定商业采购信号强度并提取用户自愿提供的商业信息。

## 判定规则
- none:普通产品/技术/价格咨询,无商业跟进信号。例:「NE503 有什么接口?」「NE503 多少钱?」——单紧行业了解或单次询价都不是线索。
- potential:出现初步商业意向。例:提到公司/项目背景、大规模部署、经销/集成意向、比较选型、索要资料用于评估。
- qualified:出现明确强信号。任一即可:明确采购/下单意向、request quotation(要求正式报价)、提到数量、project requirement(具体项目需求)、distributor/reseller/integrator 合作、bulk pricing、deployment scale、purchase timeline、明确要求销售联系。
- 只有 qualified 或用户明确要求销售联系时,后续才会邀请留联系方式;拿不准时判低不判高。

## 其他输出
- explicit_sales_request:用户本轮是否明确要求销售/人工联系或正式报价。
- stronger_signal:与「已记录线索信息」相比,本轮是否出现此前未记录的实质更强信号(数量/时间线/报价请求/项目规模/合作模式)。
- fields:只提取用户明确说过的信息,没有就留空字符串,不要推测。
- summary:一两句中文概括这个商业机会(谁/要什么/多急),供销售快速判断是否跟进。

只返回 JSON(不要 markdown 代码块):
{"lead_level": "none|potential|qualified", "explicit_sales_request": true/false, "stronger_signal": true/false, "fields": {"name": "", "company": "", "region": "", "product_interest": "", "quantity": "", "use_case": "", "purchase_intent": "", "timeline": ""}, "summary": ""}"""


def build_qualification_prompt(
    question: str,
    history: list[dict] | None,
    recorded_fields: dict[str, str] | None,
) -> list[dict]:
    """构造资格判定 LLM messages。

    Args:
        question: 当前用户消息(已 mask_pii;联系方式由确定性正则另行捕获)。
        history: 近期对话(mask 后),OpenAI 风格 {role, content}。
        recorded_fields: 该会话已记录的线索字段(供 stronger_signal 对比)。
    """
    parts: list[str] = [f"## 当前用户消息\n{question}"]
    if history:
        lines = [
            f"{'用户' if h.get('role') == 'user' else 'AI'}: {h.get('content', '')}"
            for h in history[-8:]
        ]
        parts.append("## 近期对话\n" + "\n".join(lines))
    recorded = {k: v for k, v in (recorded_fields or {}).items() if v}
    if recorded:
        parts.append("## 已记录线索信息\n" + json.dumps(recorded, ensure_ascii=False))
    return [
        {"role": "system", "content": _QUALIFIER_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _clean_str(value: object, cap: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:cap]


def parse_qualification(content: str) -> LeadQualification:
    """解析 qualifier LLM 输出为 LeadQualification。

    容忍 markdown 代码围栏;任何解析/校验失败 fail-open 返回
    ``LeadQualification(level=LEAD_NONE, ran=False)``,绝不抛异常阻断问答。
    """
    if not content:
        return LeadQualification()
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json")
        text = text.strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        logger.warning("lead qualifier 输出非 JSON,fail-open 按 none 处理")
        return LeadQualification()
    if not isinstance(data, dict):
        return LeadQualification()

    level = data.get("lead_level")
    if level not in _LEVEL_ORDER:
        level = LEAD_NONE

    raw_fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}
    kwargs = {k: _clean_str(raw_fields.get(k)) for k in _FIELD_KEYS}

    return LeadQualification(
        level=level,
        explicit_sales_request=bool(data.get("explicit_sales_request")),
        stronger_signal=bool(data.get("stronger_signal")),
        fields=LeadFields(**kwargs),
        summary=_clean_str(data.get("summary"), cap=800),
        ran=True,
    )


# --------------------------------------------------------------------------- #
# 决策:是否邀请留联系方式 / 线索状态推进
# --------------------------------------------------------------------------- #


def decide_invite(
    qual: LeadQualification,
    *,
    prompt_count: int,
    contact_present: bool,
    explicit_hint: bool = False,
) -> bool:
    """One-Proactive-Ask 规则(契约 §7)。

    - 已有联系方式:不再邀请(G004 已达成);
    - 用户明确要求销售联系(或确定性短语命中):允许邀请(含再邀请);
    - 未达 qualified:不邀请(G001);
    - 首次 qualified:邀请一次;
    - 已邀请过:仅当出现实质更强信号且未达上限(MAX_PROACTIVE_ASKS)时再邀请一次。
    """
    if contact_present:
        return False
    if qual.explicit_sales_request or explicit_hint:
        return True
    if _LEVEL_ORDER.get(qual.level, 0) < _LEVEL_ORDER[LEAD_QUALIFIED]:
        return False
    if prompt_count <= 0:
        return True
    if prompt_count >= MAX_PROACTIVE_ASKS:
        return False
    return bool(qual.stronger_signal)


def compute_status(
    prev_status: str | None,
    qual: LeadQualification,
    *,
    contact_now: bool,
) -> str:
    """推进线索状态:只升不降;handed_off 为管理员终态,自动流程不回退。"""
    if prev_status == LEAD_STATUS_HANDED_OFF:
        return LEAD_STATUS_HANDED_OFF

    level_status = (
        LEAD_STATUS_QUALIFIED
        if qual.level == LEAD_QUALIFIED
        else LEAD_STATUS_POTENTIAL if qual.level == LEAD_POTENTIAL else None
    )
    prev_rank = _STATUS_ORDER.get(prev_status or "", -1)
    rank = max(prev_rank, _STATUS_ORDER[level_status] if level_status else -1)
    if contact_now:
        rank = max(rank, _STATUS_ORDER[LEAD_STATUS_CONTACT_CAPTURED])
    if rank < 0:
        rank = _STATUS_ORDER[LEAD_STATUS_POTENTIAL]
    return LEAD_STATUSES[rank]


# --------------------------------------------------------------------------- #
# 回答内嵌指令(邀请 / 确认;由 _build_messages 附加到 system prompt)
# --------------------------------------------------------------------------- #

LEAD_INVITE_INSTRUCTION = (
    "[商务跟进指令] 本轮用户的请求包含明确采购强信号(如要求正式报价、批量采购、"
    "项目需求、经销合作、采购时间表,或明确要求销售联系)。\n"
    "要求:1) 首先完整、正常地回答用户当前的问题,不得因为推销而缩水;2) 回答完全结束后,"
    "另起一行追加一句简短自然的话,邀请用户留下任一联系方式(邮箱/电话/WhatsApp/微信均可),"
    "以便获取正式报价或方案;3) 全程只邀请这一次,不追问、不重复;"
    "4) 绝对不要承诺「销售人员一定会联系你」或给出任何联系时限——只能说已记录需求、"
    "留下联系方式后可获得正式报价或方案;5) 不使用 emoji;6) 使用与回答正文相同的语言。"
)

LEAD_ACK_INSTRUCTION = (
    "[联系方式记录指令] 用户刚刚在消息中提供了联系方式,系统已记录。\n"
    "要求:1) 简短自然地回应用户;2) 确认已记录其提供的联系方式与需求,可复述要点;"
    "3) 说明留下联系方式后可获得正式报价或方案建议;"
    "4) 绝对不要承诺「销售人员一定会联系你」或给出任何联系时限(如 24 小时内)——"
    "只能表达「已记录」;5) 不使用 emoji;6) 使用与用户消息相同的语言。"
)


# --------------------------------------------------------------------------- #
# 单轮上下文(由 LeadService 基于原始消息+DB 构建,供 pipeline 只读使用)
# --------------------------------------------------------------------------- #


@dataclass
class LeadTurnContext:
    """单轮 lead 处理上下文。

    生命周期:routes 在 mask_pii 之后、调 orchestrator 之前构建(读 DB +
    确定性正则);orchestrator 只读;apply_turn 在流结束后写 DB。
    """

    session_id: str | None = None
    has_lead: bool = False
    lead_id: uuid.UUID | None = None
    status: str | None = None
    prompt_count: int = 0
    contact_present: bool = False
    recorded_fields: dict[str, str] = field(default_factory=dict)
    contact: ContactHit | None = None
    explicit_sales_hint: bool = False
    history: list[dict] = field(default_factory=list)

    @property
    def capture_mode(self) -> bool:
        """本轮用户消息携带联系方式 → 进入联系方式捕获模式。"""
        return self.contact is not None

    def should_qualify(self, intent_category: str) -> bool:
        """资格判定门:commercial/product 常规判定;已有线索/检出联系方式/明确
        销售请求时,不论意图都判定(support 会话里补联系方式同样要接住)。"""
        return bool(
            self.has_lead
            or self.capture_mode
            or self.explicit_sales_hint
            or intent_category in ("commercial", "product")
        )
