/**
 * Ownership(IF-6 附录,文件内区域互斥):本文件 = **Track E**(观察与导出)
 * Wave 1 专属 —— 诊断侧板观察区(U-15 TI-36/37):「内容补充完成后」区块 +
 * 「▷ 内容已补充,开始观察」主 CTA(副文案逐字)。
 *
 * 三前置门全部由后端状态机权威执行(backend/services/gap_observation.py):
 * ① 操作者确认修复完成(本组件 confirmed=true 请求语义);② 相关源
 * sync/reindex 成功(真实读 sync_runs);③ post-sync 验证成功。任一未过
 * → 409 gates 明细原样呈现,前端不推断、不预判、不伪造成功。
 * 观察中态:观察窗元数据 + 中止观察(OBSERVING→OPEN)。挂载面(INT-E-01
 * 收口)= 诊断侧板概览 Tab 推荐操作区(./analytics/GapPanel.tsx;参考 PNG:
 * 推荐操作 导出相关对话卡 + 内容补充完成后段 + 开始观察大按钮)。
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  abortGapObservation,
  fetchGapObservation,
  startGapObservation,
  type GapObservationState,
} from "@/lib/api/techInsight";
import { ApiError } from "@/lib/api";
import type { AnswerGapItem } from "@/lib/api/techInsight";

export interface GapObservationSectionProps {
  gap: AnswerGapItem;
}

/** 后端 409 gates 明细 → 操作者可读门失败原因(机器真值的忠实转述)。 */
function gateFailureMessage(err: ApiError): string {
  const detail = err.detail as { gates?: Record<string, unknown> } | undefined;
  const gates = detail?.gates;
  if (!gates) return err.message;
  const parts: string[] = [];
  if (gates.confirmation === false) parts.push("操作者确认缺失");
  const sync = gates.sync as Record<string, string> | undefined;
  if (sync && Object.keys(sync).length > 0) parts.push("相关数据源同步未完成或无同步证据");
  const verification = gates.verification as Record<string, string> | undefined;
  if (verification && Object.keys(verification).length > 0)
    parts.push("同步后一致性验证未通过");
  return parts.length > 0
    ? `无法进入观察中:${parts.join(";")}。`
    : `无法进入观察中:${err.message}`;
}

export function GapObservationSection({ gap }: GapObservationSectionProps) {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const obsQuery = useQuery({
    queryKey: ["gap-observation", gap.id],
    queryFn: () => fetchGapObservation(gap.id),
  });
  const obs = obsQuery.data ?? null;

  async function runTransition(action: () => Promise<GapObservationState>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await queryClient.invalidateQueries({ queryKey: ["answer-gaps"] });
      await queryClient.invalidateQueries({ queryKey: ["gap-observation", gap.id] });
      await queryClient.invalidateQueries({ queryKey: ["gap-observation-events", gap.id] });
    } catch (e) {
      setError(
        e instanceof ApiError ? gateFailureMessage(e) : "操作失败,请稍后重试。",
      );
    } finally {
      setBusy(false);
    }
  }

  const observing = gap.status === "observing";

  return (
    <section data-gap-observation>
      {!observing && (
        <>
          <h3 className="mb-1 text-[13px] font-medium text-[var(--t1)]">内容补充完成后</h3>
          <p className="mb-3 text-[12px] leading-5 text-[var(--t2)]">
            请确认内容已经加入对应权威数据源,并已完成 ASK-AI
            数据同步。系统将检查相关知识是否已进入当前服务。
          </p>
          <button
            type="button"
            data-action="start-observation"
            disabled={busy}
            onClick={() => runTransition(() => startGapObservation(gap.id, true))}
            className="flex w-full flex-col items-start rounded-md px-4 py-3 text-left disabled:opacity-60"
            style={{ background: "var(--acc, #2563eb)", color: "#fff" }}
          >
            <span className="text-[14px] font-semibold">▷ 内容已补充,开始观察</span>
            <span className="mt-0.5 text-[11px] font-normal opacity-90">
              系统将验证数据同步状态，通过后进入观察中。
            </span>
          </button>
        </>
      )}

      {observing && obs?.observation && (
        <>
          <h3 className="mb-1 text-[13px] font-medium text-[var(--t1)]">观察中</h3>
          <dl className="mb-3 space-y-1 text-[12px] text-[var(--t2)]">
            <div className="flex justify-between">
              <dt className="text-[var(--t3)]">观察开始</dt>
              <dd className="tabular-nums">
                {obs.observation.started_at
                  ? new Date(obs.observation.started_at).toLocaleString()
                  : "—"}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-[var(--t3)]">观察窗</dt>
              <dd className="tabular-nums">
                {obs.observation.window_ends_at
                  ? new Date(obs.observation.window_ends_at).toLocaleString()
                  : "证据不可用"}
                (默认 {obs.observation.window_days} 天)
              </dd>
            </div>
            {obs.recurrence?.recurred && (
              <div className="flex justify-between" style={{ color: "var(--err)" }}>
                <dt>复现证据</dt>
                <dd className="tabular-nums">{obs.recurrence.new_evidence_count} 条,评估后回待处理</dd>
              </div>
            )}
          </dl>
          <button
            type="button"
            data-action="abort-observation"
            disabled={busy}
            onClick={() => runTransition(() => abortGapObservation(gap.id))}
            className="rounded-md border px-3 py-1.5 text-[12px] disabled:opacity-60"
            style={{ borderColor: "var(--bd)", color: "var(--t2)" }}
          >
            中止观察(回到待处理)
          </button>
        </>
      )}

      {error && (
        <div data-observation-error className="mt-2 text-[12px]" style={{ color: "var(--err)" }}>
          {error}
        </div>
      )}
    </section>
  );
}
