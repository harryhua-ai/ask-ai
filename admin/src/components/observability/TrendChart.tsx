type Day = { date: string; p50: number; p95: number };

export default function TrendChart({
  data,
  baseline,
}: {
  data: Day[];
  baseline?: number;
}) {
  const max = Math.max(...data.map((d) => d.p95), baseline ?? 0) || 1;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-end gap-1 h-40 border-b border-[var(--bd)] pb-1">
        {data.map((d) => (
          <div key={d.date} data-bar className="flex-1 flex flex-col items-center">
            <div className="w-full flex flex-col justify-end" style={{ height: "100%" }}>
              <div
                data-seg="p95"
                style={{ height: `${(d.p95 / max) * 100}%` }}
                className="bg-[var(--acc)]/30 w-full rounded-t"
              />
              <div
                data-seg="p50"
                style={{ height: `${(d.p50 / max) * 100}%` }}
                className="bg-[var(--acc)] w-full"
              />
            </div>
            <span className="text-[10px] text-[var(--t3)] mt-1">{d.date}</span>
          </div>
        ))}
      </div>
      {baseline && (
        <div className="text-[10px] text-[var(--t3)]">基线 {baseline}ms（虚线）</div>
      )}
    </div>
  );
}
