import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { Conversation } from "@/types/api";

export interface ConversationFilters {
  channel?: string;
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
