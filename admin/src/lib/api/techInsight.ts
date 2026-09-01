import { apiFetch } from "@/lib/api";
import type { ClusterList } from "@/types/api";

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
