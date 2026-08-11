type Stage = { key: string; ms: number; over?: boolean; color?: string };

/** 阶段比例条。color 存在时用四色;否则沿用 over/非 over 两态(向后兼容)。 */
export default function StageBar({ stages }: { stages: Stage[] }) {
  const total = stages.reduce((s, x) => s + x.ms, 0) || 1;
  return (
    <div className="flex h-5 rounded overflow-hidden border">
      {stages.map((st) => {
        const useColor = Boolean(st.color);
        return (
          <div
            key={st.key}
            data-seg={st.key}
            data-over={st.over ?? false}
            style={{
              width: `${(st.ms / total) * 100}%`,
              background: useColor
                ? st.color
                : st.over
                  ? "var(--warn)"
                  : "var(--acc-t)",
            }}
            className={
              "flex items-center justify-center text-[11px] " +
              (useColor || st.over ? "text-white" : "text-[var(--acc)]")
            }
          >
            <span>{st.key}</span>
            <span className="ml-1">{st.ms}ms</span>
          </div>
        );
      })}
    </div>
  );
}
