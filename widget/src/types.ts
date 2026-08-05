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
