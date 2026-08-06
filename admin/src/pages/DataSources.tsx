import { useState } from "react";
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
  fetchPreviewBranches,
} from "@/hooks/useDataSources";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { DirPicker } from "@/components/DirPicker";
import type { DataSource } from "@/types/api";

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

// Task 3:类型 + 产品线中文可读名映射(未知值降级原始 key)
const TYPE_LABELS: Record<string, string> = {
  github: "代码仓库",
  local_git: "代码仓库",
  filesystem: "文件目录",
  woocommerce: "商城",
};

const PRODUCT_LABELS: Record<string, string> = {
  ne301: "NE301 边缘相机",
  ne101: "NE101 低功耗相机",
  ne503: "NE503 AI 相机",
  ng4500: "NG4500 边缘网关",
  neomind: "NeoMind 平台",
  wiki: "官方文档",
  aitoolstack: "AI Tool Stack",
  knowledge: "支持案例",
  commercial: "商城",
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
  branches: "main",
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
        root_path: v.root_path || "",
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
  const repoName = repoPath.split("/").filter(Boolean).pop() ?? "";
  return {
    ...EMPTY_FORM,
    id: ds.id,
    type: known,
    product: ds.product,
    enabled: ds.enabled,
    sync_interval: ds.sync_interval,
    repo_url: toStr(cfg.repo_url) || (repoPath ? `https://github.com/camthink-ai/${repoName}.git` : ""),
    clone_path: toStr(cfg.clone_path) || repoPath,
    root_path: toStr(cfg.root_path),
    branches: toStr(cfg.branches) || "main",
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
  const { data: sources, isLoading } = useDataSources();
  const createDs = useCreateDataSource();
  const updateDs = useUpdateDataSource();
  const deleteDs = useDeleteDataSource();
  const toggleDs = useToggleDataSource();
  const triggerSync = useTriggerSync();
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [branchLoading, setBranchLoading] = useState(false);
  const [branchError, setBranchError] = useState<string | null>(null);

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

  const openCreate = () => {
    reset(EMPTY_FORM);
    setEditingId(null);
    setBranchError(null);
    setShowForm(true);
  };

  const openEdit = (ds: DataSource) => {
    reset(dsToForm(ds));
    setEditingId(ds.id);
    setBranchError(null);
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
      await createDs.mutateAsync({
        ...(v.id ? { id: v.id } : {}),
        type: v.type,
        product: v.product,
        enabled: v.enabled,
        sync_interval: v.sync_interval,
        config,
      });
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
      const branches = await fetchPreviewBranches(parsed.owner, parsed.repo);
      setValue("branches", branches.join(", "));
    } catch (err) {
      setBranchError(err instanceof Error ? err.message : "拉取分支失败");
    } finally {
      setBranchLoading(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm(`确定删除数据源 ${id} 吗?`)) return;
    await deleteDs.mutateAsync(id);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">数据源管理</h1>
        <Button onClick={openCreate}>新增数据源</Button>
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
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1">
              <Label>同步间隔</Label>
              <Input {...register("sync_interval")} placeholder="24h / 30m" />
              {errors.sync_interval && (
                <p className="text-xs text-destructive">{errors.sync_interval.message}</p>
              )}
            </div>
            <div className="flex items-center gap-2 pt-6">
              <input id="ds-enabled" type="checkbox" {...register("enabled")} />
              <Label htmlFor="ds-enabled">启用</Label>
            </div>
          </div>

          {type === "github" && (
            <div className="space-y-3 border-t pt-3">
              <div className="space-y-1">
                <Label>仓库 URL</Label>
                <Input {...register("repo_url")} placeholder="https://github.com/camthink-ai/ne301.git" />
              </div>
              <div className="space-y-1">
                <Label>Clone 路径 (可选,默认 ~/ask-ai-corpus/仓库名)</Label>
                <Input {...register("clone_path")} placeholder="~/ask-ai-corpus/ne301" />
              </div>
              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <Label>分支 (逗号分隔)</Label>
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
                <Input {...register("branches")} placeholder="main, hw-v1.2" />
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
          )}

          {type === "filesystem" && (
            <div className="space-y-3 border-t pt-3">
              <div className="space-y-1">
                <Label>根路径</Label>
                <Input {...register("root_path")} placeholder="/data/docs" />
              </div>
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
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label>排除目录 (逗号分隔)</Label>
                  <Input {...register("exclude_dirs")} placeholder=".git, tmp" />
                </div>
                <div className="space-y-1">
                  <Label>排除正则</Label>
                  <Input {...register("exclude_regex")} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label>最大文件大小 (字节)</Label>
                  <Input type="number" {...register("max_file_size")} />
                </div>
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

          <div className="flex gap-2">
            <Button type="submit" disabled={createDs.isPending || updateDs.isPending}>
              {editingId ? "保存" : "创建"}
            </Button>
            <Button type="button" variant="outline" onClick={closeForm}>取消</Button>
          </div>
        </form>
      )}

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
                <div className="leading-tight">{PRODUCT_LABELS[ds.product] ?? ds.product}</div>
                <div className="text-xs text-muted-foreground">{ds.id}</div>
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
              </TableCell>
              <TableCell className="space-x-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={triggerSync.isPending || !ds.enabled}
                  onClick={() => triggerSync.mutate(ds.id)}
                >
                  同步
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
    </div>
  );
}
