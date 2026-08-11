import { apiFetch } from "@/lib/api";

export interface IntentDist {
  commercial: number;
  product: number;
  support: number;
  off_topic: number;
}

export interface SceneItem {
  label: string;
  count: number;
  pct: number;
}

export interface ProductReqItem {
  label: string;
  count: number;
  pct: number;
}

export interface TopQuestionItem {
  question: string;
  count: number;
}

export interface TimeseriesDay {
  date: string;
  total: number;
  commercial: number;
  product: number;
  support: number;
  off_topic: number;
}

export interface BusinessOverviewData {
  service: {
    total: number;
    intent_dist: IntentDist;
    unknown_intent_count: number;
    north_star: number;
    satisfaction: number | null;
    up_count: number;
    down_count: number;
  };
  leads: {
    valid: number;
    potential: number;
    hot_products: { name: string; count: number }[];
  };
  scenes: SceneItem[];
  requirements: ProductReqItem[];
  top_questions: TopQuestionItem[];
  geo: { name: string; count: number; pct: number }[];
  geo_note: string;
  timeseries: TimeseriesDay[];
}

export function fetchBusinessOverview(
  range: string = "7d",
): Promise<BusinessOverviewData> {
  return apiFetch<BusinessOverviewData>(`/business/overview?range=${range}`);
}

export function fetchBusinessOverviewRange(
  from: string,
  to: string,
): Promise<BusinessOverviewData> {
  return apiFetch<BusinessOverviewData>(
    `/business/overview?from=${from}&to=${to}`,
  );
}

export function refreshBusinessSignals(): Promise<{
  scene_count: number;
  requirement_count: number;
  conversations_analyzed: number;
}> {
  return apiFetch(`/business/signals/refresh`, { method: "POST" });
}
