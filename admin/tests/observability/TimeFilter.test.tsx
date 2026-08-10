import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import TimeFilter from "@/components/observability/TimeFilter";

afterEach(cleanup);

describe("TimeFilter", () => {
  it("快捷按钮触发 onChange({ range })", () => {
    const onChange = vi.fn();
    render(<TimeFilter onChange={onChange} />);
    fireEvent.click(screen.getByText("近 7 天"));
    expect(onChange).toHaveBeenCalledWith({ range: "7d" });
  });

  it("自定义日期 + 应用按钮触发 onChange({ from, to })", () => {
    const onChange = vi.fn();
    render(<TimeFilter onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("开始"), {
      target: { value: "2026-08-01" },
    });
    fireEvent.change(screen.getByLabelText("结束"), {
      target: { value: "2026-08-05" },
    });
    fireEvent.click(screen.getByText("应用"));
    expect(onChange).toHaveBeenCalledWith({
      from: "2026-08-01",
      to: "2026-08-05",
    });
  });
});
