/**
 * v1.6.3 Wave 1 Track B(DEF-A2/A3/A4):SourceEditorDrawer 呈现一致性测试。
 *
 * 冻结依据(Planning 终局,只读合同):
 * - 合同 docs/engineering/tasks/v163-reference-remediation/track-b-contract.md
 *   + remediation plan §6 Track B 授权 + matrix-DS-P5-P6-P7.md DS-P5 行;
 * - 硬参考 = PNG1 面板5「编辑数据源 Drawer」(名称* 必填星号 / 类型 禁用 / 自动同步 toggle+说明);
 * - U-5 冻结语义:create 类型可选;edit 既有源 immutable/disabled(真值零变更);
 * - 零 PUT payload/端点/行为语义变更(enabled 真值映射保持,toggle 仅控件语法收敛)。
 *
 * 覆盖:
 * - DEF-A2(DS-P5-02):产品线 label 收敛为「名称」+必填星号;
 * - DEF-A3(DS-P5-04):edit 态类型 select disabled;create 态类型可选;
 * - DEF-A4(DS-P5-05):「状态/启用」checkbox → 「自动同步」Switch + 逐字说明
 *   「开启后，系统将按设定周期自动同步。」;切换→保存→PUT enabled 真实映射。
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { SourceEditorDrawer } from "@/components/dataSources/SourceEditorDrawer";
import type { DataSource } from "@/types/api";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const createMutate = vi.fn();
const updateMutate = vi.fn();
const deleteMutate = vi.fn();

vi.mock("@/hooks/useDataSources", () => ({
  useCreateDataSource: () => ({ mutateAsync: createMutate, isPending: false }),
  useUpdateDataSource: () => ({ mutateAsync: updateMutate, isPending: false }),
  useDeleteDataSource: () => ({ mutateAsync: deleteMutate, isPending: false }),
  useToggleDataSource: () => ({ mutate: vi.fn() }),
  useRetryDeleteDataSource: () => ({ mutateAsync: vi.fn(), isPending: false }),
  fetchPreviewBranches: vi.fn(),
  fetchPreviewFileTypes: vi.fn(),
  fetchRepoDiscovery: vi.fn(),
  fetchWebsiteDiscovery: vi.fn(),
  uploadSourceFiles: vi.fn(),
  usePreviewDirs: vi.fn(() => ({ data: { dirs: [] }, isLoading: false, error: null })),
}));

beforeEach(() => {
  createMutate.mockReset();
  updateMutate.mockReset();
  deleteMutate.mockReset();
  createMutate.mockResolvedValue({ id: "new-source" });
  updateMutate.mockResolvedValue({});
});

afterEach(cleanup);

const wooSource: DataSource = {
  id: "woo-store",
  type: "woocommerce",
  product: "WooCommerce",
  enabled: true,
  config: { store_url: "https://woocommerce.com" },
  sync_interval: "6h",
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
};

function renderDrawer(editing: DataSource | null) {
  return render(
    <SourceEditorDrawer open onOpenChange={() => {}} editing={editing} />,
  );
}

describe("Track B DEF-A2(DS-P5-02):名称* 字段", () => {
  it("编辑抽屉:产品线 label 收敛为「名称」+必填星号(参考 PNG 面板5)", () => {
    renderDrawer(wooSource);
    const nameLabel = screen.getByText(
      (_content, el) => el?.tagName === "LABEL" && el.getAttribute("for") === "ds-product",
    );
    expect(nameLabel.textContent).toMatch(/^名称\s*\*$/);
    // 必填星号(红星呈现)
    const star = nameLabel.querySelector(".text-destructive");
    expect(star?.textContent).toBe("*");
    // 旧 label「产品线」不再呈现
    expect(screen.queryByText("产品线")).toBeNull();
  });

  it("名称 label 关联输入框且编辑态预填现有真值(WooCommerce)", () => {
    renderDrawer(wooSource);
    const input = screen.getByLabelText(/^名称/);
    expect(input).toHaveValue("WooCommerce");
  });
});

describe("Track B DEF-A3(DS-P5-04,U-5 冻结):类型 immutable 语义", () => {
  it("编辑既有源:类型 select disabled(真 disabled 属性,非 CSS 伪装)", () => {
    renderDrawer(wooSource);
    const typeSelect = screen.getByLabelText("类型");
    expect(typeSelect).toBeDisabled();
    expect(typeSelect).toHaveValue("woocommerce");
  });

  it("新建态:类型选择保留且可选(切换类型呈现对应类型化字段)", () => {
    renderDrawer(null);
    const typeSelect = screen.getByLabelText("类型");
    expect(typeSelect).toBeEnabled();
    fireEvent.change(typeSelect, { target: { value: "web_crawl" } });
    expect(typeSelect).toHaveValue("web_crawl");
    // 类型切换后类型化字段(网站地址)呈现——create 态类型选择能力保留
    expect(screen.getByText("网站地址")).toBeInTheDocument();
  });

  it("编辑态保存:PUT payload 的 type 真值不变(零语义变更)", async () => {
    renderDrawer(wooSource);
    fireEvent.submit(screen.getByRole("button", { name: "保存" }).closest("form")!);
    await waitFor(() => expect(updateMutate).toHaveBeenCalledTimes(1));
    expect(updateMutate.mock.calls[0][0]).toMatchObject({
      id: "woo-store",
      type: "woocommerce",
    });
  });
});

describe("Track B DEF-A4(DS-P5-05):自动同步 toggle", () => {
  it("「状态/启用」checkbox 收敛为「自动同步」Switch + 逐字说明文案", () => {
    renderDrawer(wooSource);
    const toggle = screen.getByRole("switch", { name: "自动同步" });
    expect(toggle).toBeChecked();
    expect(screen.getByText("开启后，系统将按设定周期自动同步。")).toBeInTheDocument();
    // 旧「状态/启用」checkbox 呈现移除
    expect(screen.queryByLabelText("启用")).toBeNull();
  });

  it("禁用源编辑态:toggle 呈现为关(enabled=false 真值映射)", () => {
    renderDrawer({ ...wooSource, enabled: false });
    expect(screen.getByRole("switch", { name: "自动同步" })).not.toBeChecked();
  });

  it("切换自动同步→保存→PUT enabled=false,其余真值(type/product/sync_interval/config)不变", async () => {
    renderDrawer(wooSource);
    const toggle = screen.getByRole("switch", { name: "自动同步" });
    fireEvent.click(toggle);
    expect(toggle).not.toBeChecked();
    fireEvent.submit(screen.getByRole("button", { name: "保存" }).closest("form")!);
    await waitFor(() => expect(updateMutate).toHaveBeenCalledTimes(1));
    expect(updateMutate.mock.calls[0][0]).toMatchObject({
      id: "woo-store",
      type: "woocommerce",
      product: "WooCommerce",
      enabled: false,
      sync_interval: "6h",
      config: { store_url: "https://woocommerce.com" },
    });
  });

  it("新建态默认自动同步开启,创建 payload enabled=true(真值语义不变)", async () => {
    renderDrawer(null);
    fireEvent.change(screen.getByLabelText(/^名称/), {
      target: { value: "WB_TEST" },
    });
    expect(screen.getByRole("switch", { name: "自动同步" })).toBeChecked();
    fireEvent.submit(screen.getByRole("button", { name: "创建" }).closest("form")!);
    await waitFor(() => expect(createMutate).toHaveBeenCalledTimes(1));
    expect(createMutate.mock.calls[0][0]).toMatchObject({
      type: "github",
      product: "WB_TEST",
      enabled: true,
    });
  });
});
