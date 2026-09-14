/**
 * v1.6.3 Track C(U-12 / DS-P6-01..05):知识设置右侧抽屉。
 *
 * 冻结语义(硬参考 panel 6):
 * - 「时态角色 *」select(CURRENT=用于支持当前有效知识回答。/ HISTORICAL=
 *   仅用于历史问题与证据溯源,不支撑当前事实型断言);
 * - 「新鲜度要求 *」select(12 小时 型词表;超过该时间没有成功更新时,
 *   系统将提醒知识更新服务。)+ 超期提醒与过期态诚实呈现(后端权威);
 * - 取消 / 保存:保存读真值、写真值;时态角色变化 = 高风险变更 →
 *   先预览(计数服务端权威)再经确认 Modal 施加与预览一致 mutation。
 */

import { useEffect, useState } from "react";
import { Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import {
  useKnowledgePreview,
  useKnowledgeSettings,
  useKnowledgeSettingsSave,
} from "@/hooks/useDataSourceKnowledge";
import type { KnowledgePreview } from "@/hooks/useDataSourceKnowledge";
import { RiskPreviewModal, type RiskPreviewData } from "./RiskPreviewModal";

const FRESHNESS_CHOICES = [6, 12, 24, 72, 168];

export interface KnowledgeSettingsDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sourceId: string;
  /** 保存成功后回调(详情页刷新真值面)。 */
  onSaved?: () => void;
}

export function KnowledgeSettingsDrawer({
  open,
  onOpenChange,
  sourceId,
  onSaved,
}: KnowledgeSettingsDrawerProps) {
  const settingsQuery = useKnowledgeSettings(sourceId, open);
  const saveMutation = useKnowledgeSettingsSave(sourceId);
  const previewMutation = useKnowledgePreview(sourceId);

  const [role, setRole] = useState<string>("current");
  const [freshnessHours, setFreshnessHours] = useState<number>(24);
  const [preview, setPreview] = useState<KnowledgePreview | null>(null);

  useEffect(() => {
    if (settingsQuery.data) {
      setRole(settingsQuery.data.role);
      setFreshnessHours(settingsQuery.data.freshness_hours);
    }
  }, [settingsQuery.data]);

  const handleSave = async () => {
    const roleChanged = settingsQuery.data ? role !== settingsQuery.data.role : false;
    try {
      if (roleChanged) {
        // U-13:高风险变更(时态角色)→ 预览(计数服务端权威)→ 确认 Modal
        const p = (await previewMutation.mutateAsync({
          role,
          freshness_hours: freshnessHours,
        })) as unknown as KnowledgePreview;
        setPreview(p);
        return;
      }
      await saveMutation.mutateAsync({ role, freshness_hours: freshnessHours });
      toast.success("知识设置已保存");
      onSaved?.();
      onOpenChange(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败");
    }
  };

  const handleConfirm = async (previewToken: string) => {
    await saveMutation.mutateAsync({
      role,
      freshness_hours: freshnessHours,
      preview_token: previewToken,
    });
    setPreview(null);
    toast.success("知识设置变更已确认并生效(服务状态已重新验证)");
    onSaved?.();
    onOpenChange(false);
  };

  const freshness = settingsQuery.data?.freshness;
  const riskPreview: RiskPreviewData | null = preview
    ? {
        preview_token: preview.preview_token,
        current_policy: preview.current_policy,
        pending_policy: preview.pending_policy,
        impact: preview.impact,
      }
    : null;

  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent data-testid="knowledge-settings-drawer" className="w-[420px]">
          <div className="flex items-center justify-between">
            <SheetTitle>知识设置</SheetTitle>
            <Button
              variant="ghost"
              size="sm"
              className="px-2"
              aria-label="关闭知识设置"
              onClick={() => onOpenChange(false)}
            >
              <X className="h-4 w-4" aria-hidden />
            </Button>
          </div>

          <div className="space-y-6 px-4 pb-4">
            {settingsQuery.isLoading && <p className="text-sm text-muted-foreground">加载中...</p>}
            {settingsQuery.isError && !settingsQuery.data && (
              <p className="text-sm text-destructive">知识设置加载失败(后端不可达)</p>
            )}

            {settingsQuery.data && (
              <>
                {/* 超期提醒(后端权威真值;过期态 Admin 可见,U-12) */}
                {freshness?.overdue && (
                  <div
                    className="rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-700"
                    data-testid="freshness-overdue-alert"
                  >
                    {freshness.basis === "never_synced"
                      ? "该源还没有成功同步记录,当前无法证明知识新鲜度。"
                      : `知识已超过新鲜度要求 ${freshness.overdue_hours_ago ?? 0} 小时(后端权威判定),建议更新服务。`}
                  </div>
                )}

                <div className="space-y-1.5">
                  <Label htmlFor="ks-role">时态角色 *</Label>
                  <select
                    id="ks-role"
                    data-testid="ks-role-select"
                    aria-label="时态角色"
                    className="h-10 w-full rounded-md border px-3 text-sm"
                    value={role}
                    onChange={(e) => setRole(e.target.value)}
                  >
                    <option value="current">CURRENT</option>
                    <option value="historical">HISTORICAL</option>
                  </select>
                  <p className="text-xs text-muted-foreground">
                    {role === "historical"
                      ? "仅用于历史问题与证据溯源,不支撑当前事实型断言。"
                      : "用于支持当前有效知识回答。"}
                  </p>
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="ks-freshness">新鲜度要求 *</Label>
                  <select
                    id="ks-freshness"
                    data-testid="ks-freshness-select"
                    aria-label="新鲜度要求"
                    className="h-10 w-full rounded-md border px-3 text-sm"
                    value={freshnessHours}
                    onChange={(e) => setFreshnessHours(Number(e.target.value))}
                  >
                    {FRESHNESS_CHOICES.map((h) => (
                      <option key={h} value={h}>
                        {h} 小时
                      </option>
                    ))}
                  </select>
                  <p className="text-xs text-muted-foreground">
                    超过该时间没有成功更新时,系统将提醒知识更新服务。
                  </p>
                </div>

                <div className="flex justify-end gap-2 pt-2">
                  <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
                    取消
                  </Button>
                  <Button
                    size="sm"
                    data-testid="ks-save"
                    onClick={handleSave}
                    disabled={saveMutation.isPending || previewMutation.isPending}
                  >
                    {(saveMutation.isPending || previewMutation.isPending) && (
                      <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" aria-hidden />
                    )}
                    保存
                  </Button>
                </div>
              </>
            )}
          </div>
        </SheetContent>
      </Sheet>

      <RiskPreviewModal
        open={preview != null}
        preview={riskPreview}
        confirmPending={saveMutation.isPending}
        onCancel={() => setPreview(null)}
        onConfirm={handleConfirm}
      />
    </>
  );
}
