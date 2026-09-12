import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
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
import { SyncHistoryPanel } from "@/components/dataSources/SyncHistoryPanel";
import { SyncStatusPanel } from "@/components/dataSources/SyncStatusPanel";
import {
  useDataSources,
  useSyncHealth,
  useSyncRuns,
  useSyncStatus,
  useTriggerSync,
} from "@/hooks/useDataSources";
import {
  useSourceDocuments,
  useSourceDocumentTruth,
  useSourceGenerations,
} from "@/hooks/useDataSourceWorkspace";
import {
  bucketCountsOf,
  bucketLabel,
  bucketOfDocument,
  bucketVariant,
  generationStatusLabel,
  generationStatusVariant,
  lifecycleLabel,
  lifecycleVariant,
  notServingReason,
} from "@/lib/dataSourceLifecycle";
import { sourceLocation, TYPE_LABELS } from "@/pages/DataSources";
import type { GenerationTruth } from "@/types/dataSourceWorkspace";
import type { SyncStatusItem } from "@/types/api";

// #50 B1 详情工作面(路由 /data-sources/:sourceId = 对 #51 的冻结接口)。
// 信息层级:身份/配置摘要 → 同步与健康(复用既有三面板)→ 内容清单
// (搜索/过滤/分页)→ 生成可见性 → 最近变化(同步历史)。
// 全部真相来自权威账本读面;Weaviate 永不是 UI 真相源;零破坏性控件。

const ACTIVE_SYNC_STATES = new Set(["QUEUED", "WAITING", "RUNNING", "RECOVERING"]);

const LIFECYCLE_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "全部生命周期" },
  { value: "active", label: "在服 (active)" },
  { value: "missing_candidate", label: "源中缺失 (missing_candidate)" },
  { value: "superseded", label: "已被接替 (superseded)" },
  { value: "deleted", label: "已删除 (deleted)" },
  { value: "discovered", label: "已发现 (discovered)" },
];

function formatTs(value: string | null | undefined): string {
  return value ?? "—";
}

function Iso({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-muted-foreground">—</span>;
  return <span className="font-mono text-xs">{value}</span>;
}

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

function GenerationBadges({ gen, servingOrdinals }: { gen: GenerationTruth; servingOrdinals: number[] }) {
  return (
    <div className="flex items-center gap-1">
      <Badge variant={generationStatusVariant(gen.status)}>{generationStatusLabel(gen.status)}</Badge>
      {servingOrdinals.includes(gen.ordinal) && (
        <Badge variant="success" title="该代含当前在服文档(active_generation 权威口径)">
          在服代
        </Badge>
      )}
    </div>
  );
}

export default function DataSourceDetail() {
  const { sourceId = "" } = useParams();
  const navigate = useNavigate();

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

  // 同步与健康(复用既有读面与三面板)
  const { data: syncStatus } = useSyncStatus({ refetchInterval: 5000 });
  const activeStatus: SyncStatusItem | undefined = useMemo(
    () =>
      syncStatus?.items.find(
        (i) => i.source_id === sourceId && ACTIVE_SYNC_STATES.has(i.state),
      ),
    [syncStatus, sourceId],
  );
  const { data: syncHealth } = useSyncHealth();
  const healthItem = useMemo(
    () => syncHealth?.items.find((i) => i.source_id === sourceId),
    [syncHealth, sourceId],
  );
  const runsQuery = useSyncRuns(sourceId);
  const runsError =
    runsQuery.error instanceof Error
      ? runsQuery.error.message
      : runsQuery.error
        ? "同步历史加载失败"
        : null;

  // 内容清单(新只读端点):搜索/生命周期过滤/分页
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [lifecycle, setLifecycle] = useState("");
  const [page, setPage] = useState(1);
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
  }, [lifecycle]);

  const documentsQuery = useSourceDocuments(sourceId, {
    lifecycle: lifecycle || undefined,
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

  // 单文档真相(行展开)
  const [truthDocId, setTruthDocId] = useState<string | null>(null);
  const truthQuery = useSourceDocumentTruth(sourceId, truthDocId);

  // 生成可见性
  const generationsQuery = useSourceGenerations(sourceId);
  const generations = generationsQuery.data;

  const triggerSync = useTriggerSync();
  const runsHasMore =
    runsQuery.data != null && runsQuery.data.items.length < runsQuery.data.total;

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

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Button variant="outline" size="sm" onClick={() => navigate("/data-sources")}>
          ← 返回数据源列表
        </Button>
        <h1 className="text-2xl font-bold" data-testid="detail-title">
          {source ? source.product : sourcesLoading ? "加载中..." : sourceId}
        </h1>
      </div>

      {/* 身份/配置摘要 */}
      {sourcesLoading ? (
        <Card>
          <CardContent className="p-4 text-sm text-muted-foreground">加载中...</CardContent>
        </Card>
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
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0 p-4">
            <CardTitle className="text-base">源身份与配置</CardTitle>
            <Badge variant={source.enabled ? "success" : "destructive"}>
              {source.enabled ? "启用" : "禁用"}
            </Badge>
          </CardHeader>
          <CardContent className="grid gap-x-6 gap-y-2 p-4 pt-0 text-sm sm:grid-cols-2">
            <div>
              <span className="text-muted-foreground">数据源 ID:</span>{" "}
              <span className="font-mono">{source.id}</span>
            </div>
            <div>
              <span className="text-muted-foreground">类型:</span>{" "}
              {TYPE_LABELS[source.type] ?? source.type}
            </div>
            <div>
              <span className="text-muted-foreground">产品线:</span> {source.product}
            </div>
            <div>
              <span className="text-muted-foreground">同步间隔:</span> {source.sync_interval}
            </div>
            <div className="sm:col-span-2">
              <span className="text-muted-foreground">来源地址:</span>{" "}
              {sourceLocation(source).href ? (
                <a
                  className="underline underline-offset-2"
                  href={sourceLocation(source).href ?? "#"}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {sourceLocation(source).text}
                </a>
              ) : (
                <span className="font-mono text-xs">{sourceLocation(source).text || "—"}</span>
              )}
            </div>
            {source.lifecycle_state && (
              <div className="sm:col-span-2">
                <Badge
                  variant={source.lifecycle_state === "delete_failed" ? "destructive" : "warning"}
                  title={source.lifecycle_error ?? undefined}
                >
                  删除生命周期:{source.lifecycle_state}
                </Badge>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* 同步与健康(复用既有三面板) */}
      {source && (
        <div className="space-y-3">
          {activeStatus && (
            <SyncStatusPanel
              status={activeStatus}
              onRetry={() => triggerSync.mutate(sourceId)}
            />
          )}
          <SourceHealthPanel health={healthItem} />
        </div>
      )}

      {/* 内容清单(账本) */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0 p-4">
          <CardTitle className="text-base">内容清单(权威账本)</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 p-4 pt-0">
          {bucketCounts && (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                {(["current", "attention", "retired"] as const).map((b) => (
                  <Badge key={b} variant={bucketVariant(b)}>
                    {bucketLabel(b)} {bucketCounts[b]}
                  </Badge>
                ))}
                <span className="text-sm text-muted-foreground">
                  账本文档 {docs?.ledger_total ?? 0} 篇 · 在服(含宽限){docs?.serving_count ?? 0} 篇
                </span>
              </div>
              <p className="text-xs text-muted-foreground">
                计数真相:账本(ledger)与在服计数来自 documents 现行版本关系;已索引(向量库)计数不由账本直接证明——
                实际索引规模以最近同步一致性证据(上方健康面板)与在服代计数为准。
              </p>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Input
              aria-label="搜索标题或 URL"
              placeholder="搜索标题或 URL 子串"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className="max-w-xs"
            />
            <select
              aria-label="按生命周期过滤"
              className="h-10 rounded-md border px-3 text-sm"
              value={lifecycle}
              onChange={(e) => setLifecycle(e.target.value)}
            >
              {LIFECYCLE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>

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
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>标题</TableHead>
                    <TableHead>生命周期</TableHead>
                    <TableHead>在服</TableHead>
                    <TableHead>分块</TableHead>
                    <TableHead>更新时间</TableHead>
                    <TableHead>真相</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {docs?.items.map((row) => {
                    const bucket = bucketOfDocument(row);
                    const reason = notServingReason(row);
                    const expanded = truthDocId === row.source_id && truthQuery.data?.doc_source_id === row.source_id;
                    return (
                      <TableRow key={row.source_id} className="align-top">
                        <TableCell>
                          <div className="max-w-[260px] truncate" title={row.title}>
                            {row.title}
                          </div>
                          <div
                            className="max-w-[260px] truncate font-mono text-xs text-muted-foreground"
                            title={row.source_id}
                          >
                            {row.source_id}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant={lifecycleVariant(row.lifecycle)}>
                            {lifecycleLabel(row.lifecycle)}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant={row.serving ? "success" : "outline"}>
                            {row.serving ? "在服" : "不在服"}
                          </Badge>
                          {bucket === "attention" && reason && (
                            <div
                              className="mt-1 max-w-[220px] truncate text-xs text-amber-600"
                              title={reason}
                            >
                              {reason}
                            </div>
                          )}
                        </TableCell>
                        <TableCell>{row.chunk_count}</TableCell>
                        <TableCell>
                          <Iso value={row.updated_at} />
                        </TableCell>
                        <TableCell>
                          <Button
                            size="sm"
                            variant="outline"
                            aria-label={`查看真相 ${row.source_id}`}
                            onClick={() =>
                              setTruthDocId((cur) => (cur === row.source_id ? null : row.source_id))
                            }
                          >
                            {expanded ? "收起真相" : "查看真相"}
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                  {truthDocId && (
                    <TableRow>
                      <TableCell colSpan={6} className="bg-muted/20">
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
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="font-medium">单条真相</span>
                                <Badge
                                  variant={bucketVariant(bucketOfDocument(truthQuery.data))}
                                >
                                  {bucketLabel(bucketOfDocument(truthQuery.data))}
                                </Badge>
                                <Badge
                                  variant={lifecycleVariant(truthQuery.data.lifecycle)}
                                >
                                  {lifecycleLabel(truthQuery.data.lifecycle)}
                                </Badge>
                              </div>
                              {notServingReason(truthQuery.data) && (
                                <p className="text-sm text-amber-600">
                                  原因:{notServingReason(truthQuery.data)}
                                </p>
                              )}
                              <p className="font-mono break-all text-xs">
                                canonical:{truthQuery.data.doc_source_id}
                              </p>
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
                              <div className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
                                <p>
                                  {truthQuery.data.current_version ? (
                                    <>
                                      现行版本 #{truthQuery.data.current_version.version_seq}
                                      ({truthQuery.data.current_version.status}) · 持久 chunk{" "}
                                      {truthQuery.data.current_version.chunks_total} · 生效自{" "}
                                      {formatTs(truthQuery.data.current_version.valid_from)}
                                    </>
                                  ) : (
                                    <span className="text-amber-600">
                                      现行版本:后端无此记录
                                    </span>
                                  )}
                                </p>
                                <p>
                                  {truthQuery.data.generation ? (
                                    <>
                                      生成 #{truthQuery.data.generation.ordinal}(
                                      {generationStatusLabel(truthQuery.data.generation.status)})
                                      · 文档 {truthQuery.data.generation.doc_count} · chunk{" "}
                                      {truthQuery.data.generation.chunk_count} · 激活{" "}
                                      {formatTs(truthQuery.data.generation.activated_at)}
                                      {truthQuery.data.generation.retired_at
                                        ? ` · 退役 ${truthQuery.data.generation.retired_at}`
                                        : ""}
                                    </>
                                  ) : (
                                    <span className="text-amber-600">生成记录:后端无此记录</span>
                                  )}
                                </p>
                                <p>
                                  创建:<Iso value={truthQuery.data.created_at} /> 更新:
                                  <Iso value={truthQuery.data.updated_at} />
                                </p>
                                {truthQuery.data.superseded_at && (
                                  <p>
                                    接替时间:<Iso value={truthQuery.data.superseded_at} />
                                  </p>
                                )}
                              </div>
                            </>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
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

      {/* 生成可见性 */}
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
                      <GenerationBadges gen={g} servingOrdinals={generations.serving_ordinals} />
                    </TableCell>
                    <TableCell>{g.doc_count}</TableCell>
                    <TableCell>{g.chunk_count}</TableCell>
                    <TableCell>
                      <div className="space-y-0.5 text-xs">
                        <div>创建 <Iso value={g.created_at} /></div>
                        <div>就绪 <Iso value={g.ready_at} /></div>
                        <div>激活 <Iso value={g.activated_at} /></div>
                        <div>退役 <Iso value={g.retired_at} /></div>
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

      {/* 最近变化(同步历史) */}
      {source && (
        <div aria-label="最近同步">
          <h3 className="mb-2 text-base font-semibold">最近变化(同步历史)</h3>
          <SyncHistoryPanel
            runs={runsQuery.data}
            isLoading={runsQuery.isLoading}
            error={runsError}
            onRetry={() => runsQuery.refetch()}
          />
          {runsHasMore && (
            <p className="mt-2 text-xs text-muted-foreground">
              仅显示最近 {runsQuery.data?.items.length} 次运行(共 {runsQuery.data?.total} 次)
            </p>
          )}
        </div>
      )}
    </div>
  );
}
