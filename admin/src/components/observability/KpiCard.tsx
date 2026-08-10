type Props = {
  label: string;
  value?: number | null;
  unit?: string;
  delta?: { value: number; dir: "up" | "down" };
  baseline?: string;
  alarm?: boolean;
};

export default function KpiCard({ label, value, unit = "", delta, baseline, alarm }: Props) {
  const fmt = value != null ? value.toLocaleString() : "—";
  return (
    <div
      className="rounded-lg border p-4 bg-[var(--panel)]"
      data-alarm={alarm ?? false}
    >
      <div className="text-[13px] text-[var(--t2)]">{label}</div>
      <div className="text-2xl font-semibold mt-1 text-[var(--t1)]">
        {fmt}
        {unit}
      </div>
      {delta && (
        <div
          className={
            "text-[12px] mt-1 " +
            (delta.dir === "down" ? "text-[var(--ok)]" : "text-[var(--err)]")
          }
        >
          {delta.value > 0 ? "+" : ""}
          {delta.value}%
        </div>
      )}
      {baseline && <div className="text-[12px] text-[var(--t3)] mt-1">{baseline}</div>}
    </div>
  );
}
