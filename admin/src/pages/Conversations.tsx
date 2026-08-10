import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Lightbulb } from "lucide-react";
import {
  useConversations,
  useConversationDetail,
  useTagConversation,
  useBatchTag,
  type ConversationFilters,
} from "@/hooks/useConversations";
import { fetchTraces } from "@/lib/api/traces";
import type { TraceData } from "@/lib/api/traces";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import StageBar from "@/components/observability/StageBar";
import TraceLanes from "@/components/observability/TraceLanes";

const INTENT_LABELS: Record<string, string> = {
  commercial: "商务咨询",
  product: "产品咨询",
  support: "技术支持",
  off_topic: "无关闲聊",
};

// 阶段耗时基线(ms),超过标橙
const STAGE_NORMAL_MAX: Record<string, number> = {
  intent: 500,
  rewrite: 2000,
  retrieve: 3000,
  rerank: 2000,
  generate: 10000,
  output: 100,
};

// 将 trace stages 转为 StageBar 数据
function traceToStages(stages: Record<string, { ms: number; detail?: string }>) {
  const keys = ["intent", "rewrite", "retrieve", "rerank", "generate"];
  return keys
    .filter((k) => stages[k])
    .map((k) => ({
      key: k,
      ms: stages[k].ms,
      over: stages[k].ms > (STAGE_NORMAL_MAX[k] ?? Infinity),
    }));
}

// 将 trace stages 转为 TraceLanes 数据(5 泳道)
function traceToLanes(stages: Record<string, { ms: number; detail?: string }>) {
  const result: Record<string, { ms: number; status: "ok" | "warn" | "err"; detail?: string }> = {};
  // 前置 = intent + rewrite 合并
  const intentMs = stages["intent"]?.ms ?? 0;
  const rewriteMs = stages["rewrite"]?.ms ?? 0;
  result["intent+rewrite"] = {
    ms: intentMs + rewriteMs,
    status: intentMs + rewriteMs > (STAGE_NORMAL_MAX["rewrite"] ?? Infinity) ? "warn" : "ok",
  };
  // 路由 = retrieve
  const retrieveMs = stages["retrieve"]?.ms ?? 0;
  result["retrieve"] = {
    ms: retrieveMs,
    status: retrieveMs > (STAGE_NORMAL_MAX["retrieve"] ?? Infinity) ? "warn" : "ok",
  };
  // 检索 = rerank
  const rerankMs = stages["rerank"]?.ms ?? 0;
  result["rerank"] = {
    ms: rerankMs,
    status: rerankMs > (STAGE_NORMAL_MAX["rerank"] ?? Infinity) ? "warn" : "ok",
  };
  // 生成 = generate
  const generateMs = stages["generate"]?.ms ?? 0;
  result["generate"] = {
    ms: generateMs,
    status: generateMs > (STAGE_NORMAL_MAX["generate"] ?? Infinity) ? "warn" : "ok",
  };
  // 输出 = output
  const outputMs = stages["output"]?.ms ?? 0;
  result["output"] = {
    ms: outputMs,
    status: "ok",
  };
  return result;
}

export default function Conversations() {
  const [searchParams] = useSearchParams();
  const intentFilter = searchParams.get("intent") ?? undefined;

  const [filters, setFilters] = useState<ConversationFilters & { page: number }>({
    page: 1,
    intent_tag: intentFilter,
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
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

  const currentTrace = traces?.[0];

  return (
    <div className="flex h-full gap-4">
      {/* 主列表 */}
      <div className="flex-1 space-y-4">
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
              // 从 trace_summary 提取阶段条数据
              const traceStages = (conv as ConversationWithTrace).trace_summary?.stages;
              return (
                <div
                  key={conv.id}
                  data-row
                  className={`cursor-pointer rounded-lg border p-3 transition-colors hover:bg-muted/50 ${
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
                      {traceStages && (
                        <div className="mt-2" data-bar-seg>
                          <StageBar stages={traceToStages(traceStages)} />
                        </div>
                      )}
                    </div>
                    <div className="flex flex-col items-end gap-1 text-sm shrink-0">
                      <Badge variant={conv.is_answered ? "success" : "warning"}>
                        {conv.is_answered ? "已回答" : "拒答"}
                      </Badge>
                      {conv.response_time_ms && (
                        <span className="text-muted-foreground">
                          {conv.response_time_ms.toLocaleString()}ms
                        </span>
                      )}
                      <span className="text-xs text-muted-foreground">
                        {conv.created_at
                          ? new Date(conv.created_at).toLocaleString("zh-CN")
                          : ""}
                      </span>
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
        <div className="w-96 space-y-3 overflow-auto rounded-lg border bg-card p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">对话详情</h2>
            <Button variant="ghost" size="sm" onClick={() => setSelectedId(null)}>
              关闭
            </Button>
          </div>
          <div>
            <h3 className="text-sm font-medium text-muted-foreground">问题</h3>
            <p className="mt-1 text-sm">{detail.question}</p>
          </div>
          <div>
            <h3 className="text-sm font-medium text-muted-foreground">回答</h3>
            <p className="mt-1 whitespace-pre-wrap text-sm">
              {detail.answer || "(无回答)"}
            </p>
          </div>

          {/* trace 5 泳道 */}
          {currentTrace && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                执行 Trace（{currentTrace.total_ms?.toLocaleString() ?? "-"}ms）
              </h3>
              <TraceLanes stages={traceToLanes(currentTrace.stages)} />
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

// 扩展类型:对话可能带 trace_summary(后端 Task 9 补充)
interface ConversationWithTrace {
  trace_summary?: {
    stages: Record<string, { ms: number }>;
  };
}
