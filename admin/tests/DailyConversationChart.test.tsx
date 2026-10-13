/** #117 「每日对话量」日柱形图回归。
 *
 * 生产缺陷:行容器 `items-end` 使列不被拉伸(cross-size = 内容高度,不定高),
 * 柱子 `height: N%` 相对不定高父列解析为 0 → 全部塌缩为 minHeight 2px 底线,
 * 与数值完全无关。回归契约:百分比高度链完整(行定高 + 列定高 + 柱百分比),
 * 零值保持诚实(无固定虚假高度),日期用完整 YYYY-MM-DD 身份(键不跨年冲突)
 * 且展示层截短为 MM-DD。
 */

import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import DailyConversationChart from "@/components/observability/DailyConversationChart";

import type { TimeseriesDay } from "@/lib/api/businessOverview";

function day(date: string, total: number): TimeseriesDay {
  return { date, total, commercial: total, product: 0, support: 0, off_topic: 0 };
}

afterEach(cleanup);

describe("DailyConversationChart (#117)", () => {
  it("柱高百分比与真实计数成比例;零值诚实为 0,不伪装高度", () => {
    const { getAllByTestId } = render(
      <DailyConversationChart
        data={[day("2026-10-08", 10), day("2026-10-09", 5), day("2026-10-05", 0)]}
      />,
    );
    const bars = getAllByTestId("daily-bar");
    expect(bars).toHaveLength(3);
    // 高度 = total / max * 100:11 轮中的 10 与 5 → 100% 与 50%(旧缺陷:全部 2px)
    expect(bars[0]).toHaveStyle({ height: "100%" });
    expect(bars[1]).toHaveStyle({ height: "50%" });
    // 非零柱保留 2px 最小可见底线(比例过小时仍可见)
    expect(bars[0]).toHaveStyle({ minHeight: "2px" });
    expect(bars[1]).toHaveStyle({ minHeight: "2px" });
    // 零值:高度 0 且无最小高度,不用固定虚假高度伪装真实统计
    expect(bars[2]).toHaveStyle({ height: "0%" });
    expect(bars[2]).toHaveStyle({ minHeight: "0px" });
  });

  it("百分比高度链完整:行不定底对齐(无 items-end)、行定高、列定高 h-full", () => {
    const { getByTestId } = render(
      <DailyConversationChart data={[day("2026-10-08", 3)]} />,
    );
    const row = getByTestId("daily-chart-row");
    // 塌缩根因:items-end 让列 cross-size 收缩为内容高度,% 高度链断裂
    expect(row.className).not.toContain("items-end");
    expect(row.className).toContain("h-32");
    const column = row.firstElementChild as HTMLElement;
    // 列被拉伸/显式定高到行高,柱高百分比相对定高可解析
    expect(column.className).toContain("h-full");
    expect(column.className).toContain("justify-end");
  });

  it("日期身份为完整 YYYY-MM-DD(键不因 MM-DD 跨年冲突),展示截短为 MM-DD", () => {
    const { getByTitle, getAllByText } = render(
      <DailyConversationChart data={[day("2025-12-31", 1), day("2026-12-31", 2)]} />,
    );
    // 两个跨年同 MM-DD 日期各自独立渲染(title 用完整日期身份,键不冲突)
    expect(getByTitle("2025-12-31: 1")).toBeInTheDocument();
    expect(getByTitle("2026-12-31: 2")).toBeInTheDocument();
    // 展示文案仍为简短格式 MM-DD(两条同显 12-31,但身份/键不因此冲突)
    expect(getAllByText("12-31")).toHaveLength(2);
  });
});
