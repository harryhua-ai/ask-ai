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

export interface BusinessOverviewData {
  service: {
    total: number;
    intent_dist: IntentDist;
    north_star: number;
    satisfaction: number;
  };
  leads: {
    valid: number;
    potential: number;
    hot_products: { name: string; count: number }[];
  };
  scenes: SceneItem[];
  requirements: ProductReqItem[];
  top_questions: TopQuestionItem[];
  geo: { name: string; count: number }[];
  geo_note: string;
  timeseries: { date: string; count: number }[];
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
