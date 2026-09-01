type Props = {
  label: string;
  value?: number | null;
  unit?: string;
  delta?: { value: number; dir: "up" | "down" };
  baseline?: string;
  alarm?: boolean;
  /** 语义色调(合同 OBS-02:颜色只表达状态语义,不做装饰性区分)。 */
  tone?: "critical" | "warning" | "ok" | "neutral";
  /** 指标解释行(分母/语义说明,消除裸百分比)。 */
  footnote?: string;
};

const TONE_STYLE: Record<
  NonNullable<Props["tone"]>,
  { border: string; text: string }
> = {
  critical: { border: "var(--err)", text: "var(--err)" },
  warning: { border: "var(--warn)", text: "var(--warn)" },
  ok: { border: "var(--ok)", text: "var(--ok)" },
  neutral: { border: "var(--bd)", text: "var(--t1)" },
};

export default function KpiCard({
  label,
  value,
  unit = "",
  delta,
  baseline,
  alarm,
  tone,
  footnote,
}: Props) {
  const fmt = value != null ? value.toLocaleString() : "—";
  const t = TONE_STYLE[tone ?? "neutral"];
  return (
    <div
      className="rounded-lg border p-4 bg-[var(--panel)]"
      data-alarm={alarm ?? false}
      data-tone={tone ?? "neutral"}
      style={tone && tone !== "neutral" ? { borderColor: t.border } : undefined}
    >
      <div className="text-[13px] text-[var(--t2)]">{label}</div>
      <div
        className="text-2xl font-semibold mt-1"
        style={{ color: tone && tone !== "neutral" ? t.text : "var(--t1)" }}
      >
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
      {footnote && (
        <div className="text-[11px] text-[var(--t3)] mt-1" data-footnote>
          {footnote}
        </div>
      )}
    </div>
  );
}
