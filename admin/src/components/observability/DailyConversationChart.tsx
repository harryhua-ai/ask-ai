import type { TimeseriesDay } from "@/lib/api/businessOverview";

/** 每日对话量柱形图(#117)。
 *
 * 高度链契约:行容器定高(h-32)且**不定底对齐**——旧实现的 `items-end` 使列
 * 不被拉伸(cross-size 收缩为内容高度),柱子 `height: N%` 相对不定高父列
 * 解析为 0,全部塌缩为 2px 底线。列用 `h-full` 显式定高到行高,百分比高度
 * 相对定高可解析;`justify-end` 让柱子仍贴底。
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
            className="flex-1 h-full flex flex-col items-center justify-end"
            title={`${d.date}: ${d.total}`}
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
            <div className="text-[10px] text-[var(--t3)] mt-1">
              {d.date.length > 5 ? d.date.slice(5) : d.date}
            </div>
          </div>
        );
      })}
    </div>
  );
}
