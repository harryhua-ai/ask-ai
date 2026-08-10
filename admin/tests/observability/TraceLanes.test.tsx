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

  it("显示每条泳道的诊断 details", () => {
    render(
      <TraceLanes
        stages={{
          "intent+rewrite": { ms: 130, status: "ok", details: ["意图 product"] },
          retrieve: { ms: 200, status: "ok", details: ["召回 15 条"] },
          rerank: { ms: 120, status: "warn", details: ["top分 0.820"] },
          generate: { ms: 550, status: "ok", details: ["输出 120 token"] },
          output: { ms: 5, status: "ok", details: ["来源 3 条"] },
        }}
      />,
    );
    expect(screen.getByText("召回 15 条")).toBeInTheDocument();
    expect(screen.getByText("top分 0.820")).toBeInTheDocument();
    expect(screen.getByText("输出 120 token")).toBeInTheDocument();
    expect(screen.getByText("来源 3 条")).toBeInTheDocument();
  });
});
