import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { DataSource } from "@/types/api";

export function useDataSources() {
  return useQuery({
    queryKey: ["data-sources"],
    queryFn: () => apiFetch<DataSource[]>("/data-sources"),
  });
}

export function useCreateDataSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<DataSource> & { id: string; type: string; product: string }) =>
      apiFetch<DataSource>("/data-sources", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["data-sources"] }),
  });
}

export function useUpdateDataSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & Partial<DataSource>) =>
      apiFetch<DataSource>(`/data-sources/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["data-sources"] }),
  });
}

export function useToggleDataSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      apiFetch<DataSource>(`/data-sources/${id}`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["data-sources"] }),
  });
}

export function useTriggerSync() {
  return useMutation({
    mutationFn: (id: string) => apiFetch<{ status: string }>(`/data-sources/${id}/sync`, { method: "POST" }),
  });
}
