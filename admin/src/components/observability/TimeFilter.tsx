import { useState } from "react";

type Change = { range?: string; from?: string; to?: string };

export default function TimeFilter({ onChange }: { onChange: (c: Change) => void }) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const quickRanges = [
    { label: "今天", value: "today" },
    { label: "近 7 天", value: "7d" },
    { label: "30 天", value: "30d" },
  ];

  return (
    <div className="flex items-center gap-2 text-[13px]">
      {quickRanges.map((r) => (
        <button
          key={r.value}
          onClick={() => onChange({ range: r.value })}
          className="px-2.5 py-1 rounded border border-[var(--bd)] hover:bg-[var(--acc-t)]"
        >
          {r.label}
        </button>
      ))}
      <input
        type="date"
        aria-label="开始"
        value={from}
        onChange={(e) => setFrom(e.target.value)}
        className="border border-[var(--bd)] rounded px-2 py-1"
      />
      <input
        type="date"
        aria-label="结束"
        value={to}
        onChange={(e) => setTo(e.target.value)}
        className="border border-[var(--bd)] rounded px-2 py-1"
      />
      <button
        onClick={() => onChange({ from, to })}
        className="px-2.5 py-1 rounded bg-[var(--acc)] text-white"
      >
        应用
      </button>
    </div>
  );
}
