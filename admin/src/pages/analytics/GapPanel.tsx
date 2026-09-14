/**
 * Ownership(IF-6 附录,文件内区域互斥)— 诊断侧板(Integration 壳):
 * - 侧板壳/tab 结构/概览/典型问题/相关对话/诊断详情 = **Integration**
 *   (Wave 0B 落位;Wave 1 各轨只消费稳定 props,不编辑本文件);
 * - 诊断结论卡(data-panel-conclusion)= **Track D** 专属文件
 *   ./analytics/DiagnosisConclusion.tsx(本文件零 D 结论实现);
 * - 历史记录 tab 内容(data-panel-history)= **Track E** 专属文件
 *   ./analytics/PanelHistory.tsx(INT-E-01 收口后 = 纯流转时间线);
 * - 观察工作流(U-15 三前置门 CTA/中止)与导出卡(U-16)= **Track E**
 *   自包含组件 ./analytics/GapObservationSection.tsx、./analytics/GapExportCard.tsx,
 *   经 INT-E-01(option a,Independent Review 授权)挂载于**概览 Tab
 *   推荐操作区**(参考位置;概览与历史零重复动作);
 * - meta 计数区(data-panel-stats:相关提问/受影响回答/涉及用户/最近发生)=
 *   **Track F** 专属文件 ./analytics/PanelStats.tsx(U-17 用户聚合挂载面;
 *   window prop = IF-7 接线点,壳传入共享分析窗);
 * - 相关对话 tab = S6 归属会话证据(§3.5 例外面冻结;深链 /conversations?q=)。
 * 状态徽章 = Track E 呈现组件 ./analytics/StatusBadge.tsx;
 * 诊断详情 tab 内原因分类分布呈现 = 既有落位(词表消费经 @/lib/gapCause)。
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  fetchGapConversations,
  type AnswerGapItem,
} from "@/lib/api/techInsight";
import { parseExplicitWindow, type AnalysisWindowSerialized } from "@/lib/analysisWindow";
import type { EvidenceWindowValue } from "@/lib/api/techEvidence";
import { gapCauseLabel } from "@/lib/gapCause";
import { StatusBadge } from "./StatusBadge";
import { relTime } from "./relTime";
import { DiagnosisConclusion } from "./DiagnosisConclusion";
import { PanelHistory } from "./PanelHistory";
import { PanelStats } from "./PanelStats";
import { GapObservationSection } from "./GapObservationSection";
import { GapExportCard } from "./GapExportCard";

const PANEL_TABS = ["概览", "典型问题", "相关对话", "诊断详情", "历史记录"] as const;
type PanelTab = (typeof PANEL_TABS)[number];

/** 壳分析窗序列化值 → PanelStats(U-17)窗参数(预设直通;显式起止拆参)。 */
function toStatsWindow(value: AnalysisWindowSerialized | undefined): {
  window?: EvidenceWindowValue;
  from?: string;
  to?: string;
} {
  if (!value) return {};
  const explicit = parseExplicitWindow(value);
  if (explicit) return { window: "all", from: explicit.from, to: explicit.to };
  return { window: value as EvidenceWindowValue };
}

export interface GapPanelProps {
  gap: AnswerGapItem;
  onClose: () => void;
  /** 共享分析窗(IF-7;AnswerGapsTab 队列激活窗,U-17 聚合窗继承)。 */
  window?: AnalysisWindowSerialized;
}

export default function GapPanel({ gap, onClose, window: windowValue }: GapPanelProps) {
  const [tab, setTab] = useState<PanelTab>("概览");

  const convQuery = useQuery({
    queryKey: ["gap-conversations", gap.id],
    queryFn: () => fetchGapConversations(gap.id, 20),
    enabled: tab === "相关对话",
  });

  const typical = gap.sample_questions;
  const typicalPreview = typical.slice(0, 5);
  const statsWindow = toStatsWindow(windowValue);

  return (
    <div
      data-gap-panel
      className="w-[460px] shrink-0 rounded-lg border"
      style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
    >
      <div className="border-b p-4" style={{ borderColor: "var(--bd)" }}>
        <div className="flex items-start justify-between gap-2">
          <h2 data-panel-title className="text-[16px] font-semibold text-[var(--t1)]">
            {gap.representative_question}
          </h2>
          <div className="flex shrink-0 items-center gap-2">
            <StatusBadge status={gap.status} />
            <button
              type="button"
              onClick={onClose}
              aria-label="关闭"
              className="text-[var(--t3)] hover:text-[var(--t1)]"
            >
              ✕
            </button>
          </div>
        </div>
        <PanelStats gap={gap} {...statsWindow} />
        <div className="mt-3 flex gap-3 border-b" style={{ borderColor: "var(--bd)" }}>
          {PANEL_TABS.map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              data-panel-tab
              onClick={() => setTab(t)}
              className="-mb-px pb-1.5 text-[13px] border-b-2"
              style={{
                borderColor: tab === t ? "var(--acc)" : "transparent",
                color: tab === t ? "var(--acc)" : "var(--t2)",
                fontWeight: tab === t ? 600 : 400,
              }}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-4 p-4">
        {tab === "概览" && (
          <>
            <section>
              <h3 className="mb-1 text-[13px] font-medium text-[var(--t1)]">问题描述</h3>
              <p data-panel-description className="text-[13px] leading-6 text-[var(--t2)]">
                用户围绕「{gap.representative_question}」等主题多次提问,当前窗口内共
                {" "}{gap.question_count} 个相关提问、{gap.impacted_answer_count} 个受影响回答
                {gap.status === "resolved" ? ",已标记为已解决。" : "。"}
              </p>
            </section>

            <DiagnosisConclusion gap={gap} />

            <section>
              <div className="flex items-center justify-between">
                <h3 className="text-[13px] font-medium text-[var(--t1)]">典型问题示例</h3>
                {typical.length > typicalPreview.length && (
                  <button
                    type="button"
                    data-panel-typical-all
                    onClick={() => setTab("典型问题")}
                    className="text-[12px] text-[var(--acc)] hover:underline"
                  >
                    查看全部 ({typical.length})
                  </button>
                )}
              </div>
              <ul data-panel-typical className="mt-1 space-y-1">
                {typicalPreview.length > 0 ? (
                  typicalPreview.map((q, i) => (
                    <li
                      key={i}
                      className="list-disc pl-4 text-[13px] text-[var(--t1)] marker:text-[var(--t1)]"
                    >
                      {q}
                    </li>
                  ))
                ) : (
                  <li className="text-[12px] text-[var(--t3)]">无样例问句证据</li>
                )}
              </ul>
            </section>

            <section>
              <h3 className="mb-1 text-[13px] font-medium text-[var(--t1)]">推荐操作</h3>
              <Link
                to={`/conversations?q=${encodeURIComponent(gap.representative_question)}`}
                data-action="inspect-gap"
                className="block rounded-md border p-3 hover:bg-black/5"
                style={{ borderColor: "var(--bd)" }}
              >
                <div className="text-[13px] font-medium text-[var(--acc)]">
                  查看相关对话 →
                </div>
                <div className="mt-0.5 text-[11px] text-[var(--t3)]">
                  在对话审查中按该主题检索原始对话证据
                </div>
              </Link>
              {/* INT-E-01(option a):E 观察工作流 + 导出卡挂载于概览推荐操作区
                  (参考 PNG 侧板概览:导出相关对话卡 → 内容补充完成后段 →
                  开始观察大按钮);历史记录 Tab 仍 = 纯流转时间线,零重复动作。 */}
              <div className="mt-3">
                <GapExportCard gap={gap} heading={null} />
              </div>
              <div className="mt-3">
                <GapObservationSection gap={gap} />
              </div>
            </section>
          </>
        )}

        {tab === "典型问题" && (
          <section>
            <h3 className="mb-1 text-[13px] font-medium text-[var(--t1)]">
              典型问题({typical.length})
            </h3>
            <ul className="space-y-1">
              {typical.length > 0 ? (
                typical.map((q, i) => (
                  <li key={i} className="list-disc pl-4 text-[13px] text-[var(--t1)] marker:text-[var(--t1)]">
                    {q}
                  </li>
                ))
              ) : (
                <li className="text-[12px] text-[var(--t3)]">无样例问句证据</li>
              )}
            </ul>
          </section>
        )}

        {tab === "相关对话" && (
          <section data-panel-conversations>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-[13px] font-medium text-[var(--t1)]">
                归属对话({convQuery.data?.total ?? "…"})
              </h3>
              <Link
                to={`/conversations?q=${encodeURIComponent(gap.representative_question)}`}
                data-action="inspect-gap"
                className="text-[12px] text-[var(--acc)] hover:underline"
              >
                在对话审查中查看 →
              </Link>
            </div>
            {convQuery.isLoading ? (
              <div className="text-[12px] text-[var(--t3)]">加载中...</div>
            ) : convQuery.isError ? (
              <div className="text-[12px] text-[var(--err)]">
                会话证据读取失败,可经上方入口在对话审查中检索
              </div>
            ) : (convQuery.data?.items.length ?? 0) === 0 ? (
              <div className="text-[12px] text-[var(--t3)]">无归属会话证据</div>
            ) : (
              <div className="space-y-2">
                {convQuery.data!.items.map((c) => (
                  <Link
                    key={c.id}
                    data-panel-conv-row
                    to={`/conversations?q=${encodeURIComponent(c.question)}`}
                    className="block rounded-md border p-2 hover:bg-black/5"
                    style={{ borderColor: "var(--bd)" }}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-[13px] text-[var(--t1)]">
                        {c.question}
                      </span>
                      <span
                        className="shrink-0 rounded px-1.5 py-0.5 text-[11px]"
                        style={{
                          background: c.is_answered
                            ? "color-mix(in srgb, var(--ok) 14%, transparent)"
                            : "color-mix(in srgb, var(--err) 12%, transparent)",
                          color: c.is_answered ? "var(--ok)" : "var(--err)",
                        }}
                      >
                        {c.is_answered ? "已回答" : "未回答"}
                      </span>
                    </div>
                    <div className="mt-0.5 text-[11px] text-[var(--t3)]">
                      {relTime(c.created_at)}
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </section>
        )}

        {tab === "诊断详情" && (
          <section data-panel-diagnosis>
            <h3 className="mb-1 text-[13px] font-medium text-[var(--t1)]">
              原因分类分布(权威)
            </h3>
            {Object.keys(gap.miss_type_breakdown).length > 0 ? (
              <ul className="space-y-1">
                {Object.entries(gap.miss_type_breakdown).map(([k, v]) => (
                  <li key={k} className="flex items-center gap-2 text-[13px] text-[var(--t2)]">
                    <span className="flex-1">{gapCauseLabel(k)}</span>
                    <span className="tabular-nums">{v}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-[12px] text-[var(--t3)]">无会话证据,分类不可用</div>
            )}
            <dl className="mt-3 space-y-1 text-[12px] text-[var(--t2)]">
              <div className="flex justify-between">
                <dt className="text-[var(--t3)]">聚类创建时间</dt>
                <dd className="tabular-nums">
                  {gap.created_at ? new Date(gap.created_at).toLocaleString() : "—"}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-[var(--t3)]">统计周期</dt>
                <dd>
                  {gap.period_start
                    ? `${new Date(gap.period_start).toLocaleDateString()} ~ ${
                        gap.period_end
                          ? new Date(gap.period_end).toLocaleDateString()
                          : "至今"
                      }`
                    : "证据不可用"}
                </dd>
              </div>
            </dl>
          </section>
        )}

        {tab === "历史记录" && <PanelHistory gap={gap} />}
      </div>
    </div>
  );
}
