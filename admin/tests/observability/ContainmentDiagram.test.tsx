import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import ContainmentDiagram from "@/components/observability/ContainmentDiagram";

afterEach(cleanup);

describe("ContainmentDiagram", () => {
  it("渲染三层嵌套(anomaly ⊃ retry ⊃ fail) + 计数", () => {
    render(<ContainmentDiagram anomaly={12} retry={6} fail={2} />);
    expect(screen.getByText("异常 12")).toBeInTheDocument();
    expect(screen.getByText("重试 6")).toBeInTheDocument();
    expect(screen.getByText("失败 2")).toBeInTheDocument();
    expect(document.querySelector('[data-level="anomaly"]')).toBeTruthy();
    expect(document.querySelector('[data-level="retry"]')).toBeTruthy();
    expect(document.querySelector('[data-level="fail"]')).toBeTruthy();
  });
});
