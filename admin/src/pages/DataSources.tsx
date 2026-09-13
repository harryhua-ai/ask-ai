import { Fragment, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "@/hooks/useAuth";
import LoadError from "@/components/LoadError";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import {
  useDataSources,
  useDeleteDataSource,
  useRetryDeleteDataSource,
  useTriggerSync,
  useTriggerSyncAll,
  useSourceHealth,
  useSyncHealth,
  useSyncRuns,
  useSyncStatus,
  useAttentionSummary,
} from "@/hooks/useDataSources";
import { SourceEditorDrawer } from "@/components/dataSources/SourceEditorDrawer";
import { SourceHealthPanel } from "@/components/dataSources/SourceHealthPanel";
import { SyncHistoryPanel } from "@/components/dataSources/SyncHistoryPanel";
import { SyncStatusPanel } from "@/components/dataSources/SyncStatusPanel";
import { isDeletionInFlight, isSyncEligible } from "@/types/api";
import type { DataSource, SyncHealthItem, SyncStatusItem } from "@/types/api";
import {
  operatorStateOf,
  relativeTime,
  toneVariant,
  type OperatorTone,
} from "@/lib/dataSourceOps";
import {
  sourceLocation,
  sourceTypeLabel,
  formatSyncTime,
} from "@/lib/sourceEditorModel";

// 向后兼容:#50 详情工作面曾从本页导入 TYPE_LABELS/sourceLocation(单一出处已移至 lib)。
export { TYPE_LABELS, sourceLocation } from "@/lib/sourceEditorModel";

// ==================== v1.6.3 B1(KB-OPS-V163-002)数据源列表收敛 ====================
// 硬参考:references/data-source-operations-original.png panel 1。
// 扫描优先密集表:名称/类型/状态(操作者状态)/知识数量/需处理(一等列)/最后同步/操作;
// 需处理计数 = 后端 attention-summary 权威投影;操作者状态 = 后端权威值呈现映射;
// 异常优先排序;搜索/状态/类型过滤为呈现层;既有操作(同步/编辑/删除/可观测性)保留,
// 编辑收敛为 context-preserving 抽屉(§4.5)。前端零健康重判。

const ACTIVE_SYNC_STATES = new Set(["QUEUED", "WAITING", "RUNNING", "RECOVERING"]);

function isBackendActive(status: SyncStatusItem | undefined): status is SyncStatusItem {
  return !!status && ACTIVE_SYNC_STATES.has(status.state);
}

/** 操作者状态过滤词表(呈现层;值 = OperatorTone 语义组)。 */
const STATE_FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "全部状态" },
  { value: "attention", label: "需处理" },
  { value: "ok", label: "正常" },
  { value: "intermediate", label: "中间态(恢复中/过期/部分)" },
  { value: "unclassified", label: "待分类" },
  { value: "failed", label: "同步失败" },
  { value: "disabled", label: "已禁用" },
];

const TONE_PRIORITY: Record<OperatorTone, number> = {
  failed: 0,
  attention: 1,
  intermediate: 2,
  unclassified: 3,
  disabled: 4,
  ok: 5,
};

// A-P1-03:参考为单行密表(名称列无 URL/路径副行);来源地址不再作副行渲染,
// 收进行名 title/详情页(工作区列除外),行高收敛 ~36px。

function SourceObservabilityDetails({
  source,
  syncHealth,
  activeStatus,
  expanded,
}: {
  source: DataSource;
  /** #11 Health Authority:W2 /sync-health 权威条目,面板直呈,前端不重判 */
  syncHealth?: SyncHealthItem;
  activeStatus?: SyncStatusItem;
  expanded: boolean;
}) {
  const runsQuery = useSyncRuns(source.id, { enabled: expanded });

  if (!expanded && !activeStatus) return null;
  const historyError = runsQuery.error instanceof Error
    ? runsQuery.error.message
    : runsQuery.error
      ? "同步历史加载失败"
      : null;

  return (
    <TableRow>
      <TableCell colSpan={7} className="bg-muted/20">
        <div className="space-y-4 py-2">
          {activeStatus && <SyncStatusPanel status={activeStatus} />}
          {expanded && (
            <>
              <SyncHistoryPanel
                runs={runsQuery.data}
                isLoading={runsQuery.isLoading}
                error={historyError}
                onRetry={() => runsQuery.refetch()}
              />
              <SourceHealthPanel health={syncHealth} />
            </>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
}

export default function DataSources() {
  const navigate = useNavigate();
  const { data: syncStatus } = useSyncStatus({ refetchInterval: 5000 });
  const activeStatusMap = useMemo(
    () => new Map(
      (syncStatus?.items ?? [])
        .filter(isBackendActive)
        .map((status) => [status.source_id, status]),
    ),
    [syncStatus],
  );
  const hasActiveSyncs = activeStatusMap.size > 0;
  const { data: sources, isLoading, isError, error, refetch } = useDataSources({
    // #9 闭包:active 判定唯一事实源 = W2 /sync-status(后端),刷新即恢复、
    // 前端零启发式;#18 删除在途(delete_requested/deleting)同样保持 5s
    // 轮询,让 lifecycle 推进可见(完成 → 行自动消失;失败 → DELETE_FAILED 徽章)。
    refetchInterval: (query) => {
      const list = query.state.data as DataSource[] | undefined;
      const deleting = list?.some((s) => isDeletionInFlight(s)) ?? false;
      return hasActiveSyncs || deleting ? 5000 : false;
    },
  });
  // v1.6.3 B1:全源运营桶聚合(后端权威投影)→ 需处理 一等列 + 知识数量列
  const { data: attentionSummary } = useAttentionSummary({
    refetchInterval: hasActiveSyncs ? 5000 : false,
  });
  const summaryMap = useMemo(
    () => new Map((attentionSummary?.items ?? []).map((i) => [i.source_id, i])),
    [attentionSummary],
  );
  // DSH-02 历史可靠性(30 天窗口)降为次级证据:操作者状态徽章 hover title 呈现。
  const { data: healthData } = useSourceHealth({
    refetchInterval: hasActiveSyncs ? 5000 : false,
  });
  const healthMap = useMemo(
    () => new Map((healthData?.items ?? []).map((h) => [h.source_id, h])),
    [healthData],
  );
  // #11 Health Authority:五维健康唯一权威 = W2 /sync-health(只读直呈,前端不重判)
  const { data: syncHealthData } = useSyncHealth({
    refetchInterval: hasActiveSyncs ? 5000 : false,
  });
  const syncHealthMap = useMemo(
    () => new Map((syncHealthData?.items ?? []).map((h) => [h.source_id, h])),
    [syncHealthData],
  );

  // 呈现层过滤(列表完整无分页;不改变任何权威读面)
  const [searchInput, setSearchInput] = useState("");
  const [stateFilter, setStateFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");

  const deleteDs = useDeleteDataSource();
  const retryDeleteDs = useRetryDeleteDataSource();
  const triggerSync = useTriggerSync();
  const triggerSyncAll = useTriggerSyncAll();
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingDs, setEditingDs] = useState<DataSource | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set());

  const { user } = useAuth();
  const canWrite = user?.role === "admin" || user?.role === "editor";

  const operatorStateOfSource = (ds: DataSource) =>
    operatorStateOf({
      enabled: ds.enabled,
      lastSyncStatus: ds.last_sync_status,
      attentionCount: summaryMap.get(ds.id)?.attention_count ?? null,
      syncHealthOverall: syncHealthMap.get(ds.id)?.overall ?? null,
      lifecycleState: ds.lifecycle_state,
    });

  const visibleSources = useMemo(() => {
    const term = searchInput.trim().toLowerCase();
    const list = (sources ?? []).filter((ds) => {
      if (term) {
        const hay = `${ds.product} ${sourceLocation(ds).text} ${ds.id}`.toLowerCase();
        if (!hay.includes(term)) return false;
      }
      if (typeFilter && ds.type !== typeFilter) return false;
      if (stateFilter) {
        const tone = operatorStateOfSource(ds).tone;
        if (stateFilter === "disabled" && ds.enabled) return false;
        if (stateFilter !== "disabled" && tone !== stateFilter) return false;
      }
      return true;
    });
    // 异常优先排序(呈现层;不改变后端权威顺序语义)
    return [...list].sort((a, b) => {
      const ta = TONE_PRIORITY[operatorStateOfSource(a).tone];
      const tb = TONE_PRIORITY[operatorStateOfSource(b).tone];
      if (ta !== tb) return ta - tb;
      return a.id.localeCompare(b.id);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sources, searchInput, stateFilter, typeFilter, summaryMap, syncHealthMap]);

  const openCreate = () => {
    setEditingDs(null);
    setEditorOpen(true);
  };

  const openEdit = (ds: DataSource) => {
    setEditingDs(ds);
    setEditorOpen(true);
  };

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
    triggerSync.mutate(ds.id);
  };

  const toggleObservability = (id: string) => {
    setExpandedIds((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleSyncAll = async () => {
    await triggerSyncAll.mutateAsync();
  };

  const typesInList = useMemo(
    () => [...new Set((sources ?? []).map((ds) => ds.type))],
    [sources],
  );

  return (
    <div className="space-y-4">
      {/* 面包屑 + 页头(hard ref panel 1) */}
      <div>
        <nav aria-label="面包屑" className="text-xs text-muted-foreground">
          <span>配置</span>
          <span className="mx-1" aria-hidden>›</span>
          <span className="text-foreground">数据源</span>
        </nav>
        <div className="mt-1 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">数据源</h1>
            <p className="text-sm text-muted-foreground">
              管理 ASK-AI 的知识来源,确保内容保持更新并正常服务。
            </p>
          </div>
          {canWrite && (
            <div className="flex gap-2">
              {/* A-P1-08:参考页头仅一枚主按钮;「同步全部」收进页头 ⋯ 菜单(既有授权动作保留) */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="sm" aria-label="更多页操作" className="px-2">
                    ⋯
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    disabled={triggerSyncAll.isPending || hasActiveSyncs}
                    onClick={() => void handleSyncAll()}
                  >
                    {triggerSyncAll.isPending
                      ? "触发中..."
                      : hasActiveSyncs
                        ? "同步进行中..."
                        : "同步全部"}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <Button onClick={openCreate}>+ 添加数据源</Button>
            </div>
          )}
        </div>
      </div>

      {/* 搜索 + 状态/类型过滤(呈现层;A-P1-06:参考为紧凑控件) */}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          aria-label="搜索数据源"
          placeholder="搜索数据源..."
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          className="h-8 max-w-xs text-sm"
        />
        <select
          aria-label="按状态过滤"
          className="h-8 rounded-md border px-2 text-sm"
          value={stateFilter}
          onChange={(e) => setStateFilter(e.target.value)}
        >
          {STATE_FILTER_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <select
          aria-label="按类型过滤"
          className="h-8 rounded-md border px-2 text-sm"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
        >
          <option value="">全部类型</option>
          {typesInList.map((t) => (
            <option key={t} value={t}>{sourceTypeLabel(t)}</option>
          ))}
        </select>
      </div>

      {/* A-P1-03:参考 ~36-40px 单行密表(单元格纵向 padding 收敛;⋯ 按钮降为 h-7 不撑行) */}
      <Table className="[&_td]:!py-1.5 [&_th]:!h-9 [&_th]:!py-1.5">
        <TableHeader>
          <TableRow>
            <TableHead>名称</TableHead>
            <TableHead>类型</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>知识数量</TableHead>
            <TableHead>需处理</TableHead>
            <TableHead>最后同步</TableHead>
            <TableHead>操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isError && !sources ? (
            <TableRow>
              <TableCell colSpan={7} className="text-center">
                <LoadError error={error} onRetry={refetch} />
              </TableCell>
            </TableRow>
          ) : isLoading ? (
            <TableRow>
              <TableCell colSpan={7} className="text-center">加载中...</TableCell>
            </TableRow>
          ) : visibleSources.length === 0 ? (
            <TableRow>
              <TableCell colSpan={7} className="text-center text-muted-foreground">暂无数据源</TableCell>
            </TableRow>
          ) : (
            visibleSources.map((ds) => {
              const summary = summaryMap.get(ds.id);
              const health = healthMap.get(ds.id);
              const activeStatus = activeStatusMap.get(ds.id);
              const isActive = isBackendActive(activeStatus);
              const isExpanded = expandedIds.has(ds.id);
              const isTriggerPending = triggerSync.isPending && triggerSync.variables === ds.id;
              const state = operatorStateOfSource(ds);
              const attentionCount = summary?.attention_count ?? null;
              const rel = relativeTime(ds.last_sync);
              // 次级证据进徽章 title:历史可靠性窗口明细 + 最近同步错误明细
              const badgeTitleParts: string[] = [];
              if (health && health.health !== "disabled") {
                badgeTitleParts.push(
                  `近 ${health.window_days} 天 ${health.total_syncs} 次同步:${health.success_syncs} 次成功 / ${health.partial_syncs} 次补齐 / ${health.failed_syncs} 次失败(成功率按次数计,补齐不计入成功)`,
                );
              }
              if (ds.last_sync_error) badgeTitleParts.push(ds.last_sync_error);
              const badgeTitle =
                badgeTitleParts.length > 0 ? badgeTitleParts.join(" · ") : undefined;
              return (
                <Fragment key={ds.id}>
                  <TableRow>
                    <TableCell>
                      {/* A-P1-03:单行名称主行;来源地址收进 title(详情工作区列除外) */}
                      <button
                        type="button"
                        className="block max-w-[280px] truncate text-left leading-tight font-medium hover:underline"
                        title={sourceLocation(ds).text || ds.product}
                        onClick={() => navigate(`/data-sources/${ds.id}`)}
                      >
                        {ds.product}
                      </button>
                    </TableCell>
                    <TableCell className="text-sm">{sourceTypeLabel(ds.type)}</TableCell>
                    <TableCell>
                      <div className="flex flex-col items-start gap-1">
                        <Badge
                          variant={toneVariant(state.tone)}
                          title={badgeTitle}
                        >
                          {state.label}
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
                      {summary ? (
                        <span className="text-sm" title={`账本 ${summary.ledger_total} 篇 · 在服(含宽限)${summary.serving_count} 篇`}>
                          {summary.ledger_total.toLocaleString()}
                        </span>
                      ) : (
                        <span className="text-sm text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {attentionCount == null ? (
                        <span className="text-sm text-muted-foreground">—</span>
                      ) : attentionCount > 0 ? (
                        <span
                          className="font-semibold text-destructive"
                          title={`${attentionCount} 项知识需要处理`}
                        >
                          {attentionCount}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {rel ? (
                        <span className="text-sm" title={ds.last_sync ? formatSyncTime(ds.last_sync) : ""}>
                          {rel}
                        </span>
                      ) : (
                        <span className="text-xs text-muted-foreground">从未同步</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {/* A-P1-04:参考为单「⋯」;全部既有操作(详情/同步/编辑/可观测性/删除)收进菜单,零授权能力删除 */}
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button size="sm" variant="outline" aria-label="更多操作" className="h-7 px-2.5">
                            ⋯
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem onClick={() => navigate(`/data-sources/${ds.id}`)}>
                            详情
                          </DropdownMenuItem>
                          {canWrite && (
                            <DropdownMenuItem
                              disabled={
                                isActive ||
                                isTriggerPending ||
                                !ds.enabled ||
                                !isSyncEligible(ds) ||
                                triggerSync.isPending
                              }
                              title={isSyncEligible(ds) ? undefined : "该源处于删除流程,不能同步"}
                              onSelect={() => handleSync(ds)}
                            >
                              {isActive ? "同步中..." : isTriggerPending ? "触发中..." : "同步"}
                            </DropdownMenuItem>
                          )}
                          {canWrite && (
                            <DropdownMenuItem
                              disabled={isDeletionInFlight(ds)}
                              onSelect={() => openEdit(ds)}
                            >
                              编辑
                            </DropdownMenuItem>
                          )}
                          <DropdownMenuItem onClick={() => toggleObservability(ds.id)}>
                            {isExpanded ? "收起可观测性" : "查看可观测性"}
                          </DropdownMenuItem>
                          {canWrite && ds.lifecycle_state === "delete_failed" && (
                            <DropdownMenuItem
                              disabled={retryDeleteDs.isPending}
                              onSelect={() => handleRetryDelete(ds.id)}
                            >
                              重试删除
                            </DropdownMenuItem>
                          )}
                          {canWrite && (
                            <>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem
                                className="text-destructive focus:text-destructive"
                                disabled={deleteDs.isPending || isDeletionInFlight(ds)}
                                onSelect={() => handleDelete(ds.id)}
                              >
                                {isDeletionInFlight(ds) ? "删除中…" : "删除"}
                              </DropdownMenuItem>
                            </>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                  <SourceObservabilityDetails
                    source={ds}
                    syncHealth={syncHealthMap.get(ds.id)}
                    activeStatus={activeStatus}
                    expanded={isExpanded}
                  />
                </Fragment>
              );
            })
          )}
        </TableBody>
      </Table>
      <p className="text-xs text-muted-foreground" aria-label="数据源总数">
        共 {sources?.length ?? 0} 个数据源
      </p>

      {/* 编辑/新建:context-preserving 右侧抽屉(KB-OPS-V163-002 §4.5) */}
      <SourceEditorDrawer
        open={editorOpen}
        onOpenChange={setEditorOpen}
        editing={editingDs}
      />
    </div>
  );
}
