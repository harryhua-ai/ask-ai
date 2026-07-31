import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Lightbulb } from "lucide-react";
import {
  useConversations,
  useConversationDetail,
  useTagConversation,
  useBatchTag,
  type ConversationFilters,
} from "@/hooks/useConversations";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";

const INTENT_LABELS: Record<string, string> = {
  product_spec: "产品规格",
  tech_support: "技术支持",
  getting_started: "入门指南",
  pricing: "价格咨询",
  comparison: "产品对比",
  api_reference: "API 参考",
  documentation: "文档查询",
  other: "其他",
};

export default function Conversations() {
  const navigate = useNavigate();
  const [filters, setFilters] = useState<ConversationFilters & { page: number }>({ page: 1 });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { data, isLoading } = useConversations(filters);
  const { data: detail } = useConversationDetail(selectedId);
  const tagMutation = useTagConversation();
  const batchTag = useBatchTag();

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
            value={filters.channel || ""}
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
            value={filters.is_answered === undefined ? "" : String(filters.is_answered)}
            onChange={(e) =>
              setFilters({
                ...filters,
                is_answered:
                  e.target.value === "" ? undefined : e.target.value === "true",
                page: 1,
              })
            }
          >
            <option value="">全部状态</option>
            <option value="true">已回答</option>
            <option value="false">未回答</option>
          </select>
          <select
            className="h-9 rounded-md border px-3 text-sm"
            value={filters.feedback || ""}
            onChange={(e) =>
              setFilters({ ...filters, feedback: e.target.value || undefined, page: 1 })
            }
          >
            <option value="">全部反馈</option>
            <option value="up">赞</option>
            <option value="down">踩</option>
          </select>
        </div>

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>问题</TableHead>
              <TableHead>渠道</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>反馈</TableHead>
              <TableHead>Intent</TableHead>
              <TableHead>耗时</TableHead>
              <TableHead>时间</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center">
                  加载中...
                </TableCell>
              </TableRow>
            ) : (
              data?.items.map((conv) => (
                <TableRow
                  key={conv.id}
                  className={`cursor-pointer ${selectedId === conv.id ? "bg-muted/50" : ""}`}
                  onClick={() => setSelectedId(conv.id)}
                >
                  <TableCell className="max-w-xs truncate">{conv.question}</TableCell>
                  <TableCell>
                    <Badge variant="outline">{conv.channel}</Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={conv.is_answered ? "success" : "warning"}>
                      {conv.is_answered ? "已回答" : "拒答"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {conv.feedback === "up" && <span className="text-green-600">赞</span>}
                    {conv.feedback === "down" && <span className="text-red-600">踩</span>}
                    {!conv.feedback && "-"}
                  </TableCell>
                  <TableCell>
                    {conv.intent_tag ? (
                      <Badge variant="outline">
                        {INTENT_LABELS[conv.intent_tag] || conv.intent_tag}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground">-</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {conv.response_time_ms
                      ? `${(conv.response_time_ms / 1000).toFixed(1)}s`
                      : "-"}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {conv.created_at
                      ? new Date(conv.created_at).toLocaleString("zh-CN")
                      : "-"}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>

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
              disabled={filters.page * data.size >= data.total}
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
                navigate("/answer-overrides", {
                  state: {
                    prefill: {
                      match_pattern: detail.question,
                      override_answer: detail.answer || "",
                    },
                  },
                });
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
