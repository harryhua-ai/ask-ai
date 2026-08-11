import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import GapTypeBadge from "@/components/observability/GapTypeBadge";

describe("GapTypeBadge", () => {
  it("reject 类型渲染灰色 badge", () => {
    render(<GapTypeBadge type="reject" />);
    const badge = screen.getByText("拒答").closest("[data-gap-type]");
    expect(badge).toHaveAttribute("data-gap-type", "reject");
    expect(badge).toHaveStyle({ background: "var(--t3)" });
  });

  it("low 类型渲染橙色 badge", () => {
    render(<GapTypeBadge type="low" />);
    expect(screen.getByText("低相关")).toBeInTheDocument();
  });

  it("召回空 渲染红色", () => {
    render(<GapTypeBadge type="召回空" />);
    const badge = screen.getByText("召回空").closest("[data-gap-type]");
    expect(badge).toHaveStyle({ background: "var(--err)" });
  });
});
