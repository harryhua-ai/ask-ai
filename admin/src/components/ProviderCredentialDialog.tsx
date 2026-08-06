import { Plus, X } from "lucide-react";
import type { LLMProvider } from "@/types/api";

interface Props {
  providers: LLMProvider[];
  onEdit: (id: string) => void;
  onDelete: (id: string) => void;
  onToggle: (id: string, enabled: boolean) => void;
  onAdd: () => void;
  onClose: () => void;
}

export function ProviderCredentialDialog({
  providers,
  onEdit,
  onDelete,
  onToggle,
  onAdd,
  onClose,
}: Props) {
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
          width: 480,
          maxWidth: "90vw",
          boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3>供应商凭证</h3>
          <button onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        {providers.map((p) => {
          const cfg = p.config as Record<string, unknown>;
          const modelCount = ((cfg.available_models as string[]) ?? []).length;
          return (
            <div
              key={p.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "10px 0",
                borderBottom: "1px solid #f4f4f5",
                opacity: p.enabled ? 1 : 0.5,
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: p.enabled ? "#000" : "#ccc",
                }}
              />
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{p.id}</div>
                <div style={{ fontSize: 10, color: "#999" }}>
                  {p.type} · {modelCount} 个模型{!p.enabled && " · 已停用"}
                </div>
              </div>
              <button
                onClick={() => onEdit(p.id)}
                style={{
                  fontSize: 11,
                  padding: "4px 8px",
                  border: "1px solid #e4e4e7",
                  borderRadius: 6,
                  background: "#fff",
                  cursor: "pointer",
                }}
              >
                编辑
              </button>
              <button
                onClick={() => onToggle(p.id, !p.enabled)}
                style={{
                  fontSize: 11,
                  padding: "4px 8px",
                  border: "1px solid #e4e4e7",
                  borderRadius: 6,
                  background: "#fff",
                  cursor: "pointer",
                }}
              >
                {p.enabled ? "停用" : "启用"}
              </button>
              <button
                onClick={() => onDelete(p.id)}
                style={{
                  fontSize: 11,
                  padding: "4px 8px",
                  border: "1px solid #e4e4e7",
                  borderRadius: 6,
                  color: "#dc2626",
                  background: "#fff",
                  cursor: "pointer",
                }}
              >
                删除
              </button>
            </div>
          );
        })}

        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
          <button
            onClick={onAdd}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              background: "#000",
              color: "#fff",
              border: "none",
              borderRadius: 8,
              padding: "7px 14px",
              cursor: "pointer",
              fontSize: 12,
              fontWeight: 600,
            }}
          >
            <Plus size={14} />
            新增供应商
          </button>
        </div>
      </div>
    </div>
  );
}
