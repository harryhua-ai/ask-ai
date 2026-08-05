import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
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
});
