"""Widget Experience 语义注册表(I-UX-001:入口/主动展开/启动器/聊天窗/参与)。

与产品契约(I-UX-001-WIDGET-EXPERIENCE-plan.md)同一冻结集合;本模块是后端
唯一语义权威,Widget 侧注册表(widget/src/experience/*.ts)与 Admin 选项集
均消费此处序列化值,不各自定义。

迁移契约(冻结,§3/§5):
- 既有站点 experience 列 NULL = 未配置 → 保持 legacy 入口行为(不主动);
- 新建站点 seed 缺省 ``mini_entry``;Admin 显式配置永远权威,seed 不覆写;
- 未知/非法持久值服务端归一化回落默认(fail-safe;Widget bootstrap 不破坏),
  Admin 写入口显式 422(与 launcher 外观同规:写不允许静默改写)。

Trusted Action 契约(冻结,§2.13-§2.15):
- 语义目录封闭(PRICING/COMPARE_PRODUCTS 不默认发布);语义身份独立于展示
  label;仅 verified/published 允许主动曝光;TEST 走真实 ASK-AI 管道。
"""

from __future__ import annotations

# 入口呈现(A/B/C;NULL/legacy = 既有行为:仅 launcher,无主动展开)
ENTRY_MODE_LEGACY = "legacy"
ENTRY_MODE_PILL = "pill"
ENTRY_MODE_NUDGE = "nudge"
ENTRY_MODE_MINI_ENTRY = "mini_entry"
ENTRY_MODES: tuple[str, ...] = (
    ENTRY_MODE_LEGACY,
    ENTRY_MODE_PILL,
    ENTRY_MODE_NUDGE,
    ENTRY_MODE_MINI_ENTRY,
)
DEFAULT_NEW_SITE_ENTRY_MODE = ENTRY_MODE_MINI_ENTRY

# 主动展开时序(Fast≈3s / Balanced≈6s 默认 / Gentle≈10s / off)
PROACTIVE_OFF = "off"
PROACTIVE_FAST = "fast"
PROACTIVE_BALANCED = "balanced"
PROACTIVE_GENTLE = "gentle"
PROACTIVE_TIMINGS: tuple[str, ...] = (
    PROACTIVE_OFF,
    PROACTIVE_FAST,
    PROACTIVE_BALANCED,
    PROACTIVE_GENTLE,
)
#: 时序预设 → 延迟 ms(产品契约 §2.2 冻结近似值;实现常数是 HOW)
PROACTIVE_DELAY_MS: dict[str, int] = {
    PROACTIVE_FAST: 3000,
    PROACTIVE_BALANCED: 6000,
    PROACTIVE_GENTLE: 10000,
}
DEFAULT_PROACTIVE_TIMING = PROACTIVE_BALANCED

# 启动器动效(注意力提示,非常驻装饰;reduced-motion 下全部静止)
LAUNCHER_MOTION_STATIC = "static"
LAUNCHER_MOTION_SUBTLE_GLOW = "subtle_glow"
LAUNCHER_MOTION_SOFT_PULSE = "soft_pulse"
LAUNCHER_MOTION_SPARKLE = "sparkle"
LAUNCHER_MOTIONS: tuple[str, ...] = (
    LAUNCHER_MOTION_STATIC,
    LAUNCHER_MOTION_SUBTLE_GLOW,
    LAUNCHER_MOTION_SOFT_PULSE,
    LAUNCHER_MOTION_SPARKLE,
)
DEFAULT_LAUNCHER_MOTION = LAUNCHER_MOTION_SUBTLE_GLOW

# 启动器尺寸预设(S/M/L;内部字形等比缩放)
LAUNCHER_SIZES: tuple[str, ...] = ("small", "medium", "large")
DEFAULT_LAUNCHER_SIZE = "medium"

# 启动器品牌(独立于聊天窗主题;默认 ASK-AI 品牌保证可发现性)
LAUNCHER_BRAND_ASKAI = "askai"
LAUNCHER_BRAND_MATCH = "match"
LAUNCHER_BRAND_CUSTOM = "custom"
LAUNCHER_BRANDS: tuple[str, ...] = (
    LAUNCHER_BRAND_ASKAI,
    LAUNCHER_BRAND_MATCH,
    LAUNCHER_BRAND_CUSTOM,
)
DEFAULT_LAUNCHER_BRAND = LAUNCHER_BRAND_ASKAI

# 聊天窗主题(Match Website 默认;信号安全解析,不继承宿主任意 CSS)
CHAT_THEME_MATCH = "match"
CHAT_THEME_LIGHT = "light"
CHAT_THEME_DARK = "dark"
CHAT_THEME_CUSTOM = "custom"
CHAT_THEMES: tuple[str, ...] = (
    CHAT_THEME_MATCH,
    CHAT_THEME_LIGHT,
    CHAT_THEME_DARK,
    CHAT_THEME_CUSTOM,
)
DEFAULT_CHAT_THEME = CHAT_THEME_MATCH

# 聊天窗尺寸预设
CHAT_SIZES: tuple[str, ...] = ("default", "large")
DEFAULT_CHAT_SIZE = "default"


def normalize_entry_mode(value: str | None) -> str | None:
    """持久 entry_mode → 有效值;NULL/未知 = legacy(None 表示「未配置」语义)。"""
    if value is None:
        return None
    return value if value in ENTRY_MODES else None


def normalize_proactive_timing(value: str | None) -> str | None:
    if value is None:
        return None
    return value if value in PROACTIVE_TIMINGS else None


def normalize_launcher_motion(value: str | None) -> str | None:
    if value is None:
        return None
    return value if value in LAUNCHER_MOTIONS else None


def normalize_launcher_size(value: str | None) -> str | None:
    if value is None:
        return None
    return value if value in LAUNCHER_SIZES else None


def normalize_launcher_brand(value: str | None) -> str | None:
    if value is None:
        return None
    return value if value in LAUNCHER_BRANDS else None


def normalize_chat_theme(value: str | None) -> str | None:
    if value is None:
        return None
    return value if value in CHAT_THEMES else None


def normalize_chat_size(value: str | None) -> str | None:
    if value is None:
        return None
    return value if value in CHAT_SIZES else None


# ---------------------------------------------------------------------------
# Trusted Action 语义目录(冻结;语义身份 ≠ 展示 label)
# ---------------------------------------------------------------------------

ACTION_PRODUCT_SPECIFICATIONS = "PRODUCT_SPECIFICATIONS"
ACTION_SETUP_GUIDE = "SETUP_GUIDE"
ACTION_EXPLAIN_PAGE = "EXPLAIN_PAGE"
ACTION_TROUBLESHOOT = "TROUBLESHOOT"
ACTION_FIND_DOCUMENTATION = "FIND_DOCUMENTATION"
ACTION_COMPARE_PRODUCTS = "COMPARE_PRODUCTS"
ACTION_COMPATIBILITY = "COMPATIBILITY"
ACTION_PRICING = "PRICING"

#: 受控语义目录(封闭集合;冻结于产品契约 §2.13)
ACTION_TYPES: tuple[str, ...] = (
    ACTION_PRODUCT_SPECIFICATIONS,
    ACTION_SETUP_GUIDE,
    ACTION_EXPLAIN_PAGE,
    ACTION_TROUBLESHOOT,
    ACTION_FIND_DOCUMENTATION,
    ACTION_COMPARE_PRODUCTS,
    ACTION_COMPATIBILITY,
    ACTION_PRICING,
)

# Trusted Action 状态机(draft → verified → published;语义编辑回落 draft)
ACTION_STATE_DRAFT = "draft"
ACTION_STATE_VERIFIED = "verified"
ACTION_STATE_PUBLISHED = "published"
ACTION_STATES: tuple[str, ...] = (
    ACTION_STATE_DRAFT,
    ACTION_STATE_VERIFIED,
    ACTION_STATE_PUBLISHED,
)
#: 可进入 published 的来源状态(lifecycle 转移守卫用:仅 VERIFIED 可发布,
#: published→published 幂等重设;Role A 修正后此元组不再用于访客曝光)
PROACTIVE_ELIGIBLE_ACTION_STATES: tuple[str, ...] = (
    ACTION_STATE_VERIFIED,
    ACTION_STATE_PUBLISHED,
)
#: 访客曝光闸(Role A 修正 B;冻结生命周期语义:VERIFIED = 真实 ASK-AI 答案
#: 已人工接受,Admin 可见、生命周期有效;PUBLISHED = 有资格进入访客主动曝光。
#: 公开 site-config 只下发 published —— PUBLISHED 才是访客发布闸)
VISITOR_ELIGIBLE_ACTION_STATES: tuple[str, ...] = (ACTION_STATE_PUBLISHED,)

# 语义动作 → 默认查询模板(确定性;{product}/{page_title} 由 Widget 按当前
# 页面上下文绑定,零 LLM;语义身份 = 目录 id,不依赖模板措辞)
DEFAULT_ACTION_QUERY_TEMPLATES: dict[str, str] = {
    ACTION_PRODUCT_SPECIFICATIONS: "What are the specifications of {product}?",
    ACTION_SETUP_GUIDE: "How do I set up {product}?",
    ACTION_EXPLAIN_PAGE: "Explain this page: {page_title}",
    ACTION_TROUBLESHOOT: "Help me troubleshoot: {page_title}",
    ACTION_FIND_DOCUMENTATION: "Where can I find documentation about {product}?",
    ACTION_COMPARE_PRODUCTS: "Compare {product} with similar products",
    ACTION_COMPATIBILITY: "What is {product} compatible with?",
    ACTION_PRICING: "What is the pricing of {product}?",
}


def normalize_action_type(value: str | None) -> str | None:
    if value is None:
        return None
    return value if value in ACTION_TYPES else None


def normalize_action_state(value: str | None) -> str | None:
    if value is None:
        return None
    return value if value in ACTION_STATES else None
