import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import MiniTrend from "@/components/observability/MiniTrend";

afterEach(cleanup);

describe("MiniTrend", () => {
  it("渲染 7 根柱(data-bar)", () => {
    const { container } = render(<MiniTrend data={[1, 2, 3, 4, 5, 6, 7]} />);
    expect(container.querySelectorAll("[data-bar]")).toHaveLength(7);
  });

  it("空数组不渲染柱", () => {
    const { container } = render(<MiniTrend data={[]} />);
    expect(container.querySelectorAll("[data-bar]")).toHaveLength(0);
  });

  it("全 0 数据不产生非法高度", () => {
    const { container } = render(<MiniTrend data={[0, 0, 0]} />);
    const bars = container.querySelectorAll("[data-bar]");
    expect(bars).toHaveLength(3);
    bars.forEach((b) => {
      const h = (b as HTMLElement).style.height;
      expect(parseFloat(h)).toBeGreaterThanOrEqual(0);
    });
  });
});
