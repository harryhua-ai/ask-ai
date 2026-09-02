// Widget 类型定义

export interface SourceLink {
  url: string;
  title: string;
  type: string;
  product?: string;
}

export interface WidgetConfig {
  apiUrl: string;
  language?: string;
  primaryColor?: string;
  /** 渠道标识,缺省 "widget";admin 内嵌聊天传 "admin" 以隔离测试对话数据 */
  channel?: string;
  /** 站点体验标识(data-site-id);缺省 = legacy 公共 widget(不发站点字段) */
  siteId?: string;
}

/** GET /api/widget/site-config 响应(公开体验字段;不含 allowed_origins) */
export interface SiteExperienceConfig {
  site_id: string;
  display_name?: string;
  welcome?: string;
  language?: string;
  starters?: string[];
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
