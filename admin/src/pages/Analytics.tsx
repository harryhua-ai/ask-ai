import { useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { RefreshCw, CheckCircle, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useCoverageGaps, useRefreshGaps, useResolveGap } from "@/hooks/useAnalytics";
import { useTopQuestions, useRefreshTopQuestions } from "@/hooks/useAnalytics";
import { useSourceAnalytics } from "@/hooks/useAnalytics";

type Tab = "gaps" | "top" | "sources";

export default function Analytics() {
  const [tab, setTab] = useState<Tab>("gaps");

  return (
    <div className="space-y-6">
      <div className="flex gap-2">
        {(["gaps", "top", "sources"] as Tab[]).map((t) => (
          <Button
            key={t}
            variant={tab === t ? "default" : "outline"}
            onClick={() => setTab(t)}
          >
            {t === "gaps" ? "Coverage Gaps" : t === "top" ? "Top Questions" : "Source Analytics"}
          </Button>
        ))}
      </div>

      {tab === "gaps" && <CoverageGapsTab />}
      {tab === "top" && <TopQuestionsTab />}
      {tab === "sources" && <SourceAnalyticsTab />}
    </div>
  );
}

function CoverageGapsTab() {
  const [status, setStatus] = useState<string | undefined>();
  const { data, isLoading } = useCoverageGaps(status);
  const refresh = useRefreshGaps();
  const resolve = useResolveGap();

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Select value={status || "all"} onValueChange={(v) => setStatus(v === "all" ? undefined : v)}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部</SelectItem>
            <SelectItem value="open">未解决</SelectItem>
            <SelectItem value="resolved">已解决</SelectItem>
          </SelectContent>
        </Select>
        <Button onClick={() => refresh.mutate()} disabled={refresh.isPending}>
          <RefreshCw className="mr-2 h-4 w-4" />
          刷新聚类
        </Button>
        {refresh.data && (
          <span className="text-sm text-muted-foreground">
            {refresh.data.cluster_count} 个聚类,{refresh.data.total_questions} 个问题
          </span>
        )}
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>代表问题</TableHead>
            <TableHead>数量</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data?.items.map((cluster) => (
            <TableRow key={cluster.id}>
              <TableCell>
                <div className="font-medium">{cluster.representative_question}</div>
                {cluster.sample_questions.length > 1 && (
                  <details className="mt-1">
                    <summary className="text-xs text-muted-foreground cursor-pointer">
                      查看 {cluster.sample_questions.length} 个示例
                    </summary>
                    <ul className="mt-1 space-y-1">
                      {cluster.sample_questions.slice(1).map((q, i) => (
                        <li key={i} className="text-xs text-muted-foreground">• {q}</li>
                      ))}
                    </ul>
                  </details>
                )}
              </TableCell>
              <TableCell>{cluster.question_count}</TableCell>
              <TableCell>
                <Badge variant={cluster.status === "resolved" ? "default" : "secondary"}>
                  {cluster.status === "resolved" ? "已解决" : "未解决"}
                </Badge>
              </TableCell>
              <TableCell>
                {cluster.status === "open" ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => resolve.mutate({ id: cluster.id, status: "resolved" })}
                  >
                    <CheckCircle className="mr-1 h-3 w-3" />
                    标记解决
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => resolve.mutate({ id: cluster.id, status: "open" })}
                  >
                    <RotateCcw className="mr-1 h-3 w-3" />
                    重新打开
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {data?.items.length === 0 && (
        <div className="text-center text-muted-foreground py-8">
          {isLoading ? "加载中..." : "暂无数据,点击\"刷新聚类\"生成"}
        </div>
      )}
    </div>
  );
}

function TopQuestionsTab() {
  const { data, isLoading } = useTopQuestions();
  const refresh = useRefreshTopQuestions();

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Button onClick={() => refresh.mutate()} disabled={refresh.isPending}>
          <RefreshCw className="mr-2 h-4 w-4" />
          刷新聚类
        </Button>
        {refresh.data && (
          <span className="text-sm text-muted-foreground">
            {refresh.data.cluster_count} 个聚类,{refresh.data.total_questions} 个问题
          </span>
        )}
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>代表问题</TableHead>
            <TableHead>频次</TableHead>
            <TableHead>示例</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data?.items.map((cluster) => (
            <TableRow key={cluster.id}>
              <TableCell className="font-medium">{cluster.representative_question}</TableCell>
              <TableCell>
                <Badge>{cluster.question_count}</Badge>
              </TableCell>
              <TableCell>
                <details>
                  <summary className="text-xs text-muted-foreground cursor-pointer">
                    {cluster.sample_questions.length} 个示例
                  </summary>
                  <ul className="mt-1 space-y-1">
                    {cluster.sample_questions.map((q, i) => (
                      <li key={i} className="text-xs text-muted-foreground">• {q}</li>
                    ))}
                  </ul>
                </details>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {data?.items.length === 0 && (
        <div className="text-center text-muted-foreground py-8">
          {isLoading ? "加载中..." : "暂无数据,点击\"刷新聚类\"生成"}
        </div>
      )}
    </div>
  );
}

function SourceAnalyticsTab() {
  const [days, setDays] = useState(30);
  const { data, isLoading } = useSourceAnalytics(days);

  const chartData = (data?.items || []).slice(0, 10).map((item) => ({
    name: item.url.split("/").pop() || item.url,
    clicks: item.clicks,
  }));

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Select value={String(days)} onValueChange={(v) => setDays(Number(v))}>
          <SelectTrigger className="w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="7">最近 7 天</SelectItem>
            <SelectItem value="30">最近 30 天</SelectItem>
            <SelectItem value="90">最近 90 天</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {chartData.length > 0 && (
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} layout="vertical">
              <XAxis type="number" />
              <YAxis type="category" dataKey="name" width={150} tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="clicks" fill="hsl(var(--primary))" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>URL</TableHead>
            <TableHead>类型</TableHead>
            <TableHead>产品</TableHead>
            <TableHead>点击数</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data?.items.map((item, i) => (
            <TableRow key={i}>
              <TableCell className="font-mono text-xs">{item.url}</TableCell>
              <TableCell><Badge variant="outline">{item.source_type}</Badge></TableCell>
              <TableCell>{item.product || "-"}</TableCell>
              <TableCell>{item.clicks}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {data?.items.length === 0 && (
        <div className="text-center text-muted-foreground py-8">
          {isLoading ? "加载中..." : "暂无点击数据"}
        </div>
      )}
    </div>
  );
}
