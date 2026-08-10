import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import KpiCard from "@/components/observability/KpiCard";

afterEach(cleanup);

describe("KpiCard", () => {
  it("渲染 label、value、delta 和 baseline", () => {
    render(
      <KpiCard
        label="P95 耗时"
        value={1200}
        unit="ms"
        delta={{ value: -8, dir: "down" }}
        baseline="基线 1000ms"
      />,
    );
    expect(screen.getByText("P95 耗时")).toBeInTheDocument();
    expect(screen.getByText(/1,200/)).toBeInTheDocument();
    expect(screen.getByText(/-8%/)).toBeInTheDocument();
    expect(screen.getByText(/基线/)).toBeInTheDocument();
  });

  it("alarm=true 时 data-alarm 属性为 true", () => {
    render(<KpiCard label="异常率" value={12} unit="%" alarm />);
    expect(screen.getByText("12%").closest("[data-alarm]")).toHaveAttribute(
      "data-alarm",
      "true",
    );
  });
});
