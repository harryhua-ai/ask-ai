import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { DataSource, PreviewDir } from "@/types/api";

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

export function useDeleteDataSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/data-sources/${id}`, { method: "DELETE" }),
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

/** 预览 GitHub 仓库分支列表(供前端多选填充)。 */
export async function fetchPreviewBranches(owner: string, repo: string): Promise<string[]> {
  const data = await apiFetch<{ branches: string[] }>(
    `/data-sources/preview-branches?owner=${encodeURIComponent(owner)}&repo=${encodeURIComponent(repo)}`,
  );
  return data.branches;
}

/**
 * 预览本地 root_path 下子目录树(供目录选择器勾选 include_dirs)。
 * rootPath 为空时不发请求(前端先填 root_path 才拉)。
 */
export function usePreviewDirs(rootPath: string | undefined) {
  return useQuery({
    queryKey: ["preview-dirs", rootPath],
    queryFn: () =>
      apiFetch<{ dirs: PreviewDir[] }>(
        `/data-sources/preview-dirs?root_path=${encodeURIComponent(rootPath ?? "")}`,
      ),
    enabled: !!rootPath,
  });
}
