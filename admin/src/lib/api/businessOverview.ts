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
    prev_total?: number; // Phase 2:上一同等长度时间窗总量
    delta_pct?: number; // Phase 2:环比百分比
  };
  leads: {
    /** 商业对话量(意图口径,≠线索) */
    commercial_conversations: number;
    /** 窗口内新建线索(至少 potential 资格) */
    potential: number;
    /** 达到 qualified 及以上(含已留联系方式/已移交) */
    qualified: number;
    /** 已获得至少一种有效联系方式 */
    contactable: number;
    /** 已人工移交销售 */
    handed_off: number;
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

export function fetchHotQuestions(
  intent: string,
  range: string = "7d",
): Promise<{ items: TopQuestionItem[]; intent: string }> {
  return apiFetch(`/business/hot-questions?intent=${intent}&range=${range}`);
}
