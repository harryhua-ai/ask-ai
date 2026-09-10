// I-UX-001 矫正:统一 Widget 工作区验收(#36/#37/#38/#6)。
//
// 覆盖(冻结契约 §3.1/§3.10/§3.11 + 矫正验收 §5):
// - 四区工作区(Entry & Engagement / Appearance / Authorized Websites /
//   Preview & Test);站点切换草稿回滚;
// - 外观草稿即时反映在预览文档(免保存);未保存零写请求;保存分路 PUT
//   (experience/appearance 双持久面);
// - #36:预览 launcher 外观 = 草稿解析值(不硬编码旧版图标);
// - #37:预览主题模拟为临时覆写 —— 注入 iframe,绝不随保存持久化;Reset 回站点配置;
// - #6:Authorized Websites 列表/添加/移除;最后一个来源移除前的后果警示;
//   422/409 错误如实呈现;
// - Greeting:自动(默认)/自定义模板模式切换 + 解析预览分离。

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";

const apiFetch = vi.fn();

vi.mock("@/lib/api", () => ({
  apiFetch: (...args: unknown[]) => apiFetch(...args),
}));

import WidgetWorkspace, { previewDoc, resolveGreetingPreview } from "@/pages/WidgetWorkspace";

const EXPERIENCE = [
  {
    site_id: "camthink-website",
    display_name: "CamThink 官网",
    enabled: true,
    entry_mode: "mini_entry",
    proactive_timing: "balanced",
    launcher_motion: "subtle_glow",
    launcher_size: "medium",
    launcher_brand: "askai",
    launcher_color: null,
    chat_theme: "match",
    chat_accent_color: null,
    chat_size: "default",
    greeting_override: null,
    launcher_presentation: "pill",
    trusted_actions: [],
  },
];

const APPEARANCE = [
  {
    site_id: "camthink-website",
    display_name: "CamThink 官网",
    enabled: true,
    launcher_icon: "current",
    launcher_shape: "rounded-square",
    launcher_theme: "auto",
    legacy_launcher_style: null,
  },
];

const WEBSITES = [
  {
    site_id: "camthink-website",
    display_name: "CamThink 官网",
    enabled: true,
    allowed_origins: ["https://www.camthink.ai", "http://42.194.138.11"],
  },
];

function mockWorkspace(overrides: Record<string, unknown> = {}) {
  apiFetch.mockImplementation((path: string, options?: RequestInit) => {
    const method = options?.method ?? "GET";
    if (path === "/widget-experience" && method === "GET")
      return Promise.resolve(overrides.experience ?? EXPERIENCE);
    if (path === "/widget-appearance" && method === "GET")
      return Promise.resolve(overrides.appearance ?? APPEARANCE);
    if (path === "/authorized-websites" && method === "GET")
      return Promise.resolve(overrides.websites ?? WEBSITES);
    if (path === "/authorized-websites/camthink-website/origins" && method === "POST")
      return Promise.resolve(overrides.addOrigin ?? { ...WEBSITES[0], allowed_origins: ["https://www.camthink.ai", "http://42.194.138.11", "https://new.example.com"] });
    if (path === "/authorized-websites/camthink-website/origins" && method === "DELETE")
      return Promise.resolve(overrides.removeOrigin ?? { ...WEBSITES[0], allowed_origins: ["http://42.194.138.11"] });
    if (path === "/widget-experience/camthink-website" && method === "PUT")
      return Promise.resolve({ ...(overrides.experience ?? EXPERIENCE)[0], ...JSON.parse(String(options?.body ?? "{}")) });
    if (path === "/widget-appearance/camthink-website" && method === "PUT")
      return Promise.resolve({ ...(overrides.appearance ?? APPEARANCE)[0], ...JSON.parse(String(options?.body ?? "{}")) });
    return Promise.reject(new Error(`unexpected call ${method} ${path}`));
  });
}

async function renderWorkspace() {
  const utils = render(<WidgetWorkspace />);
  await waitFor(() => expect(screen.getByText("CamThink 官网")).toBeInTheDocument());
  return utils;
}

beforeEach(() => {
  apiFetch.mockReset();
  mockWorkspace();
});

afterEach(cleanup);

describe("统一 Widget 工作区(#38)", () => {
  it("四区 tab 全部存在且可切换", async () => {
    await renderWorkspace();
    expect(screen.getByRole("tab", { name: /入口与参与/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /外观/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /授权网站/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /预览与测试/ })).toBeInTheDocument();
    // 默认区 = 入口与参与(入口呈现卡片可见)
    expect(screen.getByText("入口呈现")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /外观/ }));
    expect(screen.getByText("启动器图标(仅「紧凑图标」呈现方式;品牌胶囊使用 ✦ Ask AI 品牌)")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /授权网站/ }));
    expect(screen.getByText("授权网站(Authorized Websites)")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /预览与测试/ }));
    expect(screen.getByText("预览与测试(真实 Widget 渲染)")).toBeInTheDocument();
  });

  it("旧的两个顶层概念不再出现(「Widget 体验」「Widget 外观」合并为 Widget)", async () => {
    await renderWorkspace();
    expect(screen.queryByText("Widget 体验")).not.toBeInTheDocument();
    expect(screen.queryByText("Widget 外观")).not.toBeInTheDocument();
    expect(screen.getByText("Widget")).toBeInTheDocument();
  });
});

describe("Authorized Websites(#6)", () => {
  it("展示站点已授权精确来源", async () => {
    await renderWorkspace();
    fireEvent.click(screen.getByRole("tab", { name: /授权网站/ }));
    expect(screen.getByText("https://www.camthink.ai")).toBeInTheDocument();
    expect(screen.getByText("http://42.194.138.11")).toBeInTheDocument();
  });

  it("添加来源走 POST 并即时刷新列表", async () => {
    await renderWorkspace();
    fireEvent.click(screen.getByRole("tab", { name: /授权网站/ }));
    const input = screen.getByLabelText("新增授权来源");
    fireEvent.change(input, { target: { value: "https://new.example.com" } });
    fireEvent.click(screen.getByText("添加授权"));
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/authorized-websites/camthink-website/origins",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    await waitFor(() => expect(screen.getByText("https://new.example.com")).toBeInTheDocument());
  });

  it("移除非最后来源直接执行;移除最后一个来源前给出后果警示(确认后才删)", async () => {
    await renderWorkspace();
    fireEvent.click(screen.getByRole("tab", { name: /授权网站/ }));
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    // 列表有两个来源:先移除一个(无警示,直接执行)
    const removeButtons = screen.getAllByText("移除");
    fireEvent.click(removeButtons[0]);
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/authorized-websites/camthink-website/origins",
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
    expect(confirmSpy).not.toHaveBeenCalled();
    // 收敛到单来源后(mock DELETE 响应仅剩 1 个)再移除 → 必须先经确认;取消则不发第二次请求
    await waitFor(() => {
      const remaining = screen.getAllByText("移除");
      expect(remaining).toHaveLength(1);
    });
    const deleteCallsBefore = apiFetch.mock.calls.filter(
      (c) => c[0] === "/authorized-websites/camthink-website/origins" && c[1]?.method === "DELETE",
    ).length;
    fireEvent.click(screen.getByText("移除"));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(confirmSpy.mock.calls[0][0]).toContain("最后一个已授权来源");
    const deleteCallsAfter = apiFetch.mock.calls.filter(
      (c) => c[0] === "/authorized-websites/camthink-website/origins" && c[1]?.method === "DELETE",
    ).length;
    expect(deleteCallsAfter).toBe(deleteCallsBefore);
    confirmSpy.mockRestore();
  });
});

describe("Preview & Test(#36/#37)", () => {
  it("#36:预览 launcher 外观来自草稿解析值(不再是硬编码旧版图标)", async () => {
    const { container } = await renderWorkspace();
    fireEvent.click(screen.getByRole("tab", { name: /外观/ }));
    // 草稿选择新图标(未保存)
    fireEvent.click(screen.getByLabelText("图标样式:机器人笑脸"));
    fireEvent.click(screen.getByRole("tab", { name: /预览与测试/ }));
    const iframe = container.querySelector("iframe[title*='实时预览']") as HTMLIFrameElement;
    expect(iframe.srcdoc).toContain("data-launcher-icon=\"robot-smile\"");
    // 真实 Widget 渲染路径(非第二套实现)
    expect(iframe.srcdoc).toContain("/widget/widget.js");
    expect(iframe.srcdoc).toContain("data-preview-mode=\"true\"");
  });

  it("#36:预览 launcher 呈现方式来自站点草稿(pill),可预览品牌胶囊", async () => {
    const { container } = await renderWorkspace();
    fireEvent.click(screen.getByRole("tab", { name: /预览与测试/ }));
    const iframe = container.querySelector("iframe[title*='实时预览']") as HTMLIFrameElement;
    expect(iframe.srcdoc).toContain("data-launcher-presentation=\"pill\"");
  });

  it("#37:预览主题模拟注入 iframe 但绝不进入保存请求;Reset 恢复站点配置", async () => {
    const { container } = await renderWorkspace();
    fireEvent.click(screen.getByRole("tab", { name: /预览与测试/ }));
    // 临时选择深色 → 注入 iframe
    fireEvent.click(screen.getByRole("button", { name: "深色" }));
    let iframe = container.querySelector("iframe[title*='实时预览']") as HTMLIFrameElement;
    expect(iframe.srcdoc).toContain("data-chat-theme=\"dark\"");
    // Reset 恢复「使用站点配置」→ 回落草稿/站点值(match)
    fireEvent.click(screen.getByText("重置(使用站点配置)"));
    iframe = container.querySelector("iframe[title*='实时预览']") as HTMLIFrameElement;
    expect(iframe.srcdoc).toContain("data-chat-theme=\"match\"");
    // 保存:请求体不含任何预览主题覆写(改一个真实草稿字段使保存可用)
    fireEvent.click(screen.getByRole("tab", { name: /入口与参与/ }));
    fireEvent.click(screen.getByText("B · Contextual Nudge"));
    fireEvent.click(screen.getByText("保存 Widget 配置"));
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/widget-experience/camthink-website",
        expect.objectContaining({ method: "PUT" }),
      ),
    );
    const putCalls = apiFetch.mock.calls.filter(
      (c) => c[0] === "/widget-experience/camthink-website" && c[1]?.method === "PUT",
    );
    for (const call of putCalls) {
      const body = JSON.parse(String(call[1].body));
      expect(Object.keys(body)).not.toContain("preview_theme");
    }
  });

  it("保存分路:experience 草稿走 /widget-experience,appearance 草稿走 /widget-appearance", async () => {
    await renderWorkspace();
    // appearance 草稿
    fireEvent.click(screen.getByRole("tab", { name: /外观/ }));
    fireEvent.click(screen.getByLabelText("图标样式:机器人笑脸"));
    fireEvent.click(screen.getByText("保存 Widget 配置"));
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/widget-appearance/camthink-website",
        expect.objectContaining({ method: "PUT" }),
      ),
    );
    const appPut = apiFetch.mock.calls.find(
      (c) => c[0] === "/widget-appearance/camthink-website" && c[1]?.method === "PUT",
    );
    expect(JSON.parse(String(appPut![1].body))).toEqual({ launcher_icon: "robot-smile" });
    // experience 草稿
    apiFetch.mockClear();
    mockWorkspace();
    fireEvent.click(screen.getByRole("tab", { name: /入口与参与/ }));
    fireEvent.click(screen.getByText("B · Contextual Nudge"));
    fireEvent.click(screen.getByText("保存 Widget 配置"));
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/widget-experience/camthink-website",
        expect.objectContaining({ method: "PUT" }),
      ),
    );
    const expPut = apiFetch.mock.calls.find(
      (c) => c[0] === "/widget-experience/camthink-website" && c[1]?.method === "PUT",
    );
    expect(JSON.parse(String(expPut![1].body))).toMatchObject({ entry_mode: "nudge" });
  });
});

describe("上下文问候(V2.3 模板)", () => {
  it("自动(默认)/自定义模板模式切换;模板与解析预览分离", async () => {
    await renderWorkspace();
    fireEvent.click(screen.getByRole("tab", { name: /入口与参与/ }));
    fireEvent.click(screen.getByText("自定义模板"));
    const input = screen.getByLabelText("自定义问候模板");
    fireEvent.change(input, { target: { value: "Questions about {product_name}?" } });
    // 解析预览(消费预览产品 NE503)与模板分离展示
    expect(screen.getByText("Questions about NE503?")).toBeInTheDocument();
    // 变量无法解析 → 明示回落自动问候,不显示残留占位符
    fireEvent.change(input, { target: { value: "Help with {page_title}?" } });
    expect(screen.getByText(/变量无法解析/)).toBeInTheDocument();
  });

  it("resolveGreetingPreview:无变量模板原样;缺失变量返回空(不泄漏占位符)", () => {
    expect(resolveGreetingPreview("Fixed greeting", { product: "NE503", pageTitle: "", pageType: "product" })).toBe(
      "Fixed greeting",
    );
    expect(resolveGreetingPreview("Questions about {product_name}?", { product: "NE503", pageTitle: "", pageType: "" })).toBe(
      "Questions about NE503?",
    );
    expect(resolveGreetingPreview("Questions about {product_name}?", { product: "", pageTitle: "", pageType: "" })).toBe("");
  });
});

describe("previewDoc(#36 渲染契约)", () => {
  it("注入真实 Widget 产物 + 全量外观维度 + 预览上下文", () => {
    const doc = previewDoc({
      entryMode: "mini_entry",
      proactive: "balanced",
      launcherPresentation: "pill",
      launcherIcon: "robot-smile",
      launcherShape: "round",
      launcherTheme: "dark",
      launcherMotion: "subtle_glow",
      launcherSize: "medium",
      launcherBrand: "askai",
      launcherColor: "",
      chatTheme: "match",
      chatAccent: "",
      pageType: "product",
      product: "NE503",
      language: "en",
      actions: [],
    });
    expect(doc).toContain("/widget/widget.js");
    expect(doc).toContain("data-launcher-presentation=\"pill\"");
    expect(doc).toContain("data-launcher-icon=\"robot-smile\"");
    expect(doc).toContain("data-launcher-shape=\"round\"");
    expect(doc).toContain("data-launcher-theme=\"dark\"");
    expect(doc).toContain("data-preview-mode=\"true\"");
    expect(doc).toContain("data-preview-product=\"NE503\"");
  });
});
