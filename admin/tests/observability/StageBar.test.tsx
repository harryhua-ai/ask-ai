import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import StageBar from "@/components/observability/StageBar";

afterEach(cleanup);

describe("StageBar", () => {
  it("渲染 5 个阶段段及对应 ms 标签", () => {
    render(
      <StageBar
        stages={[
          { key: "intent", ms: 50 },
          { key: "rewrite", ms: 80 },
          { key: "retrieve", ms: 200 },
          { key: "rerank", ms: 120 },
          { key: "generate", ms: 550 },
        ]}
      />,
    );
    expect(screen.getByText("intent")).toBeInTheDocument();
    expect(screen.getByText("550ms")).toBeInTheDocument();
  });

  it("over=true 的阶段 data-over=true", () => {
    render(<StageBar stages={[{ key: "generate", ms: 3000, over: true }]} />);
    expect(screen.getByText("generate").closest("[data-over]")).toHaveAttribute(
      "data-over",
      "true",
    );
  });
});
