/**
 * v1.6.3 Track C(U-13 / DS-P7-01..06):高风险变更影响预览 Modal。
 *
 * 冻结语义(硬参考 panel 7):
 * - 变更摘要 before→after(红);预计影响三行计数**全部来自预览端点**
 *   (服务端权威计算,前端零伪造);「不会删除持久知识」蓝系说明条;
 *   「变更后系统将重新验证服务状态」说明;取消 / 确认变更(红);
 * - 确认 = 以预览 token 施加与预览完全一致的 mutation;后端 drift 校验
 *   409 时显式提示重新预览(计数失效),绝不带旧计数硬提交。
 */

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";

export interface RiskPreviewData {
  preview_token: string;
  current_policy: { role: string; freshness_hours: number };
  pending_policy: { role: string; freshness_hours?: number };
  impact: {
    affected_documents: number;
    current_eligibility_change: number;
    historical_eligibility_change: number;
  };
}

const ROLE_LABELS: Record<string, string> = { current: "CURRENT", historical: "HISTORICAL" };

export interface RiskPreviewModalProps {
  open: boolean;
  preview: RiskPreviewData | null;
  confirmPending?: boolean;
  onCancel: () => void;
  onConfirm: (previewToken: string) => void;
  onPreviewInvalid?: () => void;
}

export function RiskPreviewModal({
  open,
  preview,
  confirmPending = false,
  onCancel,
  onConfirm,
  onPreviewInvalid,
}: RiskPreviewModalProps) {
  const [driftMessage, setDriftMessage] = useState<string | null>(null);
  if (!preview) return null;
  const roleChanged = preview.current_policy.role !== preview.pending_policy.role;
  const freshnessChanged =
    preview.pending_policy.freshness_hours != null &&
    preview.pending_policy.freshness_hours !== preview.current_policy.freshness_hours;

  const handleConfirm = async () => {
    setDriftMessage(null);
    try {
      await onConfirm(preview.preview_token);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      // U-13:drift/失效(409)→ 计数不可信,显式要求重新预览
      if (/预览|drift|一致/.test(message)) {
        setDriftMessage(message);
        onPreviewInvalid?.();
      } else {
        toast.error(message);
      }
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onCancel()}>
      <DialogContent data-testid="risk-preview-modal" className="max-w-md">
        <DialogHeader>
          <DialogTitle>确认知识设置变更</DialogTitle>
          <DialogDescription>
            此变更可能影响知识的资格和服务范围,请确认。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {roleChanged && (
            <div>
              <p className="mb-1 text-sm font-medium">时态角色</p>
              <p className="flex items-center gap-2 text-sm">
                <span className="rounded border px-1.5 py-0.5 font-mono text-xs">
                  {ROLE_LABELS[preview.current_policy.role] ?? preview.current_policy.role}
                </span>
                <span aria-hidden>→</span>
                <span className="rounded border border-red-300 bg-red-50 px-1.5 py-0.5 font-mono text-xs text-red-600">
                  {ROLE_LABELS[preview.pending_policy.role] ?? preview.pending_policy.role}
                </span>
              </p>
            </div>
          )}
          {freshnessChanged && (
            <div>
              <p className="mb-1 text-sm font-medium">新鲜度要求</p>
              <p className="flex items-center gap-2 text-sm">
                <span className="rounded border px-1.5 py-0.5 font-mono text-xs">
                  {preview.current_policy.freshness_hours} 小时
                </span>
                <span aria-hidden>→</span>
                <span className="rounded border px-1.5 py-0.5 font-mono text-xs">
                  {preview.pending_policy.freshness_hours} 小时
                </span>
              </p>
            </div>
          )}

          <div className="rounded-md border p-3 text-sm">
            <p className="mb-2 font-medium">预计影响</p>
            <dl className="space-y-1" data-testid="risk-preview-impact">
              <div className="flex items-center justify-between">
                <dt className="text-muted-foreground">受影响知识</dt>
                <dd className="font-medium">{preview.impact.affected_documents}</dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-muted-foreground">当前知识资格将变化</dt>
                <dd className="font-medium">{preview.impact.current_eligibility_change}</dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-muted-foreground">历史知识资格将变化</dt>
                <dd className="font-medium">{preview.impact.historical_eligibility_change}</dd>
              </div>
            </dl>
          </div>

          <div className="rounded-md border border-blue-200 bg-blue-50 p-3 text-xs text-blue-800">
            <p>ⓘ 不会删除持久知识。</p>
            <p>变更后系统将重新验证服务状态。</p>
          </div>

          {driftMessage && (
            <p className="rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-700">
              {driftMessage}(预览已失效,请关闭后重新保存以重算影响。)
            </p>
          )}

          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={onCancel} disabled={confirmPending}>
              取消
            </Button>
            <Button
              variant="destructive"
              size="sm"
              data-testid="risk-preview-confirm"
              onClick={handleConfirm}
              disabled={confirmPending}
            >
              {confirmPending && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" aria-hidden />}
              确认变更
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
