type Segment = { label: string; value: number; color: string };

/** 意图堆叠条(多色段横向比例条 + 图例)。total=0 时各段等宽 0,不渲染段。 */
export default function StackedBar({ segments }: { segments: Segment[] }) {
  const total = segments.reduce((s, x) => s + x.value, 0);
  return (
    <div>
      <div className="flex h-4 rounded overflow-hidden border" data-stacked-bar>
        {total > 0 &&
          segments.map((seg) => (
            <div
              key={seg.label}
              data-seg={seg.label}
              style={{ width: `${(seg.value / total) * 100}%`, background: seg.color }}
            />
          ))}
      </div>
      {segments.length > 0 && (
        <div className="flex flex-wrap gap-3 mt-2">
          {segments.map((seg) => (
            <div key={seg.label} className="flex items-center gap-1 text-[12px] text-[var(--t2)]">
              <span
                className="inline-block w-2.5 h-2.5 rounded-sm"
                style={{ background: seg.color }}
                data-legend={seg.label}
              />
              <span>{seg.label}</span>
              <span className="text-[var(--t3)]">{seg.value}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
