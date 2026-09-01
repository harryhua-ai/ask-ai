import { apiFetch } from "@/lib/api";
import type { ClusterList } from "@/types/api";

export interface TechKpi {
  p95_ms: number;
  anomaly_rate: number;
  retry_rate: number;
  fail_rate: number;
  anomaly_count: number;
  retry_count: number;
  fail_count: number;
  anomaly_delta: number;
  retry_delta: number;
  fail_delta: number;
  baseline: number;
  comparison: number;
}

export interface StagePercentile {
  p50: number;
  p95: number;
  normal_max: number;
  p50_pct?: number; // Phase 2:p50 占最大 P95 的比例
  p95_pct?: number; // Phase 2:p95 占最大 P95 的比例
}

export interface TrendDay {
  date: string;
  p50: number;
  p95: number;
}

export interface AnomalyItem {
  type: string;
  count: number;
  pct?: number;
  detail?: string;
}

export interface DegradationItem {
  from: string;
  to: string;
  reason: string;
}

export interface TechPerformanceData {
  kpi: TechKpi;
  stages: Record<string, StagePercentile>;
  trends: TrendDay[];
  anomalies: AnomalyItem[];
  degradations: DegradationItem[];
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
