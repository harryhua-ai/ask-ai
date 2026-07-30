import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { ClusterList, SourceAnalytics, RefreshResult } from "@/types/api";

export function useCoverageGaps(status?: string) {
  const qs = status ? `?status=${status}` : "";
  return useQuery({
    queryKey: ["coverage-gaps", status],
    queryFn: () => apiFetch<ClusterList>(`/analytics/coverage-gaps${qs}`),
  });
}

export function useRefreshGaps() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<RefreshResult>("/analytics/coverage-gaps/refresh", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["coverage-gaps"] }),
  });
}

export function useResolveGap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      apiFetch(`/analytics/gaps/${id}/resolve`, { method: "PATCH", body: JSON.stringify({ status }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["coverage-gaps"] }),
  });
}

export function useTopQuestions() {
  return useQuery({
    queryKey: ["top-questions"],
    queryFn: () => apiFetch<ClusterList>("/analytics/top-questions"),
  });
}

export function useRefreshTopQuestions() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<RefreshResult>("/analytics/top-questions/refresh", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["top-questions"] }),
  });
}

export function useSourceAnalytics(days = 30) {
  return useQuery({
    queryKey: ["source-analytics", days],
    queryFn: () => apiFetch<SourceAnalytics>(`/analytics/sources?days=${days}`),
  });
}
