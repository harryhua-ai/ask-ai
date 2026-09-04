// Issue #24 REV1:Widget 外观管理页验收(A1-A10,统一 icon × shape × theme)。
//
// apiFetch 以可变 mock 承载 GET/PUT;预览 iframe 断言 srcDoc 内含真实
// widget 产物引用与当前草稿(data-launcher-icon/shape/theme)—— canonical
// 渲染契约,而非复刻实现;A10 断言 UI 不暴露 SVG 文件名等实现术语。

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
    launcher_icon: "current",
    launcher_shape: "rounded-square",
    launcher_theme: "auto",
    legacy_launcher_style: null,
  },
  {
    site_id: "camthink-wiki",
    display_name: "CamThink Wiki",
    enabled: true,
    launcher_icon: "bot-sparkle",
    launcher_shape: "round",
    launcher_theme: "dark",
    legacy_launcher_style: "chat-bubble",
  },
];

function mockGet(list = SITES) {
  apiFetch.mockImplementation((path: string) => {
    if (path === "/widget-appearance") return Promise.resolve(list);
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });
}

function mockGetAndPut(
  list = SITES,
  updated = {
    ...SITES[0],
    launcher_icon: "robot-smile",
    launcher_shape: "round",
    launcher_theme: "dark",
  },
) {
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

describe("WidgetAppearance REV1(A1-A10)", () => {
  it("A1:四个新图标 + 经典卡片全部可见(视觉选择面)", async () => {
    mockGet();
    renderPage();
    await waitFor(() => expect(screen.getByText("经典(默认)")).toBeInTheDocument());
    expect(screen.getByText("机器人 + 星光")).toBeInTheDocument();
    expect(screen.getByText("气泡 + 星光 · 填充")).toBeInTheDocument();
    expect(screen.getByText("机器人笑脸")).toBeInTheDocument();
    expect(screen.getByText("气泡 + 星光 · 描边")).toBeInTheDocument();
  });

  it("A10:UI 不暴露 SVG 文件名/语义 id 等实现术语", async () => {
    mockGet();
    renderPage();
    await waitFor(() => expect(screen.getByText("经典(默认)")).toBeInTheDocument());
    expect(screen.queryByText(/\.svg/)).toBeNull();
    expect(screen.queryByText(/bot-sparkle/)).toBeNull();
    expect(screen.queryByText(/gravity-ui/)).toBeNull();
  });

  it("A2/A3:形状(Round/Rounded Square)与主题(Auto/Light/Dark)独立可选", async () => {
    mockGet();
    renderPage();
    await waitFor(() => expect(screen.getByText("圆形")).toBeInTheDocument());
    fireEvent.click(screen.getByText("圆形"));
    expect(screen.getByText("圆形")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByText("圆角方形"));
    expect(screen.getByText("圆角方形")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByText("深色"));
    expect(screen.getByText("深色")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByText("浅色"));
    expect(screen.getByText("浅色")).toHaveAttribute("aria-pressed", "true");
  });

  it("A4:icon × shape × theme 变更即时反映在预览文档(草稿态,免保存)", async () => {
    mockGet();
    renderPage();
    await waitFor(() => expect(screen.getByText("机器人笑脸")).toBeInTheDocument());
    fireEvent.click(screen.getByText("机器人笑脸"));
    fireEvent.click(screen.getByText("圆形"));
    fireEvent.click(screen.getByText("深色"));
    const iframe = screen.getByTitle(/启动器实时预览/) as HTMLIFrameElement;
    expect(iframe.getAttribute("srcdoc")).toContain('data-launcher-icon="robot-smile"');
    expect(iframe.getAttribute("srcdoc")).toContain('data-launcher-shape="round"');
    expect(iframe.getAttribute("srcdoc")).toContain('data-launcher-theme="dark"');
    // canonical 渲染契约:srcDoc 引用真实 widget 产物(css+js 成对)
    expect(iframe.getAttribute("srcdoc")).toContain("/widget/ask-ai-widget.css");
    expect(iframe.getAttribute("srcdoc")).toContain("/widget/widget.js");
  });

  it("A5:预览背景与主题相互独立(切背景不改主题)", async () => {
    mockGet();
    renderPage();
    await waitFor(() => expect(screen.getByText("深色页面")).toBeInTheDocument());
    fireEvent.click(screen.getByText("机器人笑脸"));
    fireEvent.click(screen.getByText("深色"));
    fireEvent.click(screen.getByText("深色页面"));
    const iframe = screen.getByTitle(/启动器实时预览/) as HTMLIFrameElement;
    // 主题仍是草稿选择的深色;仅页面背景切换
    expect(iframe.getAttribute("srcdoc")).toContain('data-launcher-theme="dark"');
  });

  it("A6/A7:未保存零写请求;保存 PUT 统一语义三字段载荷", async () => {
    mockGetAndPut();
    renderPage();
    await waitFor(() => expect(screen.getByText("机器人笑脸")).toBeInTheDocument());
    fireEvent.click(screen.getByText("机器人笑脸"));
    fireEvent.click(screen.getByText("圆形"));
    fireEvent.click(screen.getByText("深色"));
    // 未保存前:零 PUT(A6)
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
              JSON.stringify({
                launcher_icon: "robot-smile",
                launcher_shape: "round",
                launcher_theme: "dark",
              }),
        ),
      ).toBe(true),
    );
  });

  it("A8:重载展示已保存状态(icon · shape · theme)", async () => {
    mockGet();
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/机器人 \+ 星光 · 圆形 · 深色/)).toBeInTheDocument(),
    );
  });

  it("A9:站点切换草稿回滚到该站点已保存值(未保存选择不跨站点携带)", async () => {
    mockGet();
    renderPage();
    await waitFor(() => expect(screen.getByText("机器人笑脸")).toBeInTheDocument());
    // 初始选中第一个站点 → 切到 wiki(已保存 bot-sparkle/round/dark)
    fireEvent.click(screen.getByText("CamThink Wiki"));
    await waitFor(() => {
      const iframe = screen.getByTitle(/启动器实时预览/) as HTMLIFrameElement;
      expect(iframe.getAttribute("srcdoc")).toContain('data-launcher-icon="bot-sparkle"');
      expect(iframe.getAttribute("srcdoc")).toContain('data-launcher-shape="round"');
      expect(iframe.getAttribute("srcdoc")).toContain('data-launcher-theme="dark"');
    });
  });

  it("遗留退役提示:legacy_launcher_style 非 current 时提示重新选择", async () => {
    mockGet();
    renderPage();
    await waitFor(() => expect(screen.getByText("CamThink Wiki")).toBeInTheDocument());
    fireEvent.click(screen.getByText("CamThink Wiki"));
    await waitFor(() =>
      expect(screen.getByText(/已随新图标体系退役/)).toBeInTheDocument(),
    );
  });
});
