/** V1.6.3 Wave 1 Track A — 共享 chrome(DEF-A1 系统分组 / U-4 侧栏收起 / SH-09 顶栏分析窗控件)。
 *
 * 冻结契约(track-a-contract.md + gap-register):
 * - DEF-A1(SH-06):侧栏新增「系统」分组,用户管理/系统信息移入;既有分组语义保留;
 * - U-4(SH-12):折叠/展开纯 Admin shell 交互(零后端语义);状态持久于前端(localStorage);
 * - SH-09(GAP-SC-1/U-2):顶栏日期范围控件仅在技术洞察域(/analytics)呈现
 *   (PNG1 数据源面顶栏无日期控件;U-2 范围=技术洞察分析窗,非全站假全局过滤);
 * - UADC-4:帮助中心入口维持缺席(本文件同时守护:不得出现「帮助中心」)。
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { Sidebar } from "@/components/Sidebar";

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    user: { role: "admin", name: "Admin", email: "admin@camthink.ai" },
    login: vi.fn(),
    logout: vi.fn(),
    isLoading: false,
  }),
}));

const SIDEBAR_COLLAPSED_KEY = "askai.admin.sidebar.collapsed";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

function renderLayoutAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Layout>
        <div data-page-child>page</div>
      </Layout>
    </MemoryRouter>,
  );
}

function renderSidebar() {
  return render(
    <MemoryRouter>
      <Sidebar />
    </MemoryRouter>,
  );
}

describe("DEF-A1(SH-06):侧栏「系统」分组", () => {
  it("新增 系统 分组,用户管理/系统信息 位于其中", () => {
    renderSidebar();
    const groupLabels = screen.getAllByText(/^(运营|配置|系统)$/).map((el) => el.textContent);
    expect(groupLabels).toContain("系统");
    // 系统组成员
    const sysGroup = screen.getByText("系统").closest("div.space-y-1") ?? screen.getByText("系统").parentElement!;
    expect(sysGroup.textContent).toContain("用户管理");
    expect(sysGroup.textContent).toContain("系统信息");
  });

  it("既有分组语义保留:数据源 仍在 配置 组(不在 系统 组)", () => {
    renderSidebar();
    const configGroup = screen.getByText("配置").closest("div.space-y-1") ?? screen.getByText("配置").parentElement!;
    expect(configGroup.textContent).toContain("数据源");
    const sysGroup = screen.getByText("系统").closest("div.space-y-1") ?? screen.getByText("系统").parentElement!;
    expect(sysGroup.textContent).not.toContain("数据源");
  });

  it("UADC-4:帮助中心入口维持缺席", () => {
    renderSidebar();
    expect(screen.queryByText("帮助中心")).not.toBeInTheDocument();
  });
});

describe("U-4(SH-12):侧栏收起/展开(纯 Admin shell)", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("默认展开;点击收起 → 布局重排(导航标签隐藏,展开控件在位)", () => {
    renderLayoutAt("/data-sources");
    expect(screen.getByText("数据源")).toBeInTheDocument();
    expect(screen.queryByText("展开菜单")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /收起菜单/ }));

    // 收起态:导航标签隐藏(icon-only rail),出现展开菜单控件
    expect(screen.queryByText("数据源")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /展开菜单/ })).toBeInTheDocument();
    const aside = document.querySelector("aside[data-sidebar]");
    expect(aside?.getAttribute("data-collapsed")).toBe("true");
  });

  it("状态持久于前端:收起后 localStorage 记录,重挂载仍收起;展开后恢复", () => {
    const { unmount } = renderLayoutAt("/data-sources");
    fireEvent.click(screen.getByRole("button", { name: /收起菜单/ }));
    expect(window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY)).toBe("1");
    unmount();

    const second = render(
      <MemoryRouter initialEntries={["/data-sources"]}>
        <Layout>
          <div>page</div>
        </Layout>
      </MemoryRouter>,
    );
    expect(screen.queryByText("数据源")).not.toBeInTheDocument(); // 持久收起
    fireEvent.click(screen.getByRole("button", { name: /展开菜单/ }));
    expect(screen.getByText("数据源")).toBeInTheDocument();
    expect(window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY)).toBe("0");
    second.unmount();
  });
});

describe("SH-09/U-2:顶栏分析窗控件(技术洞察域呈现,非全站)", () => {
  it("/analytics 顶栏呈现分析窗控件(含显式起止入口)", () => {
    renderLayoutAt("/analytics");
    expect(document.querySelector("[data-topbar-window]")).not.toBeNull();
    // 默认 近 7 天(IF-7 默认)
    expect(document.querySelector("[data-topbar-window]")?.textContent).toContain("过去 7 天");
  });

  it("非技术洞察面(/data-sources)顶栏不呈现范围控件(零全站假全局过滤)", () => {
    renderLayoutAt("/data-sources");
    expect(document.querySelector("[data-topbar-window]")).toBeNull();
  });

  it("顶栏控件含 今日/过去 7 天/过去 30 天/全部时间 快选项与显式起止日历输入", () => {
    renderLayoutAt("/analytics");
    fireEvent.click(screen.getByRole("button", { name: /过去 7 天/ }));
    // 触发器与快选项同时存在「过去 7 天」(trigger+item);其余快选项唯一
    expect(screen.getAllByText("过去 7 天").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("今日")).toBeInTheDocument();
    expect(screen.getByText("过去 30 天")).toBeInTheDocument();
    expect(screen.getByText("全部时间")).toBeInTheDocument();
    // 显式起止:开始/结束日历输入 + 应用
    expect(screen.getByLabelText("开始日期")).toBeInTheDocument();
    expect(screen.getByLabelText("结束日期")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /应用/ })).toBeInTheDocument();
  });

  it("选择快选项 → 顶栏呈现更新为所选窗(单一共享分析窗状态)", () => {
    renderLayoutAt("/analytics");
    fireEvent.click(screen.getByRole("button", { name: /过去 7 天/ }));
    fireEvent.click(screen.getByText("过去 30 天"));
    expect(document.querySelector("[data-topbar-window]")?.textContent).toContain("过去 30 天");
  });
});
