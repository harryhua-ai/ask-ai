// Issue #24:Widget 外观管理页验收(A1-A7)。
//
// apiFetch 以可变 mock 承载 GET/PUT;预览 iframe 断言 srcDoc 内含真实
// widget 产物引用与当前草稿(data-launcher-style/theme)—— canonical
// 渲染契约(A7),而非复刻实现。

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";

const apiFetch = vi.fn();

vi.mock("@/lib/api", () => ({
  apiFetch: (...args: unknown[]) => apiFetch(...args),
}));

import WidgetAppearance from "@/pages/WidgetAppearance";

const SITES = [
  {
    site_id: "camthink-website",
    display_name: "CamThink 官网",
    enabled: true,
    launcher_style: "current",
    launcher_theme: "auto",
  },
  {
    site_id: "camthink-wiki",
    display_name: "CamThink Wiki",
    enabled: true,
    launcher_style: "assistant-spark",
    launcher_theme: "dark",
  },
];

function mockGet(list = SITES) {
  apiFetch.mockImplementation((path: string) => {
    if (path === "/widget-appearance") return Promise.resolve(list);
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });
}

function mockGetAndPut(list = SITES, updated = { ...SITES[0], launcher_style: "chat-bubble", launcher_theme: "dark" }) {
  apiFetch.mockImplementation((path: string, options?: RequestInit) => {
    if (path === "/widget-appearance") return Promise.resolve(list);
    if (path === "/widget-appearance/camthink-website" && options?.method === "PUT")
      return Promise.resolve(updated);
    return Promise.reject(new Error(`unexpected call ${path} ${options?.method ?? "GET"}`));
  });
}

function renderPage() {
  return render(<WidgetAppearance />);
}

beforeEach(() => {
  apiFetch.mockReset();
  // jsdom 无 matchMedia:预览 iframe 不执行(仅断言 srcDoc 字符串)
});

afterEach(cleanup);

describe("WidgetAppearance(A1-A7)", () => {
  it("A1:四个内置风格卡片全部可见", async () => {
    mockGet();
    renderPage();
    await waitFor(() => expect(screen.getByText("经典(默认)")).toBeInTheDocument());
    expect(screen.getByText("智能火花")).toBeInTheDocument();
    expect(screen.getByText("对话气泡")).toBeInTheDocument();
    expect(screen.getByText("轨道神经")).toBeInTheDocument();
  });

  it("A2/A3:选择风格与主题即时反映在预览文档(草稿态)", async () => {
    mockGet();
    renderPage();
    await waitFor(() => expect(screen.getByText("智能火花")).toBeInTheDocument());
    fireEvent.click(screen.getByText("智能火花"));
    fireEvent.click(screen.getByText("深色"));
    const iframe = screen.getByTitle(/启动器实时预览/) as HTMLIFrameElement;
    expect(iframe.getAttribute("srcdoc")).toContain('data-launcher-style="assistant-spark"');
    expect(iframe.getAttribute("srcdoc")).toContain('data-launcher-theme="dark"');
    // canonical 渲染契约:srcDoc 引用真实 widget 产物(css+js 成对)
    expect(iframe.getAttribute("srcdoc")).toContain("/widget/ask-ai-widget.css");
    expect(iframe.getAttribute("srcdoc")).toContain("/widget/widget.js");
  });

  it("A4/A5:未保存不发写请求;保存时 PUT 正确载荷", async () => {
    mockGetAndPut();
    renderPage();
    await waitFor(() => expect(screen.getByText("智能火花")).toBeInTheDocument());
    fireEvent.click(screen.getByText("智能火花"));
    fireEvent.click(screen.getByText("深色"));
    // 未保存前:零 PUT(A4)
    const putCalls = apiFetch.mock.calls.filter(
      ([, options]) => (options as RequestInit | undefined)?.method === "PUT",
    );
    expect(putCalls).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "保存外观" }));
    await waitFor(() =>
      expect(
        apiFetch.mock.calls.some(
          ([path, options]) =>
            path === "/widget-appearance/camthink-website" &&
            (options as RequestInit).method === "PUT" &&
            (options as RequestInit).body ===
              JSON.stringify({ launcher_style: "assistant-spark", launcher_theme: "dark" }),
        ),
      ).toBe(true),
    );
  });

  it("A6:重载展示已保存状态(站点列表直呈)", async () => {
    mockGet();
    renderPage();
    await waitFor(() => expect(screen.getByText(/智能火花 · 深色/)).toBeInTheDocument());
  });

  it("站点切换回滚草稿到该站点已保存值(未保存选择不跨站点携带)", async () => {
    mockGet();
    renderPage();
    await waitFor(() => expect(screen.getByText("智能火花")).toBeInTheDocument());
    // 初始选中第一个站点 → 切到 wiki(已保存 assistant-spark/dark)
    fireEvent.click(screen.getByText("CamThink Wiki"));
    await waitFor(() => {
      const iframe = screen.getByTitle(/启动器实时预览/) as HTMLIFrameElement;
      expect(iframe.getAttribute("srcdoc")).toContain('data-launcher-style="assistant-spark"');
      expect(iframe.getAttribute("srcdoc")).toContain('data-launcher-theme="dark"');
    });
  });
});
