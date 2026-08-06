import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { ChainChip } from "@/components/ChainChip";

afterEach(cleanup);

describe("ChainChip", () => {
  it("渲染编号 + 供应商名 + model", () => {
    render(
      <ChainChip
        order={1}
        providerId="deepseek"
        model="v4-pro"
        availableModels={["v4-pro", "v4-flash"]}
        onChangeModel={() => {}}
        onRemove={() => {}}
        onMoveUp={() => {}}
        onMoveDown={() => {}}
        canMoveUp={false}
        canMoveDown={true}
      />,
    );
    expect(screen.getByText("deepseek")).toBeInTheDocument();
    expect(screen.getByText("v4-pro")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("model 为 null 时显示默认标签", () => {
    render(
      <ChainChip
        order={1}
        providerId="x"
        model={null}
        availableModels={["m1"]}
        onChangeModel={() => {}}
        onRemove={() => {}}
        onMoveUp={() => {}}
        onMoveDown={() => {}}
        canMoveUp={false}
        canMoveDown={false}
      />,
    );
    expect(screen.getByText(/默认/)).toBeInTheDocument();
  });

  it("点击 chip 展开 popover 含切 model 选项", () => {
    render(
      <ChainChip
        order={1}
        providerId="x"
        model="m1"
        availableModels={["m1", "m2"]}
        onChangeModel={() => {}}
        onRemove={() => {}}
        onMoveUp={() => {}}
        onMoveDown={() => {}}
        canMoveUp={false}
        canMoveDown={false}
      />,
    );
    fireEvent.click(screen.getByText("x"));
    expect(screen.getByText("m2")).toBeInTheDocument();
  });

  it("移除需二次确认", () => {
    const onRemove = vi.fn();
    render(
      <ChainChip
        order={1}
        providerId="x"
        model="m1"
        availableModels={["m1"]}
        onChangeModel={() => {}}
        onRemove={onRemove}
        onMoveUp={() => {}}
        onMoveDown={() => {}}
        canMoveUp={false}
        canMoveDown={false}
      />,
    );
    fireEvent.click(screen.getByText("x")); // 展开 popover
    fireEvent.click(screen.getByText(/移出链路/)); // 点移除入口
    expect(screen.getByText(/确定移除/)).toBeInTheDocument(); // 出现确认
    fireEvent.click(screen.getByText("移除").closest("button")!); // 确认
    expect(onRemove).toHaveBeenCalled();
  });
});
