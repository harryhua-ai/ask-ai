import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import TrendChart from "@/components/observability/TrendChart";

describe("TrendChart", () => {
  it("渲染每日柱，每柱含 p95 + p50 两段", () => {
    render(
      <TrendChart
        data={[
          { date: "08-04", p50: 400, p95: 1200 },
          { date: "08-05", p50: 350, p95: 900 },
        ]}
      />,
    );
    expect(screen.getByText("08-04")).toBeInTheDocument();
    const bars = document.querySelectorAll("[data-bar]");
    expect(bars.length).toBe(2);
    bars.forEach((b) => {
      expect(b.querySelectorAll("[data-seg='p95']").length).toBe(1);
      expect(b.querySelectorAll("[data-seg='p50']").length).toBe(1);
    });
  });

  it("传入 baseline 时显示基线标注", () => {
    render(
      <TrendChart data={[{ date: "08-04", p50: 400, p95: 1200 }]} baseline={1000} />,
    );
    expect(screen.getByText(/基线/)).toBeInTheDocument();
  });
});
