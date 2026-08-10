import { useState, useEffect, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Lightbulb, ThumbsUp, ThumbsDown } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  useConversations,
  useConversationDetail,
  useTagConversation,
  useBatchTag,
  type ConversationFilters,
} from "@/hooks/useConversations";
import { fetchTraces, type TraceData } from "@/lib/api/traces";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const INTENT_LABELS: Record<string, string> = {
  commercial: "商务咨询",
  product: "产品咨询",
  support: "技术支持",
  off_topic: "无关闲聊",
};

const CONFIG_LABELS: Record<string, string> = {
  alpha: "混合权重",
  recall_limit: "召回上限",
  top_k: "精排保留",
  min_results: "最低阈值",
  has_pruner: "上下文裁剪",
};

function TraceStageCard({
  label,
  ms,
  total,
  children,
}: {
  label: string;
  ms: number;
  total: number;
  children?: ReactNode;
}) {
  const p = total > 0 ? Math.round((ms / total) * 100) : 0;
  const slow = p > 50;
  return (
    <div className="rounded-md border p-2.5" data-trace-stage={label}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[13px] font-medium">{label}</span>
        <span className={`text-xs tabular-nums ${slow ? "text-orange-500" : "text-muted-foreground"}`}>
          {ms.toLocaleString()}ms · {p}%
        </span>
      </div>
      <div className="h-1 rounded-full bg-muted overflow-hidden mb-1.5">
        <div
          className={`h-full rounded-full ${slow ? "bg-orange-500" : "bg-primary"}`}
          style={{ width: `${Math.max(p, 1)}%` }}
        />
      </div>
      {children && <div className="space-y-0.5">{children}</div>}
    </div>
  );
}

export default function Conversations() {
  const [searchParams] = useSearchParams();

  const [filters, setFilters] = useState<ConversationFilters & { page: number }>({
    page: 1,
    intent_tag: searchParams.get("intent") ?? undefined,
    channel: searchParams.get("channel") ?? undefined,
    feedback: searchParams.get("feedback") ?? undefined,
    is_answered:
      searchParams.get("answered") === null
        ? undefined
        : searchParams.get("answered") === "true",
    q: searchParams.get("q") ?? undefined,
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState(searchParams.get("q") ?? "");
  useEffect(() => {
    const t = setTimeout(() => {
      setFilters((f) =>
        f.q === (searchInput || undefined)
          ? f
          : { ...f, q: searchInput || undefined, page: 1 },
      );
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);
  const { data, isLoading } = useConversations(filters);
  const { data: detail } = useConversationDetail(selectedId);
  const tagMutation = useTagConversation();
  const batchTag = useBatchTag();

  // 获取选中对话的 trace 数据
  const { data: traces } = useQuery<TraceData[]>({
    queryKey: ["traces", selectedId],
    queryFn: () => fetchTraces(selectedId!),
    enabled: !!selectedId,
  });

  const [turnIndex, setTurnIndex] = useState(0);
  useEffect(() => {
    setTurnIndex(0);
  }, [selectedId]);
  const currentTrace =
    traces?.find((t) => t.turn_index === turnIndex) ?? traces?.[0];

  return (
    <div className="flex h-full gap-4 overflow-hidden">
      {/* 主列表 */}
      <div className="min-w-0 flex-[2] space-y-4 overflow-auto">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">对话审查</h1>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => batchTag.mutate()}
              disabled={batchTag.isPending}
            >
              {batchTag.isPending ? "标注中..." : "批量标注 Intent"}
            </Button>
            {batchTag.data && (
              <span className="text-sm text-muted-foreground">
                本次标注 {batchTag.data.tagged_count} 条
              </span>
            )}
          </div>
        </div>

        {/* 过滤栏 */}
        <div className="flex flex-wrap gap-3">
          <input
            type="text"
            placeholder="搜索问题/回答..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className="h-9 flex-1 min-w-[200px] rounded-md border px-3 text-sm"
          />
          <select
            className="h-9 rounded-md border px-3 text-sm"
            value={filters.channel ?? ""}
            onChange={(e) =>
              setFilters({ ...filters, channel: e.target.value || undefined, page: 1 })
            }
          >
            <option value="">全部渠道</option>
            <option value="widget">widget</option>
            <option value="discord">discord</option>
          </select>
          <select
            className="h-9 rounded-md border px-3 text-sm"
            value={filters.intent_tag ?? ""}
            onChange={(e) =>
              setFilters({ ...filters, intent_tag: e.target.value || undefined, page: 1 })
            }
          >
            <option value="">全部意图</option>
            <option value="commercial">商务咨询</option>
            <option value="product">产品咨询</option>
            <option value="support">技术支持</option>
            <option value="off_topic">无关闲聊</option>
          </select>
          <select
            className="h-9 rounded-md border px-3 text-sm"
            value={filters.is_answered === undefined ? "" : String(filters.is_answered)}
            onChange={(e) =>
              setFilters({
                ...filters,
                is_answered: e.target.value === "" ? undefined : e.target.value === "true",
                page: 1,
              })
            }
          >
            <option value="">全部状态</option>
            <option value="true">已回答</option>
            <option value="false">拒答</option>
          </select>
          <select
            className="h-9 rounded-md border px-3 text-sm"
            value={filters.feedback ?? ""}
            onChange={(e) =>
              setFilters({ ...filters, feedback: e.target.value || undefined, page: 1 })
            }
          >
            <option value="">全部反馈</option>
            <option value="up">赞</option>
            <option value="down">踩</option>
          </select>
        </div>

        <div className="space-y-2">
          {isLoading ? (
            <div className="text-center py-8 text-muted-foreground">加载中...</div>
          ) : (
            data?.items.map((conv) => {
              return (
                <div
                  key={conv.id}
                  data-row
                  className={`cursor-pointer rounded-lg border p-3 text-sm transition-colors hover:bg-muted/50 ${
                    selectedId === conv.id ? "bg-muted/50 ring-1 ring-primary" : ""
                  }`}
                  onClick={() => setSelectedId(conv.id)}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium truncate">
                          {conv.question}
                        </span>
                        {conv.intent_tag && (
                          <Badge variant="outline">
                            {INTENT_LABELS[conv.intent_tag] ?? conv.intent_tag}
                          </Badge>
                        )}
                      </div>
                    </div>
                    <div className="flex flex-col items-end gap-1 text-sm shrink-0">
                      <div className="flex items-center gap-1">
                        <Badge variant={conv.is_answered ? "success" : "warning"}>
                          {conv.is_answered ? "已回答" : "拒答"}
                        </Badge>
                        {conv.feedback === "up" && (
                          <ThumbsUp
                            className="h-3.5 w-3.5 text-[var(--ok)]"
                            data-feedback="up"
                          />
                        )}
                        {conv.feedback === "down" && (
                          <ThumbsDown
                            className="h-3.5 w-3.5 text-[var(--err)]"
                            data-feedback="down"
                          />
                        )}
                      </div>
                      {conv.response_time_ms && (
                        <span className="text-muted-foreground">
                          {conv.response_time_ms.toLocaleString()}ms
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {data && (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={filters.page <= 1}
              onClick={() => setFilters({ ...filters, page: filters.page - 1 })}
            >
              上一页
            </Button>
            <span className="text-sm">
              第 {filters.page} 页（共 {Math.ceil(data.total / data.size)} 页，{data.total} 条）
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={filters.page * 20 >= data.total}
              onClick={() => setFilters({ ...filters, page: filters.page + 1 })}
            >
              下一页
            </Button>
          </div>
        )}
      </div>

      {/* 详情侧栏 */}
      {selectedId && detail && (
        <div className="min-w-0 flex-1 space-y-3 overflow-auto rounded-lg border bg-card p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">对话详情</h2>
            <Button variant="ghost" size="sm" onClick={() => setSelectedId(null)}>
              关闭
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant={detail.is_answered ? "success" : "warning"}>
              {detail.is_answered ? "已回答" : "拒答"}
            </Badge>
            {detail.intent_tag && (
              <Badge variant="outline">
                {INTENT_LABELS[detail.intent_tag] ?? detail.intent_tag}
              </Badge>
            )}
            {detail.feedback === "up" && (
              <span className="flex items-center gap-0.5 text-[var(--ok)]">
                <ThumbsUp className="h-3 w-3" /> 赞
              </span>
            )}
            {detail.feedback === "down" && (
              <span className="flex items-center gap-0.5 text-[var(--err)]">
                <ThumbsDown className="h-3 w-3" /> 踩
              </span>
            )}
            {detail.channel && <span>渠道 {detail.channel}</span>}
            {detail.language && <span>{detail.language.toUpperCase()}</span>}
            <span>{new Date(detail.created_at).toLocaleString("zh-CN")}</span>
            {detail.response_time_ms != null && (
              <span>{detail.response_time_ms.toLocaleString()}ms</span>
            )}
          </div>
          <div>
            <h3 className="text-sm font-medium text-muted-foreground">问题</h3>
            <p className="mt-1 text-sm">{detail.question}</p>
          </div>
          <div>
            <h3 className="text-sm font-medium text-muted-foreground">回答</h3>
            <div className="mt-1 text-sm [&_p]:my-1 [&_ul]:my-1 [&_ol]:my-1 [&_li]:my-0.5 [&_pre]:my-2 [&_pre]:overflow-x-auto [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-xs [&_h1]:text-base [&_h2]:text-base [&_h3]:text-sm [&_strong]:font-semibold [&_a]:text-blue-600 [&_a]:hover:underline [&_table]:w-full [&_th]:border [&_td]:border [&_th]:px-2 [&_td]:px-2 [&_th]:py-1 [&_td]:py-1 [&_blockquote]:border-l-2 [&_blockquote]:pl-2 [&_blockquote]:text-muted-foreground">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {detail.answer || "(无回答)"}
              </ReactMarkdown>
            </div>
          </div>

          {/* trace 全链路 */}
          {currentTrace && (() => {
            const st = currentTrace.stages;
            const total = currentTrace.total_ms ?? 0;
            const intentSt = st["intent"];
            const rewriteSt = st["rewrite"];
            const retrieveSt = st["retrieve"];
            const rerankSt = st["rerank"];
            const genSt = st["generate"];
            const outSt = st["output"];
            const cfg = currentTrace.config_snapshot;

            return (
              <div className="space-y-2" data-trace-meta>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline">
                    {currentTrace.type === "rag"
                      ? "RAG 生成"
                      : currentTrace.type === "clarify"
                        ? "澄清追问"
                        : currentTrace.type === "override"
                          ? "人工覆盖"
                          : "短路拒答"}
                  </Badge>
                  {currentTrace.intent && (
                    <Badge variant="outline">
                      {INTENT_LABELS[currentTrace.intent] ?? currentTrace.intent}
                    </Badge>
                  )}
                  {currentTrace.confidence != null && (
                    <span className="text-xs text-muted-foreground">
                      置信 {(currentTrace.confidence * 100).toFixed(0)}%
                    </span>
                  )}
                  <span className="text-xs text-muted-foreground ml-auto">
                    总耗时 {total.toLocaleString()}ms
                  </span>
                </div>

                {traces && traces.length > 1 && (
                  <div className="flex gap-1" data-turn-selector>
                    {traces.map((t) => (
                      <button
                        key={t.id}
                        onClick={() => setTurnIndex(t.turn_index)}
                        className={
                          "h-6 rounded px-2 text-xs border " +
                          (turnIndex === t.turn_index
                            ? "bg-primary text-primary-foreground"
                            : "bg-card")
                        }
                      >
                        轮 {t.turn_index + 1}
                      </button>
                    ))}
                  </div>
                )}

                <TraceStageCard label="意图分类" ms={intentSt?.ms ?? 0} total={total}>
                  {intentSt?.category && (
                    <div className="text-[12px] text-muted-foreground">分类 {intentSt.category}</div>
                  )}
                  {intentSt?.reason && (
                    <div className="text-[12px] text-muted-foreground">{intentSt.reason}</div>
                  )}
                  <div className="text-[12px] text-muted-foreground">
                    置信度 {currentTrace.confidence != null
                      ? `${(currentTrace.confidence * 100).toFixed(0)}%`
                      : "—"}
                  </div>
                </TraceStageCard>

                <TraceStageCard label="查询改写" ms={rewriteSt?.ms ?? 0} total={total}>
                  <div className="space-y-0.5 text-[12px] text-muted-foreground">
                    <div><span className="text-muted-foreground/60">原文</span> {detail.question}</div>
                    {rewriteSt?.extracted && (
                      <div><span className="text-muted-foreground/60">提取</span> {rewriteSt.extracted}</div>
                    )}
                    {rewriteSt?.rewritten && (
                      <div><span className="text-muted-foreground/60">改写</span> {rewriteSt.rewritten}</div>
                    )}
                  </div>
                </TraceStageCard>

                <TraceStageCard label="路由检索" ms={retrieveSt?.ms ?? 0} total={total}>
                  {retrieveSt?.hybrid_count !== undefined && (
                    <div className="text-[12px] text-muted-foreground">
                      三路 RRF 融合召回 {retrieveSt.hybrid_count} 条
                      {retrieveSt.effective_min !== undefined && (
                        <span className="text-muted-foreground/60"> (阈值 {retrieveSt.effective_min})</span>
                      )}
                    </div>
                  )}
                  {retrieveSt?.path_counts && (
                    <div className="text-[12px] text-muted-foreground/70">
                      hybrid {retrieveSt.path_counts.hybrid} · symbol {retrieveSt.path_counts.symbol} · boost {retrieveSt.path_counts.boost}
                    </div>
                  )}
                  {retrieveSt?.min_results_met === true && (
                    <div className="text-[12px] text-muted-foreground">已满足最低阈值</div>
                  )}
                  {retrieveSt?.min_results_met === false && (
                    <div className="text-[12px] text-orange-500">⚠ 未达最低阈值</div>
                  )}
                </TraceStageCard>

                <TraceStageCard label="精排重排" ms={rerankSt?.ms ?? 0} total={total}>
                  {rerankSt?.top_score != null && (
                    <div className="text-[12px] text-muted-foreground">top分 {rerankSt.top_score.toFixed(3)}</div>
                  )}
                  {rerankSt?.count !== undefined && (
                    <div className="text-[12px] text-muted-foreground">
                      rerank {rerankSt.count} 条
                      {rerankSt.pruned != null && rerankSt.pruned > 0 && (
                        <span className="text-orange-500"> (裁剪 {rerankSt.pruned})</span>
                      )}
                    </div>
                  )}
                  {rerankSt?.results && rerankSt.results.length > 0 && (
                    <div className="mt-1 space-y-1">
                      {rerankSt.results.map((r, i) => (
                        <details key={i} className="group rounded border border-border/50 p-1">
                          <summary className="flex cursor-pointer items-center gap-1.5 text-[11px]">
                            <span className="text-muted-foreground/50 shrink-0">{i + 1}</span>
                            <Badge variant="outline" className="shrink-0 text-[9px] px-1 py-0">
                              {r.source_type}
                            </Badge>
                            {r.score != null && (
                              <span className="shrink-0 text-muted-foreground tabular-nums">{r.score.toFixed(3)}</span>
                            )}
                            <span className="text-muted-foreground truncate">{r.title}</span>
                          </summary>
                          {r.text && (
                            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground/80 whitespace-pre-wrap">
                              {r.text}
                            </p>
                          )}
                        </details>
                      ))}
                    </div>
                  )}
                </TraceStageCard>

                <TraceStageCard label="LLM 生成" ms={genSt?.ms ?? 0} total={total}>
                  {genSt?.ttft_ms != null && (
                    <div className="text-[12px] text-muted-foreground">TTFT {genSt.ttft_ms.toLocaleString()}ms</div>
                  )}
                  {genSt?.latency_ms != null && (
                    <div className="text-[12px] text-muted-foreground">LLM 延迟 {genSt.latency_ms.toLocaleString()}ms</div>
                  )}
                  {genSt?.tokens_output != null && (
                    <div className="text-[12px] text-muted-foreground">输出 {genSt.tokens_output} token</div>
                  )}
                </TraceStageCard>

                <TraceStageCard label="输出构建" ms={outSt?.ms ?? 0} total={total}>
                  {outSt?.sources_count !== undefined && (
                    <div className="text-[12px] text-muted-foreground">来源 {outSt.sources_count} 条</div>
                  )}
                </TraceStageCard>

                {cfg && Object.keys(cfg).length > 0 && (
                  <div className="flex flex-wrap gap-x-3 gap-y-0.5 rounded-md bg-muted/50 p-2 text-[11px] text-muted-foreground">
                    {Object.entries(cfg).map(([k, v]) => (
                      <span key={k}>
                        {CONFIG_LABELS[k] ?? k}{" "}
                        <span className="font-medium text-foreground">{String(v)}</span>
                      </span>
                    ))}
                  </div>
                )}

                {currentTrace.attachments && currentTrace.attachments.length > 0 && (
                  <div className="rounded-md border p-2 space-y-1">
                    <div className="text-[11px] font-medium text-muted-foreground">附件 ({currentTrace.attachments.length})</div>
                    {currentTrace.attachments.map((att, i) => (
                      <details key={i} className="rounded border border-border/50 p-1">
                        <summary className="flex cursor-pointer items-center gap-1.5 text-[11px]">
                          <Badge variant="outline" className="shrink-0 text-[9px] px-1 py-0">
                            {att.kind}
                          </Badge>
                          <span className="text-muted-foreground">{att.text_length} 字</span>
                        </summary>
                        {att.text_preview && (
                          <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground/80 whitespace-pre-wrap">
                            {att.text_preview}
                          </p>
                        )}
                      </details>
                    ))}
                  </div>
                )}
              </div>
            );
          })()}

          {/* 引用来源 */}
          {detail.sources && detail.sources.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground">
                引用来源 ({detail.sources.length})
              </h3>
              <ol className="mt-1 space-y-1">
                {(detail.sources as Array<{ url?: string; title?: string; type?: string }>).map(
                  (src, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs">
                      <span className="text-muted-foreground shrink-0">[{i + 1}]</span>
                      <Badge variant="outline" className="shrink-0 text-[10px]">
                        {src.type ?? "unknown"}
                      </Badge>
                      {src.url ? (
                        <a
                          href={src.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-600 hover:underline truncate"
                        >
                          {src.title || src.url}
                        </a>
                      ) : (
                        <span className="truncate">{src.title || "(无标题)"}</span>
                      )}
                    </li>
                  ),
                )}
              </ol>
            </div>
          )}

          {/* commercial 对话显示联系销售提示 */}
          {detail.intent_tag === "commercial" && (
            <div className="rounded-md bg-[var(--acc-t)] border border-[var(--acc)]/20 px-3 py-2 text-[13px] text-[var(--acc)]">
              商务咨询对话，请联系销售团队跟进
            </div>
          )}

          {detail.clicks && detail.clicks.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground">
                来源点击 ({detail.clicks.length})
              </h3>
              <ul className="mt-1 space-y-1">
                {detail.clicks.map((c, i) => (
                  <li key={i} className="text-xs">
                    <Badge variant="outline">{c.type}</Badge>{" "}
                    <a
                      href={c.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:underline"
                    >
                      {c.url}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex items-center gap-2 pt-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => tagMutation.mutate(selectedId)}
              disabled={tagMutation.isPending}
            >
              {tagMutation.isPending ? "标注中..." : "标注 Intent"}
            </Button>
            {tagMutation.data && (
              <Badge variant="success">
                {INTENT_LABELS[tagMutation.data.intent_tag] || tagMutation.data.intent_tag}
              </Badge>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                window.history.pushState(
                  {},
                  "",
                  "/answer-overrides",
                );
              }}
            >
              <Lightbulb className="h-4 w-4" />
              改进此答案
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
