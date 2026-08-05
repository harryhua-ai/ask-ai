import { useState } from "react";
import { Check, ChevronDown, ChevronUp, X } from "lucide-react";

interface ChainChipProps {
  order: number;
  providerId: string;
  model: string | null;
  availableModels: string[];
  canMoveUp: boolean;
  canMoveDown: boolean;
  onChangeModel: (model: string | null) => void;
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
}

export function ChainChip(props: ChainChipProps) {
  const [open, setOpen] = useState(false);
  const [confirmingRemove, setConfirmingRemove] = useState(false);

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <span
        onClick={() => setOpen(!open)}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          border: "2px solid #000",
          borderRadius: 999,
          padding: "4px 9px",
          fontSize: 12,
          fontWeight: 600,
          cursor: "pointer",
          background: "#fff",
        }}
      >
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 14,
            height: 14,
            borderRadius: "50%",
            background: "#000",
            color: "#fff",
            fontSize: 8,
            fontWeight: 700,
          }}
        >
          {props.order}
        </span>
        {props.providerId}
        <span
          style={{
            fontSize: 10,
            fontFamily: "ui-monospace,monospace",
            color: "#666",
            background: "#f4f4f5",
            border: "1px solid #e4e4e7",
            borderRadius: 4,
            padding: "1px 5px",
          }}
        >
          {props.model ?? "默认"}
        </span>
      </span>

      {open && !confirmingRemove && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            zIndex: 10,
            background: "#fff",
            border: "1px solid #e4e4e7",
            borderRadius: 10,
            boxShadow: "0 8px 28px rgba(0,0,0,0.14)",
            width: 220,
            marginTop: 4,
          }}
        >
          <div style={{ padding: "8px 12px", borderBottom: "1px solid #f4f4f5" }}>
            <div style={{ fontSize: 10, color: "#999", textTransform: "uppercase" }}>切换 model</div>
          </div>
          <div style={{ padding: "4px 0" }}>
            {props.availableModels.map((m) => (
              <button
                key={m}
                onClick={() => {
                  props.onChangeModel(m);
                  setOpen(false);
                }}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  width: "100%",
                  padding: "4px 12px",
                  border: "none",
                  background: "transparent",
                  cursor: "pointer",
                  fontSize: 12,
                  fontFamily: "ui-monospace,monospace",
                  textAlign: "left",
                }}
              >
                {props.model === m && <Check size={12} />}
                <span style={{ visibility: props.model === m ? "visible" : "hidden" }} />
                {m}
              </button>
            ))}
            <button
              onClick={() => {
                props.onChangeModel(null);
                setOpen(false);
              }}
              style={{
                display: "block",
                width: "100%",
                padding: "4px 12px",
                border: "none",
                background: "transparent",
                cursor: "pointer",
                fontSize: 12,
                textAlign: "left",
                color: "#666",
              }}
            >
              默认
            </button>
          </div>
          <div
            style={{
              padding: "8px 12px",
              borderTop: "1px solid #f4f4f5",
              display: "flex",
              justifyContent: "space-between",
            }}
          >
            <button
              onClick={() => setConfirmingRemove(true)}
              style={{
                color: "#dc2626",
                border: "none",
                background: "transparent",
                cursor: "pointer",
                fontSize: 12,
                display: "flex",
                alignItems: "center",
                gap: 4,
              }}
            >
              <X size={12} />
              移出链路
            </button>
            <div style={{ display: "flex", gap: 4 }}>
              <button
                disabled={!props.canMoveUp}
                onClick={props.onMoveUp}
                style={{
                  border: "1px solid #e4e4e7",
                  borderRadius: 5,
                  background: "#fff",
                  cursor: "pointer",
                }}
              >
                <ChevronUp size={12} />
              </button>
              <button
                disabled={!props.canMoveDown}
                onClick={props.onMoveDown}
                style={{
                  border: "1px solid #e4e4e7",
                  borderRadius: 5,
                  background: "#fff",
                  cursor: "pointer",
                }}
              >
                <ChevronDown size={12} />
              </button>
            </div>
          </div>
        </div>
      )}

      {open && confirmingRemove && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            zIndex: 10,
            background: "#fff",
            border: "1px solid #e4e4e7",
            borderRadius: 10,
            boxShadow: "0 8px 28px rgba(0,0,0,0.14)",
            padding: 12,
            marginTop: 4,
            fontSize: 12,
          }}
        >
          <div style={{ marginBottom: 8 }}>确定移除 {props.providerId}?</div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={() => setConfirmingRemove(false)}
              style={{
                border: "1px solid #e4e4e7",
                borderRadius: 6,
                padding: "4px 10px",
                background: "#fff",
                cursor: "pointer",
                fontSize: 12,
              }}
            >
              取消
            </button>
            <button
              onClick={() => {
                props.onRemove();
                setOpen(false);
                setConfirmingRemove(false);
              }}
              style={{
                background: "#dc2626",
                color: "#fff",
                border: "none",
                borderRadius: 6,
                padding: "4px 10px",
                cursor: "pointer",
                fontSize: 12,
              }}
            >
              移除
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
