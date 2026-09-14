/**
 * Ownership(IF-6 附录,文件内区域互斥):本文件 = **Track E**(观察与导出)
 * Wave 1 专属 —— 导出相关对话卡(U-16 TI-34/35/45):导出卡 + 隐私说明条 +
 * 真实 CSV 下载行为。
 *
 * 冻结语义:admin-only(后端 RBAC 权威;403 时前端诚实呈现权限语义);
 * 范围 = 所选 gap 的权威对话集(window 继承队列激活窗词表);最小必要字段
 * 与隐私排除由后端 IF-5 契约保证(前端不生成 CSV 内容,只触发真实下载)。
 * 挂载面(INT-E-01 收口)= 诊断侧板概览 Tab 推荐操作区(./analytics/GapPanel.tsx);
 * 本组件自包含:`heading` 缺省渲染自带「推荐操作」标题(独立挂载),传入
 * null 时由挂载方提供区块标题(嵌入既有推荐操作区块时避免重复)。
 */

import { useState } from "react";
import { getToken } from "@/lib/api";
import type { AnswerGapItem } from "@/lib/api/techInsight";

export interface GapExportCardProps {
  gap: AnswerGapItem;
  /** 自带区块标题;嵌入既有「推荐操作」区块时传 null(避免重复标题)。 */
  heading?: string | null;
}

export function GapExportCard({ gap, heading = "推荐操作" }: GapExportCardProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function downloadCsv() {
    setBusy(true);
    setError(null);
    try {
      const token = getToken();
      const resp = await fetch(
        `/api/admin/tech/answer-gaps/${gap.id}/conversations/export`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} },
      );
      if (resp.status === 403) {
        setError("无权限执行此操作(导出为管理员专用)。");
        return;
      }
      if (resp.status === 401) {
        window.location.href = "/admin/login";
        return;
      }
      if (!resp.ok) {
        setError("导出失败,请稍后重试。");
        return;
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `gap-conversations-${gap.id.slice(0, 8)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setDone(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section data-gap-export-card>
      {heading && (
        <h3 className="mb-1 text-[13px] font-medium text-[var(--t1)]">{heading}</h3>
      )}
      <button
        type="button"
        data-action="export-gap-conversations"
        disabled={busy}
        onClick={downloadCsv}
        className="block w-full rounded-md border p-3 text-left hover:bg-black/5 disabled:opacity-60"
        style={{ borderColor: "var(--bd)" }}
      >
        <div className="text-[13px] font-medium text-[var(--acc)]">
          ⇪ 导出相关对话{busy ? "(正在导出…)" : done ? "(已下载)" : ""}
        </div>
        <div className="mt-0.5 text-[11px] text-[var(--t3)]">
          导出问题主题对应的原始对话记录(CSV),用于整理并补充知识内容。
        </div>
      </button>
      <div
        data-export-privacy-note
        className="mt-2 flex items-start gap-2 rounded-md px-3 py-2 text-[11px] leading-5"
        style={{
          background: "color-mix(in srgb, var(--acc) 8%, transparent)",
          color: "var(--t2)",
        }}
      >
        <span aria-hidden style={{ color: "var(--acc)" }}>ⓘ</span>
        <span>
          导出内容包含用户问题、对话上下文、当前回答及引用信息,不包含用户个人身份信息。
        </span>
      </div>
      {error && (
        <div data-export-error className="mt-2 text-[12px]" style={{ color: "var(--err)" }}>
          {error}
        </div>
      )}
    </section>
  );
}
