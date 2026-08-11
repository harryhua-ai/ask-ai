/** 横条进度(带百分比)。pct 限制在 [0,100]。 */
export default function ProgressBar({
  label,
  value,
  pct,
  color = "var(--acc)",
}: {
  label: string;
  value: number;
  pct: number;
  color?: string;
}) {
  const clamped = Math.min(Math.max(pct, 0), 100);
  return (
    <div data-progress={label} className="space-y-1">
      <div className="flex justify-between text-[13px]">
        <span>{label}</span>
        <span className="text-[var(--t2)]">
          {value}（{clamped}%）
        </span>
      </div>
      <div className="h-2 rounded-full bg-[var(--bd)] overflow-hidden">
        <div
          data-fill
          className="h-full rounded-full transition-all"
          style={{ width: `${clamped}%`, background: color }}
        />
      </div>
    </div>
  );
}
