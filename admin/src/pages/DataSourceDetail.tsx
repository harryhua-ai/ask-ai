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
  useBulkDocumentRepair,
  useDocumentRepair,
  useSourceSchedule,
} from "@/hooks/useDataSourceKnowledge";
import { KnowledgeSettingsDrawer } from "@/components/dataSources/KnowledgeSettingsDrawer";
import { sourceBrandOf } from "@/lib/sourceBrand";
import { contentTypeLabel } from "@/lib/contentType";
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
  isRetiredLifecycle,
  lifecycleLabel,
  linkStateLabel,
  notServingReason,
  servingProjectionNote,
} from "@/lib/dataSourceLifecycle";
import { sourceLocation, sourceTypeLabel, formatSyncTime } from "@/lib/sourceEditorModel";

// v1.6.3 B1(KB-OPS-V163-002):Source Detail 收敛(硬参考 panel 2/3/4)。
// 层级:身份 → 操作者状态 → 最新同步摘要 → 知识总量+需处理 → prominent
// attention banner → 知识内容工作区 → 本地诊断/历史(次级,可展开)。
// 零伪造:状态/计数/原因/时间/生成/在服全部来自权威读面;/documents 聚合、
// /sync-health、/analytics/source-health、sync_runs、index_generations;
// 后端无记录 → 显式「后端无此记录」。
// v1.6.3 Wave 1 Track C(八项冻结语义,全部真值后端权威):
// U-6 品牌内建映射(sourceBrand;零远程 logo)/ U-7 逐文档 content_type
// (后端真值列+过滤+聚合,前端禁推断)/ U-8 行级修复工作流(处理/⋯/
// 重新处理=POST repair,RBAC+幂等+审计+验证卡)/ U-9 chunk serving 投影
// (X/Y=后端真值)/ U-10 恢复注记(持久化事件计数)/ U-11 下次同步
// (调度器权威 next_run_at)/ U-12 知识设置抽屉(资格政策+新鲜度)/
// U-13 高风险预览 Modal(计数服务端权威+一致 mutation)。

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

  // 知识内容工作区(权威账本读面):搜索/bucket/生命周期/类型(U-7)/排序/分页
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [bucket, setBucket] = useState("");
  const [lifecycle, setLifecycle] = useState("");
  const [contentType, setContentType] = useState("");
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
  }, [bucket, lifecycle, order, contentType]);

  const documentsQuery = useSourceDocuments(sourceId, {
    bucket: bucket || undefined,
    lifecycle: lifecycle || undefined,
    order,
    contentType: contentType || undefined,
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
  // U-12:知识设置抽屉(读/写/预览确认链)
  const [settingsOpen, setSettingsOpen] = useState(false);
  // U-8:行级修复(POST repair;RBAC/幂等/审计/验证在后端)
  const repairMutation = useDocumentRepair(sourceId);
  const bulkRepairMutation = useBulkDocumentRepair(sourceId);
  // U-11:调度真值(schedule 端点 reconcile 的权威 next_run_at)
  const scheduleQuery = useSourceSchedule(sourceId);

  const runRepair = (docSourceId: string) => {
    repairMutation.mutate(
      { doc_source_id: docSourceId },
      {
        onSuccess: (task) => {
          if (task.status === "succeeded") {
            toast.success(
              `重新处理完成:${task.result?.chunks_serving ?? 0}/${task.result?.chunks_total ?? 0} chunks 在服,一致性${task.result?.consistency === "passed" ? "通过" : "未通过"}`,
            );
          } else {
            toast.error(`重新处理未完成:${task.error ?? task.status}`);
          }
          void documentsQuery.refetch();
          void truthQuery.refetch();
        },
        onError: (err) =>
          toast.error(err instanceof Error ? err.message : "修复命令失败"),
      },
    );
  };

  const runBulkRepair = () => {
    bulkRepairMutation.mutate(undefined, {
      onSuccess: (result) => {
        if (result.failed === 0) {
          toast.success(`批量修复完成:已修复 ${result.succeeded} 项`);
        } else {
          toast.warning(`批量修复部分完成:已修复 ${result.succeeded} 项，${result.failed} 项仍需处理`);
        }
        void documentsQuery.refetch();
        void truthQuery.refetch();
      },
      onError: (err) =>
        toast.error(err instanceof Error ? err.message : "批量修复命令失败"),
    });
  };

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
        membershipStatus: source.membership_status ?? null,
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
            {/* U-6(DS-P2-02):source-type/品牌内建映射色块;零远程 logo_url 真值 */}
            <div
              aria-hidden
              data-testid="source-brand-block"
              title={`品牌呈现:内建映射(${sourceBrandOf(source.type, source.product).label})`}
              className="flex h-12 w-12 items-center justify-center rounded-lg text-lg font-bold"
              style={{
                background: sourceBrandOf(source.type, source.product).bg,
                color: sourceBrandOf(source.type, source.product).fg,
              }}
            >
              {sourceBrandOf(source.type, source.product).glyph}
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
            {/* DS-01:页头操作直接可见;返回列表是详情页的稳定导航出口。 */}
            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" onClick={() => navigate("/data-sources")}>
                返回列表
              </Button>
              {canWrite && (
                <>
                  <Button size="sm" variant="outline" onClick={() => setEditorOpen(true)}>
                    编辑
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setSettingsOpen(true)}>
                    知识设置
                  </Button>
                </>
              )}
            </div>
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

      {/* U-12:新鲜度超期提醒(后端权威超期态,Admin 可见;过期 CURRENT 诚实浮现) */}
      {source && canWrite && source.freshness_overdue && !bannerDismissed && (
        <div
          className="flex flex-wrap items-center gap-3 rounded-md border border-amber-300 bg-amber-50 p-3"
          data-testid="freshness-overdue-banner"
        >
          <span
            aria-hidden
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-500 text-[11px] font-bold text-white"
          >
            ⚠
          </span>
          <p className="flex-1 text-sm text-amber-700">
            该源知识已超过新鲜度要求
            {source.freshness_hours ? `(${source.freshness_hours} 小时)` : ""}
            ,可能无法支撑当前事实型回答;建议更新服务。
          </p>
          {canWrite && (
            <Button size="sm" variant="outline" onClick={() => setSettingsOpen(true)}>
              调整知识设置
            </Button>
          )}
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
            {canWrite && (
              <Button
                size="sm"
                variant="default"
                data-testid="bulk-document-repair"
                disabled={bulkRepairMutation.isPending}
                onClick={runBulkRepair}
              >
                {bulkRepairMutation.isPending
                  ? "一键修复中..."
                  : `一键修复全部 ${attentionCount} 项`}
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              aria-label="关闭提醒"
              onClick={() => setBannerDismissed(true)}
            >
              ✕
            </Button>
          </div>
          {bulkRepairMutation.data && (
            <p className="w-full text-xs text-muted-foreground" aria-live="polite">
              已修复 {bulkRepairMutation.data.succeeded} 项，{bulkRepairMutation.data.failed} 项仍需处理
            </p>
          )}
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
            <select
              aria-label="按类型过滤"
              data-testid="content-type-filter"
              className="h-10 rounded-md border px-3 text-sm"
              value={contentType}
              onChange={(e) => setContentType(e.target.value)}
              title="逐文档内容类型(后端账本真值)"
            >
              <option value="">全部类型</option>
              {Object.entries(docs?.content_type_counts ?? {}).map(([ct, n]) => (
                <option key={ct} value={ct}>
                  {contentTypeLabel(ct) ?? ct}({n})
                </option>
              ))}
              {(docs?.content_type_counts && Object.keys(docs.content_type_counts).length) ? (
                <option value="none">类型不可用(存量)</option>
              ) : null}
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
                            {/* U-7:逐文档 content_type(后端真值;null=不可用,禁推断) */}
                            {(() => {
                              const label = contentTypeLabel(row.content_type);
                              if (label) return <span title={row.content_type ?? undefined}>{label}</span>;
                              if (row.content_type) return <span title={row.content_type}>{row.content_type}</span>;
                              return (
                                <span className="text-muted-foreground" title="类型不可用(存量行,后端无真值)">
                                  —
                                </span>
                              );
                            })()}
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
                            <div className="flex items-center gap-1">
                              {/* U-8:修复动作与查看真相都是知识行一级操作,不藏进 overflow。 */}
                              {/* Issue #83:退役行(superseded/deleted)不提供修复入口
                                  (lifecycle authority ⊨ repair authority;后端同样
                                  fail-closed),改以明确文案呈现"无需处理"。 */}
                              {canWrite && bucketKey !== "retired" && (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="h-7 px-2"
                                  data-testid={`doc-repair-${row.source_id}`}
                                  title="执行权威修复并在完成后验证"
                                  disabled={
                                    repairMutation.isPending &&
                                    repairMutation.variables?.doc_source_id === row.source_id
                                  }
                                  onClick={() => runRepair(row.source_id)}
                                >
                                  {repairMutation.isPending &&
                                  repairMutation.variables?.doc_source_id === row.source_id
                                    ? "处理中..."
                                    : "修复此知识"}
                                </Button>
                              )}
                              {bucketKey === "retired" && (
                                <span
                                  className="text-xs text-muted-foreground"
                                  title="退役知识由权威 lifecycle 保护,不得由 repair 从历史副本复活;历史版本与删除记录保留为审计真相"
                                >
                                  已退役,无需处理
                                </span>
                              )}
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 px-2"
                                data-testid={`doc-truth-${row.source_id}`}
                                onClick={() =>
                                  setTruthDocId((cur) =>
                                    cur === row.source_id ? null : row.source_id,
                                  )
                                }
                              >
                                {expanded ? "收起真相" : "查看真相"}
                              </Button>
                            </div>
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
                                    {/* Issue #55:身份区 —— 权威身份维度显式呈现
                                        (复合身份/分支/类型/产品;账本权威列,零推断)。 */}
                                    <p
                                      className="break-all font-mono text-xs text-muted-foreground"
                                      data-testid="inspector-identity"
                                    >
                                      {truthQuery.data.doc_source_id}
                                      {truthQuery.data.branch &&
                                        ` · branch ${truthQuery.data.branch}`}
                                      {` · ${truthQuery.data.source_type} · ${truthQuery.data.product}`}
                                    </p>
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
                                        {truthQuery.data.chunk_serving ? (
                                          <>
                                            <span
                                              data-testid="chunk-serving-score"
                                              title="chunk 级 serving 投影(verify_source_vectors 权威口径)"
                                            >
                                              {truthQuery.data.chunk_serving.serving_chunks} /{" "}
                                              {truthQuery.data.chunk_serving.total_chunks}
                                            </span>
                                            {/* Issue #55(退役 ≠ healthy):退役文档的投影
                                                是审计口径,不得呈现为「不完整/在服」。 */}
                                            {servingProjectionNote(truthQuery.data.lifecycle) ? (
                                              <span className="text-muted-foreground">
                                                {" "}· {servingProjectionNote(truthQuery.data.lifecycle)}
                                              </span>
                                            ) : truthQuery.data.serving ? (
                                              " 在服"
                                            ) : (
                                              " 不完整"
                                            )}
                                          </>
                                        ) : (
                                          <>
                                            {truthQuery.data.serving ? "在服" : "不在服"}
                                            {truthQuery.data.current_version &&
                                              ` · 持久 chunk ${truthQuery.data.current_version.chunks_total}`}
                                            {truthQuery.data.current_version && (
                                              <span className="text-xs text-muted-foreground">
                                                {" "}(chunk 投影不可用)
                                              </span>
                                            )}
                                          </>
                                        )}
                                      </p>
                                      <p>
                                        <span className="text-muted-foreground">生成技术证据:</span>{" "}
                                        {truthQuery.data.generation ? (
                                          truthQuery.data.generation.ordinal === 0 ? (
                                            <span title="legacy migration sentinel; counters are not serving counts">
                                              迁移哨兵（技术记录，计数不代表在服数量）
                                            </span>
                                          ) : (
                                            `技术记录 #${truthQuery.data.generation.ordinal}(${generationStatusLabel(truthQuery.data.generation.status)}) · 文档 ${truthQuery.data.generation.doc_count} · chunk ${truthQuery.data.generation.chunk_count}`
                                          )
                                        ) : (
                                          <span className="text-amber-600">后端无此记录</span>
                                        )}
                                      </p>
                                    </div>
                                    {/* Issue #55:版本历史 —— document_versions 权威行
                                        降序展开(与现行版本同一权威关系;空 = 后端无此记录)。 */}
                                    <div>
                                      <p className="text-xs">
                                        <span className="text-muted-foreground">版本历史:</span>{" "}
                                        {truthQuery.data.versions?.length ? (
                                          <span className="text-muted-foreground">
                                            {truthQuery.data.versions.length} 条(降序)
                                          </span>
                                        ) : (
                                          <span className="text-amber-600">后端无此记录</span>
                                        )}
                                      </p>
                                      {truthQuery.data.versions?.length ? (
                                        <ul
                                          className="mt-1 space-y-0.5 text-xs"
                                          data-testid="inspector-version-history"
                                        >
                                          {truthQuery.data.versions.map((v) => (
                                            <li
                                              key={v.version_seq}
                                              className={
                                                v.version_seq ===
                                                truthQuery.data?.current_version?.version_seq
                                                  ? "font-medium"
                                                  : "text-muted-foreground"
                                              }
                                            >
                                              v{v.version_seq}({v.status}) · 生效自{" "}
                                              {v.valid_from ? formatSyncTime(v.valid_from) : "后端无此记录"}{" "}
                                              · chunk {v.chunk_count}
                                              {v.version_seq ===
                                                truthQuery.data?.current_version?.version_seq &&
                                                " · 现行"}
                                            </li>
                                          ))}
                                        </ul>
                                      ) : null}
                                      {truthQuery.data.versions_truncated && (
                                        <p className="text-[10px] text-muted-foreground">
                                          仅显示最近 20 条(后端诚实截断)
                                        </p>
                                      )}
                                    </div>
                                    {/* U-10:自动恢复注记(持久化权威事件计数,禁前端计数) */}
                                    {truthQuery.data.recovery_attempts_failed > 0 && (
                                      <p
                                        className="flex items-center gap-1 text-xs text-muted-foreground"
                                        data-testid="recovery-note"
                                      >
                                        <span aria-hidden>ⓘ</span>
                                        系统已自动尝试恢复 {truthQuery.data.recovery_attempts_failed}{" "}
                                        次,未成功。
                                      </p>
                                    )}
                                    {/* U-8(DS-P3-07):重新处理(真实修复命令;RBAC 内可见)
                                        Issue #83:退役行不提供修复入口,改以"已退役,无需处理"
                                        明确文案(后端受理/执行两阶段同样 fail-closed) */}
                                    {canWrite && !isRetiredLifecycle(truthQuery.data.lifecycle) && (
                                      <div className="flex justify-end">
                                        <Button
                                          size="sm"
                                          data-testid="doc-reprocess-truth"
                                          disabled={
                                            repairMutation.isPending &&
                                            repairMutation.variables?.doc_source_id ===
                                              truthQuery.data.doc_source_id
                                          }
                                          onClick={() => runRepair(truthQuery.data.doc_source_id)}
                                        >
                                          {repairMutation.isPending &&
                                          repairMutation.variables?.doc_source_id ===
                                            truthQuery.data.doc_source_id
                                            ? "重新处理中..."
                                            : "重新处理"}
                                        </Button>
                                      </div>
                                    )}
                                    {isRetiredLifecycle(truthQuery.data.lifecycle) && (
                                      <p
                                        className="text-right text-xs text-muted-foreground"
                                        data-testid="doc-retired-note"
                                      >
                                        已退役,无需处理(历史版本与删除记录保留为审计真相)
                                      </p>
                                    )}
                                    {/* U-8(DS-P3-08/09):重新处理完成验证卡(vN/12/12/一致性 = 后端真值)
                                        Issue #83:验证卡仅对具备服务资格的文档呈现 —— 绝不把退役
                                        文档的 index completeness 宣称为"已成功进入当前服务" */}
                                    {truthQuery.data.latest_repair_task &&
                                      truthQuery.data.latest_repair_task.status === "succeeded" &&
                                      truthQuery.data.latest_repair_task.result &&
                                      !isRetiredLifecycle(truthQuery.data.lifecycle) && (
                                        <div
                                          className="rounded-md border border-green-300 bg-green-50 p-3"
                                          data-testid="repair-verification-card"
                                        >
                                          <p className="mb-1 flex items-center gap-1 text-sm font-medium text-green-700">
                                            <span aria-hidden>✓</span> 重新处理完成
                                          </p>
                                          <p className="text-xs text-green-700/80">
                                            知识内容已成功进入当前服务。
                                          </p>
                                          <dl className="mt-2 space-y-0.5 text-xs">
                                            <div className="flex justify-between">
                                              <dt className="text-muted-foreground">当前有效版本</dt>
                                              <dd>
                                                v{truthQuery.data.latest_repair_task.result.version_seq ?? "—"}
                                              </dd>
                                            </div>
                                            <div className="flex justify-between">
                                              <dt className="text-muted-foreground">当前服务</dt>
                                              <dd>
                                                {truthQuery.data.latest_repair_task.result.chunks_serving} /{" "}
                                                {truthQuery.data.latest_repair_task.result.chunks_total}
                                              </dd>
                                            </div>
                                            <div className="flex justify-between">
                                              <dt className="text-muted-foreground">一致性验证</dt>
                                              <dd
                                                className={
                                                  truthQuery.data.latest_repair_task.result.consistency ===
                                                  "passed"
                                                    ? "font-medium text-green-700"
                                                    : "font-medium text-destructive"
                                                }
                                              >
                                                {truthQuery.data.latest_repair_task.result.consistency ===
                                                "passed"
                                                  ? "✓ 通过"
                                                  : "未通过"}
                                              </dd>
                                            </div>
                                          </dl>
                                          {/* #54 R5:完成时间主呈现 = 相对时间,原样 ISO 收进 title */}
                                          <p className="mt-1 text-[10px] text-muted-foreground">
                                            完成于{" "}
                                            <RelativeTime iso={truthQuery.data.latest_repair_task.finished_at} /> ·
                                            执行者 {truthQuery.data.latest_repair_task.requested_by ?? "—"}
                                          </p>
                                        </div>
                                      )}
                                    {/* Issue #55:引用与链接 —— 消费 #48 权威派生
                                        (link_state 词表 + slug 权威映射目标);
                                        非 external 状态不渲染 <a>,存储 URL 原样保全。 */}
                                    <p className="break-all text-xs">
                                      引用:{" "}
                                      {truthQuery.data.citation ? (
                                        <>
                                          {truthQuery.data.citation.link_state === "external" &&
                                          truthQuery.data.citation.citation_url ? (
                                            <a
                                              className="underline underline-offset-2"
                                              href={truthQuery.data.citation.citation_url}
                                              target="_blank"
                                              rel="noopener noreferrer"
                                            >
                                              {truthQuery.data.citation.citation_url}
                                            </a>
                                          ) : (
                                            <span className="font-mono">
                                              {truthQuery.data.citation.citation_url ??
                                                truthQuery.data.citation.url}
                                            </span>
                                          )}{" "}
                                          <Badge
                                            variant="outline"
                                            data-testid="inspector-link-state"
                                            title="引用有效性 = 后端权威派生(#48 冻结词表 external/none/private/stale)"
                                          >
                                            {linkStateLabel(truthQuery.data.citation.link_state)}
                                          </Badge>
                                          <span className="text-muted-foreground">
                                            {" "}· 访客可达性:
                                            {truthQuery.data.citation.visitor_reachability ?? "未记录"}
                                          </span>
                                          {truthQuery.data.citation.citation_url &&
                                            truthQuery.data.citation.citation_url !==
                                              truthQuery.data.citation.url && (
                                              <span className="text-muted-foreground">
                                                {" "}· 存储 {truthQuery.data.citation.url}
                                              </span>
                                            )}
                                        </>
                                      ) : (
                                        <span className="text-amber-600">不可用</span>
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
                                      修复语义 = 权威修复契约(U-8:RBAC/幂等/可审计/修复后验证);验证卡数值来自修复结果与一致性核验真值。
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
            schedule={scheduleQuery.data}
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
              <CardTitle className="text-base">索引生成（技术证据）</CardTitle>
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
                <>
                  <p className="mb-3 text-xs text-muted-foreground">
                    生成代序、文档数与分块数仅用于技术核证；迁移哨兵不代表在服数量。
                  </p>
                  <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>代序（技术）</TableHead>
                      <TableHead>状态</TableHead>
                      <TableHead>文档数（技术）</TableHead>
                      <TableHead>分块数（技术）</TableHead>
                      <TableHead>创建 / 就绪 / 激活 / 退役</TableHead>
                      <TableHead>失败证据</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {generations?.items.map((g) => (
                      <TableRow key={g.id}>
                        <TableCell className="font-mono">
                          {g.ordinal === 0 ? "迁移哨兵" : `#${g.ordinal}`}
                        </TableCell>
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
                        <TableCell>{g.ordinal === 0 ? "—" : g.doc_count}</TableCell>
                        <TableCell>{g.ordinal === 0 ? "—" : g.chunk_count}</TableCell>
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
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </details>

      {/* 编辑数据源(context-preserving drawer;完整编辑器能力保持权威) */}
      {source && (
        <SourceEditorDrawer open={editorOpen} onOpenChange={setEditorOpen} editing={source} />
      )}

      {/* U-12:知识设置抽屉(证据资格政策层 + 新鲜度;保存走 U-13 预览确认链) */}
      {source && canWrite && (
        <KnowledgeSettingsDrawer
          open={settingsOpen}
          onOpenChange={setSettingsOpen}
          sourceId={source.id}
          onSaved={() => {
            void refetchSources();
            void documentsQuery.refetch();
            void scheduleQuery.refetch();
          }}
        />
      )}
    </div>
  );
}
