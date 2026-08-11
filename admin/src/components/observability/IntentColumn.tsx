import { Link } from "react-router-dom";
import MiniTrend from "@/components/observability/MiniTrend";

/** 意图深入列(名 + 计数 + 百分比 + 7 日 mini-trend + 下钻链接)。 */
export default function IntentColumn({
  name,
  count,
  pct,
  trend,
  drillTo,
  color = "var(--acc)",
}: {
  name: string;
  count: number;
  pct: number;
  trend: number[];
  drillTo: string;
  color?: string;
}) {
  return (
    <Link
      to={drillTo}
      data-intent-column={name}
      className="block rounded-lg border p-3 hover:opacity-80 transition"
      style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
    >
      <div className="flex items-center justify-between">
        <span className="text-[14px] font-medium text-[var(--t1)]">{name}</span>
        <span className="text-[12px] text-[var(--t3)]">{pct}%</span>
      </div>
      <div className="text-2xl font-semibold text-[var(--t1)] mt-1">{count}</div>
      <div className="mt-2">
        <MiniTrend data={trend} color={color} />
      </div>
    </Link>
  );
}
