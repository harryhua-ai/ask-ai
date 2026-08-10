import { apiFetch } from "@/lib/api";

export interface TraceStageInfo {
  ms: number;
  status?: "ok" | "warn" | "err";
  detail?: string;
}

export interface TraceData {
  id: string;
  conversation_id: string;
  prev_trace_id: string | null;
  turn_index: number;
  type: string;
  stages: Record<string, { ms: number; detail?: string }>;
  total_ms: number | null;
  intent: string | null;
  config_snapshot: Record<string, unknown>;
  created_at: string;
}

export function fetchTraces(conversationId: string): Promise<TraceData[]> {
  return apiFetch<TraceData[]>(`/conversations/${conversationId}/traces`);
}
