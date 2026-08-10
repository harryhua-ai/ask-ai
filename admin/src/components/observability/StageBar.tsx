type Stage = { key: string; ms: number; over?: boolean };

export default function StageBar({ stages }: { stages: Stage[] }) {
  const total = stages.reduce((s, x) => s + x.ms, 0) || 1;
  return (
    <div className="flex h-5 rounded overflow-hidden border">
      {stages.map((st) => (
        <div
          key={st.key}
          style={{ width: `${(st.ms / total) * 100}%` }}
          data-over={st.over ?? false}
          className={
            "flex items-center justify-center text-[11px] " +
            (st.over
              ? "bg-[var(--warn)]/15 text-[var(--warn)]"
              : "bg-[var(--acc-t)] text-[var(--acc)]")
          }
        >
          <span>{st.key}</span>
          <span className="ml-1">{st.ms}ms</span>
        </div>
      ))}
    </div>
  );
}
