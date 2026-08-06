import { useState } from "react";
import { RefreshCw, Plus, X, Star } from "lucide-react";
import { useFetchModels } from "@/hooks/useLLMProviders";
import type { LLMProvider } from "@/types/api";

interface Props {
  provider: LLMProvider;
  onSave: (patch: {
    type?: string;
    enabled?: boolean;
    config: Record<string, unknown>;
  }) => void;
  onClose: () => void;
}

export function ProviderEditDialog({ provider, onSave, onClose }: Props) {
  const cfg = provider.config as Record<string, unknown>;
  const initialModels =
    (cfg.available_models as string[] | undefined) ??
    (cfg.model ? [cfg.model as string] : []);
  const [apiBase, setApiBase] = useState((cfg.api_base as string) ?? "");
  const [apiKey, setApiKey] = useState("");
  const [models, setModels] = useState<string[]>(initialModels);
  const [fetchResult, setFetchResult] = useState<string[] | null>(null);
  const [newModel, setNewModel] = useState("");
  const fetchModels = useFetchModels();

  const handleFetch = async () => {
    const res = await fetchModels.mutateAsync(provider.id);
    if (res.error) setFetchResult([]);
    else setFetchResult(res.models);
  };

  const handleAddManual = () => {
    if (newModel && !models.includes(newModel)) {
      setModels([...models, newModel]);
      setNewModel("");
    }
  };

  const handleSave = () => {
    const config: Record<string, unknown> = {
      ...cfg,
      api_base: apiBase,
      model: models[0] ?? cfg.model,
      available_models: models,
    };
    // 空 key 不放入 patch，后端因此保留 DB 中的现有密钥
    if (apiKey) config.api_key = apiKey;
    else delete config.api_key;
    onSave({
      type: provider.type,
      enabled: provider.enabled,
      config,
    });
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 50,
      }}
    >
      <div
        style={{
          background: "#fff",
          borderRadius: 8,
          padding: 24,
          width: 420,
          maxWidth: "90vw",
          boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
        }}
      >
        <h3>编辑供应商 · {provider.id}</h3>
        <label>API Base</label>
        <input
          value={apiBase}
          onChange={(e) => setApiBase(e.target.value)}
          style={inputStyle}
        />

        <label>
          API Key <small>留空则保留当前密钥</small>
        </label>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="留空则不修改"
          style={inputStyle}
        />

        <label>
          可用模型 <small>★ 第 1 个 = 默认</small>
        </label>
        <div>
          {models.map((m, i) => (
            <div key={m} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <Star size={12} fill={i === 0 ? "#000" : "none"} />
              <span style={{ fontFamily: "ui-monospace,monospace" }}>{m}</span>
              {i === 0 && <small>默认</small>}
              <button onClick={() => setModels(models.filter((x) => x !== m))}>
                <X size={12} />
              </button>
            </div>
          ))}
          <button onClick={handleFetch}>
            <RefreshCw size={12} />
            从 API 拉取
          </button>
          <div style={{ display: "flex", gap: 4 }}>
            <input
              placeholder="模型名"
              value={newModel}
              onChange={(e) => setNewModel(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleAddManual();
              }}
            />
            <button onClick={handleAddManual}>
              <Plus size={12} />
              手动添加
            </button>
          </div>
          {fetchResult && (
            <div>
              {fetchResult
                .filter((m) => !models.includes(m))
                .map((m) => (
                  <button key={m} onClick={() => setModels([...models, m])}>
                    {m}
                  </button>
                ))}
            </div>
          )}
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button onClick={onClose}>取消</button>
          <button onClick={handleSave}>保存</button>
        </div>
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  border: "1px solid #e4e4e7",
  borderRadius: 8,
  padding: "7px 10px",
  fontSize: 13,
  boxSizing: "border-box",
};
