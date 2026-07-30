import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import {
  useAnswerOverrides,
  useCreateOverride,
  useUpdateOverride,
  useDeleteOverride,
} from "@/hooks/useAnswerOverrides";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";

const MATCH_TYPES = ["semantic", "keyword", "regex"] as const;

interface OverrideForm {
  match_pattern: string;
  match_type: string;
  override_answer: string;
  override_sources_text: string;
}

const EMPTY_FORM: OverrideForm = {
  match_pattern: "",
  match_type: "semantic",
  override_answer: "",
  override_sources_text: "[]",
};

export default function AnswerOverrides() {
  const { data, isLoading } = useAnswerOverrides();
  const createOverride = useCreateOverride();
  const updateOverride = useUpdateOverride();
  const deleteOverride = useDeleteOverride();

  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<OverrideForm>(EMPTY_FORM);
  const [jsonError, setJsonError] = useState<string | null>(null);

  // 读取 Conversations 页面传来的 prefill state(Task 8)
  const location = useLocation();
  const prefill = (
    location.state as { prefill?: { match_pattern?: string; override_answer?: string } } | null
  )?.prefill;

  useEffect(() => {
    if (prefill) {
      setShowCreate(true);
      setForm({
        match_pattern: prefill.match_pattern || "",
        match_type: "semantic",
        override_answer: prefill.override_answer || "",
        override_sources_text: "[]",
      });
    }
  }, [prefill]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    let parsedSources: unknown;
    try {
      parsedSources = JSON.parse(form.override_sources_text);
    } catch {
      setJsonError("来源 JSON 解析失败,请检查格式");
      return;
    }
    setJsonError(null);
    await createOverride.mutateAsync({
      match_pattern: form.match_pattern,
      match_type: form.match_type,
      override_answer: form.override_answer,
      override_sources: parsedSources as unknown[],
    });
    setShowCreate(false);
    setForm(EMPTY_FORM);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">答案覆盖管理</h1>
        <Button onClick={() => setShowCreate(!showCreate)}>新增覆盖</Button>
      </div>

      {showCreate && (
        <form onSubmit={handleCreate} className="space-y-3 rounded-lg border bg-card p-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>匹配模式</Label>
              <Input
                value={form.match_pattern}
                onChange={(e) => setForm({ ...form, match_pattern: e.target.value })}
                placeholder="关键词 / 正则 / 语义匹配文本"
                required
              />
            </div>
            <div className="space-y-1">
              <Label>匹配类型</Label>
              <select
                className="h-10 w-full rounded-md border px-3"
                value={form.match_type}
                onChange={(e) => setForm({ ...form, match_type: e.target.value })}
              >
                {MATCH_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="space-y-1">
            <Label>覆盖答案</Label>
            <Textarea
              rows={4}
              value={form.override_answer}
              onChange={(e) => setForm({ ...form, override_answer: e.target.value })}
              placeholder="命中匹配规则后直接返回的答案文本"
              required
            />
          </div>
          <div className="space-y-1">
            <Label>来源 (JSON,可选)</Label>
            <Textarea
              className="font-mono text-sm"
              rows={3}
              value={form.override_sources_text}
              onChange={(e) => setForm({ ...form, override_sources_text: e.target.value })}
            />
            {jsonError && <p className="text-xs text-destructive">{jsonError}</p>}
          </div>
          <Button type="submit" disabled={createOverride.isPending}>创建</Button>
        </form>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>匹配模式</TableHead>
            <TableHead>类型</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>创建者</TableHead>
            <TableHead>创建时间</TableHead>
            <TableHead>操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center">加载中...</TableCell>
            </TableRow>
          ) : data?.items.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center text-muted-foreground">
                暂无答案覆盖
              </TableCell>
            </TableRow>
          ) : data?.items.map((ov) => (
            <TableRow key={ov.id}>
              <TableCell className="max-w-xs truncate font-mono text-sm">
                {ov.match_pattern}
              </TableCell>
              <TableCell>
                <Badge variant="outline">{ov.match_type}</Badge>
              </TableCell>
              <TableCell>
                <Badge
                  variant={ov.is_active ? "success" : "destructive"}
                  className="cursor-pointer"
                  onClick={() =>
                    updateOverride.mutate({ id: ov.id, is_active: !ov.is_active })
                  }
                >
                  {ov.is_active ? "启用" : "禁用"}
                </Badge>
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {ov.created_by || "-"}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {ov.created_at ? new Date(ov.created_at).toLocaleString("zh-CN") : "-"}
              </TableCell>
              <TableCell>
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={deleteOverride.isPending}
                  onClick={() => {
                    if (confirm("确认删除此覆盖?")) {
                      deleteOverride.mutate(ov.id);
                    }
                  }}
                >
                  删除
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {data && data.total > data.size && (
        <div className="text-sm text-muted-foreground">
          共 {data.total} 条,当前第 {data.page} 页
        </div>
      )}
    </div>
  );
}
