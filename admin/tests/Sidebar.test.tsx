import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Sidebar } from "@/components/Sidebar";

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    user: { role: "admin" },
    login: vi.fn(),
    logout: vi.fn(),
    isLoading: false,
  }),
}));

function renderSidebar() {
  render(
    <MemoryRouter>
      <Sidebar />
    </MemoryRouter>,
  );
}

describe("Sidebar", () => {
  it("#43 不再显示「同步监控」菜单项(同步状态已并入数据源页面「最新同步」列)", () => {
    renderSidebar();
    expect(screen.queryByText("同步监控")).not.toBeInTheDocument();
    expect(screen.getByText("数据源")).toBeInTheDocument();
  });
});
