import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import IntentColumn from "@/components/observability/IntentColumn";

afterEach(cleanup);

function wrap(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe("IntentColumn", () => {
  it("渲染名称/计数/百分比/下钻链接", () => {
    wrap(<IntentColumn name="销售咨询" count={30} pct={25} trend={[1, 2, 3]} drillTo="/c?x" />);
    expect(screen.getByText("销售咨询")).toBeInTheDocument();
    expect(screen.getByText("30")).toBeInTheDocument();
    expect(screen.getByText("25%")).toBeInTheDocument();
    const col = document.querySelector("[data-intent-column='销售咨询']");
    expect(col).toBeTruthy();
    expect(col?.querySelector("a, [href]") ?? col).toBeTruthy();
  });

  it("渲染 7 日 mini-trend 柱", () => {
    const { container } = wrap(
      <IntentColumn name="X" count={1} pct={1} trend={[1, 2, 3, 4, 5, 6, 7]} drillTo="/x" />,
    );
    expect(container.querySelectorAll("[data-bar]")).toHaveLength(7);
  });
});
