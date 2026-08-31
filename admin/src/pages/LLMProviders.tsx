import { useEffect, useState } from "react";
import { toast } from "sonner";
import { RefreshCw, SlidersHorizontal, Info, Plus } from "lucide-react";
import {
  useLLMProviders,
  useLLMRouting,
  useLocalModels,
  useReloadProviders,
  useUpdateProvider,
  useUpdateRouting,
  useToggleProvider,
  useCreateProvider,
} from "@/hooks/useLLMProviders";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ChainChip } from "@/components/ChainChip";
import { ProviderCredentialDialog } from "@/components/ProviderCredentialDialog";
import { ProviderEditDialog } from "@/components/ProviderEditDialog";
import { AddToTaskDialog } from "@/components/AddToTaskDialog";
import { cn } from "@/lib/utils";
import type { LLMChainItem } from "@/types/api";

const READONLY_CARDS = [
  { key: "embedding", title: "向量模型", id: "embedding" },
  { key: "reranking", title: "排序模型", id: "rerank" },
];

const CONFIGURABLE_TASKS = [
  { key: "intent", title: "意图分类", order: 1 },
  { key: "query_rewrite", title: "查询处理", order: 2 },
  { key: "pruning", title: "剪枝", order: 3, needsRestart: true },
  { key: "generation", title: "生成", order: 4 },
];

function getChain(
  routing: { task: string; chain: LLMChainItem[] | string[] }[] | undefined,
  task: string,
): LLMChainItem[] {
  const r = routing?.find((x) => x.task === task);
  if (!r) return [];
  return r.chain.map((item) =>
    typeof item === "string" ? { provider: item, model: null } : item,
  );
}

export default function LLMProviders() {
  const { data: providers } = useLLMProviders();
  const { data: routing } = useLLMRouting();
  const { data: localModels } = useLocalModels();
  const reload = useReloadProviders();
  const updateProvider = useUpdateProvider();
  const updateRouting = useUpdateRouting();
  const toggleProvider = useToggleProvider();
  const createProvider = useCreateProvider();

  const [credOpen, setCredOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [addTask, setAddTask] = useState<string | null>(null);

  const editProvider = providers?.find((p) => p.id === editId);

  useEffect(() => {
    if (reload.isSuccess && reload.data) {
      toast.success(`已应用变更：${reload.data.providers_count} 个供应商生效`);
    } else if (reload.isError) {
      toast.error("重载失败，配置未生效（详见服务端日志）");
    }
  }, [reload.isSuccess, reload.isError, reload.data]);

  const replaceChain = (task: string, chain: LLMChainItem[]) => {
    updateRouting.mutate({ task, chain });
  };

  const handleRemoveFromTask = (task: string, index: number) => {
    const chain = getChain(routing, task);
    replaceChain(task, chain.filter((_, j) => j !== index));
  };

  const handleChangeModel = (task: string, index: number, model: string | null) => {
    const chain = getChain(routing, task);
    replaceChain(
      task,
      chain.map((it, j) => (j === index ? { ...it, model } : it)),
    );
  };

  const handleMove = (task: string, from: number, to: number) => {
    const chain = getChain(routing, task);
    if (to < 0 || to >= chain.length) return;
    const next = [...chain];
    [next[from], next[to]] = [next[to], next[from]];
    replaceChain(task, next);
  };

  const handleAddToTask = (providerId: string, model: string | null) => {
    if (!addTask) return;
    const chain = getChain(routing, addTask);
    replaceChain(addTask, [...chain, { provider: providerId, model }]);
    setAddTask(null);
  };

  // T27:保存失败必须显式报错且弹窗保持打开(表单态保留),成功才关闭
  const handleSaveProvider = async (patch: {
    type?: string;
    enabled?: boolean;
    config: Record<string, unknown>;
  }) => {
    if (!editProvider) return;
    try {
      await updateProvider.mutateAsync({ id: editProvider.id, ...patch });
      toast.success("供应商已保存,点「应用变更」后生效");
      setEditId(null);
    } catch (err) {
      toast.error(`保存失败:${err instanceof Error ? err.message : "未知错误"}`);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-bold">模型配置</h1>
          <p className="text-sm text-muted-foreground">
            按流水线环节配置各阶段模型 · 改完点应用变更生效
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setCredOpen(true)}>
            <SlidersHorizontal className="mr-1.5 h-3.5 w-3.5" />
            供应商凭证
          </Button>
          <Button size="sm" onClick={() => reload.mutate()} disabled={reload.isPending}>
            <RefreshCw className={cn("mr-1.5 h-3.5 w-3.5", reload.isPending && "animate-spin")} />
            {reload.isPending ? "重载中..." : "应用变更"}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {READONLY_CARDS.map((c) => {
          const m = localModels?.find((x) => x.role === c.key);
          return (
            <Card key={c.key} className="bg-muted/50">
              <CardContent className="p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold uppercase text-muted-foreground">{c.title}</span>
                    <Badge variant="secondary" className="font-mono text-[10px]">{c.id}</Badge>
                  </div>
                  <Info className="h-3 w-3 text-muted-foreground/50" />
                </div>
                <div className="mt-1 font-mono text-sm">{m?.model_name ?? "未加载"}</div>
                <div className="text-xs text-muted-foreground">{m?.device}</div>
              </CardContent>
            </Card>
          );
        })}

        {CONFIGURABLE_TASKS.map((t) => {
          const chain = getChain(routing, t.key);
          return (
            <Card key={t.key}>
              <CardContent className="p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm font-bold">
                    <span className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-primary text-[9px] text-primary-foreground">
                      {t.order}
                    </span>
                    {t.title}
                    <Badge variant="secondary" className="font-mono text-[10px]">{t.key}</Badge>
                  </div>
                  {t.needsRestart && (
                    <Badge variant="outline" className="text-[10px] text-amber-700">首启需重启</Badge>
                  )}
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {chain.map((item, i) => {
                    const prov = providers?.find((p) => p.id === item.provider);
                    const avail =
                      (prov &&
                        ((prov.config as Record<string, unknown>).available_models as string[])) ??
                      [];
                    return (
                      <ChainChip
                        key={item.provider + i}
                        order={i + 1}
                        providerId={item.provider}
                        model={item.model}
                        availableModels={avail}
                        canMoveUp={i > 0}
                        canMoveDown={i < chain.length - 1}
                        onChangeModel={(m) => handleChangeModel(t.key, i, m)}
                        onRemove={() => handleRemoveFromTask(t.key, i)}
                        onMoveUp={() => handleMove(t.key, i, i - 1)}
                        onMoveDown={() => handleMove(t.key, i, i + 1)}
                      />
                    );
                  })}
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 gap-1 rounded-full border-dashed text-xs text-muted-foreground"
                    onClick={() => setAddTask(t.key)}
                  >
                    <Plus className="h-3 w-3" />
                    添加
                  </Button>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <p className="text-center text-xs text-muted-foreground">
        意图分类(1) → 查询处理(2) → 向量+排序检索 → 剪枝(3) → 生成(4)
      </p>

      {credOpen && (
        <ProviderCredentialDialog
          providers={providers ?? []}
          onEdit={(id) => {
            setEditId(id);
            setCredOpen(false);
          }}
          onDelete={() => {}}
          onToggle={(id, enabled) => toggleProvider.mutate({ id, enabled })}
          onAdd={(id) => {
            createProvider.mutate(
              {
                id,
                type: "openai_compatible",
                config: { api_base: "", api_key: "", model: "", available_models: [] },
              },
              {
                onSuccess: () =>
                  toast.success("已创建,请点击「编辑」填写 API 地址、密钥与模型"),
                onError: (err) =>
                  toast.error(
                    `创建失败:${err instanceof Error ? err.message : String(err)}`,
                  ),
              },
            );
          }}
          onClose={() => setCredOpen(false)}
        />
      )}
      {editProvider && (
        <ProviderEditDialog
          provider={editProvider}
          onSave={handleSaveProvider}
          onClose={() => setEditId(null)}
        />
      )}
      {addTask && (
        <AddToTaskDialog
          task={addTask}
          availableProviders={providers ?? []}
          onAdd={handleAddToTask}
          onClose={() => setAddTask(null)}
        />
      )}
    </div>
  );
}
