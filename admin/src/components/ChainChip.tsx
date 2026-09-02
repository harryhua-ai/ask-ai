import { useState, useRef, useEffect } from "react";
import { Check, ChevronDown, ChevronUp, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ChainChipProps {
  /** AFP-002:viewer 只读,隐藏编辑弹层与移除/排序入口。 */
  editable?: boolean;
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
  const editable = props.editable !== false;
  const [open, setOpen] = useState(false);
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || !editable) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setConfirmingRemove(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div ref={ref} className="relative inline-block">
      <button
        onClick={() => (editable ? setOpen(!open) : undefined)}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold transition-colors",
          open
            ? "border-primary bg-primary text-primary-foreground"
            : "border-border bg-card hover:bg-accent",
        )}
      >
        <span className="inline-flex h-3.5 w-3.5 items-center justify-center rounded-full bg-primary text-primary-foreground text-[8px] font-bold">
          {props.order}
        </span>
        {props.providerId}
        <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
          {props.model ?? "默认"}
        </span>
      </button>

      {open && !confirmingRemove && (
        <div className="absolute left-0 top-full z-10 mt-1 w-56 rounded-lg border bg-popover shadow-lg">
          <div className="border-b px-3 py-2">
            <span className="text-[10px] uppercase text-muted-foreground">切换 model</span>
          </div>
          <div className="py-1">
            {props.availableModels.map((m) => (
              <button
                key={m}
                onClick={() => {
                  props.onChangeModel(m);
                  setOpen(false);
                }}
                className={cn(
                  "flex w-full items-center gap-2 px-3 py-1.5 text-left font-mono text-xs transition-colors hover:bg-accent",
                )}
              >
                {props.model === m && <Check className="h-3 w-3 shrink-0" />}
                <span className={props.model === m ? "" : "invisible"}>
                  <Check className="h-3 w-3" />
                </span>
                {m}
              </button>
            ))}
            <button
              onClick={() => {
                props.onChangeModel(null);
                setOpen(false);
              }}
              className="block w-full px-3 py-1.5 text-left text-xs text-muted-foreground transition-colors hover:bg-accent"
            >
              默认
            </button>
          </div>
          <div className="flex items-center justify-between border-t px-3 py-2">
            <button
              onClick={() => setConfirmingRemove(true)}
              className="flex items-center gap-1 text-xs text-destructive transition-opacity hover:opacity-80"
            >
              <X className="h-3 w-3" />
              移出链路
            </button>
            <div className="flex gap-1">
              <button
                disabled={!props.canMoveUp}
                onClick={props.onMoveUp}
                className="rounded border p-0.5 transition-colors hover:bg-accent disabled:opacity-30"
              >
                <ChevronUp className="h-3 w-3" />
              </button>
              <button
                disabled={!props.canMoveDown}
                onClick={props.onMoveDown}
                className="rounded border p-0.5 transition-colors hover:bg-accent disabled:opacity-30"
              >
                <ChevronDown className="h-3 w-3" />
              </button>
            </div>
          </div>
        </div>
      )}

      {open && confirmingRemove && (
        <div className="absolute left-0 top-full z-10 mt-1 w-56 rounded-lg border bg-popover p-3 shadow-lg text-xs">
          <div className="mb-2">确定移除 {props.providerId}?</div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setConfirmingRemove(false)}
            >
              取消
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                props.onRemove();
                setOpen(false);
                setConfirmingRemove(false);
              }}
            >
              移除
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
