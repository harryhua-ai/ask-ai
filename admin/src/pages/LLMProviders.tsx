import { useEffect, useState } from "react";
import { toast } from "sonner";
import { RefreshCw, SlidersHorizontal, Info, Plus, ShieldCheck } from "lucide-react";
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
import { useAuth } from "@/hooks/useAuth";
import { ProviderCredentialDialog } from "@/components/ProviderCredentialDialog";
import { EndpointAuthDialog } from "@/components/EndpointAuthDialog";
import { ProviderEditDialog } from "@/components/ProviderEditDialog";
import { AddToTaskDialog } from "@/components/AddToTaskDialog";
import ModelRuntimeTab from "@/components/ModelRuntimeTab";
import { cn } from "@/lib/utils";
import type { LLMChainItem } from "@/types/api";

type TabKey = "pipeline" | "runtime";

const TABS: { key: TabKey; label: string }[] = [
  { key: "pipeline", label: "模型流水线" },
  { key: "runtime", label: "模型运行" },
];

const RETRIEVAL_CARDS = [
  { key: "embedding", title: "向量模型", role: "查询与知识的向量化(语义召回)", workload: "query_embedding" },
  { key: "reranking", title: "排序模型", role: "检索结果精排(提升 Top-K 质量)", workload: "query_reranker" },
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
  const { user } = useAuth();
  const canWrite = user?.role === "admin" || user?.role === "editor";
  const [tab, setTab] = useState<TabKey>("pipeline");
  const { data: providers } = useLLMProviders();
  const { data: routing } = useLLMRouting();
  const { data: localModels } = useLocalModels();
  const reload = useReloadProviders();
  const updateProvider = useUpdateProvider();
  const updateRouting = useUpdateRouting();
  const toggleProvider = useToggleProvider();
  const createProvider = useCreateProvider();

  const [credOpen, setCredOpen] = useState(false);
  const [authOpen, setAuthOpen] = useState(false);
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
            {tab === "pipeline"
              ? "按流水线环节配置各阶段模型 · 改完点应用变更生效"
              : "配置各模型工作负载的执行设备与运行容量"}
          </p>
        </div>
        {tab === "pipeline" && canWrite && (
          <div className="flex flex-wrap items-center gap-2">
            <fieldset className="rounded-md border px-2 py-1">
              <legend className="px-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                连接管理
              </legend>
              <div className="flex gap-1.5">
                <Button variant="ghost" size="sm" onClick={() => setCredOpen(true)}>
                  <SlidersHorizontal className="mr-1.5 h-3.5 w-3.5" />
                  供应商凭证
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setAuthOpen(true)}>
                  <ShieldCheck className="mr-1.5 h-3.5 w-3.5" />
                  端点授权
                </Button>
              </div>
            </fieldset>
            <Button size="sm" onClick={() => reload.mutate()} disabled={reload.isPending}>
              <RefreshCw className={cn("mr-1.5 h-3.5 w-3.5", reload.isPending && "animate-spin")} />
              {reload.isPending ? "重载中..." : "应用变更"}
            </Button>
          </div>
        )}
      </div>

      {/* 主 Tab:模型流水线 / 模型运行(侧边导航保持「模型配置」单一入口) */}
      <div className="flex gap-1 border-b" role="tablist" aria-label="模型配置分区">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              "rounded-t-md px-4 py-2 text-sm font-medium",
              tab === t.key
                ? "border-b-2 border-primary text-primary"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "runtime" ? (
        <ModelRuntimeTab canWrite={canWrite} />
      ) : (
        <div className="space-y-4">
          {/* A. 检索模型(向量 / 排序;硬件面向呈现,不暴露裸 cuda) */}
          <div>
            <h2 className="mb-2 text-sm font-semibold text-muted-foreground">检索模型</h2>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {RETRIEVAL_CARDS.map((c) => {
                const m = localModels?.find((x) => x.role === c.key) as
                  | { model_name?: string; device?: string; device_label?: string }
                  | undefined;
                const deviceLabel = m?.device_label ?? m?.device;
                return (
                  <Card key={c.key} className="bg-muted/50">
                    <CardContent className="p-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-bold uppercase text-muted-foreground">
                            {c.title}
                          </span>
                          <Badge variant="secondary" className="font-mono text-[10px]">
                            {c.key}
                          </Badge>
                        </div>
                        <Info className="h-3 w-3 text-muted-foreground/50" />
                      </div>
                      <div className="mt-1 font-mono text-sm">{m?.model_name ?? "未加载"}</div>
                      <div className="text-xs text-muted-foreground">
                        {c.role}
                      </div>
                      <div className="mt-1 text-xs">
                        <span className="text-muted-foreground">运行设备:</span>
                        <span className="ml-1 font-medium">{deviceLabel ?? "—"}</span>
                      </div>
                      <button
                        type="button"
                        className="mt-1 text-xs text-primary underline-offset-2 hover:underline"
                        onClick={() => setTab("runtime")}
                      >
                        在「模型运行」中配置执行设备 →
                      </button>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          </div>

          {/* B. LLM 流水线(阶段链;链内序号即优先序,不重复编号) */}
          <div>
            <h2 className="mb-2 text-sm font-semibold text-muted-foreground">
              LLM 流水线
              <span className="ml-2 text-xs font-normal">
                意图分类 → 查询处理 → 向量+排序检索 → 剪枝 → 生成
              </span>
            </h2>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {CONFIGURABLE_TASKS.map((t) => {
                const chain = getChain(routing, t.key);
                return (
                  <Card key={t.key}>
                    <CardContent className="p-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 text-sm font-bold">
                          {t.title}
                          <Badge variant="secondary" className="font-mono text-[10px]">
                            {t.key}
                          </Badge>
                        </div>
                        {t.needsRestart && (
                          <Badge variant="outline" className="text-[10px] text-amber-700">
                            首启需重启
                          </Badge>
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
                              editable={canWrite}
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
                        {canWrite && (
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-7 gap-1 rounded-full border-dashed text-xs text-muted-foreground"
                            onClick={() => setAddTask(t.key)}
                          >
                            <Plus className="h-3 w-3" />
                            添加
                          </Button>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          </div>
        </div>
      )}

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
      {authOpen && <EndpointAuthDialog onClose={() => setAuthOpen(false)} />}
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
