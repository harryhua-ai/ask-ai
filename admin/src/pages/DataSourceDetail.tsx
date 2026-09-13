import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChevronDown, ChevronRight } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/hooks/useAuth";
import LoadError from "@/components/LoadError";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { Pagination } from "@/components/Pagination";
import { SourceHealthPanel } from "@/components/dataSources/SourceHealthPanel";
import { SyncActivityPanel } from "@/components/dataSources/SyncActivityPanel";
import { SourceEditorDrawer } from "@/components/dataSources/SourceEditorDrawer";
import {
  useDataSources,
  useSourceHealth,
  useSyncHealth,
  useSyncRuns,
  useTriggerSync,
} from "@/hooks/useDataSources";
import {
  useSourceDocuments,
  useSourceDocumentTruth,
  useSourceGenerations,
} from "@/hooks/useDataSourceWorkspace";
import {
  attentionReasonClasses,
  operatorStateOf,
  relativeTime,
  toneVariant,
} from "@/lib/dataSourceOps";
import {
  bucketCountsOf,
  bucketLabel,
  bucketOfDocument,
  generationStatusLabel,
  lifecycleLabel,
  notServingReason,
} from "@/lib/dataSourceLifecycle";
import { sourceLocation, sourceTypeLabel, formatSyncTime } from "@/lib/sourceEditorModel";

// v1.6.3 B1(KB-OPS-V163-002):Source Detail 收敛(硬参考 panel 2/3/4)。
// 层级:身份 → 操作者状态 → 最新同步摘要 → 知识总量+需处理 → prominent
// attention banner → 知识内容工作区 → 本地诊断/历史(次级,可展开)。
// 零伪造:状态/计数/原因/时间/生成/在服全部来自权威读面;/documents 聚合、
// /sync-health、/analytics/source-health、sync_runs、index_generations;
// 后端无记录 → 显式「后端无此记录」。无新增变更语义(无 重新处理/知识设置)。

/** 知识行状态(权威 lifecycle+serving 的呈现映射;reference 四态词表)。 */
function knowledgeStatusOf(doc: { lifecycle: string; serving: boolean }): {
  label: string;
  variant: "success" | "warning" | "destructive" | "secondary" | "outline";
} {
  if (doc.lifecycle === "active" && doc.serving) return { label: "正常", variant: "success" };
  if (doc.lifecycle === "missing_candidate") return { label: "需处理", variant: "destructive" };
  if (doc.lifecycle === "active") return { label: "待分类", variant: "warning" };
  if (doc.lifecycle === "discovered") return { label: "待分类", variant: "warning" };
  if (doc.lifecycle === "superseded" || doc.lifecycle === "deleted") {
    return { label: "已退役", variant: "outline" };
  }
  return { label: "待分类", variant: "warning" };
}

const BUCKET_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "current", label: "当前在服" },
  { value: "attention", label: "需要关注" },
  { value: "retired", label: "已退役" },
];

const SORT_OPTIONS = [
  { value: "-updated_at", label: "更新时间" },
  { value: "title", label: "名称" },
];

const LIFECYCLE_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "全部生命周期" },
  { value: "active", label: "在服 (active)" },
  { value: "missing_candidate", label: "源中缺失 (missing_candidate)" },
  { value: "superseded", label: "已被接替 (superseded)" },
  { value: "deleted", label: "已删除 (deleted)" },
  { value: "discovered", label: "已发现 (discovered)" },
];

/** 生成行失败证据(JSONB 原样键值呈现,不改写)。 */
function FailureEvidence({ failure }: { failure: Record<string, unknown> }) {
  return (
    <div className="rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs">
      <p className="mb-1 font-medium text-destructive">失败证据(后端 failure 原文)</p>
      {Object.entries(failure).map(([k, v]) => (
        <p key={k} className="font-mono break-all">
          {k}: {typeof v === "string" ? v : JSON.stringify(v)}
        </p>
      ))}
    </div>
  );
}

function RelativeTime({ iso }: { iso: string | null | undefined }) {
  const rel = relativeTime(iso);
  if (!iso || !rel) return <span className="text-muted-foreground">—</span>;
  // A-P2-03(audit):单格式呈现 = 仅相对时间;精确时间收进 title tooltip,不再双格式并排
  return (
    <span title={iso} className="whitespace-nowrap">
      {rel}
    </span>
  );
}

export default function DataSourceDetail() {
  const { sourceId = "" } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canWrite = user?.role === "admin" || user?.role === "editor";

  // 身份/配置:复用既有 /data-sources 列表读面(零新增配置端点)
  const {
    data: sources,
    isLoading: sourcesLoading,
    isError: sourcesError,
    error: sourcesErrorObj,
    refetch: refetchSources,
  } = useDataSources();
  const source = useMemo(
    () => sources?.find((s) => s.id === sourceId),
    [sources, sourceId],
  );

  const { data: syncHealth } = useSyncHealth();
  const healthItem = useMemo(
    () => syncHealth?.items.find((i) => i.source_id === sourceId),
    [syncHealth, sourceId],
  );
  const { data: windowHealth } = useSourceHealth();
  const reliability = useMemo(
    () => windowHealth?.items.find((i) => i.source_id === sourceId),
    [windowHealth, sourceId],
  );
  const runsQuery = useSyncRuns(sourceId);
  const runsError =
    runsQuery.error instanceof Error
      ? runsQuery.error.message
      : runsQuery.error
        ? "同步历史加载失败"
        : null;

  const triggerSync = useTriggerSync();

  // 知识内容工作区(权威账本读面):搜索/bucket/生命周期/排序/分页
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [bucket, setBucket] = useState("");
  const [lifecycle, setLifecycle] = useState("");
  const [order, setOrder] = useState("-updated_at");
  const [page, setPage] = useState(1);
  const [bannerDismissed, setBannerDismissed] = useState(false);
  const SIZE = 20;
  // 搜索防抖(300ms)后提交,过滤变更回到第 1 页(跳过挂载首跑,避免重置分页)
  const searchMounted = useRef(false);
  useEffect(() => {
    if (!searchMounted.current) {
      searchMounted.current = true;
      return;
    }
    const t = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);
  useEffect(() => {
    setPage(1);
  }, [bucket, lifecycle, order]);

  const documentsQuery = useSourceDocuments(sourceId, {
    bucket: bucket || undefined,
    lifecycle: lifecycle || undefined,
    order,
    search: search || undefined,
    page,
    size: SIZE,
  });
  const docs = documentsQuery.data;
  const bucketCounts = useMemo(
    () =>
      docs
        ? bucketCountsOf({
            lifecycle_counts: docs.lifecycle_counts,
            current_count: docs.current_count,
            serving_count: docs.serving_count,
            ledger_total: docs.ledger_total,
          })
        : null,
    [docs],
  );

  // 单文档真相(行展开 = 本地诊断,panel 3 只读部分)
  const [truthDocId, setTruthDocId] = useState<string | null>(null);
  const truthQuery = useSourceDocumentTruth(sourceId, truthDocId);

  // 生成可见性(次级证据,本地诊断内)
  const generationsQuery = useSourceGenerations(sourceId);
  const generations = generationsQuery.data;

  // 编辑数据源(context-preserving drawer,§4.5)
  const [editorOpen, setEditorOpen] = useState(false);

  if (sourcesError && !sources) {
    return (
      <div className="space-y-4">
        <Button variant="outline" size="sm" onClick={() => navigate("/data-sources")}>
          ← 返回数据源列表
        </Button>
        <LoadError error={sourcesErrorObj} onRetry={refetchSources} />
      </div>
    );
  }

  const operatorState = source
    ? operatorStateOf({
        enabled: source.enabled,
        lastSyncStatus: source.last_sync_status,
        attentionCount: bucketCounts ? bucketCounts.attention : null,
        syncHealthOverall: healthItem?.overall ?? null,
        lifecycleState: source.lifecycle_state,
      })
    : null;
  const attentionCount = bucketCounts?.attention ?? 0;
  const reasonLines = docs
    ? attentionReasonClasses(docs.lifecycle_counts, attentionCount)
    : [];
  const location = source ? sourceLocation(source) : null;

  return (
    <div className="space-y-4">
      {/* 面包屑(A-P1-07:参考分隔符「›」;返回列表由面包屑承担) */}
      <nav aria-label="面包屑" className="text-xs text-muted-foreground">
        <Link to="/data-sources" className="hover:underline">配置</Link>
        <span className="mx-1" aria-hidden>›</span>
        <Link to="/data-sources" className="hover:underline">数据源</Link>
        <span className="mx-1" aria-hidden>›</span>
        <span className="text-foreground">{source?.product ?? sourceId}</span>
      </nav>

      {/* 层级 1-2:身份 + 操作者状态 + 最新同步摘要 + 知识/需处理总量 */}
      {sourcesLoading ? (
        <p className="text-sm text-muted-foreground">加载中...</p>
      ) : !source ? (
        <Card>
          <CardContent className="space-y-2 p-4">
            <p className="text-sm font-medium text-destructive">后端无此记录</p>
            <p className="text-sm text-muted-foreground">
              数据源配置中不存在 id 为 <span className="font-mono">{sourceId}</span> 的源。
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div
              aria-hidden
              className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10 text-lg font-bold text-primary"
            >
              {source.product.slice(0, 1).toUpperCase()}
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-2xl font-bold" data-testid="detail-title">
                  {source.product}
                </h1>
                {operatorState && (
                  <Badge variant={toneVariant(operatorState.tone)} title={source.id}>
                    {operatorState.label}
                  </Badge>
                )}
              </div>
              <p className="text-sm text-muted-foreground">
                {sourceTypeLabel(source.type)}
                {location?.text && (
                  <>
                    {" | "}
                    {location.href ? (
                      <a
                        className="underline underline-offset-2"
                        href={location.href}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {location.text}
                      </a>
                    ) : (
                      <span className="font-mono text-xs">{location.text}</span>
                    )}
                  </>
                )}
                <span className="ml-2 font-mono text-[10px]" title={`数据源 ID:${source.id}`}>
                  {source.id}
                </span>
              </p>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1 text-sm">
            {/* A-P2-05(audit):页头动作收敛为单「⋯」(编辑/返回列表保留在菜单;返回列表同时由面包屑承担) */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="sm" variant="ghost" aria-label="更多页操作" className="px-2">
                  ⋯
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {canWrite && (
                  <DropdownMenuItem onSelect={() => setEditorOpen(true)}>编辑</DropdownMenuItem>
                )}
                <DropdownMenuItem onSelect={() => navigate("/data-sources")}>
                  返回列表
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <div>
              <span className="text-muted-foreground">最后同步</span>{" "}
              {source.last_sync ? (
                <RelativeTime iso={source.last_sync} />
              ) : (
                <span className="text-muted-foreground">从未同步</span>
              )}
              {source.last_sync_status && (
                <>
                  {" · "}
                  {source.last_sync_status === "partial" ? (
                    /* A-P2-01(audit):「部分成功」= 链接态(蓝+chevron),指向既有同步活动区,无新路由语义 */
                    <button
                      type="button"
                      data-testid="partial-result-link"
                      className="inline-flex items-center gap-0.5 font-medium text-[var(--acc)] hover:underline"
                      title="查看同步状态与活动中的部分成功证据"
                      onClick={() =>
                        document
                          .getElementById("sync-activity")
                          ?.scrollIntoView({ behavior: "smooth", block: "start" })
                      }
                    >
                      部分成功
                      <ChevronDown className="h-3.5 w-3.5" aria-hidden />
                    </button>
                  ) : (
                    <span
                      className={
                        source.last_sync_status === "failed"
                          ? "text-destructive"
                          : "text-green-600"
                      }
                    >
                      {{ success: "成功", partial: "部分成功", failed: "失败" }[source.last_sync_status] ?? source.last_sync_status}
                    </span>
                  )}
                </>
              )}
            </div>
            <div>
              <span>{docs?.ledger_total ?? "—"}</span> 条知识
              {attentionCount > 0 ? (
                <>
                  {" · "}
                  <span className="font-medium text-destructive">{attentionCount} 项需处理</span>
                </>
              ) : null}
            </div>
          </div>
        </div>
      )}

      {/* 层级 5:prominent attention banner(权威原因摘要;可关闭为本地呈现状态) */}
      {source && attentionCount > 0 && !bannerDismissed && (
        <div className="flex flex-wrap items-start gap-3 rounded-md border border-destructive/40 bg-destructive/10 p-3">
          {/* A-P2-04(audit):banner 图标 = 红圈 ⚠ 图标,不再裸「!」 */}
          <span
            aria-hidden
            className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-red-600 text-[11px] font-bold text-white"
          >
            ⚠
          </span>
          <div className="min-w-0 flex-1 space-y-1">
            <p className="font-medium text-destructive">有 {attentionCount} 项知识需要处理</p>
            {reasonLines.length > 0 && (
              <ul className="space-y-0.5 text-xs text-muted-foreground">
                {reasonLines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setBucket("attention");
                setLifecycle("");
                setPage(1);
              }}
            >
              查看需处理
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label="关闭提醒"
              onClick={() => setBannerDismissed(true)}
            >
              ✕
            </Button>
          </div>
        </div>
      )}

      {/* 层级 6:知识内容工作区 */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0 p-4">
          <CardTitle className="text-base">知识内容</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 p-4 pt-0">
          <div className="flex flex-wrap items-center gap-2">
            <Input
              aria-label="搜索知识内容"
              placeholder="搜索知识内容..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className="max-w-xs"
            />
            <select
              aria-label="按状态过滤"
              className="h-10 rounded-md border px-3 text-sm"
              value={bucket}
              onChange={(e) => setBucket(e.target.value)}
            >
              {BUCKET_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <select
              aria-label="按生命周期过滤"
              className="h-10 rounded-md border px-3 text-xs text-muted-foreground"
              value={lifecycle}
              onChange={(e) => setLifecycle(e.target.value)}
              title="技术过滤(生命周期词表)"
            >
              {LIFECYCLE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <div className="ml-auto flex items-center gap-2">
              <span className="text-xs text-muted-foreground">
                共 {docs?.total ?? 0} 条(账本 {docs?.ledger_total ?? 0})
              </span>
              <select
                aria-label="排序"
                className="h-10 rounded-md border px-3 text-sm"
                value={order}
                onChange={(e) => setOrder(e.target.value)}
              >
                {SORT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
          </div>

          {bucketCounts && (
            <div className="flex flex-wrap items-center gap-2">
              {(["current", "attention", "retired"] as const).map((b) => (
                <button
                  key={b}
                  type="button"
                  onClick={() => {
                    setBucket(b === "current" ? "current" : b === "attention" ? "attention" : "retired");
                    setPage(1);
                  }}
                  title="点击过滤该运营桶"
                >
                  <Badge variant={b === "current" ? "success" : b === "attention" ? "warning" : "outline"}>
                    {bucketLabel(b)} {bucketCounts[b]}
                  </Badge>
                </button>
              ))}
              <span className="text-xs text-muted-foreground">
                在服(含宽限){docs?.serving_count ?? 0} 篇 · 计数真相 = 账本(documents)权威聚合
              </span>
            </div>
          )}

          {documentsQuery.isError && !docs ? (
            <LoadError
              error={documentsQuery.error}
              onRetry={() => documentsQuery.refetch()}
            />
          ) : documentsQuery.isLoading ? (
            <p className="text-sm text-muted-foreground">加载中...</p>
          ) : (docs?.items.length ?? 0) === 0 ? (
            <p className="text-sm text-muted-foreground">该源暂无账本文档</p>
          ) : (
            <>
              <Table className="[&_td]:!py-1.5 [&_th]:!h-9 [&_th]:!py-1.5">
                <TableHeader>
                  <TableRow>
                    <TableHead>名称</TableHead>
                    <TableHead>类型</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>当前版本</TableHead>
                    <TableHead>服务</TableHead>
                    <TableHead>更新时间</TableHead>
                    <TableHead>操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {docs?.items.map((row) => {
                    const bucketKey = bucketOfDocument(row);
                    const reason = notServingReason(row);
                    const kStatus = knowledgeStatusOf(row);
                    const expanded =
                      truthDocId === row.source_id &&
                      truthQuery.data?.doc_source_id === row.source_id;
                    return (
                      <Fragment key={row.source_id}>
                        <TableRow className="align-top">
                          <TableCell>
                            {/* A-P3-01(audit):行头 = 展开触发(⌄/⌃ + 名称),参考 grammar;A-P1-03 同口径:名称单行,doc_source_id 收进 title */}
                            <button
                              type="button"
                              data-testid="doc-row-toggle"
                              aria-expanded={expanded}
                              className="flex max-w-[280px] items-center gap-1 text-left font-medium hover:underline"
                              title={`${row.title} · ${row.source_id}`}
                              onClick={() =>
                                setTruthDocId((cur) => (cur === row.source_id ? null : row.source_id))
                              }
                            >
                              {expanded ? (
                                <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                              ) : (
                                <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                              )}
                              <span className="truncate">{row.title}</span>
                            </button>
                          </TableCell>
                          <TableCell className="text-sm">
                            {sourceTypeLabel(row.source_type)}
                          </TableCell>
                          <TableCell>
                            <Badge variant={kStatus.variant}>{kStatus.label}</Badge>
                            {bucketKey !== "current" && reason && (
                              <div
                                className="mt-1 max-w-[220px] truncate text-xs text-amber-600"
                                title={reason}
                              >
                                {reason}
                              </div>
                            )}
                          </TableCell>
                          <TableCell className="text-sm">
                            {row.current_version_seq != null ? (
                              <span title={`现行版本 #${row.current_version_seq}(权威版本链)`}>
                                v{row.current_version_seq}
                              </span>
                            ) : (
                              <span className="text-muted-foreground" title="后端无此记录">—</span>
                            )}
                          </TableCell>
                          <TableCell>
                            {/* A-P2-02(audit):同一 serving 真相的词+色映射:正常(绿)/不完整(蓝)/—(灰,无现行版本) */}
                            {row.current_version_seq == null ? (
                              <span className="text-sm text-muted-foreground" title="后端无现行版本记录">—</span>
                            ) : row.serving ? (
                              <Badge variant="success">正常</Badge>
                            ) : (
                              <Badge variant="info">不完整</Badge>
                            )}
                          </TableCell>
                          <TableCell className="text-sm">
                            <RelativeTime iso={row.updated_at} />
                          </TableCell>
                          <TableCell>
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-7 px-2"
                              aria-label={`查看真相 ${row.source_id}`}
                              onClick={() =>
                                setTruthDocId((cur) => (cur === row.source_id ? null : row.source_id))
                              }
                            >
                              {expanded ? "收起真相" : "真相"}
                            </Button>
                          </TableCell>
                        </TableRow>
                        {/* A-P3-01(audit):诊断真相 = 行下原地展开(不再挂在整表之后的表级附录) */}
                        {expanded && (
                          <TableRow>
                            <TableCell colSpan={7} className="bg-muted/20">
                              <div className="space-y-2 py-1 text-sm">
                                {truthQuery.isLoading && (
                                  <p className="text-muted-foreground">加载中...</p>
                                )}
                                {truthQuery.isError && !truthQuery.data && (
                                  <LoadError
                                    compact
                                    error={truthQuery.error}
                                    onRetry={() => truthQuery.refetch()}
                                  />
                                )}
                                {truthQuery.data && (
                                  <>
                                    <p className="font-medium">问题</p>
                                    <p className="text-muted-foreground">
                                      {notServingReason(truthQuery.data) ?? "该文档当前在服,无异常记录"}
                                    </p>
                                    <div className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
                                      <p>
                                        <span className="text-muted-foreground">源内容状态:</span>{" "}
                                        <Badge variant="outline">
                                          {lifecycleLabel(truthQuery.data.lifecycle)}
                                        </Badge>
                                      </p>
                                      <p>
                                        <span className="text-muted-foreground">当前有效版本:</span>{" "}
                                        {truthQuery.data.current_version ? (
                                          <>
                                            v{truthQuery.data.current_version.version_seq}({truthQuery.data.current_version.status}) · 生效自{" "}
                                            {/* A-P3-02(audit):人类化时间,精确值收进 tooltip */}
                                            <span
                                              title={truthQuery.data.current_version.valid_from ?? undefined}
                                            >
                                              {truthQuery.data.current_version.valid_from
                                                ? formatSyncTime(truthQuery.data.current_version.valid_from)
                                                : "后端无此记录"}
                                            </span>
                                          </>
                                        ) : (
                                          <span className="text-amber-600">后端无此记录</span>
                                        )}
                                      </p>
                                      <p>
                                        <span className="text-muted-foreground">当前服务:</span>{" "}
                                        {truthQuery.data.serving ? "在服" : "不在服"}
                                        {truthQuery.data.current_version &&
                                          ` · 持久 chunk ${truthQuery.data.current_version.chunks_total}`}
                                      </p>
                                      <p>
                                        <span className="text-muted-foreground">生成真相:</span>{" "}
                                        {truthQuery.data.generation ? (
                                          `#${truthQuery.data.generation.ordinal}(${generationStatusLabel(truthQuery.data.generation.status)}) · 文档 ${truthQuery.data.generation.doc_count} · chunk ${truthQuery.data.generation.chunk_count}`
                                        ) : (
                                          <span className="text-amber-600">后端无此记录</span>
                                        )}
                                      </p>
                                    </div>
                                    <p className="break-all text-xs">
                                      URL:{" "}
                                      {truthQuery.data.url.startsWith("http") ? (
                                        <a
                                          className="underline underline-offset-2"
                                          href={truthQuery.data.url}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                        >
                                          {truthQuery.data.url}
                                        </a>
                                      ) : (
                                        <span className="font-mono">{truthQuery.data.url}</span>
                                      )}
                                    </p>
                                    <p className="text-xs text-muted-foreground">
                                      创建 <RelativeTime iso={truthQuery.data.created_at} /> · 更新{" "}
                                      <RelativeTime iso={truthQuery.data.updated_at} />
                                      {truthQuery.data.superseded_at && (
                                        <>
                                          {" "}· 接替 <RelativeTime iso={truthQuery.data.superseded_at} />
                                        </>
                                      )}
                                      {truthQuery.data.superseded_by && ` · 接替者 ${truthQuery.data.superseded_by}`}
                                    </p>
                                    <p className="text-xs text-muted-foreground">
                                      本诊断为只读真相呈现;行级修复操作需待权威修复契约(v1.6.3 不提供)。
                                    </p>
                                  </>
                                )}
                              </div>
                            </TableCell>
                          </TableRow>
                        )}
                      </Fragment>
                    );
                  })}
                </TableBody>
              </Table>
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">
                  共 {docs?.total ?? 0} 条(账本 {docs?.ledger_total ?? 0} 篇)
                </span>
                <Pagination
                  page={page}
                  onPageChange={setPage}
                  hasMore={page * SIZE < (docs?.total ?? 0)}
                />
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* 层级 7:同步状态与活动(panel 4;异常优先时间线;A-P2-01 链接态锚点) */}
      {source && (
        <div id="sync-activity" className="scroll-mt-4">
          <SyncActivityPanel
            source={source}
            runs={runsQuery.data}
            runsLoading={runsQuery.isLoading}
            runsError={runsError}
            onRetryRuns={() => runsQuery.refetch()}
            health={reliability}
            onTriggerSync={
              source.enabled
                ? () => {
                    triggerSync.mutate(source.id, {
                      onSuccess: () =>
                        toast.success(`已触发同步:${source.id}(后台进行中,完成后自动刷新)`),
                    });
                  }
                : undefined
            }
            syncPending={triggerSync.isPending}
          />
        </div>
      )}

      {/* 本地诊断(次级证据,可展开):五维健康 + 索引生成真相(#55 证据定位) */}
      <details className="rounded-md border">
        <summary className="cursor-pointer p-3 text-sm font-medium">本地诊断(健康与生成真相)</summary>
        <div className="space-y-3 p-3 pt-0">
          <SourceHealthPanel health={healthItem} />
          <Card>
            <CardHeader className="flex-row items-center justify-between space-y-0 p-4">
              <CardTitle className="text-base">索引生成</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 p-4 pt-0">
              {generationsQuery.isError && !generations ? (
                <LoadError
                  error={generationsQuery.error}
                  onRetry={() => generationsQuery.refetch()}
                />
              ) : generationsQuery.isLoading ? (
                <p className="text-sm text-muted-foreground">加载中...</p>
              ) : (generations?.items.length ?? 0) === 0 ? (
                <p className="text-sm text-muted-foreground">该源尚无索引生成记录(后端无此记录)</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>序数</TableHead>
                      <TableHead>状态</TableHead>
                      <TableHead>文档数</TableHead>
                      <TableHead>分块数</TableHead>
                      <TableHead>创建 / 就绪 / 激活 / 退役</TableHead>
                      <TableHead>失败证据</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {generations?.items.map((g) => (
                      <TableRow key={g.id}>
                        <TableCell className="font-mono">#{g.ordinal}</TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1">
                            <Badge
                              variant={
                                g.status === "failed"
                                  ? "destructive"
                                  : g.status === "ready"
                                    ? "success"
                                    : g.status === "processing"
                                      ? "warning"
                                      : "outline"
                              }
                            >
                              {generationStatusLabel(g.status)}
                            </Badge>
                            {generations.serving_ordinals.includes(g.ordinal) && (
                              <Badge variant="success" title="该代含当前在服文档(active_generation 权威口径)">
                                在服代
                              </Badge>
                            )}
                          </div>
                        </TableCell>
                        <TableCell>{g.doc_count}</TableCell>
                        <TableCell>{g.chunk_count}</TableCell>
                        <TableCell>
                          <div className="space-y-0.5 text-xs">
                            <div>创建 <RelativeTime iso={g.created_at} /></div>
                            <div>就绪 <RelativeTime iso={g.ready_at} /></div>
                            <div>激活 <RelativeTime iso={g.activated_at} /></div>
                            <div>退役 <RelativeTime iso={g.retired_at} /></div>
                          </div>
                        </TableCell>
                        <TableCell>
                          {g.failure ? (
                            <FailureEvidence failure={g.failure} />
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>
      </details>

      {/* 编辑数据源(context-preserving drawer;完整编辑器能力保持权威) */}
      {source && (
        <SourceEditorDrawer open={editorOpen} onOpenChange={setEditorOpen} editing={source} />
      )}
    </div>
  );
}
