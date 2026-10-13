/** #117 「每日对话量」日柱形图回归。
 *
 * 生产缺陷:行容器 `items-end` 使列不被拉伸(cross-size = 内容高度,不定高),
 * 柱子 `height: N%` 相对不定高父列解析为 0 → 全部塌缩为 minHeight 2px 底线,
 * 与数值完全无关。回归契约:百分比高度链完整(行定高 + 列定高 + 独立绘图区
 * 含块 + 柱百分比,日期标签在绘图区之外,柱无 flex-shrink 失真),
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

  it("高度链:行定高、列定高,列内为 [绘图区, 标签] 顺序(柱底对齐标签顶)", () => {
    const { getByTestId } = render(
      <DailyConversationChart data={[day("2026-10-08", 3)]} />,
    );
    const row = getByTestId("daily-chart-row");
    // 塌缩根因:items-end 让列 cross-size 收缩为内容高度,% 高度链断裂
    expect(row.className).not.toContain("items-end");
    expect(row.className).toContain("h-32");
    const column = row.firstElementChild as HTMLElement;
    // 列被拉伸/显式定高到行高
    expect(column.className).toContain("h-full");
    // 列内顺序:绘图区在上、日期标签在下 → 柱底 = 标签顶,各列底对齐一致
    expect(getByTestId("daily-chart-plot")).toBe(column.firstElementChild);
    expect(column.lastElementChild).not.toBe(column.firstElementChild);
  });

  it("柱的百分比包含块是独立绘图区,标签在区外:绘图区内无同容器兄弟可触发 flex-shrink 失真", () => {
    // review blocker 1(r2):旧实现柱与日期标签同列(同一 flex 容器),
    // 柱 height:100% + 标签高度超出列高,flex-shrink:1 压缩满高柱而
    // 50% 柱不受影响 → 10:5 不再可靠 2:1。结构性契约:柱的包含块是不含
    // 标签的独立绘图区,区内只有柱一个子元素 → 不存在能对柱施加
    // flex-shrink 的兄弟;绘图区以 flex-1+min-h-0 吸收标签高度(行 h-32
    // 定高 → 区高确定),柱按区高百分比等比缩放,比例与区高无关。
    const { getAllByTestId, getByTestId } = render(
      <DailyConversationChart
        data={[day("2026-10-08", 10), day("2026-10-09", 5), day("2026-10-05", 0)]}
      />,
    );
    const bars = getAllByTestId("daily-bar");
    const plots = getAllByTestId("daily-chart-plot");
    expect(plots).toHaveLength(3);
    const columns = Array.from(
      getByTestId("daily-chart-row").children,
    ) as HTMLElement[];
    expect(columns).toHaveLength(3);
    for (let i = 0; i < 3; i++) {
      const plot = plots[i];
      const bar = bars[i];
      const column = columns[i];
      // 柱的百分比包含块 = 绘图区(旧缺陷:包含块是含标签的 flex 列)
      expect(bar.parentElement).toBe(plot);
      expect(bar.parentElement).not.toBe(column);
      // 绘图区内只有柱:无兄弟可与柱竞争 flex-shrink
      expect(plot.children).toHaveLength(1);
      // 标签在绘图区之外(列的直接子节点),且固定自然高度不参与收缩
      const label = column.lastElementChild as HTMLElement;
      expect(plot.contains(label)).toBe(false);
      expect(label.className).toContain("shrink-0");
      // 绘图区吸收标签高度后高度确定(flex-1 + min-h-0,行 h-32 定高)
      expect(plot.className).toContain("flex-1");
      expect(plot.className).toContain("min-h-0");
      // 柱贴绘图区底(区内 justify-end),底部对齐与数值无关
      expect(plot.className).toContain("justify-end");
    }
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
