import { apiFetch } from "@/lib/api";
import type { ClusterList } from "@/types/api";

export interface TechKpi {
  p95_ms: number;
  anomaly_rate: number;
  retry_rate: number;
  fail_rate: number;
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
