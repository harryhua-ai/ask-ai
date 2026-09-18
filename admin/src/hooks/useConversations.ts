import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { Conversation } from "@/types/api";

export interface ConversationFilters {
  channel?: string;
  /** #68:ISO 3166-1 alpha-2 或 "UNKNOWN"(服务端过滤) */
  country?: string;
  /** #68:site_id 或 "UNKNOWN"(服务端过滤;独立于 transport channel) */
  entry?: string;
  is_answered?: boolean;
  feedback?: string;
  intent_tag?: string;
  q?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  has_retry?: boolean; // literal 重试(stages 显式 retry_count;生产路径暂不写入)
  has_failure?: boolean; // 真实失败(trace type=generation_error)
  has_feedback?: boolean; // Phase 2:有反馈
  has_clarify?: boolean; // Phase 2:触发澄清
}

interface PaginatedConversations {
  items: Conversation[];
  total: number;
  page: number;
  size: number;
}

export interface SourceClickItem {
  url: string;
  type: string;
  product?: string;
  clicked_at?: string;
}

export interface ConversationDetail {
  id: string;
  question: string;
  answer: string | null;
  channel: string;
  language: string | null;
  sources: unknown[];
  is_answered: boolean;
  feedback: string | null;
  response_time_ms: number | null;
  created_at: string;
  intent_tag: string | null;
  clicks: SourceClickItem[];
  /** 阶段⑯:最新 trace 类型(区分 拒答/生成失败/服务繁忙),additive */
  trace_type?: string | null;
  failure_kind?: string | null;
  /** #68:权威国家值(null = Unknown)与来源标记 */
  country?: string | null;
  country_source?: string | null;
  /** #68:入口权威投影(null = Unknown) */
  entry?: { site_id: string; display_name: string } | null;
}

export interface EntryOption {
  site_id: string;
  display_name: string;
}

export function useConversations(filters: ConversationFilters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== "") params.set(k, String(v));
  });
  return useQuery({
    queryKey: ["conversations", filters],
    queryFn: () => apiFetch<PaginatedConversations>(`/conversations?${params.toString()}`),
  });
}

export function useConversationDetail(id: string | null) {
  return useQuery({
    queryKey: ["conversation", id],
    queryFn: () => apiFetch<ConversationDetail>(`/conversations/${id}`),
    enabled: !!id,
  });
}

/** #68:Entry 筛选候选(站点标识 + 权威显示名,viewer 可读) */
export function useEntryOptions() {
  return useQuery({
    queryKey: ["conversation-entry-options"],
    queryFn: () => apiFetch<EntryOption[]>(`/conversations/entry-options`),
  });
}

/** #68:Country 筛选候选(仅权威来源值) */
export function useCountryOptions() {
  return useQuery({
    queryKey: ["conversation-country-options"],
    queryFn: () => apiFetch<{ countries: string[] }>(`/conversations/country-options`),
  });
}

export function useTagConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<{ intent_tag: string }>(`/conversations/${id}/tag`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["conversations"] }),
  });
}

export function useBatchTag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ tagged_count: number }>("/conversations/batch-tag", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["conversations"] }),
  });
}
