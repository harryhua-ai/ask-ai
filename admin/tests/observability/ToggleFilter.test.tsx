import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ToggleFilter from "@/components/observability/ToggleFilter";

describe("ToggleFilter", () => {
  it("active 态有 data-active=true 且点击触发 onToggle", () => {
    const onToggle = vi.fn();
    render(<ToggleFilter label="异常重试" active={true} onToggle={onToggle} />);
    const btn = screen.getByText("异常重试").closest("button")!;
    expect(btn).toHaveAttribute("data-active", "true");
    fireEvent.click(btn);
    expect(onToggle).toHaveBeenCalled();
  });

  it("inactive 态 data-active=false", () => {
    render(<ToggleFilter label="有反馈" active={false} onToggle={() => {}} />);
    expect(
      screen.getByText("有反馈").closest("button"),
    ).toHaveAttribute("data-active", "false");
  });
});
