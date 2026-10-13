import type { TimeseriesDay } from "@/lib/api/businessOverview";

/** 每日对话量柱形图(#117)。
 *
 * 高度链契约(r2 修正):柱的百分比包含块是**独立绘图区**,日期标签在绘图区
 * **之外**——r1 把柱与标签放进同一个 flex 列,柱 `height:100%` + 标签高度
 * 超出列高,`flex-shrink:1`(默认)只压缩满高柱而 50% 柱不受影响,10:5 的
 * 显示比例不再可靠 2:1。现在列(h-full,行 h-32 定高)内是
 * [绘图区(flex-1 min-h-0,区内 justify-end), 标签(shrink-0)]:
 * 绘图区是柱的唯一 flex 容器(区内只有柱一个子元素,不存在能对柱施加
 * flex-shrink 的兄弟);标签高度只影响绘图区的最终高度(flex-1 + min-h-0
 * 吸收全部收缩,行定高 → 区高确定),柱按区高的百分比等比缩放,10:5 与
 * 区高无关恒为 2:1;柱贴区底,各列区底 = 标签顶,列底对齐一致。
 *
 * 零值诚实:total=0 的柱高为 0,不用固定虚假高度伪装真实统计。
 * 日期身份为完整 YYYY-MM-DD(键跨年唯一),展示截短为 MM-DD。
 */
export default function DailyConversationChart({
  data,
}: {
  data: TimeseriesDay[];
}) {
  const max = Math.max(...data.map((t) => t.total), 1);
  return (
    <div className="flex gap-1 h-32" data-testid="daily-chart-row">
      {data.map((d) => {
        const h = (d.total / max) * 100;
        return (
          <div
            key={d.date}
            className="flex-1 h-full flex flex-col items-center"
            title={`${d.date}: ${d.total}`}
          >
            <div
              className="w-full flex-1 min-h-0 flex flex-col justify-end"
              data-testid="daily-chart-plot"
            >
              <div
                className="w-full rounded-t"
                data-testid="daily-bar"
                style={{
                  height: `${h}%`,
                  background: "var(--acc)",
                  minHeight: d.total > 0 ? "2px" : "0",
                }}
              />
            </div>
            <div className="shrink-0 text-[10px] text-[var(--t3)] mt-1">
              {d.date.length > 5 ? d.date.slice(5) : d.date}
            </div>
          </div>
        );
      })}
    </div>
  );
}
