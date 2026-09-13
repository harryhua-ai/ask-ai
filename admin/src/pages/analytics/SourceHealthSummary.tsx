/**
 * Ownership: Track A — Wave 1(S2 数据源健康窗面:days=30 硬编码 →
 * 绑定共享分析窗 + 后端 BC-2 /analytics/source-health 全词表,§3.5 能力矩阵;
 * DSH-01 历史可靠性语义原样,禁当前态误读)。其余 = Integration(Wave 0B 落位)。
 */

import { Link } from "react-router-dom";

/** 数据源健康摘要:一行计数 + 跳转链接;逐源明细与操作见数据源管理页。
 *  #21:导出仅为测试 — 内容是历史窗口可靠性(signal=historical_reliability)。 */
export function SourceHealthSummary({
  items,
}: {
  items: { health: string }[];
}) {
  const counts = items.reduce<Record<string, number>>((acc, s) => {
    acc[s.health] = (acc[s.health] ?? 0) + 1;
    return acc;
  }, {});
  const parts: string[] = [];
  if (counts.healthy) parts.push(`正常 ${counts.healthy}`);
  if (counts.degraded) parts.push(`偏低 ${counts.degraded}`);
  // #21:此处是历史窗口可靠性(/analytics/source-health,signal=
  // historical_reliability),不是当前知识健康 —— 低成功率不称「严重」。
  if (counts.critical) parts.push(`历史低成功率 ${counts.critical}`);
  if (counts.insufficient_data) parts.push(`样本不足 ${counts.insufficient_data}`);
  if (counts.disabled) parts.push(`已禁用 ${counts.disabled}`);

  return (
    <div
      className="rounded-lg border p-4"
      style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
      data-source-health-summary
      data-source-health-signal="historical_reliability"
    >
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-[14px] font-medium text-[var(--t1)]">
          数据源历史可靠性(近 30 天)
        </h2>
        <Link
          to="/data-sources"
          className="text-[12px] text-[var(--acc)] hover:underline"
        >
          明细与操作 → 数据源管理
        </Link>
      </div>
      <div className="text-[13px] text-[var(--t2)]">
        {parts.length > 0 ? parts.join(" · ") : "暂无数据源"}
      </div>
    </div>
  );
}
