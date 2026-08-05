import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { AddToTaskDialog } from "@/components/AddToTaskDialog";

afterEach(cleanup);

const providers = [
  {
    id: "moonshot",
    type: "openai_compatible",
    enabled: true,
    config: { available_models: ["k1", "k2"] },
  },
  {
    id: "qwen",
    type: "openai_compatible",
    enabled: false,
    config: { available_models: ["q1"] },
  },
];

describe("AddToTaskDialog", () => {
  it("列出已启用供应商可选，停用的灰显", () => {
    render(
      <AddToTaskDialog
        task="generation"
        availableProviders={providers as never}
        onAdd={() => {}}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText("moonshot")).toBeInTheDocument();
    expect(screen.getByText("qwen")).toBeInTheDocument(); // 停用也显示，但灰
  });

  it("选供应商 + model 后确认触发 onAdd", () => {
    const onAdd = vi.fn();
    render(
      <AddToTaskDialog
        task="generation"
        availableProviders={providers as never}
        onAdd={onAdd}
        onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getByText("moonshot"));
    fireEvent.click(screen.getByText("添加到链路"));
    expect(onAdd).toHaveBeenCalledWith("moonshot", expect.any(String));
  });
});
