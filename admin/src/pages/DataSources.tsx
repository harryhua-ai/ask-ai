import { useState, useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  useDataSources,
  useCreateDataSource,
  useUpdateDataSource,
  useDeleteDataSource,
  useToggleDataSource,
  useTriggerSync,
  useTriggerSyncAll,
  fetchPreviewBranches,
  fetchPreviewFileTypes,
  uploadSourceFiles,
} from "@/hooks/useDataSources";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { DirPicker } from "@/components/DirPicker";
import type { DataSource } from "@/types/api";
import { toast } from "sonner";
import { toUploadItems, filterByWhitelist, isJunkPath } from "@/utils/upload";

// 决策 2A:github 为唯一 git 源类型(local_git 降为实现细节,不再暴露给用户)
// Task 4:woocommerce 进数据源类型枚举
const SOURCE_TYPES = ["github", "filesystem", "woocommerce"] as const;
type SourceType = (typeof SOURCE_TYPES)[number];

const formSchema = z.object({
  id: z.string().optional(),
  type: z.enum(["github", "filesystem", "woocommerce"]),
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
});

// Task 3:类型中文可读名映射(未知值降级原始 key)
const TYPE_LABELS: Record<string, string> = {
  github: "代码仓库",
  local_git: "代码仓库",
  filesystem: "文件目录",
  woocommerce: "商城",
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
};

function splitComma(s: string | undefined): string[] {
  if (!s) return [];
  return s
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

/** ISO 时间 → 本地可读时间(如 "07-31 14:30")，非法/空输入返回 "—"。 */
function formatSyncTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
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
  };
}

export default function DataSources() {
  const [syncingIds, setSyncingIds] = useState<Set<string>>(() => new Set());
  const [triggeredAt, setTriggeredAt] = useState<Record<string, number>>(() => ({}));
  const { data: sources, isLoading } = useDataSources({
    refetchInterval: syncingIds.size > 0 ? 5000 : false,
  });
  const createDs = useCreateDataSource();
  const updateDs = useUpdateDataSource();
  const deleteDs = useDeleteDataSource();
  const toggleDs = useToggleDataSource();
  const triggerSync = useTriggerSync();
  const triggerSyncAll = useTriggerSyncAll();
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [branchLoading, setBranchLoading] = useState(false);
  const [branchError, setBranchError] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [fetchedBranches, setFetchedBranches] = useState<string[]>([]);
  const [syncCustom, setSyncCustom] = useState(false);
  const [pickedFiles, setPickedFiles] = useState<File[]>([]);
  const [uploadProgress, setUploadProgress] = useState<{ done: number; total: number } | null>(
    null,
  );

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

  const openCreate = () => {
    reset(EMPTY_FORM);
    setEditingId(null);
    setBranchError(null);
    setFetchedBranches([]);
    setSyncCustom(false);
    setPickedFiles([]);
    setUploadProgress(null);
    setShowAdvanced(false);
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
          toast.success(
            `创建成功,已上传 ${saved}/${kept.length} 个文件` +
              (skipped.length > 0 ? `(已跳过 ${skipped.length} 个系统文件或白名单外文件)` : ""),
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

  const handlePullBranches = async () => {
    const repoUrl = getValues("repo_url") || "";
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
      // C10 增补:仓库出现的全部文件后缀默认全列,用户按需删
      try {
        const ft = await fetchPreviewFileTypes(parsed.owner, parsed.repo, defaultBranch);
        if (ft.extensions.length) {
          setValue("file_types", ft.extensions.join(", "), { shouldDirty: true });
        }
      } catch {
        // 文件类型拉取失败不打断分支流程(用户仍可手填)
      }
    } catch (err) {
      setBranchError(err instanceof Error ? err.message : "拉取分支失败");
    } finally {
      setBranchLoading(false);
    }
  };

  const toggleBranch = (b: string) => {
    const next = selectedBranches.includes(b)
      ? selectedBranches.filter((x) => x !== b)
      : [...selectedBranches, b];
    setValue("branches", next.join(", "), { shouldDirty: true });
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm(`确定删除数据源 ${id} 吗?`)) return;
    await deleteDs.mutateAsync(id);
  };

  const handleSync = (ds: DataSource) => {
    setSyncingIds((prev) => new Set(prev).add(ds.id));
    setTriggeredAt((prev) => ({ ...prev, [ds.id]: Date.now() }));
    triggerSync.mutate(ds.id);
  };

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
      </div>
      {showForm && (
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-3 rounded-lg border bg-card p-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>类型</Label>
              <select className="h-10 w-full rounded-md border px-3" {...register("type")}>
                {SOURCE_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
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
              <div className="space-y-1">
                <Label>Clone 路径 (可选,默认 ~/ask-ai-corpus/仓库名)</Label>
                <Input {...register("clone_path")} placeholder="~/ask-ai-corpus/ne301" />
              </div>
              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <Label>分支</Label>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={handlePullBranches}
                    disabled={branchLoading}
                  >
                    {branchLoading ? "拉取中..." : "拉取分支"}
                  </Button>
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
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label>文件类型 (逗号分隔,留空=全部)</Label>
                  <Input {...register("file_types")} placeholder=".md, .py" />
                </div>
                <div className="space-y-1">
                  <Label>排除目录 (逗号分隔)</Label>
                  <Input {...register("exclude_dirs")} placeholder=".git, node_modules" />
                </div>
              </div>
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
                  包含目录 {rootPath ? "(勾选根路径下子目录)" : "(逗号分隔,填根路径后可浏览)"}
                </Label>
                {rootPath ? (
                  <DirPicker
                    rootPath={rootPath}
                    value={splitComma(watch("include_dirs"))}
                    onChange={(dirs) => setValue("include_dirs", dirs.join(", "))}
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

          {(type === "github" || type === "filesystem") && (
            <div className="space-y-2 border-t pt-3">
              <button
                type="button"
                className="text-xs text-muted-foreground hover:text-foreground"
                onClick={() => setShowAdvanced((v) => !v)}
              >
                {showAdvanced ? "▾ 隐藏高级选项" : "▸ 高级选项(排除正则 / 最大文件大小)"}
              </button>
              <div className={showAdvanced ? "grid grid-cols-2 gap-3" : "hidden"}>
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
            <TableHead>同步间隔</TableHead>
            <TableHead>最新同步</TableHead>
            <TableHead>操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center">加载中...</TableCell>
            </TableRow>
          ) : sources?.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center text-muted-foreground">暂无数据源</TableCell>
            </TableRow>
          ) : sources?.map((ds) => (
            <TableRow key={ds.id}>
              <TableCell>
                <div className="leading-tight">{ds.product}</div>
                <SourceLocationLine ds={ds} />
              </TableCell>
              <TableCell>{TYPE_LABELS[ds.type] ?? ds.type}</TableCell>
              <TableCell>
                <Badge
                  variant={ds.enabled ? "success" : "destructive"}
                  className="cursor-pointer"
                  onClick={() => toggleDs.mutate({ id: ds.id, enabled: !ds.enabled })}
                >
                  {ds.enabled ? "启用" : "禁用"}
                </Badge>
              </TableCell>
              <TableCell>{ds.sync_interval}</TableCell>
              <TableCell>
                <span title={ds.last_sync ?? "暂无同步记录"}>{formatSyncTime(ds.last_sync)}</span>
                {ds.last_sync_status === "partial" && (
                  <Badge variant="warning" className="ml-2">
                    {ds.last_sync_error ?? "已补齐缺口"}
                  </Badge>
                )}
              </TableCell>
              <TableCell className="space-x-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={syncingIds.has(ds.id) || !ds.enabled}
                  onClick={() => handleSync(ds)}
                >
                  {syncingIds.has(ds.id) ? "同步中..." : "同步"}
                </Button>
                <Button size="sm" variant="outline" onClick={() => openEdit(ds)}>
                  编辑
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={deleteDs.isPending}
                  onClick={() => handleDelete(ds.id)}
                >
                  删除
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      )}
    </div>
  );
}
