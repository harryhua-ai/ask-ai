import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import DualStageBar from "@/components/observability/DualStageBar";

describe("DualStageBar", () => {
  it("渲染 P50(浅)+ P95(深)双段 + 超标 data-over=true", () => {
    render(
      <DualStageBar
        stage="generate"
        p50={100}
        p95={3000}
        normalMax={2000}
        p50Pct={5}
        p95Pct={15}
      />,
    );
    expect(screen.getByText("generate")).toBeInTheDocument();
    const p50 = document.querySelector("[data-seg='p50']");
    const p95 = document.querySelector("[data-seg='p95']");
    expect(p50).toBeTruthy();
    expect(p95).toBeTruthy();
    // P95 超 normalMax → over
    expect(screen.getByText("generate").closest("[data-over]")).toHaveAttribute(
      "data-over",
      "true",
    );
  });

  it("未超标 data-over=false", () => {
    render(
      <DualStageBar
        stage="intent"
        p50={50}
        p95={80}
        normalMax={500}
        p50Pct={3}
        p95Pct={4}
      />,
    );
    expect(screen.getByText("intent").closest("[data-over]")).toHaveAttribute(
      "data-over",
      "false",
    );
  });
});
