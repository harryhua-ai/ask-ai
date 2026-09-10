import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { ProviderCredentialDialog } from "@/components/ProviderCredentialDialog";

afterEach(cleanup);

const providers = [
  {
    id: "deepseek",
    type: "openai_compatible",
    enabled: true,
    config: { available_models: ["m1", "m2"] },
  },
  {
    id: "moonshot",
    type: "openai_compatible",
    enabled: false,
    config: { available_models: ["k1"] },
  },
];

describe("ProviderCredentialDialog", () => {
  it("列出全部供应商 + 模型数", () => {
    render(
      <ProviderCredentialDialog
        providers={providers as never}
        onEdit={() => {}}
        onDelete={() => {}}
        onToggle={() => {}}
        onAdd={() => {}}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText("deepseek")).toBeInTheDocument();
    expect(screen.getByText(/2 个模型/)).toBeInTheDocument();
    expect(screen.getByText("moonshot")).toBeInTheDocument();
    expect(screen.getByText(/1 个模型/)).toBeInTheDocument();
  });

  it("点编辑触发 onEdit", () => {
    const onEdit = vi.fn();
    render(
      <ProviderCredentialDialog
        providers={providers as never}
        onEdit={onEdit}
        onDelete={() => {}}
        onToggle={() => {}}
        onAdd={() => {}}
        onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getAllByText("编辑")[0]);
    expect(onEdit).toHaveBeenCalledWith("deepseek");
  });

  it("停用的供应商灰显", () => {
    render(
      <ProviderCredentialDialog
        providers={providers as never}
        onEdit={() => {}}
        onDelete={() => {}}
        onToggle={() => {}}
        onAdd={() => {}}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText(/已停用/)).toBeInTheDocument();
  });

  it("C-修复: 新增走内联输入(嵌入式浏览器可用),确认后回调供应商 ID", () => {
    const onAdd = vi.fn();
    render(
      <ProviderCredentialDialog
        providers={providers as never}
        onEdit={() => {}}
        onDelete={() => {}}
        onToggle={() => {}}
        onAdd={onAdd}
        onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getByText("新增供应商"));
    // 内联输入出现(不再依赖 window.prompt——嵌入式浏览器会拦截)
    const input = screen.getByPlaceholderText("供应商 ID(如 my-provider)");
    fireEvent.change(input, { target: { value: "my-provider" } });
    fireEvent.click(screen.getByText("确认"));
    expect(onAdd).toHaveBeenCalledWith("my-provider");
  });

  it("C-修复: 空 ID 确认不回调", () => {
    const onAdd = vi.fn();
    render(
      <ProviderCredentialDialog
        providers={providers as never}
        onEdit={() => {}}
        onDelete={() => {}}
        onToggle={() => {}}
        onAdd={onAdd}
        onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getByText("新增供应商"));
    fireEvent.click(screen.getByText("确认"));
    expect(onAdd).not.toHaveBeenCalled();
  });
});

describe("#4 删除两步确认(block-if-referenced 前端守卫)", () => {
  const props = (onDelete: (id: string) => void | Promise<void>) => ({
    providers: providers as never,
    onEdit: () => {},
    onDelete,
    onToggle: () => {},
    onAdd: () => {},
    onClose: () => {},
  });

  it("点垃圾桶只进入行内确认态,不调用 onDelete、不发请求", () => {
    const onDelete = vi.fn();
    render(<ProviderCredentialDialog {...props(onDelete)} />);
    fireEvent.click(screen.getByLabelText("删除 deepseek"));
    expect(screen.getByText("删除 deepseek？")).toBeInTheDocument();
    expect(onDelete).not.toHaveBeenCalled();
  });

  it("取消退出确认态且不调用 onDelete", () => {
    const onDelete = vi.fn();
    render(<ProviderCredentialDialog {...props(onDelete)} />);
    fireEvent.click(screen.getByLabelText("删除 moonshot"));
    fireEvent.click(screen.getByText("取消"));
    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.queryByText("确认删除")).not.toBeInTheDocument();
    // 垃圾桶恢复可再点
    expect(screen.getByLabelText("删除 moonshot")).toBeInTheDocument();
  });

  it("确认删除恰调用一次 onDelete 且只带该行 id", async () => {
    const onDelete = vi.fn().mockResolvedValue(undefined);
    render(<ProviderCredentialDialog {...props(onDelete)} />);
    fireEvent.click(screen.getByLabelText("删除 deepseek"));
    fireEvent.click(screen.getByText("确认删除"));
    await waitFor(() => expect(onDelete).toHaveBeenCalledTimes(1));
    expect(onDelete).toHaveBeenCalledWith("deepseek");
    // 完成后退出确认态
    await waitFor(() =>
      expect(screen.queryByText("确认删除")).not.toBeInTheDocument(),
    );
  });

  it("确认请求进行中按钮禁用,其余行垃圾桶不受影响", () => {
    const onDelete = () => new Promise<void>(() => {});
    render(<ProviderCredentialDialog {...props(onDelete)} />);
    fireEvent.click(screen.getByLabelText("删除 deepseek"));
    fireEvent.click(screen.getByText("确认删除"));
    // 请求进行中:按钮切换为「删除中...」且禁用
    const pendingBtn = screen.getByText("删除中...").closest("button") as HTMLButtonElement;
    expect(pendingBtn.disabled).toBe(true);
    expect((screen.getByText("取消").closest("button") as HTMLButtonElement).disabled).toBe(true);
    // 另一行的垃圾桶仍是普通按钮(未进入确认态)
    expect(screen.getByLabelText("删除 moonshot")).toBeInTheDocument();
  });
});
