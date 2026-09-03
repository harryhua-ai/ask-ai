import type { TraceStageData } from "@/lib/api/traces";

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

export type SyncState =
  | "QUEUED"
  | "WAITING"
  | "RUNNING"
  | "RECOVERING"
  | "COMPLETED"
  | "FAILED"
  | "INTERRUPTED"
  | "IDLE";

export type SyncStage =
  | "DISCOVER"
  | "SAFETY_FILTER"
  | "FETCH"
  | "PARSE"
  | "CHUNK"
  | "EMBED"
  | "INDEX"
  | "CONSISTENCY"
  | "DONE";

/**
 * W2 execution_device 原始串。后端下发的是设备原文(如 "cuda"/"cpu",
 * GPU→CPU 降级伴随 fallback_reason/fallback_detail 字段),不保证封闭枚举,
 * 故类型为 string——展示层由 deviceLabel() 归一为 GPU/CPU/原文。
 * 已知归一值:GPU / CPU / UNKNOWN。
 */
export type ExecutionDevice = string;

export interface SyncCounters {
  docs_total?: number | null;
  docs_processed?: number | null;
  docs_new?: number | null;
  docs_updated?: number | null;
  docs_deleted?: number | null;
  items_unchanged?: number | null;
  chunks_written?: number | null;
  chunks_deleted?: number | null;
  [key: string]: number | null | undefined;
}

export interface SyncConsistency {
  missing?: number | null;
  missing_count?: number | null;
  orphan_count?: number | null;
  orphan?: number | null;
  verification_failed?: boolean | null;
  [key: string]: number | boolean | string | null | undefined;
}

export interface SyncStatusItem {
  source_id: string;
  state: SyncState;
  request_id: number | null;
  attempt: number | null;
  recovering: boolean | null;
  stage: SyncStage | null;
  stage_current: number | null;
  stage_total: number | null;
  counters: SyncCounters | null;
  execution_device: ExecutionDevice | null;
  started_at: string | null;
  updated_at: string | null;
}

export interface SyncStatusResponse {
  items: SyncStatusItem[];
}

export interface SyncRunLog {
  status: "success" | "failed" | "partial" | string | null;
  items_new: number | null;
  chunks_written: number | null;
  items_deleted: number | null;
  items_unchanged: number | null;
  error_detail: string | null;
}

export interface SyncRun {
  id: number;
  source_id: string;
  triggered_by: string | null;
  request_id: number | null;
  attempt: number | null;
  recovery: boolean | null;
  status: "running" | "completed" | "failed" | "interrupted" | string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  stage: SyncStage | null;
  counters: SyncCounters | null;
  consistency: SyncConsistency | null;
  execution_device: ExecutionDevice | null;
  fallback_reason: string | null;
  fallback_detail: string | null;
  error_summary: string | null;
  sync_log: SyncRunLog | null;
}

export interface SyncRunList {
  items: SyncRun[];
  total: number;
  page: number;
  size: number;
}

// --------------------------------------------------------------------------- //
// W2 /sync-health(#11 Health Authority):五维健康唯一权威读模型。
// state 为后端权威词表原文(维度级小写 ok/healthy/degraded/critical/failed/
// stale/fresh/partial/unknown/insufficient_data;overall 大写聚合词表);
// 前端只本地化呈现,绝不重判或派生第二健康态。
// --------------------------------------------------------------------------- //

export interface SyncHealthDimension {
  state: string;
  evidence: string | null;
  as_of: string | null;
}

export interface SyncHealthItem {
  source_id: string;
  source_type: string;
  enabled: boolean;
  expected_state: string;
  overall: string;
  recovering: boolean;
  document_count: number | null;
  connectivity: SyncHealthDimension;
  sync: SyncHealthDimension;
  coverage: SyncHealthDimension;
  freshness: SyncHealthDimension;
  consistency: SyncHealthDimension;
}

export interface SyncHealthResponse {
  items: SyncHealthItem[];
}

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
  /** 最近一次同步时间(由后端从 sync_log 聚合,无记录为 null)。 */
  last_sync: string | null;
  /** 最近一次同步的状态(success/failed/...),无记录为 null。 */
  last_sync_status: string | null;
  /** 最近一次同步失败时的错误明细(无记录或成功时为 null)。 */
  last_sync_error: string | null;
  /**
   * #18 删除生命周期(NULL = active 正常态)。持久化在数据源行上,
   * 刷新页面即可恢复;delete_failed 时附 lifecycle_error。
   */
  lifecycle_state: string | null;
  lifecycle_since: string | null;
  lifecycle_error: string | null;
}

/** #18:删除是否在途(已受理未终态;此时禁止同步/重复删除)。 */
export function isDeletionInFlight(ds: DataSource): boolean {
  return ds.lifecycle_state === "delete_requested" || ds.lifecycle_state === "deleting";
}

/** #18:是否允许发起新同步(deny-by-default,仅正常态可同步)。 */
export function isSyncEligible(ds: DataSource): boolean {
  return !ds.lifecycle_state; // NULL = active
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

// ==================== #16 代码仓库 Simple Mode:Discovery 契约 ====================
// 与后端 DiscoveryResultOut(source_center_schemas)一一对应;推荐/理由均为
// 后端冻结产物,前端只呈现,不本地重判知识价值或安全性。

export type RepoRecommendation = "include" | "exclude" | "review";

/** 逐候选准入结论(后端 FileAdmission + 人读冻结理由)。 */
export interface RepoDiscoveryCandidate {
  path: string;
  size: number;
  technical_safe: boolean;
  technical_reason: string | null;
  knowledge_role: string;
  recommendation: RepoRecommendation;
  policy_result: string;
  eligible: boolean;
  reason: string;
}

/** 候选分组(顶层目录;根目录散文件归入“(根目录)”)。 */
export interface RepoDiscoveryGroup {
  key: string;
  count: number;
  total_size: number;
  recommendation: RepoRecommendation;
  samples: string[];
}

/** #16/#17 preview 端点统一 envelope(S0 共享契约)。 */
export interface RepoDiscoveryResult {
  kind: string;
  target: { owner: string; repo: string; branch: string };
  totals: {
    files: number;
    safe_files: number;
    unsafe_files: number;
    total_size: number;
  };
  by_role: Record<string, { count: number; size: number; recommendation: string }>;
  groups: RepoDiscoveryGroup[];
  candidates: RepoDiscoveryCandidate[];
  /** 推荐编译产物 = 既有 config 词表(前端原样采用,不二次推导)。 */
  recommended_config: {
    file_types?: string[];
    exclude_dirs?: string[];
  };
  warnings: string[];
  capability_notes: string[];
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

/** LLM 路由链元素:{provider, model}。model 为 null = 用 provider 默认。 */
export interface LLMChainItem {
  provider: string;
  model: string | null;
}

export interface LLMRouting {
  task: string;
  /** chain 元素为 {provider, model} 对象(过渡期兼容旧字符串格式)。 */
  chain: LLMChainItem[] | string[];
}

export interface TraceMarkers {
  retry: boolean;
  failure: boolean;
  clarify: boolean;
  reject_short: boolean;
  degraded: boolean;
}

export interface TraceSummary {
  type: string;
  stages: Record<string, TraceStageData>;
  total_ms: number | null;
  confidence: number | null;
  markers?: TraceMarkers | null;
  /** 阶段⑯:generation_error 时的失败类别(additive) */
  failure_kind?: string | null;
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
  trace_summary?: TraceSummary | null;
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
  miss_type?: string;
}

export interface ClusterList {
  items: QuestionCluster[];
  total: number;
  page: number;
  size: number;
  miss_type_summary?: Record<string, number>;
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
