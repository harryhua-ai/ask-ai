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
}

export type MessageType = "user" | "assistant";

export interface ChatMessage {
  id: string;
  type: MessageType;
  content: string;
  sources?: SourceLink[];
}
