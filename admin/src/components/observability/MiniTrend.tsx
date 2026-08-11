/** 迷你柱图(单色,n 根柱)。空数组不渲染柱;全 0 不产生非法高度。 */
export default function MiniTrend({
  data,
  color = "var(--acc)",
}: {
  data: number[];
  color?: string;
}) {
  const max = Math.max(...data, 0) || 1;
  return (
    <div className="flex items-end gap-0.5 h-8" data-mini-trend>
      {data.map((v, i) => (
        <div
          key={i}
          data-bar={i}
          className="flex-1 rounded-t min-w-[2px]"
          style={{
            height: `${Math.max((v / max) * 100, v > 0 ? 6 : 0)}%`,
            background: color,
            minHeight: v > 0 ? "2px" : "0",
          }}
        />
      ))}
    </div>
  );
}
