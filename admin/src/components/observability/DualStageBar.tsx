/** 双色水平条:浅 P50 + 深 P95 + 正常区间标注。技术洞察阶段表用。 */
export default function DualStageBar({
  stage,
  p50,
  p95,
  normalMax,
  p50Pct,
  p95Pct,
}: {
  stage: string;
  p50: number;
  p95: number;
  normalMax: number;
  p50Pct: number;
  p95Pct: number;
}) {
  const over = p95 > normalMax;
  const max = Math.max(p95, normalMax, 1);
  return (
    <div data-over={over} className="space-y-1">
      <div className="flex items-center gap-2 text-[12px]">
        <span className="w-20 text-[var(--t2)]">{stage}</span>
        <div
          className="flex-1 h-4 rounded overflow-hidden border relative"
          style={{ borderColor: "var(--bd)" }}
        >
          {/* P95 外条 */}
          <div
            data-seg="p95"
            className="absolute top-0 left-0 h-full rounded"
            style={{
              width: `${(p95 / max) * 100}%`,
              background: over ? "var(--err)" : "var(--acc)",
              opacity: 0.4,
            }}
          />
          {/* P50 内条(叠加) */}
          <div
            data-seg="p50"
            className="absolute top-0 left-0 h-full rounded"
            title={`P50 ${p50.toLocaleString()}ms (${p50Pct}%)`}
            style={{
              width: `${(p50 / max) * 100}%`,
              background: over ? "var(--err)" : "var(--acc)",
            }}
          />
          {/* normalMax 标线 */}
          <div
            data-mark="normal-max"
            className="absolute top-0 h-full w-px"
            style={{ left: `${(normalMax / max) * 100}%`, background: "var(--t3)" }}
          />
        </div>
        <span
          className={
            "tabular-nums " +
            (over ? "text-[var(--err)] font-medium" : "text-[var(--t2)]")
          }
        >
          {p95.toLocaleString()}ms
          <span className="text-[var(--t3)] ml-1">({p95Pct}%)</span>
        </span>
      </div>
    </div>
  );
}
