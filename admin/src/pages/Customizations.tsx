import { useState } from "react";
import {
  useCustomizations,
  useBindings,
  useUpdateCustomization,
  useUpdateBinding,
} from "@/hooks/useCustomizations";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import type { Customization } from "@/types/api";
import { useAuth } from "@/hooks/useAuth";
import LoadError from "@/components/LoadError";

/** 与后端 VALID_CHANNELS 对齐。 */
const CHANNELS = ["widget", "discord", "whatsapp", "mcp"] as const;

export default function Customizations() {
  const { user } = useAuth();
  // AFP-CLOSURE-01 §6.5:viewer 只读——编辑/保存/绑定控件不可操作
  const canWrite = user?.role === "admin" || user?.role === "editor";
  const { data: customizations, isLoading, isError, error, refetch } = useCustomizations();
  const { data: bindings } = useBindings();
  const updateCust = useUpdateCustomization();
  const updateBinding = useUpdateBinding();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<Partial<Customization>>({});

  const bindingMap = new Map(
    (bindings || []).map((b) => [b.channel, b.customization_id] as const),
  );

  const startEdit = (cust: Customization) => {
    setEditingId(cust.id);
    setEditForm({
      system_prompt: cust.system_prompt,
      style_tone: cust.style_tone,
      guardrails: cust.guardrails,
      assistant_name: cust.assistant_name,
    });
  };

  const handleSave = async () => {
    if (!editingId) return;
    await updateCust.mutateAsync({ id: editingId, ...editForm });
    setEditingId(null);
  };

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">对话接入</h1>

      {/* 渠道绑定矩阵 */}
      <div className="rounded-lg border bg-card p-4">
        <h2 className="mb-3 text-lg font-semibold">渠道绑定</h2>
        <div className="grid grid-cols-4 gap-3">
          {CHANNELS.map((ch) => (
            <div key={ch} className="space-y-1">
              <Label className="text-xs uppercase text-muted-foreground">
                {ch}
              </Label>
              <select
                className="h-9 w-full rounded-md border px-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
                value={bindingMap.get(ch) || ""}
                disabled={!canWrite}
                title={canWrite ? undefined : "只读账号(viewer)不可修改渠道绑定"}
                onChange={(e) =>
                  updateBinding.mutate({
                    channel: ch,
                    customization_id: e.target.value,
                  })
                }
              >
                <option value="">未绑定</option>
                {customizations?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </div>
      </div>

      {/* 对话接入 列表 */}
      <div className="space-y-3">
        {isError && !customizations && (
          <LoadError error={error} onRetry={refetch} />
        )}
        {isLoading && !isError ? (
          <div className="text-center">加载中...</div>
        ) : (
          customizations && !isError && customizations.map((cust) => (
            <div key={cust.id} className="rounded-lg border bg-card p-4">
              <div className="mb-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <h3 className="font-semibold">{cust.name}</h3>
                  <Badge variant="outline">{cust.id}</Badge>
                  <Badge variant={cust.is_active ? "success" : "destructive"}>
                    {cust.is_active ? "启用" : "停用"}
                  </Badge>
                </div>
                {canWrite && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      editingId === cust.id
                        ? setEditingId(null)
                        : startEdit(cust)
                    }
                  >
                    {editingId === cust.id ? "取消" : "编辑"}
                  </Button>
                )}
              </div>
              {editingId === cust.id ? (
                <div className="space-y-3">
                  <div className="space-y-1">
                    <Label>System Prompt</Label>
                    <Textarea
                      className="font-mono text-sm"
                      rows={8}
                      value={editForm.system_prompt || ""}
                      onChange={(e) =>
                        setEditForm({ ...editForm, system_prompt: e.target.value })
                      }
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <Label>风格语气</Label>
                      <Textarea
                        rows={3}
                        value={editForm.style_tone || ""}
                        onChange={(e) =>
                          setEditForm({ ...editForm, style_tone: e.target.value })
                        }
                      />
                    </div>
                    <div className="space-y-1">
                      <Label>边界规则</Label>
                      <Textarea
                        rows={3}
                        value={editForm.guardrails || ""}
                        onChange={(e) =>
                          setEditForm({ ...editForm, guardrails: e.target.value })
                        }
                      />
                    </div>
                  </div>
                  <Button onClick={handleSave} disabled={updateCust.isPending}>
                    保存
                  </Button>
                </div>
              ) : (
                <div className="space-y-1">
                  <p className="text-sm text-muted-foreground">
                    {cust.assistant_name} · {cust.language}
                  </p>
                  <pre className="max-h-32 overflow-auto rounded bg-muted p-2 text-xs">
                    {cust.system_prompt.slice(0, 500)}
                    {cust.system_prompt.length > 500 ? "..." : ""}
                  </pre>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
