import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import ContainmentDiagram from "@/components/observability/ContainmentDiagram";

afterEach(cleanup);

describe("ContainmentDiagram(OBS-03 语义修正后)", () => {
  it("两层包含(诊断异常 ⊃ 真实失败)+ 降级恢复独立呈现", () => {
    render(<ContainmentDiagram anomaly={12} fail={2} recovered={5} />);
    expect(screen.getByText(/诊断异常 12/)).toBeInTheDocument();
    expect(screen.getByText("真实失败 2")).toBeInTheDocument();
    expect(screen.getByText(/降级恢复 5/)).toBeInTheDocument();
    // 嵌套:fail 在 anomaly 层内;recovered 独立于 anomaly 层
    const anomaly = document.querySelector('[data-level="anomaly"]');
    expect(anomaly).toBeTruthy();
    expect(anomaly?.querySelector('[data-level="fail"]')).toBeTruthy();
    expect(anomaly?.querySelector('[data-level="recovered"]')).toBeNull();
    expect(document.querySelector('[data-level="recovered"]')).toBeTruthy();
  });

  it("异常层标注「≠失败」诊断语义", () => {
    render(<ContainmentDiagram anomaly={3} fail={0} recovered={0} />);
    expect(screen.getByText(/≠失败/)).toBeInTheDocument();
  });
});
