import { useState } from "react";
import { Plus } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
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
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>添加到 · {task}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label>选供应商</Label>
            {availableProviders.map((p) => {
              const pModels = ((p.config as Record<string, unknown>).available_models as string[]) ?? [];
              return (
                <div
                  key={p.id}
                  onClick={() => {
                    if (!p.enabled) return;
                    setSelected(p.id);
                    setModel(pModels.length > 0 ? pModels[0] : null);
                  }}
                  className={cn(
                    "flex items-center gap-2.5 rounded-md border p-2.5 transition-colors",
                    selected === p.id
                      ? "border-primary border-2"
                      : "border-border",
                    p.enabled ? "cursor-pointer hover:bg-accent" : "cursor-not-allowed opacity-50",
                  )}
                >
                  <span
                    className={cn(
                      "h-3.5 w-3.5 shrink-0 rounded-full border-2",
                      selected === p.id
                        ? "border-primary border-4 bg-primary"
                        : "border-muted-foreground",
                    )}
                  />
                  <span className="text-sm font-semibold">{p.id}</span>
                  {!p.enabled && (
                    <span className="text-xs text-muted-foreground">已停用</span>
                  )}
                </div>
              );
            })}
          </div>

          {provider && models.length > 0 && (
            <div className="space-y-2">
              <Label>用哪个 model</Label>
              <div className="flex gap-1.5 flex-wrap">
                {models.map((m: string) => (
                  <button
                    key={m}
                    onClick={() => setModel(m)}
                    className={cn(
                      "rounded-md border px-2.5 py-1 font-mono text-xs transition-colors",
                      model === m
                        ? "border-primary border-2 bg-primary text-primary-foreground"
                        : "border-border hover:bg-accent",
                    )}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            onClick={() => selected && onAdd(selected, model)}
            disabled={!selected}
          >
            <Plus className="mr-1.5 h-4 w-4" />
            添加到链路
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
