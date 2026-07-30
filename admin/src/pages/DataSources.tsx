import { useState } from "react";
import { useDataSources, useCreateDataSource, useToggleDataSource, useTriggerSync } from "@/hooks/useDataSources";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";

const DEFAULT_CONFIG = '{"owner":"","repo":"","branch":"main"}';

const SOURCE_TYPES = ["github", "filesystem", "web_crawl", "sdk"] as const;

interface CreateForm {
  id: string;
  type: string;
  product: string;
  config_text: string;
}

const EMPTY_FORM: CreateForm = {
  id: "",
  type: "github",
  product: "",
  config_text: DEFAULT_CONFIG,
};

export default function DataSources() {
  const { data: sources, isLoading } = useDataSources();
  const createDs = useCreateDataSource();
  const toggleDs = useToggleDataSource();
  const triggerSync = useTriggerSync();
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<CreateForm>(EMPTY_FORM);
  const [jsonError, setJsonError] = useState<string | null>(null);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    let parsedConfig: unknown;
    try {
      parsedConfig = JSON.parse(form.config_text);
    } catch (err) {
      setJsonError("配置 JSON 解析失败，请检查格式");
      return;
    }
    setJsonError(null);
    await createDs.mutateAsync({
      id: form.id,
      type: form.type,
      product: form.product,
      config: parsedConfig as Record<string, unknown>,
    });
    setShowCreate(false);
    setForm(EMPTY_FORM);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">数据源管理</h1>
        <Button onClick={() => setShowCreate(!showCreate)}>新增数据源</Button>
      </div>
      {showCreate && (
        <form onSubmit={handleCreate} className="space-y-3 rounded-lg border bg-card p-4">
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1">
              <Label>ID</Label>
              <Input value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} required />
            </div>
            <div className="space-y-1">
              <Label>类型</Label>
              <select
                className="h-10 w-full rounded-md border px-3"
                value={form.type}
                onChange={(e) => setForm({ ...form, type: e.target.value })}
              >
                {SOURCE_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label>产品线</Label>
              <Input
                value={form.product}
                onChange={(e) => setForm({ ...form, product: e.target.value })}
                required
              />
            </div>
          </div>
          <div className="space-y-1">
            <Label>配置 (JSON)</Label>
            <Textarea
              className="font-mono"
              rows={5}
              value={form.config_text}
              onChange={(e) => setForm({ ...form, config_text: e.target.value })}
            />
            {jsonError && <p className="text-xs text-destructive">{jsonError}</p>}
          </div>
          <Button type="submit" disabled={createDs.isPending}>创建</Button>
        </form>
      )}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>ID</TableHead>
            <TableHead>类型</TableHead>
            <TableHead>产品线</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>同步间隔</TableHead>
            <TableHead>操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center">加载中...</TableCell>
            </TableRow>
          ) : sources?.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center text-muted-foreground">暂无数据源</TableCell>
            </TableRow>
          ) : sources?.map((ds) => (
            <TableRow key={ds.id}>
              <TableCell className="font-mono text-sm">{ds.id}</TableCell>
              <TableCell>{ds.type}</TableCell>
              <TableCell>{ds.product}</TableCell>
              <TableCell>
                <Badge
                  variant={ds.enabled ? "success" : "destructive"}
                  className="cursor-pointer"
                  onClick={() => toggleDs.mutate({ id: ds.id, enabled: !ds.enabled })}
                >
                  {ds.enabled ? "启用" : "禁用"}
                </Badge>
              </TableCell>
              <TableCell>{ds.sync_interval}</TableCell>
              <TableCell className="space-x-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={triggerSync.isPending || !ds.enabled}
                  onClick={() => triggerSync.mutate(ds.id)}
                >
                  同步
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
