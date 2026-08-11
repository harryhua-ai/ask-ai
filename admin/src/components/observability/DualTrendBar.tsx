/** 双段趋势柱(P95 外 + P50 内)+ 告警基线虚线 + y 轴刻度。 */
export default function DualTrendBar({
  data,
  baseline,
}: {
  data: { date: string; p50: number; p95: number }[];
  baseline: number;
}) {
  const max = Math.max(...data.map((d) => d.p95), baseline, 1);
  const yAxisTicks = [0, Math.round(max * 0.5), max];
  return (
    <div className="flex gap-2" data-dual-trend>
      {/* y 轴 */}
      <div
        data-y-axis
        className="flex flex-col justify-between text-[10px] text-[var(--t3)] h-40 pb-4 text-right pr-1"
      >
        {yAxisTicks.map((t) => (
          <span key={t}>{t}</span>
        ))}
      </div>
      <div className="flex-1 relative">
        <div className="flex items-end gap-1 h-40 border-b border-[var(--bd)] pb-1 relative">
          {/* 基线虚线 */}
          <div
            data-baseline
            className="absolute left-0 right-0 border-t border-dashed border-[var(--warn)] z-10 pointer-events-none"
            style={{ bottom: `${(baseline / max) * 100}%` }}
          />
          {data.map((d) => {
            const over = d.p95 > baseline;
            return (
              <div
                key={d.date}
                data-bar
                data-over={over}
                title={`${d.date}: P50 ${d.p50}ms / P95 ${d.p95}ms`}
                className="flex-1 flex flex-col justify-end relative"
                style={{ height: "100%" }}
              >
                {/* P95 外条(浅) */}
                <div
                  data-seg="p95"
                  className="w-full rounded-t"
                  style={{
                    height: `${(d.p95 / max) * 100}%`,
                    background: over ? "var(--err)" : "var(--acc)",
                    opacity: 0.4,
                  }}
                />
                {/* P50 内条(深,绝对定位叠加底部) */}
                <div
                  data-seg="p50"
                  className="w-full absolute bottom-0 left-0 rounded-t"
                  style={{
                    height: `${(d.p50 / max) * 100}%`,
                    background: over ? "var(--err)" : "var(--acc)",
                  }}
                />
              </div>
            );
          })}
        </div>
        <div className="flex gap-1 mt-1">
          {data.map((d) => (
            <div
              key={d.date}
              className="flex-1 text-[9px] text-[var(--t3)] text-center"
            >
              {d.date}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
