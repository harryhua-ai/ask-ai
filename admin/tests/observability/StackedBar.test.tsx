import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import StackedBar from "@/components/observability/StackedBar";

afterEach(cleanup);

describe("StackedBar", () => {
  it("渲染各段按比例宽度 + 图例", () => {
    render(
      <StackedBar
        segments={[
          { label: "销售", value: 30, color: "var(--acc)" },
          { label: "产品", value: 50, color: "var(--ok)" },
          { label: "支持", value: 20, color: "var(--warn)" },
        ]}
      />,
    );
    expect(screen.getByText("销售")).toBeInTheDocument();
    expect(screen.getByText("产品")).toBeInTheDocument();
    expect(screen.getByText("支持")).toBeInTheDocument();
    expect(screen.getByText("30")).toBeInTheDocument();
    const seg = document.querySelector('[data-seg="产品"]');
    expect(seg).toBeTruthy();
  });

  it("total=0 时不渲染段(宽度 0)", () => {
    const { container } = render(
      <StackedBar
        segments={[
          { label: "A", value: 0, color: "var(--acc)" },
          { label: "B", value: 0, color: "var(--ok)" },
        ]}
      />,
    );
    expect(container.querySelectorAll("[data-seg]")).toHaveLength(0);
  });
});
