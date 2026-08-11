import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import DualTrendBar from "@/components/observability/DualTrendBar";

describe("DualTrendBar", () => {
  it("渲染双段柱 + 基线虚线 + y 轴刻度 + 超标着色", () => {
    const data = [
      { date: "08-01", p50: 300, p95: 1000 },
      { date: "08-02", p50: 400, p95: 6000 }, // 超 baseline
    ];
    render(<DualTrendBar data={data} baseline={3000} />);
    const bars = document.querySelectorAll("[data-bar]");
    expect(bars.length).toBe(2);
    bars.forEach((b) => {
      expect(b.querySelectorAll("[data-seg='p95']").length).toBe(1);
      expect(b.querySelectorAll("[data-seg='p50']").length).toBe(1);
    });
    // 基线虚线存在
    expect(document.querySelector("[data-baseline]")).toBeTruthy();
    // y 轴刻度存在
    expect(document.querySelector("[data-y-axis]")).toBeTruthy();
    // 超标日(P95 > baseline)有 data-over=true
    expect(bars[1].getAttribute("data-over")).toBe("true");
    expect(bars[0].getAttribute("data-over")).toBe("false");
  });
});
