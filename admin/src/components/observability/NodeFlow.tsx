type Tone = "ok" | "warn" | "err";
type Node = { label: string; tone: Tone };

const TONE_COLOR: Record<Tone, string> = {
  ok: "var(--ok)",
  warn: "var(--warn)",
  err: "var(--err)",
};

/** 节点-箭头链路图(绿/黄/红色块)。降级链路用。 */
export default function NodeFlow({ nodes }: { nodes: Node[] }) {
  return (
    <div className="flex flex-wrap items-center gap-1" data-node-flow>
      {nodes.map((n, i) => (
        <div key={i} className="flex items-center gap-1">
          <span
            data-node={n.label}
            data-tone={n.tone}
            className="px-2 py-0.5 rounded text-[12px] text-white"
            style={{ background: TONE_COLOR[n.tone] }}
          >
            {n.label}
          </span>
          {i < nodes.length - 1 && (
            <span data-arrow className="text-[var(--t3)]">→</span>
          )}
        </div>
      ))}
    </div>
  );
}
