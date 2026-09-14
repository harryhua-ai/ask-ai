/**
 * Ownership: Track A — Wave 1(页面壳:共享分析窗状态 + 顶栏范围接线 +
 * TI-10 工具栏窗选择绑定,IF-7 三控制面呈现;Wave 1 将局部 range 状态升级为
 * 单一共享窗状态并真实联动 BC-1/BC-2,零假联动)。
 * 其余:域内双 Tab 壳 = Integration(Wave 0B 落位);面板实现见 ./analytics/*:
 *   TechPerfTab(S1 性能窗面=Track A)、IncidentSection(S3/S4 例外面冻结)、
 *   SourceHealthSummary(S2 窗面=Track A)、AnswerGapsTab(队列壳 + 区域占位)、
 *   GapPanel(诊断侧板区域占位)、CauseBadge(Track D)、StatusBadge(Track E)。
 * 公共入口冻结:默认导出 Analytics 与命名导出 SourceHealthSummary
 * (既有测试 import 零改动)。
 */

import { useState } from "react";
import TimeFilter from "@/components/observability/TimeFilter";
import { useAnalysisWindow, type AnalysisWindowSerialized } from "@/lib/analysisWindow";
import TechPerfTab from "./analytics/TechPerfTab";
import AnswerGapsTab from "./analytics/AnswerGapsTab";

export { SourceHealthSummary } from "./analytics/SourceHealthSummary";

// ===========================================================================
// v1.6.3 B2 — Technical Insights Convergence(KB-OPS-V163-002 / #57 #58 #59)
// 共享壳:技术性能 + 回答缺口 为同一 技术洞察 域的 sibling tabs。
// 回答缺口 = 只读操作者投影(GET /tech/answer-gaps),无 OBSERVING/导出/修复语义。
// ===========================================================================

type Tab = "tech" | "gaps";

function ShellTab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: string;
}) {
  return (
    <button
      role="tab"
      type="button"
      aria-selected={active}
      data-active={active ? "true" : "false"}
      onClick={onClick}
      className="-mb-px pb-2 text-[14px] border-b-2"
      style={{
        borderColor: active ? "var(--acc)" : "transparent",
        color: active ? "var(--acc)" : "var(--t2)",
        fontWeight: active ? 600 : 400,
      }}
    >
      {children}
    </button>
  );
}

// --------------------------------------------------------------------------- //
// 共享壳
// --------------------------------------------------------------------------- //

export default function Analytics() {
  const [tab, setTab] = useState<Tab>("tech");
  // IF-7:局部 range 状态升级为单一共享分析窗状态(Provider 在位=共享;
  // 隔离渲染回退局部)。TimeFilter(tech tab 控制面)改窗 → 各窗口面真实联动。
  const { value: win, setValue: setWin } = useAnalysisWindow();

  return (
    <div
      className="space-y-5 p-4"
      style={{ background: "var(--bg)", minHeight: "100%" }}
    >
      <div>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-baseline gap-3 flex-wrap">
            {/* A-B2-01(audit):参考「技术洞察」标题为深蓝(RGB 4,3,108 深靛),与主操作蓝区分 */}
            <h1
              className="text-[26px] font-bold"
              style={{ color: "rgb(4, 3, 108)" }}
            >
              技术洞察
            </h1>
            <span className="text-[13px] text-[var(--t2)]">
              从真实用户对话中发现回答问题，定位原因，并形成知识补充和优化闭环。
            </span>
          </div>
          {tab === "tech" && (
            <TimeFilter
              onChange={(c) => {
                // 既有快选(今天/近 7 天/30 天)直传;from/to 此前被丢弃未发送(§3.5 S1)
                // → 现以显式起止表达入共享窗(任一面改窗 → 整页窗口面真实联动)。
                if (c.range) {
                  setWin(c.range as AnalysisWindowSerialized);
                } else if (c.from && c.to) {
                  setWin(`range:${c.from}/${c.to}`);
                }
              }}
            />
          )}
        </div>

        {/* 域内双 Tab:强选中态(蓝色下划线),不拆分顶层域(#57) */}
        <div
          role="tablist"
          data-shell-tabs
          className="mt-3 flex gap-6 border-b"
          style={{ borderColor: "var(--bd)" }}
        >
          <ShellTab active={tab === "tech"} onClick={() => setTab("tech")}>
            技术性能
          </ShellTab>
          <ShellTab active={tab === "gaps"} onClick={() => setTab("gaps")}>
            回答缺口
          </ShellTab>
        </div>
      </div>

      {tab === "tech" && <TechPerfTab window={win} />}
      {tab === "gaps" && <AnswerGapsTab />}
    </div>
  );
}
