import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import NodeFlow from "@/components/observability/NodeFlow";

afterEach(cleanup);

describe("NodeFlow", () => {
  it("渲染节点 + data-tone + 箭头", () => {
    render(
      <NodeFlow
        nodes={[
          { label: "正常 RAG", tone: "ok" },
          { label: "单路检索", tone: "warn" },
        ]}
      />,
    );
    expect(screen.getByText("正常 RAG")).toBeInTheDocument();
    expect(screen.getByText("单路检索")).toBeInTheDocument();
    expect(screen.getByText("→")).toBeInTheDocument();
    expect(document.querySelector('[data-tone="ok"]')).toBeTruthy();
    expect(document.querySelector('[data-tone="warn"]')).toBeTruthy();
  });

  it("单节点不渲染箭头", () => {
    render(<NodeFlow nodes={[{ label: "A", tone: "err" }]} />);
    expect(screen.queryByText("→")).not.toBeInTheDocument();
  });
});
