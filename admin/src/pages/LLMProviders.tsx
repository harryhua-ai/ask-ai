import { useState } from "react";
import { RefreshCw, SlidersHorizontal, Info } from "lucide-react";
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
import { ChainChip } from "@/components/ChainChip";
import { ProviderCredentialDialog } from "@/components/ProviderCredentialDialog";
import { ProviderEditDialog } from "@/components/ProviderEditDialog";
import { AddToTaskDialog } from "@/components/AddToTaskDialog";
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

/** 取某 task 的 chain（统一为 LLMChainItem[] 对象格式）。 */
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

  /** 更新某 task 的整条 chain。 */
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

  const handleSaveProvider = (patch: {
    type?: string;
    enabled?: boolean;
    config: Record<string, unknown>;
  }) => {
    if (!editProvider) return;
    updateProvider.mutate({ id: editProvider.id, ...patch });
    setEditId(null);
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 18 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700 }}>模型配置</h1>
          <p style={{ fontSize: 13, color: "#888" }}>
            按流水线环节配置各阶段模型 · 改完点应用变更生效
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={() => setCredOpen(true)} style={outlineBtnStyle}>
            <SlidersHorizontal size={13} />
            供应商凭证
          </button>
          <button
            onClick={() => reload.mutate()}
            disabled={reload.isPending}
            style={primaryBtnStyle}
          >
            <RefreshCw size={13} />
            {reload.isPending ? "重载中..." : "应用变更"}
          </button>
        </div>
      </div>

      {/* 6 环节网格 */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        {/* 行1：只读 */}
        {READONLY_CARDS.map((c) => {
          const m = localModels?.find((x) => x.role === c.key);
          return (
            <div key={c.key} style={{ ...cardStyle, background: "#fafafa" }}>
              <Info size={12} style={{ float: "right", color: "#bbb" }} />
              <div style={{ fontWeight: 700, fontSize: 12 }}>
                {c.title} <code style={codeStyle}>{c.id}</code>
              </div>
              <div style={{ fontFamily: "ui-monospace,monospace", fontSize: 13 }}>
                {m?.model_name ?? "未加载"}
              </div>
              <div style={{ fontSize: 11, color: "#999" }}>{m?.device}</div>
            </div>
          );
        })}

        {/* 行2-3：可配任务 */}
        {CONFIGURABLE_TASKS.map((t) => {
          const chain = getChain(routing, t.key);
          return (
            <div key={t.key} style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <div style={{ fontWeight: 700, fontSize: 13 }}>
                  {t.order && <span style={numStyle}>{t.order}</span>}
                  {t.title} <code style={codeStyle}>{t.key}</code>
                </div>
                {t.needsRestart && <span style={warnBadgeStyle}>首启需重启</span>}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
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
                <button onClick={() => setAddTask(t.key)} style={addBtnStyle}>
                  + 添加
                </button>
              </div>
            </div>
          );
        })}
      </div>

      <p style={{ textAlign: "center", fontSize: 11, color: "#999", marginTop: 12 }}>
        意图分类(1) → 查询处理(2) → 向量+排序检索 → 剪枝(3) → 生成(4)
      </p>

      {/* 弹窗 */}
      {credOpen && (
        <ProviderCredentialDialog
          providers={providers ?? []}
          onEdit={(id) => {
            setEditId(id);
            setCredOpen(false);
          }}
          onDelete={() => {}}
          onToggle={(id, enabled) => toggleProvider.mutate({ id, enabled })}
          onAdd={() => {
            // 新增供应商：跳到凭证弹窗内的简易创建（沿用 createProvider）
            const id = window.prompt("新供应商 ID");
            if (id) {
              createProvider.mutate({
                id,
                type: "openai_compatible",
                config: { api_base: "", api_key: "", model: "", available_models: [] },
              });
            }
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

const cardStyle: React.CSSProperties = {
  border: "1px solid #dbdbdb",
  borderRadius: 11,
  padding: "12px 15px",
};
const codeStyle: React.CSSProperties = {
  background: "#f4f4f5",
  borderRadius: 4,
  padding: "0 5px",
  fontSize: 10,
  fontFamily: "ui-monospace,monospace",
};
const numStyle: React.CSSProperties = {
  display: "inline-flex",
  width: 16,
  height: 16,
  borderRadius: "50%",
  background: "#000",
  color: "#fff",
  fontSize: 9,
  alignItems: "center",
  justifyContent: "center",
  marginRight: 6,
};
const warnBadgeStyle: React.CSSProperties = {
  fontSize: 10,
  color: "#b45309",
  background: "#fef3c7",
  border: "1px solid #fde68a",
  borderRadius: 4,
  padding: "1px 6px",
};
const primaryBtnStyle: React.CSSProperties = {
  background: "#000",
  color: "#fff",
  border: "none",
  borderRadius: 10,
  padding: "8px 14px",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
  display: "flex",
  alignItems: "center",
  gap: 7,
};
const outlineBtnStyle: React.CSSProperties = {
  background: "#fff",
  color: "#333",
  border: "1px solid #dbdbdb",
  borderRadius: 10,
  padding: "8px 13px",
  fontSize: 13,
  cursor: "pointer",
  display: "flex",
  alignItems: "center",
  gap: 6,
};
const addBtnStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  border: "1px dashed #ccc",
  borderRadius: 999,
  padding: "4px 9px",
  fontSize: 11,
  color: "#888",
  cursor: "pointer",
  background: "#fff",
};
