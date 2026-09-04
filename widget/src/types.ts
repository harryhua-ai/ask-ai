// Widget 类型定义

export interface SourceLink {
  url: string;
  title: string;
  type: string;
  product?: string;
}

/** Issue #24:launcher 风格语义身份(封闭枚举;未知持久值回落 current)。 */
export type LauncherStyle = "current" | "assistant-spark" | "chat-bubble" | "orbit-neural";

/** Issue #24:launcher 主题偏好(auto = 系统主题;未知持久值回落 auto)。 */
export type LauncherThemePref = "auto" | "light" | "dark";

/** 主题解析后的落地值(auto 已按系统偏好消解)。 */
export type LauncherTheme = "light" | "dark";

export interface WidgetConfig {
  apiUrl: string;
  language?: string;
  primaryColor?: string;
  /** 渠道标识,缺省 "widget";admin 内嵌聊天传 "admin" 以隔离测试对话数据 */
  channel?: string;
  /** 站点体验标识(data-site-id);缺省 = legacy 公共 widget(不发站点字段) */
  siteId?: string;
  /** Issue #24 预览/测试覆写(data-launcher-style);优先级高于 site-config */
  launcherStyle?: string;
  /** Issue #24 预览/测试覆写(data-launcher-theme);优先级高于 site-config */
  launcherTheme?: string;
}

/** GET /api/widget/site-config 响应(公开体验字段;不含 allowed_origins) */
export interface SiteExperienceConfig {
  site_id: string;
  display_name?: string;
  welcome?: string;
  language?: string;
  starters?: string[];
  /** Issue #24:服务端已归一化的 launcher 外观(未配置 = current|auto) */
  launcher_style?: string;
  launcher_theme?: string;
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
