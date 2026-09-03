import { useState, useEffect, useMemo } from "react";
import { useAuth } from "@/hooks/useAuth";
import LoadError from "@/components/LoadError";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  useDataSources,
  useCreateDataSource,
  useUpdateDataSource,
  useDeleteDataSource,
  useRetryDeleteDataSource,
  useToggleDataSource,
  useTriggerSync,
  useTriggerSyncAll,
  useSourceHealth,
  fetchPreviewBranches,
  fetchRepoDiscovery,
  fetchWebsiteDiscovery,
  type WebsiteDiscoveryResult,
  uploadSourceFiles,
} from "@/hooks/useDataSources";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { DirPicker } from "@/components/DirPicker";
import { PolicyChips, RepoDiscoveryPanel } from "@/components/dataSources/RepoDiscoveryPanel";
import { isDeletionInFlight, isSyncEligible } from "@/types/api";
import type { DataSource, RepoDiscoveryResult } from "@/types/api";
import type { SourceHealthItem } from "@/lib/api/techInsight";
import { toast } from "sonner";
import { toUploadItems, filterByWhitelist, isJunkPath } from "@/utils/upload";
import { apiFetch } from "@/lib/api";

// 决策 2A:github 为唯一 git 源类型(local_git 降为实现细节,不再暴露给用户)
// Task 4:woocommerce 进数据源类型枚举
// C8B:web_crawl 进枚举(C8 后端 connector 已交付),关闭"未知类型归一 github"对爬站源的编辑陷阱
const SOURCE_TYPES = ["github", "filesystem", "woocommerce", "web_crawl"] as const;
type SourceType = (typeof SOURCE_TYPES)[number];

const formSchema = z
  .object({
    id: z.string().optional(),
    type: z.enum(["github", "filesystem", "woocommerce", "web_crawl"]),
    product: z.string().min(1, "产品线必填"),
    enabled: z.boolean(),
    sync_interval: z.string().regex(/^\d+[hm]$/, "格式如 24h 或 30m"),
    repo_url: z.string().optional(),
    clone_path: z.string().optional(),
    root_path: z.string().optional(),
    upload_mode: z.boolean().optional(),
    branches: z.string().optional(),
    file_types: z.string().optional(),
    include_dirs: z.string().optional(),
    exclude_dirs: z.string().optional(),
    exclude_regex: z.string().optional(),
    max_file_size: z.string().optional(),
    store_url: z.string().optional(),
    consumer_key: z.string().optional(),
    consumer_secret: z.string().optional(),
    base_url: z.string().optional(),
    sitemap_url: z.string().optional(),
    exclude_patterns: z.string().optional(),
    crawl_delay_ms: z.string().optional(),
  })
  .superRefine((v, ctx) => {
    if (v.type === "web_crawl" && !(v.base_url ?? "").trim()) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["base_url"], message: "站点地址必填" });
    }
  });

// Task 3:类型中文可读名映射(未知值降级原始 key)
const TYPE_LABELS: Record<string, string> = {
  github: "代码仓库",
  local_git: "代码仓库",
  filesystem: "文件目录",
  woocommerce: "商城",
  web_crawl: "网站爬取",
};

type FormValues = z.infer<typeof formSchema>;

const EMPTY_FORM: FormValues = {
  id: "",
  type: "github",
  product: "",
  enabled: true,
  sync_interval: "24h",
  repo_url: "",
  clone_path: "",
  root_path: "",
  upload_mode: false,
  branches: "",
  file_types: "",
  include_dirs: "",
  exclude_dirs: "",
  exclude_regex: "",
  max_file_size: "",
  store_url: "",
  consumer_key: "",
  consumer_secret: "",
  base_url: "",
  sitemap_url: "",
  exclude_patterns: "",
  crawl_delay_ms: "",
};

function splitComma(s: string | undefined): string[] {
  if (!s) return [];
  return s
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

/** 上传落盘根目录(与后端 _upload_root 同语义)。 */
const uploadRootOf = (sourceId: string) => `data/uploads/data-sources/${sourceId}`;

// #17 Website Simple Mode:发现方式与推荐结论的展示文案(后端冻结语义)
const DISCOVERY_MODE_LABELS: Record<string, string> = {
  explicit: "已使用手动指定的 Sitemap",
  robots: "已自动检测 Sitemap(robots.txt 声明)",
  generic: "已自动检测 Sitemap(标准地址)",
  none: "未检测到 Sitemap",
};

const REC_META: Record<string, { label: string; className: string }> = {
  include: { label: "建议纳入", className: "text-green-600" },
  exclude: { label: "排除", className: "text-destructive" },
  review: { label: "待确认", className: "text-amber-600" },
};

/** 上传完成后取上传根目录下全部顶层子目录,作为 include_dirs 默认全选;失败返回空数组(不阻断流程)。 */
async function fetchTopDirPaths(rootPath: string): Promise<string[]> {
  try {
    const { dirs } = await apiFetch<{ dirs: { path: string }[] }>(
      `/data-sources/preview-dirs?root_path=${encodeURIComponent(rootPath)}`,
    );
    return dirs.map((d) => d.path);
  } catch {
    return [];
  }
}

/** ISO 时间 → 本地可读时间(如 "07-31 14:30")，非法/空输入返回 "—"。 */
function formatSyncTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// ==================== DSH-01/02:数据源健康语义 ====================
// 当前态(最近一次同步,来自 /data-sources 的 last_sync_*)与
// 历史可靠性(窗口内成功率,来自 /analytics/source-health)分开呈现,
// 两者可以合法共存(如"最新成功 + 近 30 天不稳定"),措辞不共用"健康"一词。

/** 最新一次同步状态的展示元数据。 */
const LATEST_STATUS_META: Record<string, { label: string; variant: "success" | "destructive" | "warning" } | undefined> = {
  success: { label: "成功", variant: "success" },
  failed: { label: "失败", variant: "destructive" },
  partial: { label: "补齐", variant: "warning" },
};

/** 历史可靠性(health)结论的展示元数据,阈值语义由后端判定。 */
const HEALTH_META: Record<
  string,
  { label: string; variant: "success" | "destructive" | "warning" | "secondary" | "outline" } | undefined
> = {
  healthy: { label: "正常", variant: "success" },
  degraded: { label: "不稳定", variant: "warning" },
  critical: { label: "严重", variant: "destructive" },
  insufficient_data: { label: "样本不足", variant: "secondary" },
  disabled: { label: "已禁用", variant: "outline" },
};

/** 历史可靠性明细(悬停 title):分子/分母/窗口全量可见,partial 单列。 */
function healthTooltipTitle(h: SourceHealthItem): string {
  return (
    `近 ${h.window_days} 天 ${h.total_syncs} 次同步:` +
    `${h.success_syncs} 次成功 / ${h.partial_syncs} 次补齐 / ${h.failed_syncs} 次失败` +
    `(成功率按次数计,补齐不计入成功)`
  );
}

/** 历史可靠性一行文案:带窗口与分母,样本不足时拒绝给出百分比。 */
function healthHistoryLine(h: SourceHealthItem): string {
  if (h.health === "insufficient_data") {
    return h.total_syncs > 0 ? `仅 ${h.total_syncs} 次同步,暂不评估` : "暂无同步记录";
  }
  const pct = Math.round(h.sync_success_rate * 100);
  return `${pct}% 成功 · 近${h.window_days}天 ${h.total_syncs} 次`;
}

/** config 取字符串字段(非字符串/缺失返回空串)。 */
function cfgStr(cfg: Record<string, unknown>, key: string): string {
  const v = cfg[key];
  return typeof v === "string" ? v : "";
}

/**
 * github/local_git 源的仓库 URL:优先 config.repo_url;
 * 历史 local_git 源 DB 里只有 repo_path(本地 clone 路径),按 camthink-ai 约定
 * 由 repo_path 末段重建 repo_url(与 dsToForm 编辑回填同规则),不裸显本地路径。
 */
function githubRepoUrl(ds: DataSource): string {
  const cfg = ds.config || {};
  const explicit = cfgStr(cfg, "repo_url");
  if (explicit) return explicit;
  const repoPath = cfgStr(cfg, "repo_path");
  if (!repoPath) return "";
  const repoName = repoPath.split("/").filter(Boolean).pop() ?? "";
  return repoName ? `https://github.com/camthink-ai/${repoName}.git` : "";
}

/**
 * 按数据源类型取"来源地址"副标题:
 * github/local_git → githubRepoUrl(由 repo_path 重建,不裸显本地路径),
 * filesystem → root_path,woocommerce → store_url。
 * href 非 null 表示是可点击 URL(http 开头)。
 */
function sourceLocation(ds: DataSource): { text: string; href: string | null } {
  const cfg = ds.config || {};
  let text = "";
  switch (ds.type) {
    case "github":
    case "local_git":
      text = githubRepoUrl(ds);
      break;
    case "filesystem":
      text = cfgStr(cfg, "root_path");
      break;
    case "woocommerce":
      text = cfgStr(cfg, "store_url");
      break;
    case "web_crawl":
      text = cfgStr(cfg, "base_url");
      break;
  }
  return { text, href: text.startsWith("http") ? text : null };
}

/** 产品线列的来源地址副标题:URL 渲染为可点击链接(新标签),本地路径/缺失渲染为纯文本。 */
function SourceLocationLine({ ds }: { ds: DataSource }) {
  const { text, href } = sourceLocation(ds);
  if (!text) return <div className="max-w-[280px] truncate text-xs text-muted-foreground">—</div>;
  if (href)
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="block max-w-[280px] truncate text-xs text-muted-foreground underline-offset-2 hover:underline"
      >
        {text}
      </a>
    );
  return (
    <div className="max-w-[280px] truncate text-xs text-muted-foreground" title={text}>
      {text}
    </div>
  );
}

/** repo_url → {owner, repo}(与后端 _REPO_URL_RE 一致),用于"拉取分支"预览。 */
function parseRepoUrl(url: string): { owner: string; repo: string } | null {
  const m = url.match(/github\.com\/([^/]+)\/([^/]+?)(?:\.git)?\/?$/i);
  return m ? { owner: m[1], repo: m[2] } : null;
}

/** 把表单值组装成后端 config dict(按 type 分发)。 */
function buildConfig(v: FormValues): Record<string, unknown> {
  switch (v.type) {
    case "github":
      return {
        repo_url: v.repo_url || "",
        clone_path: v.clone_path || "",
        branches: splitComma(v.branches),
        file_types: splitComma(v.file_types),
        exclude_dirs: splitComma(v.exclude_dirs),
        exclude_regex: v.exclude_regex || "",
        max_file_size: v.max_file_size ? Number(v.max_file_size) : undefined,
      };
    case "filesystem":
      return {
        root_path: v.upload_mode ? "" : v.root_path || "",
        upload_mode: v.type === "filesystem" ? v.upload_mode : false,
        file_types: splitComma(v.file_types),
        include_dirs: splitComma(v.include_dirs),
        exclude_dirs: splitComma(v.exclude_dirs),
        exclude_regex: v.exclude_regex || "",
        max_file_size: v.max_file_size ? Number(v.max_file_size) : undefined,
      };
    case "woocommerce":
      return {
        store_url: v.store_url || "",
        consumer_key: v.consumer_key || "",
        consumer_secret: v.consumer_secret || "",
      };
    case "web_crawl": {
      // 与 connectors/web_crawl.py 约定一致:可选键留空即不写 config。
      // #17:sitemap_url 缺省 = 自动发现(robots 指令 → 通用回退),不再
      // 钉死 {base_url}/sitemap_index.xml;exclude_patterns 提供时替换默认
      // 排除清单(自动发现后由推荐清单回填,保证「预览=同步视野」)。
      const delay = Number(v.crawl_delay_ms);
      return {
        base_url: (v.base_url || "").trim(),
        ...(v.sitemap_url?.trim() ? { sitemap_url: v.sitemap_url.trim() } : {}),
        ...(splitComma(v.exclude_patterns).length > 0
          ? { exclude_patterns: splitComma(v.exclude_patterns) }
          : {}),
        ...(v.crawl_delay_ms && Number.isFinite(delay) ? { crawl_delay_ms: delay } : {}),
      };
    }
    default:
      return {};
  }
}

/** 从 DataSource 反解出表单值(用于编辑预填)。 */
function dsToForm(ds: DataSource): FormValues {
  const cfg = ds.config || {};
  const toStr = (v: unknown): string => {
    if (Array.isArray(v)) return (v as string[]).join(", ");
    return typeof v === "string" || typeof v === "number" ? String(v) : "";
  };
  const known = (SOURCE_TYPES as readonly string[]).includes(ds.type)
    ? (ds.type as SourceType)
    : "github";
  // 历史 local_git 源在 DB 中 config 仍为 repo_path 结构;
  // 编辑时归一为 github 表单,同时把 repo_path 等价转换为
  // repo_url + clone_path(与 scripts/migrate_github_source_schema.py
  // build_github_config 同规则),避免"类型变了但配置字段丢了"。
  const repoPath = toStr(cfg.repo_path);
  return {
    ...EMPTY_FORM,
    id: ds.id,
    type: known,
    product: ds.product,
    enabled: ds.enabled,
    sync_interval: ds.sync_interval,
    repo_url: githubRepoUrl(ds),
    clone_path: toStr(cfg.clone_path) || repoPath,
    root_path: toStr(cfg.root_path),
    upload_mode: cfg.upload_mode === true,
    branches: toStr(cfg.branches),
    file_types: toStr(cfg.file_types),
    include_dirs: toStr(cfg.include_dirs),
    exclude_dirs: toStr(cfg.exclude_dirs),
    exclude_regex: toStr(cfg.exclude_regex),
    max_file_size: cfg.max_file_size != null ? String(cfg.max_file_size) : "",
    store_url: toStr(cfg.store_url),
    consumer_key: toStr(cfg.consumer_key),
    consumer_secret: toStr(cfg.consumer_secret),
    base_url: toStr(cfg.base_url),
    sitemap_url: toStr(cfg.sitemap_url),
    exclude_patterns: toStr(cfg.exclude_patterns),
    crawl_delay_ms: cfg.crawl_delay_ms != null ? String(cfg.crawl_delay_ms) : "",
  };
}

export default function DataSources() {
  const [syncingIds, setSyncingIds] = useState<Set<string>>(() => new Set());
  const [triggeredAt, setTriggeredAt] = useState<Record<string, number>>(() => ({}));
  // #18:删除在途(delete_requested/deleting)期间同样保持 5s 轮询,
  // 让 lifecycle 推进可见(完成 → 行自动消失;失败 → DELETE_FAILED 徽章)。
  const { data: sources, isLoading, isError, error, refetch } = useDataSources({
    refetchInterval: (query) => {
      const list = query.state.data as DataSource[] | undefined;
      const deleting = list?.some((s) => isDeletionInFlight(s)) ?? false;
      return syncingIds.size > 0 || deleting ? 5000 : false;
    },
  });
  // DSH-02:数据源健康的主展示位。窗口 30 天历史可靠性按 source_id join 当前列表;
  // 同步进行中与列表同节奏 5s 轮询,同步完成后健康态即时跟进。
  const { data: healthData } = useSourceHealth({
    refetchInterval: syncingIds.size > 0 ? 5000 : false,
  });
  const healthMap = useMemo(
    () => new Map((healthData?.items ?? []).map((h) => [h.source_id, h])),
    [healthData],
  );
  const createDs = useCreateDataSource();
  const updateDs = useUpdateDataSource();
  const deleteDs = useDeleteDataSource();
  const retryDeleteDs = useRetryDeleteDataSource();
  const toggleDs = useToggleDataSource();
  const triggerSync = useTriggerSync();
  const triggerSyncAll = useTriggerSyncAll();
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [branchLoading, setBranchLoading] = useState(false);
  const [branchError, setBranchError] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [fetchedBranches, setFetchedBranches] = useState<string[]>([]);
  // #16 Simple Mode:仓库发现结果(只读预览;采用推荐策略才写入表单字段)
  const [discovery, setDiscovery] = useState<RepoDiscoveryResult | null>(null);
  const [discoveryLoading, setDiscoveryLoading] = useState(false);
  const [discoveryError, setDiscoveryError] = useState<string | null>(null);
  const [syncCustom, setSyncCustom] = useState(false);
  const [pickedFiles, setPickedFiles] = useState<File[]>([]);
  const [uploadProgress, setUploadProgress] = useState<{ done: number; total: number } | null>(
    null,
  );
  // #17 Website Simple Mode:自动发现预览(结果 / 加载 / 错误 / 推荐清单是否已回填)
  const [websiteDiscovery, setWebsiteDiscovery] = useState<WebsiteDiscoveryResult | null>(null);
  const [websiteDiscovering, setWebsiteDiscovering] = useState(false);
  const [websiteDiscoveryError, setWebsiteDiscoveryError] = useState<string | null>(null);
  const [websiteExcludeApplied, setWebsiteExcludeApplied] = useState<boolean | null>(null);

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    getValues,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: EMPTY_FORM,
  });
  const type = watch("type");
  const rootPath = watch("root_path");
  const watchUploadMode = watch("upload_mode") === true;
  const selectedBranches = splitComma(watch("branches"));
  const syncInterval = watch("sync_interval");
  const syncSelect =
    syncCustom || !["1h", "12h", "24h"].includes(syncInterval) ? "__custom" : syncInterval;
  const watchedFileTypes = watch("file_types");
  // 选中文件按当前白名单实时预览:将上传多少、跳过多少(与提交时同一套过滤逻辑)
  const uploadPreview = useMemo(
    () => filterByWhitelist(toUploadItems(pickedFiles), splitComma(watchedFileTypes)),
    [pickedFiles, watchedFileTypes],
  );
  // #17:发现结果的纳入/排除/待确认计数(推荐结论摘要行)
  const discoveryRecCounts = useMemo(() => {
    const counts = { include: 0, exclude: 0, review: 0 };
    websiteDiscovery?.candidates.forEach((c) => {
      counts[c.recommendation] += 1;
    });
    return counts;
  }, [websiteDiscovery]);

  const openCreate = () => {
    reset(EMPTY_FORM);
    setEditingId(null);
    setBranchError(null);
    setFetchedBranches([]);
    setSyncCustom(false);
    setPickedFiles([]);
    setUploadProgress(null);
    setShowAdvanced(false);
    setDiscovery(null);
    setDiscoveryError(null);
    setWebsiteDiscovery(null);
    setWebsiteDiscoveryError(null);
    setWebsiteExcludeApplied(null);
    setShowForm(true);
  };

  const openEdit = (ds: DataSource) => {
    const fv = dsToForm(ds);
    reset(fv);
    setEditingId(ds.id);
    setBranchError(null);
    setFetchedBranches([]);
    setSyncCustom(!["1h", "12h", "24h"].includes(fv.sync_interval));
    setPickedFiles([]);
    setUploadProgress(null);
    setShowAdvanced(false);
    setDiscovery(null);
    setDiscoveryError(null);
    setWebsiteDiscovery(null);
    setWebsiteDiscoveryError(null);
    setWebsiteExcludeApplied(null);
    setShowForm(true);
  };

  const closeForm = () => {
    setShowForm(false);
    setEditingId(null);
  };

  const onSubmit = async (v: FormValues) => {
    const config = buildConfig(v);
    if (editingId) {
      await updateDs.mutateAsync({
        id: editingId,
        type: v.type,
        product: v.product,
        enabled: v.enabled,
        sync_interval: v.sync_interval,
        config,
      });
      // C9 编辑态:再次选择文件夹 = 合并覆盖上传(与表单文案一致);保存已生效,上传失败不回滚
      if (v.upload_mode && pickedFiles.length > 0) {
        const { kept, skipped } = filterByWhitelist(
          toUploadItems(pickedFiles),
          splitComma(v.file_types),
        );
        if (kept.length === 0) {
          toast.error("没有符合文件类型白名单的可上传文件,本次未上传");
        } else {
          setUploadProgress({ done: 0, total: kept.length });
          try {
            const { saved } = await uploadSourceFiles(editingId, kept, (done, total) =>
              setUploadProgress({ done, total }),
            );
            // 上传成功:重算顶层目录全集写入 include_dirs(默认全选,与当前内容保持一致)
            let allSelNote = "";
            const topDirs = await fetchTopDirPaths(uploadRootOf(editingId));
            if (topDirs.length > 0) {
              try {
                await updateDs.mutateAsync({
                  id: editingId,
                  type: v.type,
                  product: v.product,
                  enabled: v.enabled,
                  sync_interval: v.sync_interval,
                  config: { ...config, include_dirs: topDirs },
                });
                allSelNote = `,已默认包含全部 ${topDirs.length} 个目录`;
              } catch {
                // 全选回写失败不阻断,保持表单保存时的 include_dirs
              }
            }
            toast.success(
              `已合并上传 ${saved}/${kept.length} 个文件` +
                (skipped.length > 0 ? `(已跳过 ${skipped.length} 个)` : "") +
                allSelNote,
            );
          } catch (err) {
            toast.error(`上传失败:${err instanceof Error ? err.message : "未知错误"},保存已生效,可重试上传`);
            setUploadProgress(null);
            return;
          }
          setUploadProgress(null);
        }
      }
    } else {
      // id 可选:用户没填则不传,后端按 product+短 hash 自动生成
      let created: DataSource;
      try {
        created = await createDs.mutateAsync({
          ...(v.id ? { id: v.id } : {}),
          type: v.type,
          product: v.product,
          enabled: v.enabled,
          sync_interval: v.sync_interval,
          config,
        });
      } catch (err) {
        toast.error(`创建失败:${err instanceof Error ? err.message : "未知错误"}`);
        return;
      }
      // C9 上传模式:创建成功后把选中的文件夹分批直传(每批 50,串行)
      if (v.upload_mode && pickedFiles.length > 0) {
        // 客户端先过滤:系统文件/白名单外文件不上传(后端整批 400 拒收,故必须在客户端滤净)
        const { kept, skipped } = filterByWhitelist(
          toUploadItems(pickedFiles),
          splitComma(v.file_types),
        );
        if (kept.length === 0) {
          toast.error("没有符合文件类型白名单的可上传文件,已回滚该数据源");
          await deleteDs.mutateAsync(created.id);
          return;
        }
        setUploadProgress({ done: 0, total: kept.length });
        try {
          const { saved } = await uploadSourceFiles(created.id, kept, (done, total) =>
            setUploadProgress({ done, total }),
          );
          // 上传成功:默认全选已上传内容的顶层目录,用户无需逐一勾选
          // 注意:必须走 updateDs(内含缓存失效),否则列表缓存仍旧,编辑预填拿不到 include_dirs
          let allSelNote = "";
          const topDirs = await fetchTopDirPaths(uploadRootOf(created.id));
          if (topDirs.length > 0) {
            try {
              await updateDs.mutateAsync({
                id: created.id,
                type: created.type,
                product: created.product,
                enabled: created.enabled,
                sync_interval: created.sync_interval,
                config: { ...created.config, include_dirs: topDirs },
              });
              allSelNote = `,已默认包含全部 ${topDirs.length} 个目录`;
            } catch {
              // 全选回写失败不阻断创建,include_dirs 保持空(同步语义=全部包含)
            }
          }
          toast.success(
            `创建成功,已上传 ${saved}/${kept.length} 个文件` +
              (skipped.length > 0 ? `(已跳过 ${skipped.length} 个系统文件或白名单外文件)` : "") +
              allSelNote,
          );
        } catch (err) {
          // 上传失败回滚刚建的空源,避免半成品源+表单残留诱发重复创建
          toast.error(
            `上传失败:${err instanceof Error ? err.message : "未知错误"},已删除该数据源,请重试`,
          );
          await deleteDs.mutateAsync(created.id);
          setUploadProgress(null);
          return;
        }
        setUploadProgress(null);
      }
    }
    closeForm();
  };

  /**
   * #17 Website Simple Mode:按站点地址自动发现,呈现 Preview/Recommendation。
   * 成功后把推荐排除清单回填进高级选项(仅当该字段为空,不覆盖用户自定义);
   * 零发现不伪装成功——由面板显式呈现告警与下一步建议。
   */
  const handleWebsiteDiscover = async () => {
    const baseUrl = (getValues("base_url") || "").trim();
    if (!baseUrl) {
      setWebsiteDiscoveryError("请先填写网站地址");
      return;
    }
    setWebsiteDiscovering(true);
    setWebsiteDiscoveryError(null);
    try {
      const result = await fetchWebsiteDiscovery(baseUrl, getValues("sitemap_url"));
      setWebsiteDiscovery(result);
      const rec = result.recommended_config as { exclude_patterns?: unknown };
      if (Array.isArray(rec?.exclude_patterns) && rec.exclude_patterns.length > 0) {
        const current = (getValues("exclude_patterns") || "").trim();
        if (!current) {
          setValue("exclude_patterns", (rec.exclude_patterns as string[]).join(", "), {
            shouldDirty: true,
          });
          setWebsiteExcludeApplied(true);
        } else {
          setWebsiteExcludeApplied(false);
        }
      } else {
        setWebsiteExcludeApplied(null);
      }
    } catch (err) {
      setWebsiteDiscovery(null);
      setWebsiteExcludeApplied(null);
      setWebsiteDiscoveryError(err instanceof Error ? err.message : "检测失败");
    } finally {
      setWebsiteDiscovering(false);
    }
  };

  const handlePullBranches = async () => {    const repoUrl = getValues("repo_url") || "";
    const parsed = parseRepoUrl(repoUrl);
    if (!parsed) {
      setBranchError("请先填写合法 repo_url(如 https://github.com/camthink-ai/ne301.git)");
      return;
    }
    setBranchLoading(true);
    setBranchError(null);
    try {
      const { branches, defaultBranch } = await fetchPreviewBranches(parsed.owner, parsed.repo);
      setFetchedBranches(branches);
      // C10:字段为空或为旧硬编码 main 时,自动跟随仓库真实 default_branch
      const current = getValues("branches")?.trim() ?? "";
      if ((!current || current === "main") && branches.includes(defaultBranch)) {
        setValue("branches", defaultBranch, { shouldDirty: true });
      }
      // #16:不再把仓库全部后缀预填进 file_types(「检测到什么就纳入什么」已废除);
      // 纳入策略由「扫描并推荐策略」的发现流程给出,用户确认后写入。
    } catch (err) {
      setBranchError(err instanceof Error ? err.message : "拉取分支失败");
    } finally {
      setBranchLoading(false);
    }
  };

  /** #16 Simple Mode:扫描仓库内容并获取推荐纳入/排除策略(只读,不落盘)。 */
  const handleDiscoverRepo = async () => {
    const repoUrl = getValues("repo_url") || "";
    if (!parseRepoUrl(repoUrl)) {
      setDiscoveryError("请先填写合法 repo_url(如 https://github.com/camthink-ai/ne301.git)");
      return;
    }
    setDiscoveryLoading(true);
    setDiscoveryError(null);
    try {
      const branch = selectedBranches[0] ?? null;
      const result = await fetchRepoDiscovery(repoUrl, branch);
      setDiscovery(result);
    } catch (err) {
      setDiscovery(null);
      setDiscoveryError(err instanceof Error ? err.message : "仓库扫描失败");
    } finally {
      setDiscoveryLoading(false);
    }
  };

  /** 采用推荐策略:后端编译产物原样写入既有 config 字段(文件类型/排除目录)。 */
  const handleApplyDiscovery = (config: { file_types: string[]; exclude_dirs: string[] }) => {
    setValue("file_types", config.file_types.join(", "), { shouldDirty: true });
    setValue("exclude_dirs", config.exclude_dirs.join(", "), { shouldDirty: true });
  };

  const toggleBranch = (b: string) => {
    const next = selectedBranches.includes(b)
      ? selectedBranches.filter((x) => x !== b)
      : [...selectedBranches, b];
    setValue("branches", next.join(", "), { shouldDirty: true });
  };

  const { user } = useAuth();
  const handleDelete = async (id: string) => {
    if (
      !window.confirm(
        `确定删除数据源 ${id} 吗?\n删除受理后将在后台清理向量语料,期间该源暂停同步;完成后此行自动消失。`,
      )
    )
      return;
    try {
      await deleteDs.mutateAsync(id);
      toast.success(`删除已受理:${id}(后台清理中,完成后自动从列表移除)`);
    } catch (err) {
      toast.error(`删除受理失败:${err instanceof Error ? err.message : "未知错误"}`);
    }
  };

  const handleRetryDelete = async (id: string) => {
    try {
      await retryDeleteDs.mutateAsync(id);
      toast.success(`删除重试已受理:${id}(后台清理中)`);
    } catch (err) {
      toast.error(`删除重试失败:${err instanceof Error ? err.message : "未知错误"}`);
    }
  };

  const handleSync = (ds: DataSource) => {
    setSyncingIds((prev) => new Set(prev).add(ds.id));
    setTriggeredAt((prev) => ({ ...prev, [ds.id]: Date.now() }));
    triggerSync.mutate(ds.id);
  };

  const canWrite =
    user?.role === "admin" || user?.role === "editor";
  const handleSyncAll = async () => {
    // 后端顺序同步所有启用源(一个后台任务,避免并发 GPU OOM);
    // 把返回的 source_ids 批量入 syncingIds + triggeredAt,复用现有轮询逐个检测完成。
    const data = await triggerSyncAll.mutateAsync();
    if (data.count === 0) return;
    const now = Date.now();
    setSyncingIds((prev) => {
      const next = new Set(prev);
      data.source_ids.forEach((id) => next.add(id));
      return next;
    });
    setTriggeredAt((prev) => {
      const next = { ...prev };
      data.source_ids.forEach((id) => {
        next[id] = now;
      });
      return next;
    });
  };

  // 后端 trigger_sync 为 fire-and-forget,需轮询 list 检测 last_sync 推进以判定结束;
  // 再按 last_sync_status 区分成功/失败/补齐(partial),失败/补齐时带 error_detail。
  useEffect(() => {
    if (syncingIds.size === 0) return;
    const now = Date.now();
    const completed: string[] = [];
    const failed: { id: string; error: string | null }[] = [];
    const partial: { id: string; error: string | null }[] = [];
    const stale: string[] = [];
    for (const id of syncingIds) {
      const ds = sources?.find((s) => s.id === id);
      const ts = ds?.last_sync ? new Date(ds.last_sync).getTime() : 0;
      const triggered = triggeredAt[id] ?? 0;
      if (ts && ts > triggered) {
        // last_sync 推进 → 同步尝试已结束,按 status 区分成功/失败/补齐
        if (ds?.last_sync_status === "failed") {
          failed.push({ id, error: ds.last_sync_error ?? null });
        } else if (ds?.last_sync_status === "partial") {
          partial.push({ id, error: ds.last_sync_error ?? null });
        } else {
          completed.push(id);
        }
      } else if (now - triggered > 5 * 60 * 1000) {
        stale.push(id);
      }
    }
    if (completed.length > 0) {
      completed.forEach((id) => toast.success(`同步完成:${id}`));
      setSyncingIds((prev) => {
        const next = new Set(prev);
        completed.forEach((id) => next.delete(id));
        return next;
      });
    }
    if (failed.length > 0) {
      failed.forEach(({ id, error }) => toast.error(`同步失败:${error || id}`));
      setSyncingIds((prev) => {
        const next = new Set(prev);
        failed.forEach(({ id }) => next.delete(id));
        return next;
      });
    }
    if (partial.length > 0) {
      partial.forEach(({ id, error }) =>
        toast.warning(`同步完成(补齐缺口):${error ?? id}`),
      );
      setSyncingIds((prev) => {
        const next = new Set(prev);
        partial.forEach(({ id }) => next.delete(id));
        return next;
      });
    }
    if (stale.length > 0) {
      stale.forEach((id) => toast.warning(`同步超时,请稍后在「最新同步」列确认:${id}`));
      setSyncingIds((prev) => {
        const next = new Set(prev);
        stale.forEach((id) => next.delete(id));
        return next;
      });
    }
  }, [sources, syncingIds, triggeredAt]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">数据源管理</h1>
        {canWrite && (
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={handleSyncAll}
            disabled={triggerSyncAll.isPending || syncingIds.size > 0}
          >
            {triggerSyncAll.isPending ? "触发中..." : "同步全部"}
          </Button>
          <Button onClick={openCreate}>新增数据源</Button>
        </div>
        )}
      </div>
      {showForm && (
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-3 rounded-lg border bg-card p-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>类型</Label>
              <select className="h-10 w-full rounded-md border px-3" {...register("type")}>
                {SOURCE_TYPES.map((t) => (
                  <option key={t} value={t}>{TYPE_LABELS[t] ?? t}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label>产品线</Label>
              <Input {...register("product")} />
              {errors.product && <p className="text-xs text-destructive">{errors.product.message}</p>}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>同步间隔</Label>
              <select
                aria-label="同步间隔"
                className="h-10 w-full rounded-md border px-3"
                value={syncSelect}
                onChange={(e) => {
                  const v = e.target.value;
                  if (v === "__custom") {
                    setSyncCustom(true);
                    setValue("sync_interval", "", { shouldDirty: true });
                  } else {
                    setSyncCustom(false);
                    setValue("sync_interval", v, { shouldDirty: true });
                  }
                }}
              >
                <option value="1h">1 小时</option>
                <option value="12h">12 小时</option>
                <option value="24h">1 天</option>
                <option value="__custom">自定义</option>
              </select>
              {syncSelect === "__custom" && (
                <Input {...register("sync_interval")} placeholder="30m / 48h" />
              )}
              {errors.sync_interval && (
                <p className="text-xs text-destructive">{errors.sync_interval.message}</p>
              )}
            </div>
            <div className="space-y-1">
              <Label>状态</Label>
              <div className="flex h-10 items-center gap-2">
                <input id="ds-enabled" type="checkbox" {...register("enabled")} />
                <Label htmlFor="ds-enabled" className="font-normal">启用</Label>
              </div>
            </div>
          </div>

          {type === "github" && (
            <div className="space-y-3 border-t pt-3">
              <div className="space-y-1">
                <Label>仓库 URL</Label>
                <Input
                  {...register("repo_url", {
                    onChange: () => {
                      setFetchedBranches([]);
                      setBranchError(null);
                    },
                  })}
                  placeholder="https://github.com/camthink-ai/ne301.git"
                />
              </div>
              <p className="text-xs text-muted-foreground">
                本地缓存路径:
                {watch("clone_path")?.trim()
                  ? `${watch("clone_path")}(高级选项可修改)`
                  : "自动管理(默认 ~/ask-ai-corpus/仓库名;如需覆盖见高级选项)"}
              </p>
              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <Label>分支</Label>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={handlePullBranches}
                      disabled={branchLoading}
                    >
                      {branchLoading ? "拉取中..." : "拉取分支"}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={handleDiscoverRepo}
                      disabled={discoveryLoading}
                    >
                      {discoveryLoading ? "扫描中..." : "扫描并推荐策略"}
                    </Button>
                  </div>
                </div>
                {fetchedBranches.length > 0 ? (
                  <div className="max-h-48 overflow-y-auto rounded-md border p-2">
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                      {fetchedBranches.map((b) => (
                        <label key={b} className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={selectedBranches.includes(b)}
                            onChange={() => toggleBranch(b)}
                          />
                          <span className="truncate">{b}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                ) : (
                  <Input {...register("branches")} placeholder="拉取分支后勾选;或手输逗号分隔分支" />
                )}
                {branchError && <p className="text-xs text-destructive">{branchError}</p>}
              </div>
              {discoveryError && <p className="text-xs text-destructive">{discoveryError}</p>}
              {discovery && (
                <RepoDiscoveryPanel result={discovery} onApply={handleApplyDiscovery} />
              )}
              <PolicyChips
                fileTypes={splitComma(watch("file_types"))}
                excludeDirs={splitComma(watch("exclude_dirs"))}
                onChange={handleApplyDiscovery}
              />
              <p className="text-xs text-muted-foreground">
                文件类型与排除目录建议使用「扫描并推荐策略」生成;系统默认排除测试、构建产物、
                依赖目录与密钥文件,且技术安全边界不因白名单放宽而失效。
              </p>
            </div>
          )}

          {type === "filesystem" && (
            <div className="space-y-3 border-t pt-3">
              <div className="space-y-1">
                <Label>内容来源</Label>
                <div className="flex gap-4 text-sm">
                  <label className="flex items-center gap-1">
                    <input
                      type="radio"
                      name="content-source-mode"
                      checked={!watchUploadMode}
                      onChange={() => setValue("upload_mode", false, { shouldDirty: true })}
                    />
                    服务器路径
                  </label>
                  <label className="flex items-center gap-1">
                    <input
                      type="radio"
                      name="content-source-mode"
                      checked={watchUploadMode}
                      onChange={() =>
                        setValue("upload_mode", true, {
                          shouldDirty: true,
                        })
                      }
                    />
                    上传文件夹
                  </label>
                </div>
              </div>
              {watchUploadMode && (
                <div className="space-y-1">
                  <Label>选择文件夹 (创建后自动分批上传,再次上传合并覆盖)</Label>
                  <input
                    type="file"
                    aria-label="选择文件夹"
                    multiple
                    {...{
                      webkitdirectory: "",
                      directory: "",
                    }}
                    onChange={(e) => {
                      const picked = Array.from(e.target.files ?? []);
                      setPickedFiles(picked);
                      // 按所选文件后缀预填白名单(系统元数据文件不计入),用户按需删
                      const exts = [
                        ...new Set(
                          picked
                            .filter((f) => !isJunkPath(f.name))
                            .map((f) => f.name.slice(f.name.lastIndexOf(".")).toLowerCase())
                            .filter((x) => x.startsWith(".")),
                        ),
                      ];
                      if (exts.length) {
                        setValue("file_types", exts.join(", "), { shouldDirty: true });
                      }
                    }}
                  />
                  {pickedFiles.length > 0 && (
                    <p className="text-xs text-muted-foreground">
                      已选择 {pickedFiles.length} 个文件,将上传 {uploadPreview.kept.length} 个
                      {uploadPreview.skipped.length > 0
                        ? `(跳过 ${uploadPreview.skipped.length} 个系统文件或白名单外文件)`
                        : ""}
                      {uploadProgress
                        ? ` · 上传中 ${uploadProgress.done}/${uploadProgress.total}`
                        : ""}
                    </p>
                  )}
                </div>
              )}
              {!watchUploadMode && (
              <div className="space-y-1">
                <Label>根路径</Label>
                <Input {...register("root_path")} placeholder="/data/docs" />
              </div>
              )}
              <div className="space-y-1">
                <Label>文件类型 (逗号分隔,留空=全部)</Label>
                <Input {...register("file_types")} placeholder=".md, .txt" />
              </div>
              <div className="space-y-1">
                <Label>
                  包含目录{" "}
                  {watchUploadMode
                    ? "(勾选已上传内容的子目录)"
                    : rootPath
                      ? "(勾选根路径下子目录)"
                      : "(逗号分隔,填根路径后可浏览)"}
                </Label>
                {rootPath ? (
                  <DirPicker
                    rootPath={rootPath}
                    value={splitComma(watch("include_dirs"))}
                    onChange={(dirs) => setValue("include_dirs", dirs.join(", "))}
                    missingHint={
                      watchUploadMode
                        ? "该源还没有上传过文件,上传后这里会显示服务器上的目录结构"
                        : undefined
                    }
                  />
                ) : (
                  <Input {...register("include_dirs")} placeholder="docs, guides" />
                )}
              </div>
              <div className="space-y-1">
                <Label>排除目录 (逗号分隔)</Label>
                <Input {...register("exclude_dirs")} placeholder=".git, tmp" />
              </div>
            </div>
          )}

          {type === "woocommerce" && (
            <div className="space-y-3 border-t pt-3">
              <div className="space-y-1">
                <Label>店铺地址</Label>
                <Input {...register("store_url")} placeholder="https://camthink.ai" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label>Consumer Key</Label>
                  <Input {...register("consumer_key")} placeholder="ck_..." />
                </div>
                <div className="space-y-1">
                  <Label>Consumer Secret</Label>
                  <Input type="password" {...register("consumer_secret")} placeholder="cs_..." />
                </div>
              </div>
            </div>
          )}

          {type === "web_crawl" && (
            <div className="space-y-3 border-t pt-3">
              <div className="space-y-1">
                <Label>网站地址</Label>
                <div className="flex gap-2">
                  <Input {...register("base_url")} placeholder="https://www.camthink.ai" />
                  <Button
                    type="button"
                    variant="outline"
                    disabled={websiteDiscovering}
                    onClick={handleWebsiteDiscover}
                  >
                    {websiteDiscovering ? "检测中…" : "检测站点内容"}
                  </Button>
                </div>
                {errors.base_url && (
                  <p className="text-xs text-destructive">{errors.base_url.message}</p>
                )}
                <p className="text-xs text-muted-foreground">
                  输入官网地址即可:系统自动发现 Sitemap 并给出采集范围建议;专业参数在下方高级选项。
                </p>
              </div>

              {websiteDiscoveryError && (
                <p className="text-xs text-destructive">检测失败:{websiteDiscoveryError}</p>
              )}

              {websiteDiscovery && websiteDiscovery.totals.files === 0 && (
                <div className="space-y-1 rounded-md border border-destructive/50 bg-destructive/10 p-3">
                  <p className="text-sm font-medium text-destructive">
                    未发现任何可采集页面(本次不建立有效采集范围)
                  </p>
                  {websiteDiscovery.warnings.map((w) => (
                    <p key={w} className="text-xs text-muted-foreground">· {w}</p>
                  ))}
                  <p className="text-xs">
                    请核对网站地址是否正确;若站点使用了非标准位置的 sitemap,可展开高级选项手动填写。
                  </p>
                </div>
              )}

              {websiteDiscovery && websiteDiscovery.totals.files > 0 && (
                <div className="space-y-2 rounded-md border bg-muted/40 p-3">
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                    <span className="font-medium">
                      {DISCOVERY_MODE_LABELS[websiteDiscovery.target.discovery_mode] ??
                        websiteDiscovery.target.discovery_mode}
                    </span>
                    <span>发现 {websiteDiscovery.totals.files} 页</span>
                    <span className={REC_META.include.className}>
                      建议纳入 {discoveryRecCounts.include}
                    </span>
                    <span className={REC_META.exclude.className}>
                      自动排除 {discoveryRecCounts.exclude}
                    </span>
                    <span className={REC_META.review.className}>
                      待确认 {discoveryRecCounts.review}
                    </span>
                  </div>
                  {websiteDiscovery.target.resolved_sitemaps.length > 0 && (
                    <p className="text-xs text-muted-foreground">
                      Sitemap: {websiteDiscovery.target.resolved_sitemaps.join(", ")}
                    </p>
                  )}
                  {websiteDiscovery.warnings.map((w) => (
                    <p key={w} className="text-xs text-amber-600">⚠ {w}</p>
                  ))}
                  <div className="space-y-1">
                    <p className="text-xs font-medium text-muted-foreground">按目录分组:</p>
                    {websiteDiscovery.groups.slice(0, 10).map((g) => (
                      <div key={g.key} className="flex items-center gap-2 text-xs">
                        <span className={REC_META[g.recommendation]?.className ?? ""}>
                          {REC_META[g.recommendation]?.label ?? g.recommendation}
                        </span>
                        <span className="font-mono">/{g.key === "(root)" ? "" : g.key}</span>
                        <span className="text-muted-foreground">{g.count} 页</span>
                        <span className="truncate text-muted-foreground" title={g.samples.join(" | ")}>
                          如 {g.samples[0]}
                        </span>
                      </div>
                    ))}
                    {websiteDiscovery.groups.length > 10 && (
                      <p className="text-xs text-muted-foreground">
                        仅显示前 10 组,其余 {websiteDiscovery.groups.length - 10} 组同规则处理
                      </p>
                    )}
                  </div>
                  {websiteDiscovery.capability_notes.map((n) => (
                    <p key={n} className="text-xs text-muted-foreground">· {n}</p>
                  ))}
                  <p className="text-xs text-muted-foreground">
                    {websiteExcludeApplied === false
                      ? "已保留高级选项中的自定义排除清单(未覆盖)。"
                      : "推荐排除清单已写入高级选项,可按需微调;确认无误后点「创建/保存」生效。"}
                  </p>
                </div>
              )}

              <button
                type="button"
                className="text-xs text-muted-foreground hover:text-foreground"
                onClick={() => setShowAdvanced((v) => !v)}
              >
                {showAdvanced ? "▾ 隐藏高级选项" : "▸ 高级选项(Sitemap / 排除路径 / 抓取速率)"}
              </button>
              <div className={showAdvanced ? "space-y-3" : "hidden"}>
                <div className="space-y-1">
                  <Label>Sitemap 地址 (可选,留空 = 自动发现:robots 声明 → 标准地址)</Label>
                  <Input
                    {...register("sitemap_url")}
                    placeholder="https://www.camthink.ai/sitemap_index.xml"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <Label>排除路径 (逗号分隔,留空 = 默认排除清单)</Label>
                    <Input {...register("exclude_patterns")} placeholder="/store/, /tmp" />
                  </div>
                  <div className="space-y-1">
                    <Label>抓取间隔 (毫秒,留空默认 500)</Label>
                    <Input type="number" {...register("crawl_delay_ms")} placeholder="500" />
                  </div>
                </div>
              </div>
            </div>
          )}

          {(type === "github" || type === "filesystem") && (
            <div className="space-y-2 border-t pt-3">
              <button
                type="button"
                className="text-xs text-muted-foreground hover:text-foreground"
                onClick={() => setShowAdvanced((v) => !v)}
              >
                {showAdvanced
                  ? "▾ 隐藏高级选项"
                  : type === "github"
                    ? "▸ 高级选项(Clone 路径 / 文件类型 / 排除目录 / 排除正则 / 最大文件大小)"
                    : "▸ 高级选项(排除正则 / 最大文件大小)"}
              </button>
              <div className={showAdvanced ? "space-y-3" : "hidden"}>
                {type === "github" && (
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <Label>Clone 路径 (高级/运维选项,默认自动管理)</Label>
                      <Input {...register("clone_path")} placeholder="~/ask-ai-corpus/ne301" />
                    </div>
                    <div className="space-y-1">
                      <Label>文件类型 (逗号分隔白名单;留空将不纳入任何文件)</Label>
                      <Input {...register("file_types")} placeholder=".md, .py" />
                    </div>
                    <div className="space-y-1">
                      <Label>排除目录 (逗号分隔,任意层级同名目录生效)</Label>
                      <Input {...register("exclude_dirs")} placeholder=".git, node_modules" />
                    </div>
                  </div>
                )}
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <Label>排除正则</Label>
                    <Input {...register("exclude_regex")} placeholder="(test|spec)_" />
                  </div>
                  <div className="space-y-1">
                    <Label>最大文件大小 (字节)</Label>
                    <Input type="number" {...register("max_file_size")} placeholder="1048576" />
                  </div>
                </div>
              </div>
            </div>
          )}

          <div className="flex justify-end gap-2 border-t pt-3">
            <Button type="button" variant="outline" onClick={closeForm}>取消</Button>
            <Button
              type="submit"
              disabled={createDs.isPending || updateDs.isPending || !!uploadProgress}
            >
              {uploadProgress
                ? `上传中 ${uploadProgress.done}/${uploadProgress.total}…`
                : editingId
                  ? "保存"
                  : "创建"}
            </Button>
          </div>
        </form>
      )}

      {!showForm && (
        <Table>
        <TableHeader>
          <TableRow>
            <TableHead>产品线</TableHead>
            <TableHead>类型</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>健康 (近30天)</TableHead>
            <TableHead>最新同步</TableHead>
            <TableHead>内容</TableHead>
            <TableHead>同步间隔</TableHead>
            <TableHead>操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isError && !sources ? (
            <TableRow>
              <TableCell colSpan={8} className="text-center">
                <LoadError error={error} onRetry={refetch} />
              </TableCell>
            </TableRow>
          ) : isLoading ? (
            <TableRow>
              <TableCell colSpan={8} className="text-center">加载中...</TableCell>
            </TableRow>
          ) : sources?.length === 0 ? (
            <TableRow>
              <TableCell colSpan={8} className="text-center text-muted-foreground">暂无数据源</TableCell>
            </TableRow>
          ) : sources?.map((ds) => {
            const health = healthMap.get(ds.id);
            const healthMeta = health ? HEALTH_META[health.health] : undefined;
            const latestMeta = ds.last_sync_status
              ? LATEST_STATUS_META[ds.last_sync_status]
              : undefined;
            return (
            <TableRow key={ds.id}>
              <TableCell>
                <div className="leading-tight">{ds.product}</div>
                <SourceLocationLine ds={ds} />
              </TableCell>
              <TableCell>{TYPE_LABELS[ds.type] ?? ds.type}</TableCell>
              <TableCell>
                <div className="flex flex-col items-start gap-1">
                  <Badge
                    variant={ds.enabled ? "success" : "destructive"}
                    className="cursor-pointer"
                    onClick={() => toggleDs.mutate({ id: ds.id, enabled: !ds.enabled })}
                  >
                    {ds.enabled ? "启用" : "禁用"}
                  </Badge>
                  {/* #18 删除生命周期:状态持久化在行上,刷新后仍可见 */}
                  {ds.lifecycle_state === "delete_requested" && (
                    <Badge variant="warning" title="删除已受理,等待后台清理">
                      待删除
                    </Badge>
                  )}
                  {ds.lifecycle_state === "deleting" && (
                    <Badge variant="warning" title="正在清理向量语料,完成后自动移除">
                      删除中…
                    </Badge>
                  )}
                  {ds.lifecycle_state === "delete_failed" && (
                    <Badge
                      variant="destructive"
                      title={ds.lifecycle_error ?? "删除失败,可重试"}
                    >
                      删除失败
                    </Badge>
                  )}
                  {ds.lifecycle_state === "delete_failed" && ds.lifecycle_error && (
                    <div
                      className="max-w-[180px] truncate text-xs text-destructive"
                      title={ds.lifecycle_error}
                    >
                      {ds.lifecycle_error}
                    </div>
                  )}
                </div>
              </TableCell>
              <TableCell>
                {healthMeta && health ? (
                  <div className="leading-tight">
                    <Badge variant={healthMeta.variant} title={healthTooltipTitle(health)}>
                      {healthMeta.label}
                    </Badge>
                    {health.health !== "disabled" && (
                      <div
                        className="mt-0.5 text-xs text-muted-foreground"
                        title={healthTooltipTitle(health)}
                      >
                        {healthHistoryLine(health)}
                      </div>
                    )}
                  </div>
                ) : (
                  <span className="text-xs text-muted-foreground">—</span>
                )}
              </TableCell>
              <TableCell>
                <div className="leading-tight">
                  {latestMeta ? (
                    <Badge variant={latestMeta.variant}>{latestMeta.label}</Badge>
                  ) : ds.last_sync ? (
                    <Badge variant="secondary">未知</Badge>
                  ) : (
                    <Badge variant="outline">从未同步</Badge>
                  )}
                  <span
                    className="ml-2 text-xs"
                    title={ds.last_sync ? formatSyncTime(ds.last_sync) : "暂无同步记录"}
                  >
                    {formatSyncTime(ds.last_sync)}
                  </span>
                </div>
                {(ds.last_sync_status === "failed" || ds.last_sync_status === "partial") &&
                  ds.last_sync_error && (
                    <div
                      className="mt-0.5 max-w-[180px] truncate text-xs text-destructive"
                      title={ds.last_sync_error}
                    >
                      {ds.last_sync_error}
                    </div>
                  )}
              </TableCell>
              <TableCell>
                <span
                  className="text-xs"
                  title={health ? `${health.doc_count} 篇文档 / ${health.chunk_count} 个分块` : undefined}
                >
                  {health ? `${health.doc_count} 篇` : "—"}
                </span>
              </TableCell>
              <TableCell>{ds.sync_interval}</TableCell>
              <TableCell className="space-x-2">
                {canWrite && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={syncingIds.has(ds.id) || !ds.enabled || !isSyncEligible(ds)}
                  title={isSyncEligible(ds) ? undefined : "该源处于删除流程,不能同步"}
                  onClick={() => handleSync(ds)}
                >
                  {syncingIds.has(ds.id) ? "同步中..." : "同步"}
                </Button>
                )}
                {canWrite && (
                <>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={isDeletionInFlight(ds)}
                  onClick={() => openEdit(ds)}
                >
                  编辑
                </Button>
                {ds.lifecycle_state === "delete_failed" && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={retryDeleteDs.isPending}
                    onClick={() => handleRetryDelete(ds.id)}
                  >
                    重试删除
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={deleteDs.isPending || isDeletionInFlight(ds)}
                  onClick={() => handleDelete(ds.id)}
                >
                  {isDeletionInFlight(ds) ? "删除中…" : "删除"}
                </Button>
                </>
                )}
              </TableCell>
            </TableRow>
            );
          })}
        </TableBody>
      </Table>
      )}
    </div>
  );
}
