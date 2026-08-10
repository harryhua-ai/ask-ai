import { apiFetch } from "@/lib/api";

/** 后端 RAG 各阶段记录的诊断字段(ms 之外的可选详情)。对应 backend/pipeline/rag.py stages 写入。 */
export interface TraceStageData {
  ms: number;
  // intent
  category?: string;
  reason?: string;
  // rewrite
  extracted?: string;
  rewritten?: string;
  // retrieve
  hybrid_count?: number;
  min_results_met?: boolean;
  effective_min?: number;
  path_counts?: { hybrid: number; symbol: number; boost: number };
  // rerank
  top_score?: number | null;
  count?: number;
  pruned?: number;
  results?: RerankSnippet[];
  // generate
  latency_ms?: number | null;
  tokens_output?: number | null;
  ttft_ms?: number | null;
  // output
  sources_count?: number;
}

export interface RerankSnippet {
  title: string;
  score: number | null;
  source_type: string;
  product: string;
  url: string;
  text?: string;
}

export interface AttachmentSummary {
  kind: string;
  text_length: number;
  text_preview: string;
}

export interface TraceData {
  id: string;
  conversation_id: string;
  prev_trace_id: string | null;
  turn_index: number;
  type: string;
  stages: Record<string, TraceStageData>;
  total_ms: number | null;
  intent: string | null;
  confidence: number | null;
  config_snapshot: Record<string, unknown>;
  attachments?: AttachmentSummary[];
  created_at: string;
}

export function fetchTraces(conversationId: string): Promise<TraceData[]> {
  return apiFetch<TraceData[]>(`/conversations/${conversationId}/traces`);
}
