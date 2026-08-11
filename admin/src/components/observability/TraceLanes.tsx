type LaneStatus = "ok" | "warn" | "err" | "skip";
type StageInfo = { ms: number; status: LaneStatus; details?: string[] };
type Stages = Record<string, StageInfo>;

const LANE = [
  { key: "intent+rewrite", label: "前置" },
  { key: "retrieve", label: "路由" },
  { key: "rerank", label: "检索" },
  { key: "generate", label: "生成" },
  { key: "output", label: "输出" },
];

const STATUS_COLOR: Record<LaneStatus, string> = {
  ok: "var(--ok)",
  warn: "var(--warn)",
  err: "var(--err)",
  skip: "var(--t3)",
};

/** Trace 横向泳道(5 阶段)。skip 状态(无数据/跳过)标灰。 */
export default function TraceLanes({ stages }: { stages: Stages }) {
  return (
    <div className="flex flex-col gap-2" data-trace-lanes>
      {LANE.map((lane) => {
        const s = stages[lane.key] ?? { ms: 0, status: "skip" as LaneStatus };
        const color = STATUS_COLOR[s.status] ?? STATUS_COLOR.ok;
        return (
          <div
            key={lane.key}
            data-status={s.status}
            className="flex flex-col gap-1 border border-[var(--bd)] rounded px-3 py-2"
          >
            <div className="flex items-center gap-3 text-[13px]">
              <span
                className="inline-block w-2.5 h-2.5 rounded-sm"
                style={{ background: color }}
                data-lane-color={lane.key}
              />
              <span className="w-12 text-[var(--t2)]">{lane.label}</span>
              <span style={{ color }}>{s.ms}ms</span>
            </div>
            {s.details?.length ? (
              <div className="ml-6 flex flex-col gap-0.5">
                {s.details.map((d, i) => (
                  <span key={i} className="text-[12px] text-[var(--t3)]">
                    {d}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
