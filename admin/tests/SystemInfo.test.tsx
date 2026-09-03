/** #10 SystemInfo(/system)页面测试。

验收 D:值全部来自 API(零前端版本常量)、loading/error truthful、
路由 /system 可达、CI 链接仅在 ci_run_id 可靠存在时出现。
 */

import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SystemInfo from "@/pages/SystemInfo";
import { useReleaseInfo } from "@/hooks/useReleaseInfo";

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: { role: "admin", email: "t@x.com" } }),
}));

vi.mock("@/hooks/useReleaseInfo", () => ({
  useReleaseInfo: vi.fn(),
}));

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

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
