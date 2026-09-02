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

  it("tone + footnote:语义色调与解释行(OBS-02)", () => {
    render(
      <KpiCard
        label="真实失败"
        value={17}
        unit="%"
        tone="critical"
        footnote="2 / 12 条 trace · 生成失败,用户收到错误提示"
      />,
    );
    expect(screen.getByText("17%").closest("[data-tone]")).toHaveAttribute(
      "data-tone",
      "critical",
    );
    expect(screen.getByText(/2 \/ 12 条 trace/)).toBeInTheDocument();
  });

  it("value=null 显示占位符(无数据态)", () => {
    render(<KpiCard label="诊断异常" value={null} unit="%" />);
    const card = screen.getByText("诊断异常").closest("[data-tone]");
    expect(card?.textContent).toContain("—");
  });
});
