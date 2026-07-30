export interface User {
  id: string;
  email: string;
  name: string | null;
  role: "admin" | "editor" | "viewer";
  is_active: boolean;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface DataSource {
  id: string;
  type: string;
  product: string;
  enabled: boolean;
  config: Record<string, unknown>;
  sync_interval: string;
  created_at: string;
  updated_at: string;
}

export interface SyncLog {
  id: string;
  source_id: string;
  source_type: string;
  status: "success" | "failed" | "partial";
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  items_new: number;
  items_updated: number;
  items_deleted: number;
  error_detail: string | null;
  triggered_by: string;
}

export interface Customization {
  id: string;
  name: string;
  system_prompt: string;
  style_tone: string | null;
  guardrails: string | null;
  language: string;
  assistant_name: string;
  is_active: boolean;
  version: string;
}

export interface LLMProvider {
  id: string;
  type: string;
  enabled: boolean;
  config: Record<string, unknown>;
}

export interface LLMRouting {
  task: string;
  chain: string[];
}

export interface Conversation {
  id: string;
  question: string;
  answer: string | null;
  channel: string;
  language: string | null;
  sources: unknown[];
  is_answered: boolean;
  feedback: string | null;
  response_time_ms: number | null;
  created_at: string;
  intent_tag: string | null;
}
