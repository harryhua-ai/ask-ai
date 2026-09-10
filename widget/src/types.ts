// Widget 类型定义

export interface SourceLink {
  url: string;
  title: string;
  type: string;
  product?: string;
}

/**
 * Issue #24 REV1:launcher 统一外观语义 = icon × shape × theme。
 * 语义 id 是集成契约(与后端 LAUNCHER_ICONS/LAUNCHER_SHAPES、Admin、集成文档同一冻结集合);
 * 未知持久值回落 current | rounded-square | auto(fail-safe)。
 */
export type LauncherIcon =
  | "current"
  | "bot-sparkle"
  | "bubble-sparkle-fill"
  | "robot-smile"
  | "bubble-sparkle-outline";

export type LauncherShape = "round" | "rounded-square";

/**
 * V2.3 矫正:launcher 呈现方式(pill = 品牌「✦ Ask AI」紧凑胶囊 /
 * icon = 紧凑图标)。语义 id 与后端 LAUNCHER_PRESENTATIONS / Admin 同一冻结集合;
 * NULL/未配置 = icon(既有站点 legacy 行为,零迁移改写)。
 */
export type LauncherPresentation = "pill" | "icon";

/** Issue #24:launcher 主题偏好(auto = 系统主题;未知持久值回落 auto)。 */
export type LauncherThemePref = "auto" | "light" | "dark";

/** 主题解析后的落地值(auto 已按系统偏好消解)。 */
export type LauncherTheme = "light" | "dark";

/** @deprecated REV0 遗留风格 id(assistant-spark 等)已被权威视觉设计取代;
 *  仅作遗留桥识别(一律退役为 current),不再是集成契约面。 */
export type LauncherStyle = "current" | "assistant-spark" | "chat-bubble" | "orbit-neural";

export interface WidgetConfig {
  apiUrl: string;
  language?: string;
  primaryColor?: string;
  /** 渠道标识,缺省 "widget";admin 内嵌聊天传 "admin" 以隔离测试对话数据 */
  channel?: string;
  /** 站点体验标识(data-site-id);缺省 = legacy 公共 widget(不发站点字段) */
  siteId?: string;
  /** REV1 高级覆写(data-launcher-icon);优先级高于 site-config */
  launcherIcon?: string;
  /** REV1 高级覆写(data-launcher-shape);优先级高于 site-config */
  launcherShape?: string;
  /** V2.3 矫正覆写(data-launcher-presentation);优先级高于 site-config */
  launcherPresentation?: string;
  /** Issue #24 预览/测试覆写(data-launcher-theme);优先级高于 site-config */
  launcherTheme?: string;
  /** @deprecated REV0 遗留覆写(data-launcher-style);退役为 current,保留仅为兼容 */
  launcherStyle?: string;
  // ---- I-UX-001 嵌入级覆写(优先级高于 site-config;Admin 预览/高级集成)----
  /** data-entry-mode:legacy|pill|nudge|mini_entry */
  entryMode?: string;
  /** data-proactive:off|fast|balanced|gentle */
  proactive?: string;
  /** data-launcher-motion:static|subtle_glow|soft_pulse|sparkle */
  launcherMotion?: string;
  /** data-launcher-size:small|medium|large */
  launcherSize?: string;
  /** data-launcher-brand:askai|match|custom */
  launcherBrand?: string;
  /** data-launcher-color:#RRGGBB(brand=custom 时) */
  launcherColor?: string;
  /** data-chat-theme:match|light|dark|custom */
  chatTheme?: string;
  /** data-chat-accent:#RRGGBB(theme=custom 时) */
  chatAccent?: string;
  /** data-chat-size:default|large */
  chatSize?: string;
  /** I-UX-001 预览模式(Admin 实时预览;复用真实渲染路径,禁真实 /ask) */
  previewMode?: boolean;
  /** 预览页面上下文(仅 previewMode;喂给 greeting/action 解析器) */
  previewPageType?: string;
  previewProduct?: string;
  previewTitle?: string;
  /** 预览用 Trusted Actions(仅 Admin 预览注入;不来自站点配置) */
  previewActions?: TrustedActionRef[];
}

/** GET /api/widget/site-config 响应(公开体验字段;不含 allowed_origins) */
export interface SiteExperienceConfig {
  site_id: string;
  display_name?: string;
  welcome?: string;
  language?: string;
  starters?: string[];
  /** REV1:服务端已归一化+遗留桥的统一外观(未配置 = current|rounded-square|auto) */
  launcher_icon?: string;
  launcher_shape?: string;
  launcher_theme?: string;
  /** V2.3 矫正:呈现方式(pill|icon);未配置 = undefined → icon(legacy) */
  launcher_presentation?: string;
  /** @deprecated REV0 遗留回显(兼容缓存中的旧 Widget);新集成勿消费 */
  launcher_style?: string;
  // ---- I-UX-001(per-site;未配置 = undefined → legacy/默认)----
  entry_mode?: string;
  proactive_timing?: string;
  launcher_motion?: string;
  launcher_size?: string;
  launcher_brand?: string;
  launcher_color?: string;
  chat_theme?: string;
  chat_accent_color?: string;
  chat_size?: string;
  greeting_override?: string;
  /** 仅 verified/published 的 Trusted Actions(语义身份+展示 label+绑定查询) */
  trusted_actions?: TrustedActionRef[];
}

/** Trusted Action 下发形态(语义身份独立于展示 label;I-UX-001 §2.14) */
export interface TrustedActionRef {
  type: string;
  label: string;
  query: string;
}

/** 宿主页面上下文(非信任语义提示;后端只作软加分与背景段) */
export interface PageContextPayload {
  url?: string;
  title?: string;
  language?: string;
  page_type?: string;
  product?: string;
  product_id?: string;
  sku?: string;
  section?: string;
}

export type MessageType = "user" | "assistant";

export interface AttachmentRef {
  id: string;
  filename: string;
  kind: string;
  status: "uploading" | "ready" | "failed";
  error?: string;
}

export interface ChatMessage {
  id: string;
  type: MessageType;
  content: string;
  sources?: SourceLink[];
  attachments?: AttachmentRef[];
}
