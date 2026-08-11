type Lane = { label: string; ms: number; color: string };

/** Trace 总比例条(按各阶段耗时占比着色)。ms=0 的 lane 不渲染段。 */
export default function LanesBar({ lanes }: { lanes: Lane[] }) {
  const total = lanes.reduce((s, x) => s + x.ms, 0);
  return (
    <div className="space-y-2">
      <div className="flex h-3 rounded overflow-hidden border" data-lanes-bar>
        {total > 0 &&
          lanes
            .filter((l) => l.ms > 0)
            .map((l) => (
              <div
                key={l.label}
                data-seg={l.label}
                style={{ width: `${(l.ms / total) * 100}%`, background: l.color }}
                title={`${l.label}: ${l.ms}ms`}
              />
            ))}
      </div>
      <div className="flex flex-wrap gap-3">
        {lanes.map((l) => (
          <div key={l.label} className="flex items-center gap-1 text-[11px] text-[var(--t2)]">
            <span
              className="inline-block w-2 h-2 rounded-sm"
              style={{ background: l.color }}
              data-legend={l.label}
            />
            <span>{l.label}</span>
            <span className="text-[var(--t3)]">{l.ms}ms</span>
          </div>
        ))}
      </div>
    </div>
  );
}
