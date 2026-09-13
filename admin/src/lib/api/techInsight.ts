import { apiFetch } from "@/lib/api";
import type { ClusterList, SyncRunList } from "@/types/api";

export interface TechKpi {
  p95_ms: number;
  anomaly_rate: number;
  fail_rate: number;
  recovered_rate: number;
  anomaly_count: number;
  fail_count: number;
  recovered_count: number;
  /** 环比 delta;上一等长时间窗无数据时为 null(不假装环比)。 */
  anomaly_delta: number | null;
  fail_delta: number | null;
  recovered_delta: number | null;
  /** 真实失败类别分布(generation_error 的 failure_kind)。 */
  failure_kinds: Record<string, number>;
  /** 分母:当前窗口 trace 总数(无裸百分比)。 */
  trace_total: number;
  window: { from: string; to: string };
  baseline: number;
  /** previous_window=历史对比;current_window_p50_fallback=诊断参考,非历史对比。 */
  baseline_source: "previous_window" | "current_window_p50_fallback";
  comparison: number;
}

export interface StagePercentile {
  p50: number;
  p95: number;
  normal_max: number;
  /** 当前窗口该阶段超过 normal_max 的 trace 条数(瓶颈识别证据)。 */
  over_count: number;
  p50_pct?: number;
  p95_pct?: number;
}

export interface TrendDay {
  date: string;
  p50: number;
  p95: number;
}

export interface AnomalyItem {
  /** 机器可读类型(如 generate_slow / generation_error:provider_error)。 */
  type: string;
  /** 人类可读标签。 */
  label: string;
  /** 语义严重度:error=错误类,slow=慢类(前端按语义着色,不按计数)。 */
  severity: "slow" | "error";
  count: number;
  pct?: number;
}

export interface DegradationItem {
  from: string;
  to: string;
  reason: string;
}

export interface TechHealth {
  /** healthy | degraded | critical | insufficient_data | no_data */
  status: string;
  reasons: string[];
  sample_size: number;
}

export interface TechPerformanceData {
  kpi: TechKpi;
  stages: Record<string, StagePercentile>;
  trends: TrendDay[];
  anomalies: AnomalyItem[];
  degradations: DegradationItem[];
  health: TechHealth;
  trace_coverage_from: string | null;
}

export function fetchTechPerformance(
  range: string = "7d",
): Promise<TechPerformanceData> {
  return apiFetch<TechPerformanceData>(`/tech/performance?range=${range}`);
}

export function fetchCoverageGaps(
  status?: string,
): Promise<ClusterList> {
  const qs = status ? `?status=${status}` : "";
  return apiFetch<ClusterList>(`/analytics/coverage-gaps${qs}`);
}

export interface GapTrendDay {
  date: string;
  total: number;
  unanswered: number;
  unanswered_rate: number;
}

export function fetchGapTrends(
  days: number = 30,
): Promise<{ trends: GapTrendDay[] }> {
  return apiFetch(`/analytics/gap-trends?days=${days}`);
}

export interface SourceHealthItem {
  source_id: string;
  source_type: string;
  product: string;
  enabled: boolean;
  doc_count: number;
  chunk_count: number;
  /** 成功率统计窗口(天),与请求参数一致。 */
  window_days: number;
  total_syncs: number;
  success_syncs: number;
  /** 一致性自愈(部分补齐)次数:计入分母、不计入成功数。 */
  partial_syncs: number;
  failed_syncs: number;
  sync_success_rate: number;
  /** healthy | degraded | critical | insufficient_data | disabled */
  health: string;
  last_sync: string | null;
  /** 最近一次同步状态(success/failed/partial/null),全部时间范围。 */
  last_sync_status: string | null;
  last_sync_error: string | null;
}

export function fetchSourceHealth(
  days: number = 30,
): Promise<{ items: SourceHealthItem[]; days: number }> {
  return apiFetch(`/analytics/source-health?days=${days}`);
}

// --------------------------------------------------------------------------- //
// #51 B2 事件信号区(复用优先:同步级事件消费既有 GET /sync-runs 权威读面;
// 生成级事件是该缺口唯一新增只读读面 GET /tech/generation-events)
// --------------------------------------------------------------------------- //

/** 生成级事件(index_generations failed/retired;后端 P 轴权威表只读透传)。 */
export interface GenerationEventItem {
  generation_id: string;
  ordinal: number;
  source_id: string;
  status: string;
  /** failed=error / retired=info(机器词表;运营标签见 lib/generationStatus.ts)。 */
  severity: string;
  doc_count: number;
  chunk_count: number;
  /** 失败证据 JSONB 原样透传(retired 为 null)。 */
  failure: Record<string, unknown> | null;
  reason_summary: string | null;
  created_at: string | null;
  activated_at: string | null;
  retired_at: string | null;
  /** retired→retired_at;failed→updated_at(诚实近似,后端注明)。 */
  event_at: string | null;
}

export interface GenerationEventList {
  items: GenerationEventItem[];
  total: number;
}

export function fetchGenerationEvents(
  limit: number = 10,
): Promise<GenerationEventList> {
  return apiFetch(`/tech/generation-events?limit=${limit}`);
}

/**
 * 同步级事件信号(复用既有 GET /sync-runs,零新增后端):
 * 跨源取 failed 与 interrupted 两类终态(status 参数为单词表,两次并行),
 * 运营标签/严重度映射见 lib/generationStatus.ts。
 */
export async function fetchSyncIncidents(
  sizePerStatus: number = 10,
): Promise<{ failed: SyncRunList; interrupted: SyncRunList }> {
  const [failed, interrupted] = await Promise.all([
    apiFetch<SyncRunList>(`/sync-runs?status=failed&size=${sizePerStatus}`),
    apiFetch<SyncRunList>(`/sync-runs?status=interrupted&size=${sizePerStatus}`),
  ]);
  return { failed, interrupted };
}

// --------------------------------------------------------------------------- //
// v1.6.3 B2 Answer Gaps 操作者投影(GET /tech/answer-gaps)。
// 聚类/会话权威真相之上的投影,miss_type 与 /analytics/coverage-gaps
// 权威分类同源。Wave 1 Track E 扩展:观察状态机(U-15)+ 导出(U-16)API 面。
// --------------------------------------------------------------------------- //

/** 单个答案缺口投影项(全部字段均有权威来源,见后端端点 docstring)。 */
export interface AnswerGapItem {
  id: string;
  cluster_type: "gap";
  representative_question: string;
  sample_questions: string[];
  /** 相关提问数(聚类权威)。 */
  question_count: number;
  /** 受影响回答数 = 归属会话计数(conversations.cluster_id 权威)。 */
  impacted_answer_count: number;
  status: "open" | "observing" | "resolved";
  /** 权威原因分类(reject/low/召回空/召回不足);无证据 → 未分类。 */
  miss_type: string;
  /** 本聚类内各权威分类的会话计数分布(诊断详情证据)。 */
  miss_type_breakdown: Record<string, number>;
  /** 最近发生 = 归属会话 MAX(created_at);无会话证据 → null(UI 显示证据不可用)。 */
  last_seen_at: string | null;
  period_start: string | null;
  period_end: string | null;
  created_at: string;
}

export interface AnswerGapList {
  items: AnswerGapItem[];
  total: number;
  page: number;
  size: number;
  miss_type_summary: Record<string, number>;
}

export interface AnswerGapQuery {
  status?: "open" | "observing" | "resolved";
  cause?: string;
  q?: string;
  /** 时间窗:7d/30d/all;last_seen 未知(时间不可用)不因窗口被排除。 */
  window?: "7d" | "30d" | "all";
  order?: "last_seen" | "questions" | "impacted";
  dir?: "asc" | "desc";
  page?: number;
  size?: number;
}

export function fetchAnswerGaps(query: AnswerGapQuery = {}): Promise<AnswerGapList> {
  const params = new URLSearchParams();
  if (query.status) params.set("status", query.status);
  if (query.cause) params.set("cause", query.cause);
  if (query.q) params.set("q", query.q);
  if (query.window) params.set("window", query.window);
  if (query.order) params.set("order", query.order);
  if (query.dir) params.set("dir", query.dir);
  if (query.page) params.set("page", String(query.page));
  if (query.size) params.set("size", String(query.size));
  const qs = params.toString();
  return apiFetch<AnswerGapList>(`/tech/answer-gaps${qs ? `?${qs}` : ""}`);
}

/** 缺口归属会话证据(诊断侧板「相关对话」只读投影)。 */
export interface GapConversationItem {
  id: string;
  question: string;
  is_answered: boolean;
  created_at: string;
}

export function fetchGapConversations(
  gapId: string,
  limit: number = 20,
): Promise<{ items: GapConversationItem[]; total: number }> {
  return apiFetch(`/tech/answer-gaps/${gapId}/conversations?limit=${limit}`);
}

// --------------------------------------------------------------------------- //
// Wave 1 Track E — U-15 观察状态机(OPEN→OBSERVING→RESOLVED;IF-1)+ U-16
// 导出与隐私(admin-only;IF-5)。权威语义 = backend/services/gap_observation.py
// 与 backend/api/admin/tech_export.py;前端不推断任何转移/隐私规则。
// --------------------------------------------------------------------------- //

/** 观察窗元数据(gap_observations 权威投影)。 */
export interface GapObservationMeta {
  started_at: string | null;
  window_days: number;
  window_ends_at: string | null;
  is_active: boolean;
  ended_at: string | null;
  /** recurrence(复现回 OPEN)| aborted(中止)| window_elapsed(满窗解决)| null。 */
  ended_reason: string | null;
}

/** 观察状态(lazy 评估后读;复现仅在 observing 态存在)。 */
export interface GapObservationState {
  gap_id: string;
  status: "open" | "observing" | "resolved";
  observation: GapObservationMeta | null;
  recurrence: { recurred: boolean; new_evidence_count: number } | null;
}

/** 观察流转事件(历史时间线;append-only 持久化事件)。 */
export interface GapObservationEventItem {
  id: string;
  /** start | recurrence | abort | resolve。 */
  event_type: string;
  from_status: string;
  to_status: string;
  actor: string | null;
  detail: Record<string, unknown>;
  created_at: string | null;
}

export function fetchGapObservation(
  gapId: string,
): Promise<GapObservationState> {
  return apiFetch<GapObservationState>(
    `/tech/answer-gaps/${gapId}/observation`,
  );
}

export function fetchGapObservationEvents(
  gapId: string,
): Promise<{ items: GapObservationEventItem[]; total: number }> {
  return apiFetch(`/tech/answer-gaps/${gapId}/observation/events`);
}

/** 开始观察(操作者确认修复完成=confirmed;后端三前置门:确认+sync/reindex
 *  成功+post-sync 验证成功;任一未过 → 409 detail={code,gates})。 */
export function startGapObservation(
  gapId: string,
  confirmed: boolean,
): Promise<GapObservationState> {
  return apiFetch<GapObservationState>(
    `/tech/answer-gaps/${gapId}/observation/start`,
    { method: "POST", body: JSON.stringify({ confirmed }) },
  );
}

/** 中止观察(OBSERVING→OPEN;禁直接 RESOLVED 由后端状态机保证)。 */
export function abortGapObservation(
  gapId: string,
): Promise<GapObservationState> {
  return apiFetch<GapObservationState>(
    `/tech/answer-gaps/${gapId}/observation/abort`,
    { method: "POST" },
  );
}

/** 导出动作审计 trail(admin-only)。 */
export interface GapExportAuditItem {
  id: string;
  cluster_id: string;
  actor: string;
  actor_role: string;
  window: string;
  row_count: number;
  created_at: string | null;
}

export function fetchGapExportAudits(
  gapId: string,
): Promise<{ items: GapExportAuditItem[]; total: number }> {
  return apiFetch(`/tech/answer-gaps/${gapId}/export-audits`);
}
