import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { SyncLog } from "@/types/api";

interface PaginatedSyncLogs {
  items: SyncLog[];
  total: number;
  page: number;
  size: number;
}

export function useSyncLogs(params: { sourceId?: string; status?: string; page?: number } = {}) {
  const searchParams = new URLSearchParams();
  if (params.sourceId) searchParams.set("source_id", params.sourceId);
  if (params.status) searchParams.set("status", params.status);
  searchParams.set("page", String(params.page || 1));
  return useQuery({
    queryKey: ["sync-logs", params],
    queryFn: () => apiFetch<PaginatedSyncLogs>(`/sync-logs?${searchParams.toString()}`),
    refetchInterval: 10000, // 10 秒自动刷新
  });
}
