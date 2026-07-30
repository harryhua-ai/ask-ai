import { useState } from "react";
import {
  useLLMProviders,
  useLLMRouting,
  useCreateProvider,
  useToggleProvider,
  useTestProvider,
  useUpdateRouting,
  type ConnectivityTestResult,
} from "@/hooks/useLLMProviders";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";

export default function LLMProviders() {
  const { data: providers, isLoading } = useLLMProviders();
  const { data: routing } = useLLMRouting();
  const createProvider = useCreateProvider();
  const toggleProvider = useToggleProvider();
  const testProvider = useTestProvider();
  const updateRouting = useUpdateRouting();

  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({
    id: "",
    type: "openai_compatible",
    config_text:
      '{"api_base":"","api_key":"","model":"","max_tokens":4096,"temperature":0.3}',
  });
  const [testResults, setTestResults] = useState<
    Record<string, ConnectivityTestResult>
  >({});
  /** 正在进行连通性测试的供应商 ID,用于逐行显示 loading 状态。 */
  const [testingId, setTestingId] = useState<string | null>(null);

  const handleTest = async (id: string) => {
    setTestingId(id);
    try {
      const result = await testProvider.mutateAsync(id);
      setTestResults((prev) => ({ ...prev, [id]: result }));
    } finally {
      setTestingId(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">LLM 供应商管理</h1>
        <Button onClick={() => setShowCreate(!showCreate)}>新增供应商</Button>
      </div>

      {/* 路由配置 */}
      <div className="rounded-lg border bg-card p-4">
        <h2 className="mb-3 text-lg font-semibold">路由配置</h2>
        {routing?.map((r) => (
          <div key={r.task} className="mb-2 flex items-center gap-2">
            <Badge variant="outline" className="min-w-[160px]">
              {r.task}
            </Badge>
            <Input
              className="flex-1"
              defaultValue={r.chain.join(", ")}
              onBlur={(e) => {
                const chain = e.target.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean);
                if (chain.join(",") !== r.chain.join(",")) {
                  updateRouting.mutate({ task: r.task, chain });
                }
              }}
            />
          </div>
        ))}
      </div>

      {/* 新增供应商表单 */}
      {showCreate && (
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            await createProvider.mutateAsync({
              id: form.id,
              type: form.type,
              config: JSON.parse(form.config_text),
            });
            setShowCreate(false);
          }}
          className="space-y-3 rounded-lg border bg-card p-4"
        >
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>ID</Label>
              <Input
                value={form.id}
                onChange={(e) => setForm({ ...form, id: e.target.value })}
                required
              />
            </div>
            <div className="space-y-1">
              <Label>类型</Label>
              <select
                className="h-10 w-full rounded-md border px-3"
                value={form.type}
                onChange={(e) => setForm({ ...form, type: e.target.value })}
              >
                <option value="openai_compatible">openai_compatible</option>
                <option value="anthropic">anthropic</option>
                <option value="openai">openai</option>
              </select>
            </div>
          </div>
          <div className="space-y-1">
            <Label>配置 (JSON,含 api_key)</Label>
            <Textarea
              className="font-mono text-sm"
              rows={5}
              value={form.config_text}
              onChange={(e) =>
                setForm({ ...form, config_text: e.target.value })
              }
            />
          </div>
          <Button type="submit" disabled={createProvider.isPending}>
            创建
          </Button>
        </form>
      )}

      {/* 供应商列表 */}
      <div className="space-y-2">
        {isLoading ? (
          <div className="text-center">加载中...</div>
        ) : (
          providers?.map((p) => {
            const result = testResults[p.id];
            const isTestingThis = testingId === p.id;
            return (
              <div
                key={p.id}
                className="flex items-center justify-between rounded-lg border bg-card p-4"
              >
                <div className="flex items-center gap-3">
                  <span className="font-mono font-medium">{p.id}</span>
                  <Badge variant="outline">{p.type}</Badge>
                  <Badge
                    variant={p.enabled ? "success" : "destructive"}
                    className="cursor-pointer"
                    onClick={() =>
                      toggleProvider.mutate({ id: p.id, enabled: !p.enabled })
                    }
                  >
                    {p.enabled ? "启用" : "禁用"}
                  </Badge>
                  <span className="text-sm text-muted-foreground">
                    model: {String(p.config.model || "-")}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  {result && (
                    <Badge
                      variant={result.success ? "success" : "destructive"}
                      title={result.error || undefined}
                    >
                      {result.success
                        ? `${result.latency_ms ?? "-"}ms`
                        : "失败"}
                    </Badge>
                  )}
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={isTestingThis}
                    onClick={() => handleTest(p.id)}
                  >
                    {isTestingThis ? "测试中..." : "测试连通性"}
                  </Button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
