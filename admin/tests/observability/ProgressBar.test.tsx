import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import ProgressBar from "@/components/observability/ProgressBar";

afterEach(cleanup);

describe("ProgressBar", () => {
  it("渲染 label/value 和 [data-fill]", () => {
    render(<ProgressBar label="中国" value={60} pct={50} />);
    expect(screen.getByText(/中国/)).toBeInTheDocument();
    expect(screen.getByText(/60/)).toBeInTheDocument();
    const fill = document.querySelector("[data-fill]");
    expect(fill).toBeTruthy();
    expect((fill as HTMLElement).style.width).toBe("50%");
  });

  it("pct > 100 被 clamp 到 100", () => {
    render(<ProgressBar label="X" value={200} pct={150} />);
    const fill = document.querySelector("[data-fill]") as HTMLElement;
    expect(fill.style.width).toBe("100%");
  });

  it("pct < 0 被 clamp 到 0", () => {
    render(<ProgressBar label="Y" value={0} pct={-10} />);
    const fill = document.querySelector("[data-fill]") as HTMLElement;
    expect(fill.style.width).toBe("0%");
  });
});
