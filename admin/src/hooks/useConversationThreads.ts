import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";

/** #87:会话(Thread)审查 API。聚合/过滤/分页均在服务端完成;
 *  thread_id 由首轮 Conversation ID 确定性派生(稳定、短)。 */

export interface ThreadItem {
  thread_id: string;
  first_question: string;
  turn_count: number;
  started_at: string;
  last_activity_at: string;
  intent_tag: string | null;
  channel: string | null;
  site_id: string | null;
  entry: { site_id: string; display_name: string } | null;
  country: string | null;
  country_source: string | null;
  /** 真实派生:任一轮未回答或 trace 失败(无推断成分) */
  has_abnormal: boolean;
}

export interface ThreadTurn {
  id: string;
  question: string;
  answer: string | null;
  is_answered: boolean;
  intent_tag: string | null;
  channel: string | null;
  created_at: string;
  response_time_ms: number | null;
}

export interface ThreadDetail {
  thread_id: string;
  turn_count: number;
  started_at: string;
  last_activity_at: string;
  session_id: string | null;
  channel: string | null;
  entry: { site_id: string; display_name: string } | null;
  country: string | null;
  country_source: string | null;
  turns: ThreadTurn[];
}

export interface ConversationThreadFilters {
  q?: string;
  channel?: string;
  entry?: string;
  country?: string;
  intent_tag?: string;
  is_answered?: boolean;
  feedback?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
}

export function useConversationThreads(
  filters: ConversationThreadFilters = {},
  enabled = true,
) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== "") params.set(k, String(v));
  });
  return useQuery({
    queryKey: ["conversation-threads", filters],
    queryFn: () =>
      apiFetch<{ items: ThreadItem[]; total: number; page: number; size: number }>(
        `/conversations/threads?${params.toString()}`,
      ),
    enabled,
  });
}

export function useConversationThread(threadId: string | null) {
  return useQuery({
    queryKey: ["conversation-thread", threadId],
    queryFn: () => apiFetch<ThreadDetail>(`/conversations/threads/${threadId}`),
    enabled: !!threadId,
  });
}
