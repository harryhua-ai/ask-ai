/**
 * v1.6.3 B1(KB-OPS-V163-002 §4.5):编辑数据源右侧抽屉(context-preserving)。
 *
 * 冻结语义:
 * - 完整编辑器能力保持权威(类型/产品线/同步间隔/连接配置/发现策略/上传),
 *   仅交互容器从页内表单收敛为右侧抽屉;字段与提交行为与原实现逐字等价;
 * - 新建与编辑共用;编辑时数据源保留其运营上下文(列表行/详情页不离开)。
 */

import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { DirPicker } from "@/components/DirPicker";
import {
  applyRepoDecisions,
  PolicyChips,
  RepoDiscoveryPanel,
} from "@/components/dataSources/RepoDiscoveryPanel";
import {
  useCreateDataSource,
  useUpdateDataSource,
  useDeleteDataSource,
  fetchPreviewBranches,
  fetchRepoDiscovery,
  fetchWebsiteDiscovery,
  uploadSourceFiles,
  type WebsiteDiscoveryResult,
} from "@/hooks/useDataSources";
import {
  buildConfig,
  DISCOVERY_MODE_LABELS,
  dsToForm,
  EMPTY_FORM,
  formatSyncTime as _formatSyncTime,
  parseRepoUrl,
  REC_META,
  splitComma,
  SOURCE_TYPES,
  TYPE_LABELS,
  uploadRootOf,
  upsertDiscoveryRule,
  formSchema,
  type FormValues,
} from "@/lib/sourceEditorModel";
import type { DataSource, RepoDiscoveryResult } from "@/types/api";
import { apiFetch } from "@/lib/api";
import { toUploadItems, filterByWhitelist, isJunkPath } from "@/utils/upload";

void _formatSyncTime;
void TYPE_LABELS;

export interface SourceEditorDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** null = 新建;非 null = 编辑该源(完整编辑器能力,类型可改) */
  editing: DataSource | null;
  /** 创建成功后回调(供列表页导航/详情页刷新) */
  onCreated?: (created: DataSource) => void;
}

export function SourceEditorDrawer({
  open,
  onOpenChange,
  editing,
  onCreated,
}: SourceEditorDrawerProps) {
  const createDs = useCreateDataSource();
  const updateDs = useUpdateDataSource();
  const deleteDs = useDeleteDataSource();

  const [branchLoading, setBranchLoading] = useState(false);
  const [branchError, setBranchError] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [fetchedBranches, setFetchedBranches] = useState<string[]>([]);
  // #16 Simple Mode:仓库发现结果(只读预览;采用推荐策略才写入表单字段)
  const [discovery, setDiscovery] = useState<RepoDiscoveryResult | null>(null);
  const [discoveryLoading, setDiscoveryLoading] = useState(false);
  const [discoveryError, setDiscoveryError] = useState<string | null>(null);
  // #22 会话内组决策(预览会话作用域;持久记忆经 discovery_rules 随 config 保存)
  const [repoDecisions, setRepoDecisions] = useState<Record<string, "include" | "exclude">>({});
  const [siteDecisions, setSiteDecisions] = useState<Record<string, "include" | "exclude">>({});
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

  // 打开时按 新建/编辑 预填(与原 openCreate/openEdit 逐字等价)
  useEffect(() => {
    if (!open) return;
    if (editing) {
      const fv = dsToForm(editing);
      reset(fv);
      setBranchError(null);
      setFetchedBranches([]);
      setSyncCustom(!["1h", "12h", "24h"].includes(fv.sync_interval));
    } else {
      reset(EMPTY_FORM);
      setBranchError(null);
      setFetchedBranches([]);
      setSyncCustom(false);
    }
    setPickedFiles([]);
    setUploadProgress(null);
    setShowAdvanced(false);
    setDiscovery(null);
    setDiscoveryError(null);
    setWebsiteDiscovery(null);
    setWebsiteDiscoveryError(null);
    setWebsiteExcludeApplied(null);
    setRepoDecisions({});
    setSiteDecisions({});
  }, [open, editing, reset]);

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

  const closeForm = () => onOpenChange(false);

  const onSubmit = async (v: FormValues) => {
    const config = buildConfig(v);
    if (editing) {
      await updateDs.mutateAsync({
        id: editing.id,
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
            const { saved } = await uploadSourceFiles(editing.id, kept, (done, total) =>
              setUploadProgress({ done, total }),
            );
            // 上传成功:重算顶层目录全集写入 include_dirs(默认全选,与当前内容保持一致)
            let allSelNote = "";
            const topDirs = await fetchTopDirPaths(uploadRootOf(editing.id));
            if (topDirs.length > 0) {
              try {
                await updateDs.mutateAsync({
                  id: editing.id,
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
      onCreated?.(created);
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
      setSiteDecisions({}); // 新预览=新会话(持久决策由服务端继承,见 admin_decision)
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
      setRepoDecisions({}); // 新预览=新会话(持久决策由服务端继承,见 admin_decision)
    } catch (err) {
      setDiscovery(null);
      setDiscoveryError(err instanceof Error ? err.message : "仓库扫描失败");
    } finally {
      setDiscoveryLoading(false);
    }
  };

  /**
   * #22 组决策(仓库):纳入/排除/恢复推荐。
   * 生效策略 = 表单 file_types/exclude_dirs(基线推荐 ⊕ 会话决策,单一权威;
   * connector 语义保证 exclude_dirs 胜过白名单,排除组成员机械不进范围);
   * 同时写入 config.discovery_rules(治理记忆,保存后后续发现自动继承)。
   */
  const handleRepoDecide = (groupKey: string, decision: "include" | "exclude" | null) => {
    if (!discovery) return;
    const next = { ...repoDecisions };
    if (decision) next[groupKey] = decision;
    else delete next[groupKey];
    setRepoDecisions(next);
    const chips = applyRepoDecisions(discovery, next);
    setValue("file_types", chips.file_types.join(", "), { shouldDirty: true });
    setValue("exclude_dirs", chips.exclude_dirs.join(", "), { shouldDirty: true });
    setValue(
      "discovery_rules",
      upsertDiscoveryRule(getValues("discovery_rules") ?? [], "github", groupKey, decision),
      { shouldDirty: true },
    );
  };

  /**
   * #22 组决策(网站):排除 = 家族前缀写入 exclude_patterns(预览=同步视野);
   * 纳入 = 移除该家族排除 + 记录策略记忆;恢复推荐 = 删决策并按基线重算。
   */
  const handleSiteDecide = (groupKey: string, decision: "include" | "exclude" | null) => {
    if (!websiteDiscovery || groupKey === "(root)") return;
    const next = { ...siteDecisions };
    if (decision) next[groupKey] = decision;
    else delete next[groupKey];
    setSiteDecisions(next);
    const baseline =
      ((websiteDiscovery.recommended_config as { exclude_patterns?: string[] })
        .exclude_patterns) ?? [];
    const patterns = new Set(baseline);
    for (const [key, d] of Object.entries(next)) {
      const pat = `/${key}/`;
      if (d === "exclude") patterns.add(pat);
      else patterns.delete(pat);
    }
    setValue("exclude_patterns", [...patterns].sort().join(", "), { shouldDirty: true });
    setValue(
      "discovery_rules",
      upsertDiscoveryRule(
        getValues("discovery_rules") ?? [],
        "web_crawl",
        `/${groupKey}/`,
        decision,
      ),
      { shouldDirty: true },
    );
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

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent aria-label={editing ? "编辑数据源" : "添加数据源"}>
        <SheetTitle className="text-lg font-semibold">
          {editing ? "编辑数据源" : "添加数据源"}
        </SheetTitle>
        <SheetDescription className="sr-only">
          {editing ? "编辑数据源配置" : "创建新的数据源"}
        </SheetDescription>
        <form onSubmit={handleSubmit(onSubmit)} className="mt-4 space-y-3">
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
                <RepoDiscoveryPanel
                  result={discovery}
                  decisions={repoDecisions}
                  onDecide={handleRepoDecide}
                  onApply={handleApplyDiscovery}
                />
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
                    {websiteDiscovery.groups.slice(0, 10).map((g) => {
                      const decided = siteDecisions[g.key];
                      return (
                        <div key={g.key} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                          <span className={REC_META[g.recommendation]?.className ?? ""}>
                            {REC_META[g.recommendation]?.label ?? g.recommendation}
                          </span>
                          <span className="font-mono">/{g.key === "(root)" ? "" : g.key}</span>
                          <span className="text-muted-foreground">{g.count} 页</span>
                          {g.admin_decision && (
                            <span className="rounded border border-blue-200 bg-blue-50 px-1 text-blue-700">
                              已按策略
                            </span>
                          )}
                          {g.recommendation === "include" && g.scope_confirmed === false && (
                            <span className="text-amber-600" role="alert">
                              ⚠ 有纳入页不在生效范围
                            </span>
                          )}
                          {(g.member_review ?? 0) > 0 && (
                            <span
                              className="text-amber-600"
                              title="组内存在待人工确认页面;采用策略不会替你决定该部分"
                            >
                              {g.member_review} 待确认
                            </span>
                          )}
                          <span className="truncate text-muted-foreground" title={g.samples.join(" | ")}>
                            如 {g.samples[0]}
                          </span>
                          {g.key !== "(root)" && (
                            <span className="ml-auto flex items-center gap-1">
                              {decided ? (
                                <>
                                  <span className="text-blue-700">
                                    已决定:{decided === "include" ? "纳入" : "排除"}
                                  </span>
                                  <button
                                    type="button"
                                    className="text-muted-foreground underline hover:text-foreground"
                                    onClick={() => handleSiteDecide(g.key, null)}
                                  >
                                    恢复推荐
                                  </button>
                                </>
                              ) : (
                                <>
                                  <button
                                    type="button"
                                    className="text-green-700 underline hover:text-green-900"
                                    onClick={() => handleSiteDecide(g.key, "include")}
                                  >
                                    纳入
                                  </button>
                                  <button
                                    type="button"
                                    className="text-muted-foreground underline hover:text-foreground"
                                    onClick={() => handleSiteDecide(g.key, "exclude")}
                                  >
                                    排除
                                  </button>
                                </>
                              )}
                            </span>
                          )}
                        </div>
                      );
                    })}
                    {websiteDiscovery.groups.length > 10 && (
                      <p className="text-xs text-muted-foreground">
                        仅显示前 10 组,其余 {websiteDiscovery.groups.length - 10} 组同规则处理
                      </p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      组决定会实时写入高级选项的排除清单(即生效采集策略),并按策略记忆保存——
                      下次检测同族页面不再重复询问;决定后点「创建/保存」生效。
                    </p>
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
                : editing
                  ? "保存"
                  : "创建"}
            </Button>
          </div>
        </form>
      </SheetContent>
    </Sheet>
  );
}

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
