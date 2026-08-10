import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import TraceLanes from "@/components/observability/TraceLanes";

describe("TraceLanes", () => {
  it("渲染 5 泳道标签、ms 和状态", () => {
    render(
      <TraceLanes
        stages={{
          "intent+rewrite": { ms: 130, status: "ok" },
          retrieve: { ms: 200, status: "ok" },
          rerank: { ms: 120, status: "warn" },
          generate: { ms: 550, status: "ok" },
          output: { ms: 5, status: "ok" },
        }}
      />,
    );
    expect(screen.getByText("前置")).toBeInTheDocument();
    expect(screen.getByText("路由")).toBeInTheDocument();
    expect(screen.getByText("检索")).toBeInTheDocument();
    expect(screen.getByText("生成")).toBeInTheDocument();
    expect(screen.getByText("输出")).toBeInTheDocument();
    expect(screen.getByText("检索").closest("[data-status]")).toHaveAttribute(
      "data-status",
      "warn",
    );
  });
});
