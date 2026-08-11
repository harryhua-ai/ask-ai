import { apiFetch } from "@/lib/api";
import type { ClusterList } from "@/types/api";

export interface TechKpi {
  p95_ms: number;
  anomaly_rate: number;
  retry_rate: number;
  fail_rate: number;
  baseline: number;
  comparison: number;
}

export interface StagePercentile {
  p50: number;
  p95: number;
  normal_max: number;
}

export interface TrendDay {
  date: string;
  p50: number;
  p95: number;
}

export interface AnomalyItem {
  type: string;
  count: number;
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
  sync_success_rate: number;
  total_syncs: number;
  failed_syncs: number;
  health: string;
  last_sync: string | null;
}

export function fetchSourceHealth(
  days: number = 30,
): Promise<{ items: SourceHealthItem[]; days: number }> {
  return apiFetch(`/analytics/source-health?days=${days}`);
}
