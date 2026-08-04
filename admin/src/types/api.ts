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

export type DataSourceType = "github" | "filesystem";

/** GitHub 数据源 config 形状(统一 git 类型:clone + fetch+reset + API SHA 感知)。 */
export interface GithubSourceConfig {
  repo_url?: string;
  clone_path?: string;
  branches?: string[];
  file_types?: string[];
  exclude_dirs?: string[];
  exclude_regex?: string;
  max_file_size?: number;
}

/** 文件系统数据源 config 形状。 */
export interface FilesystemSourceConfig {
  root_path?: string;
  file_types?: string[];
  include_dirs?: string[];
  exclude_dirs?: string[];
  exclude_regex?: string;
  max_file_size?: number;
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

/** preview-dirs 返回的目录项(供目录选择器渲染)。 */
export interface PreviewDir {
  name: string;
  /** 相对 root_path 的相对路径(不泄露服务器绝对路径)。 */
  path: string;
  /** 该目录下可列子目录总数(供前端展示)。 */
  children_count: number;
  /** 第二层子目录(已限 50,懒展开时直接渲染)。 */
  children?: PreviewDir[];
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

export interface AnswerOverride {
  id: string;
  match_pattern: string;
  match_type: "semantic" | "keyword" | "regex";
  override_answer: string;
  override_sources: unknown[];
  created_by: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AnswerOverrideList {
  items: AnswerOverride[];
  total: number;
  page: number;
  size: number;
}

export interface QuestionCluster {
  id: string;
  cluster_type: "gap" | "top";
  representative_question: string;
  sample_questions: string[];
  question_count: number;
  status: "open" | "resolved";
  period_start: string | null;
  period_end: string | null;
  created_at: string;
}

export interface ClusterList {
  items: QuestionCluster[];
  total: number;
  page: number;
  size: number;
}

export interface SourceAnalyticsItem {
  url: string;
  source_type: string;
  product: string | null;
  clicks: number;
  references: number;
}

export interface SourceAnalytics {
  items: SourceAnalyticsItem[];
  days: number;
}

export interface RefreshResult {
  cluster_count: number;
  total_questions: number;
}
