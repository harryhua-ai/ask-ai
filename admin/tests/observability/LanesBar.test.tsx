import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import LanesBar from "@/components/observability/LanesBar";

afterEach(cleanup);

describe("LanesBar", () => {
  it("按 ms 占比渲染段 + 图例", () => {
    const { container } = render(
      <LanesBar
        lanes={[
          { label: "前置", ms: 100, color: "var(--acc)" },
          { label: "检索", ms: 200, color: "var(--ok)" },
        ]}
      />,
    );
    expect(container.querySelectorAll("[data-seg]")).toHaveLength(2);
    expect(container.querySelectorAll('[data-legend="前置"]')).toHaveLength(1);
  });

  it("ms=0 的 lane 不渲染比例段(图例仍显示)", () => {
    const { container } = render(
      <LanesBar lanes={[{ label: "路由", ms: 0, color: "var(--t3)" }]} />,
    );
    expect(container.querySelectorAll("[data-seg]")).toHaveLength(0);
    expect(container.querySelectorAll('[data-legend="路由"]')).toHaveLength(1);
  });
});
