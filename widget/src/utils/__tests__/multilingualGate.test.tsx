// ML 门(Widget 面):语言解析链 + UI 文案 + 本地化请求参数。
// 冻结语义:宿主显式 → <html lang> → 站点默认 → 浏览器 → 省略(en);
// UI_LANGUAGE 与 ANSWER_LANGUAGE 分离。

import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import {
  normalizeLanguage,
  readBrowserLanguage,
  readHtmlLang,
  resolveAskLanguage,
  resolveUiLanguage,
} from "../language";
import { uiStrings } from "../../i18n";
import { ChatPanel } from "../../components/ChatPanel";

describe("normalizeLanguage(en/zh 归一化,ML-G004 widget 面)", () => {
  it("zh/en 族归一到规范形", () => {
    expect(normalizeLanguage("zh-CN")).toBe("zh");
    expect(normalizeLanguage("zh_tw")).toBe("zh");
    expect(normalizeLanguage("zh-Hans")).toBe("zh");
    expect(normalizeLanguage("en-US")).toBe("en");
    expect(normalizeLanguage("EN")).toBe("en");
  });

  it("其他语言取主子标签;无效为 null", () => {
    expect(normalizeLanguage("fr-FR")).toBe("fr");
    expect(normalizeLanguage("pt-BR")).toBe("pt");
    expect(normalizeLanguage("")).toBeNull();
    expect(normalizeLanguage(null)).toBeNull();
    expect(normalizeLanguage("!!")).toBeNull();
  });
});

describe("resolveAskLanguage(解析链优先级,ML-G003/ML-G010)", () => {
  it("页面/宿主语言优先于浏览器语言(G-L2/G-L3)", () => {
    expect(
      resolveAskLanguage({
        htmlLang: "en",
        browserLanguage: "zh-CN",
        siteLanguage: "zh",
      }),
    ).toBe("en");
  });

  it("宿主显式配置最高;html lang 次之", () => {
    expect(
      resolveAskLanguage({
        configLanguage: "zh",
        htmlLang: "en",
        siteLanguage: "en",
      }),
    ).toBe("zh");
    expect(resolveAskLanguage({ htmlLang: "en-US", siteLanguage: "zh" })).toBe("en");
  });

  it("浏览器语言仅兜底;全空省略(交服务端文本检测)", () => {
    expect(resolveAskLanguage({ browserLanguage: "zh-CN" })).toBe("zh");
    expect(resolveAskLanguage({})).toBeUndefined();
  });
});

describe("readHtmlLang / readBrowserLanguage", () => {
  it("读取 <html lang>(jsdom)", () => {
    document.documentElement.setAttribute("lang", "zh-CN");
    expect(readHtmlLang(document)).toBe("zh-CN");
    document.documentElement.removeAttribute("lang");
    expect(readHtmlLang(document)).toBeNull();
  });

  it("读取浏览器语言", () => {
    expect(readBrowserLanguage({ language: "fr", languages: ["fr"] } as unknown as Navigator)).toBe("fr");
    expect(readBrowserLanguage(undefined)).toBeNull();
  });
});

describe("UI 文案(ML-G005:UI_LANGUAGE 与 ANSWER_LANGUAGE 分离)", () => {
  it("en/zh 文案切换;zh 失败文案与后端常量逐字一致", () => {
    expect(uiStrings("en").placeholder).toBe("Type your question...");
    expect(uiStrings("zh").placeholder).toBe("输入你的问题...");
    expect(uiStrings("zh").send).toBe("发送");
    expect(uiStrings("en").send).toBe("Send");
    // 与后端 SERVICE_UNAVAILABLE_MSG 逐字一致(PC-01 兜底)
    expect(uiStrings("zh").serviceUnavailable).toBe("服务暂时不可用,请稍后再试。");
  });

  it("UI 语言二值:非 zh 一律 en", () => {
    expect(resolveUiLanguage({ htmlLang: "fr" })).toBe("en");
    expect(resolveUiLanguage({ htmlLang: "zh-CN" })).toBe("zh");
  });
});

describe("ChatPanel 渲染本地化(ML-G005)", () => {
  const baseProps = {
    config: { apiUrl: "http://t" },
    messages: [],
    isStreaming: false,
    conversationId: null,
    suggestedQuestions: [],
    welcome: undefined as string | undefined,
    onSend: () => {},
    onClose: () => {},
    onFeedback: () => {},
    onUpload: async () => [],
  };

  it("en UI:英文占位/按钮/兜底欢迎语", () => {
    const html = renderToString(<ChatPanel {...baseProps} strings={uiStrings("en")} />);
    expect(html).toContain("Type your question...");
    expect(html).toContain("Send");
    expect(html).toContain("Hi! I&#x27;m Ask Camthink.ai — how can I help?");
    expect(html).not.toContain("输入你的问题");
  });

  it("zh UI:中文占位/按钮/兜底欢迎语", () => {
    const html = renderToString(<ChatPanel {...baseProps} strings={uiStrings("zh")} />);
    expect(html).toContain("输入你的问题...");
    expect(html).toContain("发送");
    expect(html).toContain("你好!我是 Ask Camthink.ai,有什么可以帮你?");
  });
});
