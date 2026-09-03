import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { fetchSourceHealth } from "@/lib/api/techInsight";
import { splitIntoBatches } from "@/utils/upload";
import type { DataSource, PreviewDir, RepoDiscoveryResult } from "@/types/api";

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

/**
 * #16 Simple Mode:仓库内容发现(S0 共享契约)。
 * 只读远程扫描,不 clone 不落盘;返回后端冻结的推荐策略与人读理由,
 * 前端只呈现与原样采用,不二次推导。
 */
export async function fetchRepoDiscovery(
  repoUrl: string,
  branch: string | null,
): Promise<RepoDiscoveryResult> {
  return apiFetch<RepoDiscoveryResult>("/data-sources/discover-repo", {
    method: "POST",
    body: JSON.stringify({ repo_url: repoUrl, ...(branch ? { branch } : {}) }),
  });
}

/**
 * 预览仓库内全部文件后缀(保留端点兼容)。
 * #16 起"全部后缀默认纳入"的预填行为已废除——策略由发现流程推荐,
 * 本函数仅保留给高级场景/既有测试使用。
 */
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

/** #17 Website Simple Mode:逐候选准入结论(wire 形态 = FileAdmission + 人读理由)。 */
export interface WebsiteDiscoveryCandidate {
  path: string;
  size: number;
  technical_safe: boolean;
  technical_reason: string | null;
  knowledge_role: string;
  recommendation: "include" | "exclude" | "review";
  policy_result: string;
  eligible: boolean;
  reason: string;
}

/** #17 发现结果分组(首层路径段;样本 URL)。 */
export interface WebsiteDiscoveryGroup {
  key: string;
  count: number;
  total_size: number;
  recommendation: "include" | "exclude" | "review";
  samples: string[];
}

/** #17 Website 自动发现预览响应(后端 DiscoveryResultOut)。 */
export interface WebsiteDiscoveryResult {
  kind: string;
  target: {
    base_url: string;
    requested_sitemap_url: string | null;
    discovery_mode: "explicit" | "robots" | "generic" | "none";
    resolved_sitemaps: string[];
    robots_declared: string[];
    cross_domain_skipped: string[];
  };
  totals: { files: number; safe_files: number; unsafe_files: number; total_size: number };
  by_role: Record<string, { count: number; size: number; recommendation: string }>;
  groups: WebsiteDiscoveryGroup[];
  candidates: WebsiteDiscoveryCandidate[];
  recommended_config: Record<string, unknown>;
  warnings: string[];
  capability_notes: string[];
}

/**
 * #17 Website Simple Mode 自动发现:输入站点 URL(+可选 sitemap override)
 * → sitemap 发现 → 逐 URL 知识分类推荐。零发现返回 200 空结果(显式呈现),
 * 只有非法入参才 4xx。
 */
export async function fetchWebsiteDiscovery(
  baseUrl: string,
  sitemapUrl?: string,
): Promise<WebsiteDiscoveryResult> {
  return apiFetch<WebsiteDiscoveryResult>("/data-sources/preview-website", {
    method: "POST",
    body: JSON.stringify({
      base_url: baseUrl,
      ...(sitemapUrl?.trim() ? { sitemap_url: sitemapUrl.trim() } : {}),
    }),
  });
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
