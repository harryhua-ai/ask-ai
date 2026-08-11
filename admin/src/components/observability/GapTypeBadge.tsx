/** 缺口类型标签:拒答灰/召回空红/低相关橙/召回不足黄。 */
const GAP_CONFIG: Record<string, { label: string; color: string }> = {
  reject: { label: "拒答", color: "var(--t3)" },
  "召回空": { label: "召回空", color: "var(--err)" },
  low: { label: "低相关", color: "var(--warn)" },
  "召回不足": { label: "召回不足", color: "var(--acc)" },
};

export default function GapTypeBadge({ type }: { type: string }) {
  const cfg = GAP_CONFIG[type] ?? { label: type, color: "var(--t3)" };
  return (
    <span
      data-gap-type={type}
      className="inline-flex items-center rounded px-1.5 py-0.5 text-[11px] text-white"
      style={{ background: cfg.color }}
    >
      {cfg.label}
    </span>
  );
}
