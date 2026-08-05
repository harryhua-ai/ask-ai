import { useState } from "react";
import { X, Plus } from "lucide-react";
import type { LLMProvider } from "@/types/api";

interface Props {
  task: string;
  availableProviders: LLMProvider[];
  onAdd: (providerId: string, model: string | null) => void;
  onClose: () => void;
}

export function AddToTaskDialog({ task, availableProviders, onAdd, onClose }: Props) {
  const [selected, setSelected] = useState<string | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const provider = availableProviders.find((p) => p.id === selected);
  const models = provider
    ? ((provider.config as Record<string, unknown>).available_models as string[]) ?? []
    : [];

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
          width: 380,
          maxWidth: "90vw",
          boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <h3>添加到 · {task}</h3>
          <button onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <label>选供应商</label>
        {availableProviders.map((p) => {
          const pModels = ((p.config as Record<string, unknown>).available_models as string[]) ?? [];
          return (
            <div
              key={p.id}
              onClick={() => {
                setSelected(p.id);
                // 选中供应商时默认选其第一个 model（若有）
                setModel(pModels.length > 0 ? pModels[0] : null);
              }}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "8px 10px",
                border: selected === p.id ? "2px solid #000" : "1px solid #e4e4e7",
                borderRadius: 6,
                cursor: p.enabled ? "pointer" : "not-allowed",
                opacity: p.enabled ? 1 : 0.5,
                margin: "4px 0",
              }}
            >
              <span
                style={{
                  width: 14,
                  height: 14,
                  borderRadius: "50%",
                  border: selected === p.id ? "4px solid #000" : "1.5px solid #999",
                }}
              />
              <span style={{ fontSize: 12, fontWeight: 600 }}>{p.id}</span>
              {!p.enabled && <small>已停用</small>}
            </div>
          );
        })}

        {provider && models.length > 0 && (
          <>
            <label>用哪个 model</label>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {models.map((m: string) => (
                <button
                  key={m}
                  onClick={() => setModel(m)}
                  style={{
                    border: model === m ? "2px solid #000" : "1px solid #e4e4e7",
                    borderRadius: 6,
                    padding: "4px 9px",
                    fontSize: 11,
                    fontFamily: "ui-monospace,monospace",
                    cursor: "pointer",
                    background: "#fff",
                  }}
                >
                  {m}
                </button>
              ))}
            </div>
          </>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
          <button
            onClick={() => selected && onAdd(selected, model)}
            disabled={!selected}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              background: selected ? "#000" : "#ccc",
              color: "#fff",
              border: "none",
              borderRadius: 8,
              padding: "7px 14px",
              cursor: selected ? "pointer" : "not-allowed",
              fontSize: 12,
              fontWeight: 600,
            }}
          >
            <Plus size={14} />
            添加到链路
          </button>
        </div>
      </div>
    </div>
  );
}
