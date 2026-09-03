import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { fetchSourceHealth } from "@/lib/api/techInsight";
import { splitIntoBatches } from "@/utils/upload";
import type { DataSource, PreviewDir, SyncRunList, SyncStatusResponse } from "@/types/api";

export interface SyncRunParams {
  status?: string;
  page?: number;
  size?: number;
}

export function fetchSyncStatus(): Promise<SyncStatusResponse> {
  return apiFetch<SyncStatusResponse>("/sync-status");
}

export function fetchSyncRuns(sourceId: string, params: SyncRunParams = {}): Promise<SyncRunList> {
  const search = new URLSearchParams({ source_id: sourceId });
  if (params.status !== undefined) search.set("status", params.status);
  if (params.page !== undefined) search.set("page", String(params.page));
  if (params.size !== undefined) search.set("size", String(params.size));
  return apiFetch<SyncRunList>(`/sync-runs?${search.toString()}`);
}

export function useSyncStatus(options?: { refetchInterval?: number | false }) {
  return useQuery({
    queryKey: ["sync-status"],
    queryFn: fetchSyncStatus,
    refetchInterval: options?.refetchInterval,
  });
}

export function useSyncRuns(
  sourceId: string,
  options?: SyncRunParams & { enabled?: boolean; refetchInterval?: number | false },
) {
  const { enabled = true, refetchInterval, status, page, size } = options ?? {};
  return useQuery({
    queryKey: ["sync-runs", sourceId, { status, page, size }],
    queryFn: () => fetchSyncRuns(sourceId, { status, page, size }),
    enabled: enabled && !!sourceId,
    refetchInterval,
  });
}

export function useDataSources(options?: { refetchInterval?: number | false }) {
  return useQuery({
    queryKey: ["data-sources"],
    queryFn: () => apiFetch<DataSource[]>("/data-sources"),
    refetchInterval: options?.refetchInterval,
  });
}

/**
 * 数据源健康度(DSH-01/02:数据源健康的主入口在本页)。
 * 窗口固定 30 天;当前态(最近一次同步)由 /data-sources 的 last_sync_* 承载,
 * 历史可靠性(窗口成功率)由此 hook 承载,按 source_id 与列表 join。
 */
export function useSourceHealth(options?: { refetchInterval?: number | false }) {
  return useQuery({
    queryKey: ["source-health"],
    queryFn: () => fetchSourceHealth(30),
    refetchInterval: options?.refetchInterval,
  });
}

export function useCreateDataSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<DataSource> & { id?: string; type: string; product: string }) =>
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
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<{ status: string; source_id: string }>(`/data-sources/${id}/sync`, { method: "POST" }),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["data-sources"] });
      toast.success(`已触发同步:${id}(后台进行中,完成后「最新同步」列自动刷新)`);
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : "未知错误";
      toast.error(`同步触发失败:${msg}`);
    },
  });
}

export function useTriggerSyncAll() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ status: string; source_ids: string[]; count: number }>(`/data-sources/sync-all`, {
        method: "POST",
      }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["data-sources"] });
      if (data.count === 0) {
        toast.warning("没有可同步的启用数据源");
      } else {
        toast.success(
          `已触发同步全部 ${data.count} 个数据源(后台顺序进行,逐个完成时提示)`,
        );
      }
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : "未知错误";
      toast.error(`同步触发失败:${msg}`);
    },
  });
}

/** C9:分批上传语料文件(每批 50,串行;onProgress 汇报已完成文件数)。 */
export async function uploadSourceFiles(
  sourceId: string,
  items: { file: File; path: string }[],
  onProgress?: (done: number, total: number) => void,
): Promise<{ saved: number }> {
  const batches = splitIntoBatches(items, 50);
  let saved = 0;
  let done = 0;
  for (const batch of batches) {
    const fd = new FormData();
    for (const it of batch) {
      fd.append("files", it.file, it.file.name);
      fd.append("paths", it.path);
    }
    const r = await apiFetch<{ saved: number }>(`/data-sources/${sourceId}/upload`, {
      method: "POST",
      body: fd,
    });
    saved += r.saved;
    done += batch.length;
    onProgress?.(done, items.length);
  }
  return { saved };
}

/** 预览仓库内全部文件后缀(C10 增补:默认全列,用户按需删)。 */
export async function fetchPreviewFileTypes(
  owner: string,
  repo: string,
  branch: string,
): Promise<{ extensions: string[] }> {
  const data = await apiFetch<{ extensions: string[] }>(
    `/data-sources/preview-file-types?owner=${encodeURIComponent(owner)}`
    + `&repo=${encodeURIComponent(repo)}&branch=${encodeURIComponent(branch)}`,
  );
  return data;
}

/** 预览 GitHub 仓库分支列表 + 默认分支(供表单消除 main 硬编码)。 */
export async function fetchPreviewBranches(
  owner: string,
  repo: string,
): Promise<{ branches: string[]; defaultBranch: string }> {
  const data = await apiFetch<{ branches: string[]; default_branch: string }>(
    `/data-sources/preview-branches?owner=${encodeURIComponent(owner)}&repo=${encodeURIComponent(repo)}`,
  );
  return { branches: data.branches, defaultBranch: data.default_branch };
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
