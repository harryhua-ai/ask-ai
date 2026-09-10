import { useState } from "react";
import { Plus, Pencil, Trash2, Power } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { LLMProvider } from "@/types/api";

interface Props {
  providers: LLMProvider[];
  onEdit: (id: string) => void;
  /** #4:删除必须显式确认后才发起;返回 Promise 时确认钮在完成前保持禁用。 */
  onDelete: (id: string) => void | Promise<void>;
  onToggle: (id: string, enabled: boolean) => void;
  onAdd: (id: string) => void;
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
  // 新增走内联输入:window.prompt 在嵌入式浏览器(如 IDE 内嵌 webview)中
  // 会被拦截返回 null,导致添加静默失效(C 修复)。
  const [adding, setAdding] = useState(false);
  const [newId, setNewId] = useState("");
  // #4:删除两步确认 —— 点垃圾桶只进入行内确认态,不发起请求;
  // window.confirm/prompt 同样会被嵌入式浏览器拦截,故用 UI 内确认。
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const confirmDelete = async () => {
    if (!confirmDeleteId || deleting) return;
    setDeleting(true);
    try {
      await onDelete(confirmDeleteId);
    } finally {
      setDeleting(false);
      setConfirmDeleteId(null);
    }
  };

  const confirmAdd = () => {
    const id = newId.trim();
    if (!id) return;
    onAdd(id);
    setAdding(false);
    setNewId("");
  };

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
                {confirmDeleteId === p.id ? (
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-medium text-destructive">
                      删除 {p.id}？
                    </span>
                    <Button
                      variant="destructive"
                      size="sm"
                      disabled={deleting}
                      onClick={confirmDelete}
                    >
                      {deleting ? "删除中..." : "确认删除"}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={deleting}
                      onClick={() => setConfirmDeleteId(null)}
                    >
                      取消
                    </Button>
                  </div>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    aria-label={`删除 ${p.id}`}
                    title={`删除 ${p.id}`}
                    onClick={() => setConfirmDeleteId(p.id)}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                )}
              </div>
            );
          })}
        </div>

        <div className="flex justify-end pt-2">
          {adding ? (
            <div className="flex w-full items-center gap-2">
              <Input
                autoFocus
                placeholder="供应商 ID(如 my-provider)"
                value={newId}
                onChange={(e) => setNewId(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") confirmAdd();
                }}
                className="h-8 text-xs"
              />
              <Button size="sm" onClick={confirmAdd}>
                确认
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setAdding(false);
                  setNewId("");
                }}
              >
                取消
              </Button>
            </div>
          ) : (
            <Button onClick={() => setAdding(true)}>
              <Plus className="mr-1.5 h-4 w-4" />
              新增供应商
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
