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

  it("保存 workload 设备:PUT 规范载荷 + 待「应用更改」生效提示", async () => {
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
    expect(await screen.findByText(/待应用更改生效/)).toBeInTheDocument();
    // 保存(持久化)后出现显式「应用更改」入口,Save 与 Apply 语义可区分
    expect(await screen.findByTestId("apply-runtime-button")).toBeInTheDocument();
  });

  it("Apply:有待生效配置时点击「应用更改」→ POST apply,成功后刷新为已生效真相", async () => {
    const pendingRuntime = {
      ...RUNTIME,
      policies: RUNTIME.policies.map((p) =>
        p.workload === "sync_embedding"
          ? {
              ...p,
              configured: { kind: "cpu", gpu_uuid: null, label: "CPU · Intel Xeon Gold 6133" },
              restart_required: true,
            }
          : p,
      ),
      runtime_plan: {
        mode: "dual_resident",
        budget_mb: 9000,
        pending_mode: "cpu_only",
        restart_required: true,
        generation: 1,
      },
    };
    const appliedRuntime = {
      ...pendingRuntime,
      policies: pendingRuntime.policies.map((p) => ({
        ...p,
        restart_required: false,
      })),
      runtime_plan: {
        mode: "cpu_only",
        budget_mb: 9000,
        pending_mode: "cpu_only",
        restart_required: false,
        generation: 2,
      },
    };
    apiFetch.mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/model-runtime") return Promise.resolve(pendingRuntime);
      if (path === "/model-runtime/apply" && options?.method === "POST")
        return Promise.resolve(appliedRuntime);
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    renderTab();
    const button = await screen.findByTestId("apply-runtime-button");
    expect(button).toHaveTextContent("应用更改");
    fireEvent.click(button);
    await waitFor(() =>
      expect(
        apiFetch.mock.calls.some(
          ([path, options]) =>
            path === "/model-runtime/apply" && (options as RequestInit).method === "POST",
        ),
      ).toBe(true),
    );
    // 成功后真相面刷新:待生效徽标消失,运行计划变为已生效模式,Apply 入口收起
    await waitFor(() =>
      expect(screen.queryByText("待应用生效")).not.toBeInTheDocument(),
    );
    await waitFor(() => expect(screen.getByTestId("runtime-plan")).toHaveTextContent(/运行计划:无 GPU 工作负载/));
    expect(screen.queryByTestId("apply-runtime-button")).not.toBeInTheDocument();
  });

  it("Apply 处理中:按钮禁用并显示「应用中…」", async () => {
    let resolveApply: (value: unknown) => void = () => {};
    const pendingRuntime = {
      ...RUNTIME,
      runtime_plan: {
        mode: "dual_resident",
        budget_mb: 9000,
        pending_mode: "cpu_only",
        restart_required: true,
        generation: 1,
      },
    };
    apiFetch.mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/model-runtime") return Promise.resolve(pendingRuntime);
      if (path === "/model-runtime/apply" && options?.method === "POST")
        return new Promise((resolve) => {
          resolveApply = resolve;
        });
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    renderTab();
    const button = await screen.findByTestId("apply-runtime-button");
    fireEvent.click(button);
    await waitFor(() => expect(button).toHaveTextContent("应用中…"));
    expect(button).toBeDisabled();
    resolveApply({
      ...pendingRuntime,
      runtime_plan: { ...pendingRuntime.runtime_plan, restart_required: false, generation: 2 },
    });
    // 成功后待生效清零,Apply 入口收起
    await waitFor(() =>
      expect(screen.queryByTestId("apply-runtime-button")).not.toBeInTheDocument(),
    );
  });

  it("Apply 失败:明确说明「当前运行配置未改变」及可操作错误", async () => {
    const pendingRuntime = {
      ...RUNTIME,
      policies: RUNTIME.policies.map((p) => ({ ...p, restart_required: true })),
      runtime_plan: {
        mode: "dual_resident",
        budget_mb: 9000,
        pending_mode: "cpu_only",
        restart_required: true,
        generation: 1,
      },
    };
    apiFetch.mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/model-runtime") return Promise.resolve(pendingRuntime);
      if (path === "/model-runtime/apply" && options?.method === "POST")
        return Promise.reject(
          new Error(
            "应用更改被拒绝:候选配置无安全运行计划。当前运行配置未改变,线上查询不受影响;请提高 GPU 运行预算后重试。",
          ),
        );
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    renderTab();
    const button = await screen.findByTestId("apply-runtime-button");
    fireEvent.click(button);
    const error = await screen.findByTestId("apply-error");
    expect(error).toHaveTextContent("应用失败,当前运行配置未改变");
    expect(error).toHaveTextContent(/请提高 GPU 运行预算后重试/);
    // 失败后待生效状态保持(配置未丢,可调整后重试)
    expect(screen.getByTestId("apply-runtime-button")).toHaveTextContent("应用更改");
    expect(screen.getAllByText("待应用生效").length).toBeGreaterThan(0);
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

  it("REV1 B3/B4:瞬态驻留徽标 + 运行计划真相行(预算变化→待重启提示)", async () => {
    const transientRuntime = {
      ...RUNTIME,
      policies: RUNTIME.policies.map((p) =>
        p.workload === "query_reranker"
          ? {
              ...p,
              configured: {
                kind: "gpu",
                gpu_uuid: "GPU-3caad314",
                label: "NVIDIA Tesla T4 · GPU 0",
              },
              effective: {
                kind: "gpu",
                gpu_uuid: "GPU-3caad314",
                label: "NVIDIA Tesla T4 · GPU 0",
              },
              residency: "transient",
            }
          : p,
      ),
      runtime_plan: {
        mode: "reranker_transient",
        budget_mb: 4096,
        reason: "预算仅可容纳嵌入常驻;重排瞬态驻留",
        pending_mode: "gpu_insufficient",
        restart_required: true,
      },
    };
    apiFetch.mockImplementation((path: string) => {
      if (path === "/model-runtime") return Promise.resolve(transientRuntime);
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    renderTab();
    await waitFor(() =>
      expect(screen.getByTestId("transient-residency-badge")).toBeInTheDocument(),
    );
    expect(screen.getByText("瞬态驻留")).toBeInTheDocument();
    const plan = screen.getByTestId("runtime-plan");
    expect(plan).toHaveTextContent(/运行计划:重排瞬态驻留/);
    expect(plan).toHaveTextContent(/点击「应用更改」后变为:GPU 容量不足/);
  });

  it("REV1 B4:按容量计划落 CPU 的 workload 显式标注(非静默降级)", async () => {
    const plannedCpu = {
      ...RUNTIME,
      policies: RUNTIME.policies.map((p) => ({
        ...p,
        status: "cpu_by_capacity_plan",
      })),
      runtime_plan: { mode: "gpu_insufficient", budget_mb: 3800, restart_required: false },
    };
    apiFetch.mockImplementation((path: string) => {
      if (path === "/model-runtime") return Promise.resolve(plannedCpu);
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    renderTab();
    await waitFor(() =>
      expect(screen.getByTestId("status-query_embedding")).toHaveTextContent(
        "按容量计划以 CPU 运行",
      ),
    );
    expect(screen.getAllByText("按容量计划以 CPU 运行").length).toBeGreaterThanOrEqual(3);
  });

  it("REV2 R2-1:UNSAFE 计划下查询侧显式标注(拒绝执行,未自动降级 CPU)+行动要求", async () => {
    const unsafeRuntime = {
      ...RUNTIME,
      policies: RUNTIME.policies.map((p) =>
        p.workload === "sync_embedding"
          ? {
              ...p,
              configured: {
                kind: "gpu",
                gpu_uuid: "GPU-3caad314",
                label: "NVIDIA Tesla T4 · GPU 0",
              },
              effective: { kind: "cpu", gpu_uuid: null, label: "CPU · Intel Xeon Gold 6133" },
              status: "cpu_by_capacity_plan",
            }
          : p.workload === "query_embedding"
            ? { ...p, status: "unsafe_no_safe_plan" }
            : p,
      ),
      runtime_plan: {
        mode: "gpu_insufficient",
        budget_mb: 3800,
        reason: "预算低于瞬态下限:GPU 侧不装配(按计划落 CPU)",
        action_required: true,
        pending_mode: "gpu_insufficient",
        restart_required: false,
      },
    };
    apiFetch.mockImplementation((path: string) => {
      if (path === "/model-runtime") return Promise.resolve(unsafeRuntime);
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    renderTab();
    await waitFor(() => expect(screen.getByTestId("unsafe-plan-badge")).toBeInTheDocument());
    expect(screen.getByText("UNSAFE · 无安全运行计划")).toBeInTheDocument();
    expect(screen.getByTestId("status-query_embedding")).toHaveTextContent(
      "无安全运行计划,已拒绝执行(未自动降级 CPU)",
    );
    const plan = screen.getByTestId("runtime-plan");
    expect(plan).toHaveTextContent(/运行计划:GPU 容量不足/);
    expect(plan).toHaveTextContent(/需要操作:在上方调整设备策略或提高运行预算/);
  });
});
