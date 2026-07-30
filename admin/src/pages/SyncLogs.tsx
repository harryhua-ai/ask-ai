import { useState } from "react";
import { useSyncLogs } from "@/hooks/useSyncLogs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";

export default function SyncLogs() {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const { data, isLoading } = useSyncLogs({ status: statusFilter || undefined, page });

  const statusVariant = (status: string): "success" | "destructive" | "warning" =>
    status === "success" ? "success" : status === "failed" ? "destructive" : "warning";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">同步监控</h1>
        <div className="flex items-center gap-2">
          <select
            className="h-9 rounded-md border px-3 text-sm"
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(1);
            }}
          >
            <option value="">全部状态</option>
            <option value="success">成功</option>
            <option value="failed">失败</option>
            <option value="partial">部分成功</option>
          </select>
        </div>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>数据源</TableHead>
            <TableHead>类型</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>开始时间</TableHead>
            <TableHead>耗时</TableHead>
            <TableHead>新增/更新/删除</TableHead>
            <TableHead>触发方式</TableHead>
            <TableHead>错误详情</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableRow>
              <TableCell colSpan={8} className="text-center">加载中...</TableCell>
            </TableRow>
          ) : (
            data?.items.map((log) => (
              <TableRow key={log.id}>
                <TableCell className="font-mono text-sm">{log.source_id}</TableCell>
                <TableCell>{log.source_type}</TableCell>
                <TableCell>
                  <Badge variant={statusVariant(log.status)}>{log.status}</Badge>
                </TableCell>
                <TableCell className="text-sm">
                  {new Date(log.started_at).toLocaleString("zh-CN")}
                </TableCell>
                <TableCell>{log.duration_ms ? `${(log.duration_ms / 1000).toFixed(1)}s` : "-"}</TableCell>
                <TableCell className="text-sm">
                  <span className="text-green-600">+{log.items_new}</span> /{" "}
                  <span className="text-blue-600">~{log.items_updated}</span> /{" "}
                  <span className="text-red-600">-{log.items_deleted}</span>
                </TableCell>
                <TableCell>
                  <Badge variant="outline">{log.triggered_by}</Badge>
                </TableCell>
                <TableCell
                  className="max-w-xs truncate text-sm text-destructive"
                  title={log.error_detail || ""}
                >
                  {log.error_detail || "-"}
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
      {data && (
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            上一页
          </Button>
          <span className="text-sm">
            第 {page} 页（共 {Math.ceil(data.total / data.size)} 页，{data.total} 条）
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page * data.size >= data.total}
            onClick={() => setPage(page + 1)}
          >
            下一页
          </Button>
        </div>
      )}
    </div>
  );
}
