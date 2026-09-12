/** #10 SystemInfo(/system)页面测试。

验收 D:值全部来自 API(零前端版本常量)、loading/error truthful、
路由 /system 可达、CI 链接仅在 ci_run_id 可靠存在时出现。

#7 系统运行时:四组信息(主机/资源/加速器/服务状态)完整渲染、
不可得项显式「不可用+原因」、手动刷新可用、零操作按钮。
 */

import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SystemInfo from "@/pages/SystemInfo";
import { useReleaseInfo } from "@/hooks/useReleaseInfo";
import { useSystemRuntime } from "@/hooks/useSystemRuntime";
import type { SystemRuntimeInfo } from "@/types/api";

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: { role: "admin", email: "t@x.com" } }),
}));

vi.mock("@/hooks/useReleaseInfo", () => ({
  useReleaseInfo: vi.fn(),
}));

vi.mock("@/hooks/useSystemRuntime", () => ({
  useSystemRuntime: vi.fn(),
}));

afterEach(cleanup);

const idleRuntime = () => ({
  data: undefined,
  isLoading: false,
  isError: false,
  error: null,
  refetch: vi.fn(),
  isFetching: false,
});

beforeEach(() => {
  vi.clearAllMocks();
  // 既有 #10 测试不关心 #7 section:钉 idle 默认,防跨用例 mock 泄漏
  vi.mocked(useSystemRuntime).mockReturnValue(idleRuntime() as never);
});

function renderAtSystem() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/system"]}>
        <Routes>
          <Route path="/system" element={<SystemInfo />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const releaseFixture = {
  version: "1.2.3",
  git_sha: "b".repeat(40),
  built_at: "2026-09-03T08:30:00Z",
  app_mode: "production",
  image: "ghcr.io/harryhua-ai/ask-ai:v1.2.3",
  ci_run_id: "98765",
  source: "manifest" as const,
};

describe("SystemInfo(/system)", () => {
  it("API 值直呈:版本/SHA/构建时间/环境/镜像,零前端版本常量", () => {
    vi.mocked(useReleaseInfo).mockReturnValue({
      data: releaseFixture,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as never);
    renderAtSystem();
    expect(screen.getByText("1.2.3")).toBeInTheDocument();
    expect(screen.getByText("b".repeat(40))).toBeInTheDocument();
    expect(screen.getByText("2026-09-03T08:30:00Z")).toBeInTheDocument();
    expect(screen.getByText("production")).toBeInTheDocument();
    expect(screen.getByText("ghcr.io/harryhua-ai/ask-ai:v1.2.3")).toBeInTheDocument();
    // 正式发布徽章(source=manifest)
    expect(screen.getByText("正式发布")).toBeInTheDocument();
  });

  it("开发兜底身份如实标注(不假冒正式发布)", () => {
    vi.mocked(useReleaseInfo).mockReturnValue({
      data: { ...releaseFixture, version: "0.0.0-dev", source: "fallback", image: null, ci_run_id: null, built_at: null },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as never);
    renderAtSystem();
    expect(screen.getByText("0.0.0-dev")).toBeInTheDocument();
    expect(screen.getByText("开发态")).toBeInTheDocument();
    expect(screen.queryByText("正式发布")).not.toBeInTheDocument();
    // 不可用字段如实显示占位(built_at/image 均为 null)
    expect(screen.getAllByText("—").length).toBe(2);
  });

  it("loading 状态 truthful", () => {
    vi.mocked(useReleaseInfo).mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as never);
    renderAtSystem();
    expect(screen.getByText(/正在加载发布信息/)).toBeInTheDocument();
  });

  it("error 状态 truthful 且可重试", async () => {
    const refetch = vi.fn();
    vi.mocked(useReleaseInfo).mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("boom"),
      refetch,
    } as never);
    renderAtSystem();
    const retry = screen.getByRole("button", { name: /重试/ });
    fireEvent.click(retry);
    await waitFor(() => expect(refetch).toHaveBeenCalled());
  });

  it("CI 链接仅在 ci_run_id 存在时出现,且指向 Actions run", () => {
    vi.mocked(useReleaseInfo).mockReturnValue({
      data: releaseFixture,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as never);
    renderAtSystem();
    const link = screen.getByRole("link", { name: /run 98765/ });
    expect(link).toHaveAttribute("href", "https://github.com/harryhua-ai/ask-ai/actions/runs/98765");
  });

  it("ci_run_id 缺失时显示不可用,不渲染假链接", () => {
    vi.mocked(useReleaseInfo).mockReturnValue({
      data: { ...releaseFixture, ci_run_id: null },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as never);
    renderAtSystem();
    expect(screen.getByText("不可用")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});

// ====================  Final RC:DataSources 与 SystemInfo 共存(Admin 双页)  ====================

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

describe("Final RC Admin 共存", () => {
  it("两页模块可同时导入(零模块/注册冲突)", async () => {
    const [ds, sys] = await Promise.all([
      import("@/pages/DataSources"),
      import("@/pages/SystemInfo"),
    ]);
    expect(typeof ds.default).toBe("function");
    expect(typeof sys.default).toBe("function");
  });

  it("App 路由表同时注册 /data-sources 与 /system(静态契约锁)", () => {
    const appSrc = readFileSync(resolve(process.cwd(), "src/App.tsx"), "utf-8");
    expect(appSrc).toContain('path="/data-sources"');
    expect(appSrc).toContain('path="/system"');
  });
});

// ====================  #7 系统运行时(只读快照分区)  ====================

const T = "2026-09-12T01:02:03+00:00";
const obs = (value: string | number | null) => ({
  available: true,
  value,
  reason: null,
  as_of: T,
});
const unobs = (reason: string) => ({ available: false, value: null, reason, as_of: T });

const runtimeFull: SystemRuntimeInfo = {
  as_of: T,
  host: {
    as_of: T,
    hostname: obs("prod-gpu-host-1"),
    os: obs("Linux 5.15.0-107-generic x86_64"),
    kernel: obs("5.15.0-107-generic"),
    uptime_seconds: obs(2678400),
  },
  resources: {
    as_of: T,
    cpu_model: obs("Intel(R) Xeon(R) Silver 4210"),
    cpu_logical_cores: obs(16),
    cpu_utilization_percent: obs(12.5),
    loadavg_1m: obs(0.42),
    loadavg_5m: obs(0.35),
    loadavg_15m: obs(0.3),
    memory_total_mb: obs(16000),
    memory_used_mb: obs(8000),
    memory_available_mb: obs(8000),
    swap_total_mb: obs(2000),
    swap_used_mb: obs(1000),
    disk_path: obs("/app"),
    disk_total_gb: obs(100),
    disk_used_gb: obs(40),
    disk_free_gb: obs(60),
    disk_used_percent: obs(40),
  },
  accelerator: {
    as_of: T,
    available: true,
    reason: null,
    driver_version: obs("535.104.05"),
    cuda_version: obs("12.2"),
    gpus: [
      {
        index: 0,
        uuid: "GPU-3caad314",
        name: "NVIDIA Tesla T4",
        driver_version: "535.104.05",
        utilization_percent: 12,
        memory_used_mb: 1234,
        memory_free_mb: 14126,
        memory_total_mb: 15360,
        temperature_c: 41,
        as_of: T,
      },
    ],
    nvidia_smi_error: null,
  },
  service: {
    as_of: T,
    health: obs("ok"),
    release: { available: true, value: releaseFixture, reason: null, as_of: T },
    model_runtime: {
      available: true,
      value: {
        devices: [{ kind: "gpu", uuid: "GPU-x", label: "Tesla T4 · GPU 0" }],
        policies: [
          {
            workload: "query_embedding",
            status: "loaded",
            effective: { kind: "gpu", label: "Tesla T4 · GPU 0" },
          },
        ],
        shared_embedding_runtime: true,
        runtime_plan: { mode: "GPU_RESIDENT", generation: 1 },
        capacity: { state: "HEALTHY", gpu_free_mb: 14126 },
      },
      reason: null,
      as_of: T,
    },
  },
};

function degradedRuntime(): SystemRuntimeInfo {
  return {
    as_of: T,
    host: {
      as_of: T,
      hostname: obs("dev-host"),
      os: obs("Darwin 24.6.0 arm64"),
      kernel: obs("24.6.0"),
      uptime_seconds: unobs("uptime 不可得(需 Linux /proc/uptime,当前平台无此接口)"),
    },
    resources: {
      as_of: T,
      cpu_model: unobs("CPU 型号需 Linux /proc/cpuinfo(当前平台不可得)"),
      cpu_logical_cores: obs(10),
      cpu_utilization_percent: unobs("CPU 利用率需 Linux /proc/stat 双采样(当前平台不可得)"),
      loadavg_1m: unobs("load average 在当前平台不可得"),
      loadavg_5m: unobs("load average 在当前平台不可得"),
      loadavg_15m: unobs("load average 在当前平台不可得"),
      memory_total_mb: unobs("内存水位需 Linux /proc/meminfo(当前平台不可得)"),
      memory_used_mb: unobs("内存水位需 Linux /proc/meminfo(当前平台不可得)"),
      memory_available_mb: unobs("内存水位需 Linux /proc/meminfo(当前平台不可得)"),
      swap_total_mb: unobs("内存水位需 Linux /proc/meminfo(当前平台不可得)"),
      swap_used_mb: unobs("内存水位需 Linux /proc/meminfo(当前平台不可得)"),
      disk_path: obs("/app"),
      disk_total_gb: unobs("磁盘用量采集失败(OSError:/app)"),
      disk_used_gb: unobs("磁盘用量采集失败(OSError:/app)"),
      disk_free_gb: unobs("磁盘用量采集失败(OSError:/app)"),
      disk_used_percent: unobs("磁盘用量采集失败(OSError:/app)"),
    },
    accelerator: {
      as_of: T,
      available: false,
      reason: "未发现 NVIDIA GPU(nvidia-smi 不可用:nvidia-smi 不可执行(未安装);torch CUDA 亦不可见)",
      driver_version: unobs("驱动版本需 nvidia-smi(当前不可得)"),
      cuda_version: unobs("CUDA 版本需 nvidia-smi(当前不可得)"),
      gpus: [],
      nvidia_smi_error: "nvidia-smi 不可执行(未安装)",
    },
    service: {
      as_of: T,
      health: obs("ok"),
      release: { available: true, value: releaseFixture, reason: null, as_of: T },
      model_runtime: {
        available: false,
        value: null,
        reason: "模型运行时未就绪(本进程未初始化 model runtime)",
        as_of: T,
      },
    },
  };
}

describe("SystemInfo 系统运行时(#7)", () => {
  it("四组信息完整渲染且值直呈(主机/资源/加速器/服务状态)", () => {
    vi.mocked(useSystemRuntime).mockReturnValue({
      data: runtimeFull,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    } as never);
    const { container } = renderAtSystem();
    // 四组分区齐全
    for (const title of ["主机", "资源(CPU · 内存 · 磁盘)", "加速器", "服务状态"]) {
      expect(container.querySelector(`[data-runtime-group="${title}"]`)).not.toBeNull();
    }
    // 主机
    expect(screen.getByText("prod-gpu-host-1")).toBeInTheDocument();
    expect(screen.getByText(/31 天 0 小时/)).toBeInTheDocument();
    // 资源
    expect(screen.getByText("16")).toBeInTheDocument();
    expect(screen.getByText("12.5")).toBeInTheDocument();
    // 加速器
    expect(screen.getByText("NVIDIA Tesla T4 · GPU 0")).toBeInTheDocument();
    expect(screen.getByText("535.104.05")).toBeInTheDocument();
    expect(screen.getByText("12.2")).toBeInTheDocument();
    // 服务状态:容量徽章 + 推理负载
    expect(screen.getByText("容量正常")).toBeInTheDocument();
    expect(screen.getByText(/query_embedding: loaded/)).toBeInTheDocument();
    // 发布身份区(#10)不受影响,仍在上
    expect(screen.getByText("1.2.3")).toBeInTheDocument();
    // 每项含采集时间(as_of)
    expect(container.querySelector("[data-runtime-as-of]")).toHaveTextContent(T);
  });

  it("不可得项显式「不可用+原因」,绝不虚构值(无 GPU 降级态)", () => {
    vi.mocked(useSystemRuntime).mockReturnValue({
      data: degradedRuntime(),
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    } as never);
    const { container } = renderAtSystem();
    // 多个观测项带显式不可用标记 + 原因可见
    expect(container.querySelectorAll("[data-obs-unavailable]").length).toBeGreaterThanOrEqual(8);
    expect(screen.getAllByText(/需 Linux \/proc\/uptime/).length).toBeGreaterThan(0);
    // 加速器段整体显式不可用 + 原因(非错误、非空壳)
    expect(container.querySelector("[data-accelerator-reason]")).toHaveTextContent(
      /未发现 NVIDIA GPU/
    );
    // 服务状态:模型运行时未就绪 → 显式原因
    expect(screen.getAllByText(/模型运行时未就绪/).length).toBeGreaterThan(0);
  });

  it("手动刷新可用,且页面零操作按钮(仅刷新)", () => {
    const refetch = vi.fn();
    vi.mocked(useSystemRuntime).mockReturnValue({
      data: runtimeFull,
      isLoading: false,
      isError: false,
      error: null,
      refetch,
      isFetching: false,
    } as never);
    const { container } = renderAtSystem();
    const refresh = screen.getByRole("button", { name: "刷新" });
    fireEvent.click(refresh);
    expect(refetch).toHaveBeenCalledTimes(1);
    // 安全边界:整页唯一按钮 = 刷新(无重启/清理等任何操作控制)
    expect(container.querySelectorAll("button").length).toBe(1);
  });

  it("loading 状态 truthful(独立于发布信息加载)", () => {
    vi.mocked(useSystemRuntime).mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: true,
    } as never);
    renderAtSystem();
    expect(screen.getByText(/正在加载系统运行时/)).toBeInTheDocument();
  });

  it("error 状态 truthful 且可重试(LoadError 纪律)", async () => {
    const refetch = vi.fn();
    vi.mocked(useSystemRuntime).mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("boom"),
      refetch,
      isFetching: false,
    } as never);
    const { container } = renderAtSystem();
    expect(container.querySelector("[data-load-error]")).not.toBeNull();
    const retry = container.querySelector("[data-load-error-retry]") as HTMLElement;
    fireEvent.click(retry);
    await waitFor(() => expect(refetch).toHaveBeenCalled());
  });
});
