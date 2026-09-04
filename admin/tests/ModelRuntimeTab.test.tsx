// 模型运行 Tab 验收(§35 API 子集):真实设备呈现/三 workload 配置与真相
// (Configured/Effective/Status)/共享运行时指示/容量状态/GPU 预算 auto+manual。

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";

const apiFetch = vi.fn();

vi.mock("@/lib/api", () => ({
  apiFetch: (...args: unknown[]) => apiFetch(...args),
}));

import ModelRuntimeTab from "@/components/ModelRuntimeTab";

const RUNTIME = {
  devices: [
    {
      kind: "gpu",
      uuid: "GPU-3caad314",
      index: 0,
      label: "NVIDIA Tesla T4 · GPU 0",
      name: "NVIDIA Tesla T4",
      total_memory_mb: 15564,
    },
    {
      kind: "cpu",
      uuid: null,
      index: null,
      label: "CPU · Intel Xeon Gold 6133",
      name: "Intel Xeon Gold 6133",
      logical_cores: 8,
    },
  ],
  policies: [
    {
      workload: "query_embedding",
      model_name: "BAAI/bge-m3",
      configured: { kind: "gpu", gpu_uuid: "GPU-3caad314", label: "NVIDIA Tesla T4 · GPU 0" },
      effective: { kind: "gpu", gpu_uuid: "GPU-3caad314", label: "NVIDIA Tesla T4 · GPU 0" },
      status: "loaded",
      shared: true,
      fallback_reason: null,
      fallback_detail: null,
    },
    {
      workload: "sync_embedding",
      model_name: "BAAI/bge-m3",
      configured: { kind: "gpu", gpu_uuid: "GPU-3caad314", label: "NVIDIA Tesla T4 · GPU 0" },
      effective: { kind: "gpu", gpu_uuid: "GPU-3caad314", label: "NVIDIA Tesla T4 · GPU 0" },
      status: "loaded",
      shared: true,
      fallback_reason: null,
      fallback_detail: null,
    },
    {
      workload: "query_reranker",
      model_name: "BAAI/bge-reranker-v2-m3",
      configured: { kind: "cpu", gpu_uuid: null, label: "CPU · Intel Xeon Gold 6133" },
      effective: { kind: "cpu", gpu_uuid: null, label: "CPU · Intel Xeon Gold 6133" },
      status: "loaded",
      shared: false,
      fallback_reason: null,
      fallback_detail: null,
    },
  ],
  shared_embedding_runtime: true,
  capacity: {
    state: "CAPACITY_LIMITED",
    budget_mode: "auto",
    budget_mb: 3960,
    gpu_uuid: "GPU-3caad314",
    gpu_total_mb: 15564,
    gpu_used_mb: 11600,
    gpu_free_mb: 3960,
    askai_resident_mb: 4044,
    peak_reserve_mb: 512,
  },
};

function renderTab(canWrite = true) {
  return render(<ModelRuntimeTab canWrite={canWrite} />);
}

beforeEach(() => {
  apiFetch.mockReset();
  apiFetch.mockImplementation((path: string) => {
    if (path === "/model-runtime") return Promise.resolve(RUNTIME);
    return Promise.reject(new Error(`unexpected ${path}`));
  });
});

afterEach(cleanup);

describe("ModelRuntimeTab(§35 模型运行)", () => {
  it("呈现真实发现设备(GPU 具名/CPU 具名,无裸 cuda)", async () => {
    renderTab();
    await waitFor(() => expect(screen.getByTestId("device-gpu-0")).toBeInTheDocument());
    expect(screen.getAllByText("NVIDIA Tesla T4 · GPU 0").length).toBeGreaterThan(0);
    expect(screen.getByTestId("device-cpu")).toHaveTextContent("CPU · Intel Xeon Gold 6133");
    expect(screen.getByTestId("device-cpu")).toHaveTextContent("可用于模型运行");
    // 用户可见设备名不得出现裸 cuda
    expect(document.body.textContent).not.toMatch(/运行设备:\s*cuda/);
  });

  it("三个 workload 均呈现 Configured/Effective/Status", async () => {
    renderTab();
    await waitFor(() =>
      expect(screen.getByTestId("policy-query_embedding")).toBeInTheDocument(),
    );
    for (const w of ["query_embedding", "sync_embedding", "query_reranker"]) {
      expect(screen.getByTestId(`configured-${w}`)).toHaveTextContent(/Tesla T4|CPU ·/);
      expect(screen.getByTestId(`effective-${w}`)).toBeInTheDocument();
      expect(screen.getByTestId(`status-${w}`)).toBeInTheDocument();
    }
  });

  it("共享嵌入运行时显式指示(同模型+同 GPU)", async () => {
    renderTab();
    await waitFor(() =>
      expect(screen.getAllByTestId("shared-runtime-badge").length).toBe(2),
    );
    expect(screen.getAllByText("共享模型运行实例").length).toBe(2);
  });

  it("容量状态与建议(业务语言;外部占用只读)", async () => {
    renderTab();
    await waitFor(() => expect(screen.getByTestId("capacity-state")).toBeInTheDocument());
    expect(screen.getByTestId("capacity-state")).toHaveTextContent("GPU 容量紧张");
    expect(screen.getByText(/外部占用/)).toBeInTheDocument();
  });

  it("保存 workload 设备:PUT 规范载荷 + 重启生效提示", async () => {
    apiFetch.mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/model-runtime") return Promise.resolve(RUNTIME);
      if (path === "/model-runtime/policies/sync_embedding" && options?.method === "PUT")
        return Promise.resolve({
          ...RUNTIME.policies[1],
          configured: { kind: "cpu", gpu_uuid: null, label: "CPU · Intel Xeon Gold 6133" },
          restart_required: true,
        });
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    renderTab();
    await waitFor(() => expect(screen.getByTestId("policy-sync_embedding")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("同步嵌入设备"), { target: { value: "cpu" } });
    const card = screen.getByTestId("policy-sync_embedding");
    fireEvent.click(
      Array.from(card.querySelectorAll("button")).find((b) =>
        b.textContent?.includes("保存设备"),
      )!,
    );
    await waitFor(() =>
      expect(
        apiFetch.mock.calls.some(
          ([path, options]) =>
            path === "/model-runtime/policies/sync_embedding" &&
            (options as RequestInit).method === "PUT" &&
            (options as RequestInit).body ===
              JSON.stringify({ device_kind: "cpu", gpu_uuid: null }),
        ),
      ).toBe(true),
    );
    expect(await screen.findByText(/重启后生效/)).toBeInTheDocument();
  });

  it("GPU 预算:auto 默认可见,manual 输入 GB 并 PUT", async () => {
    apiFetch.mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/model-runtime") return Promise.resolve(RUNTIME);
      if (path === "/model-runtime/gpu-budget" && options?.method === "PUT")
        return Promise.resolve({
          ...RUNTIME.capacity,
          budget_mode: "manual",
          budget_mb: 4096,
        });
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    renderTab();
    await waitFor(() => expect(screen.getByLabelText(/自动管理/)).toBeChecked());
    fireEvent.click(screen.getByLabelText(/手动上限/));
    const input = screen.getByLabelText(/手动最大运行预算/);
    fireEvent.change(input, { target: { value: "4.0" } });
    fireEvent.click(screen.getByRole("button", { name: /保存容量策略/ }));
    await waitFor(() =>
      expect(
        apiFetch.mock.calls.some(
          ([path, options]) =>
            path === "/model-runtime/gpu-budget" &&
            (options as RequestInit).body ===
              JSON.stringify({ mode: "manual", manual_budget_mb: 4096 }),
        ),
      ).toBe(true),
    );
  });

  it("viewer 只读:无设备选择器与保存按钮", async () => {
    renderTab(false);
    await waitFor(() => expect(screen.getByTestId("device-cpu")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /保存设备/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /保存容量策略/ })).toBeNull();
  });
});
