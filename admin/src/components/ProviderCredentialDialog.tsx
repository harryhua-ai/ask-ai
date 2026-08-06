import { Plus, Pencil, Trash2, Power } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
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
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>供应商凭证</DialogTitle>
        </DialogHeader>

        <div className="space-y-2">
          {providers.map((p) => {
            const cfg = p.config as Record<string, unknown>;
            const modelCount = ((cfg.available_models as string[]) ?? []).length;
            return (
              <div
                key={p.id}
                className={cn(
                  "flex items-center gap-3 rounded-lg border p-3 transition-colors",
                  p.enabled ? "bg-card" : "bg-muted/50 opacity-60",
                )}
              >
                <span
                  className={cn(
                    "h-2 w-2 shrink-0 rounded-full",
                    p.enabled ? "bg-emerald-500" : "bg-muted-foreground/30",
                  )}
                />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold">{p.id}</div>
                  <div className="text-xs text-muted-foreground">
                    {p.type} · {modelCount} 个模型{!p.enabled && " · 已停用"}
                  </div>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onEdit(p.id)}
                >
                  <Pencil className="mr-1 h-3 w-3" />
                  编辑
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onToggle(p.id, !p.enabled)}
                >
                  <Power className="mr-1 h-3 w-3" />
                  {p.enabled ? "停用" : "启用"}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={() => onDelete(p.id)}
                >
                  <Trash2 className="h-3 w-3" />
                </Button>
              </div>
            );
          })}
        </div>

        <div className="flex justify-end pt-2">
          <Button onClick={onAdd}>
            <Plus className="mr-1.5 h-4 w-4" />
            新增供应商
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
