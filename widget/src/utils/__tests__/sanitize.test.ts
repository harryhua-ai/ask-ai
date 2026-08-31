import { describe, it, expect, afterEach } from "vitest";
import { renderMarkdownSafe, sanitizeHtml } from "../sanitize";
import { isAllowedUrl } from "../urlPolicy";
import type { SourceLink } from "../../types";

afterEach(() => {
  document.body.innerHTML = "";
});

describe("renderMarkdownSafe", () => {
  it("strips <script> injection", () => {
    expect(renderMarkdownSafe("<script>alert(1)</script>")).not.toContain("<script>");
  });

  it("strips <img onerror>", () => {
    const out = renderMarkdownSafe('<img src=x onerror="alert(1)">');
    expect(out).not.toContain("onerror");
    expect(out).not.toContain("<img");
  });

  it("preserves bold markdown", () => {
    expect(renderMarkdownSafe("**bold**")).toContain("<strong>bold</strong>");
  });

  it("preserves code block markdown", () => {
    const out = renderMarkdownSafe("```\ncode\n```");
    expect(out).toContain("<pre>");
    expect(out).toContain("<code>");
  });

  it("renders ### headings", () => {
    expect(renderMarkdownSafe("### Heading")).toContain("<h4>Heading</h4>");
  });

  it("renders #### headings", () => {
    expect(renderMarkdownSafe("#### Heading")).toContain("<h4>Heading</h4>");
  });

  it("renders ## headings", () => {
    expect(renderMarkdownSafe("## Heading")).toContain("<h4>Heading</h4>");
  });

  it("renders whitelist-domain links as <a>", () => {
    const out = renderMarkdownSafe("[Wiki](https://wiki.camthink.ai/guide)");
    expect(out).toContain('<a href="https://wiki.camthink.ai/guide"');
    expect(out).toContain("Wiki");
    expect(out).toContain('target="_blank"');
  });

  it("strips non-whitelist-domain links to plain text", () => {
    const out = renderMarkdownSafe("[Evil](https://evil.com/path)");
    expect(out).not.toContain("<a");
    expect(out).not.toContain("evil.com");
    expect(out).toContain("Evil");
  });

  it("renders multiple independent lists separately", () => {
    const md = "- Item A\n- Item B\n\nText between\n\n- Item C\n- Item D";
    const out = renderMarkdownSafe(md);
    const ulCount = (out.match(/<ul>/g) || []).length;
    expect(ulCount).toBe(2);
    expect(out).toContain("Item A");
    expect(out).toContain("Item C");
    expect(out).toContain("Text between");
  });

  it("consolidates [N] citations to paragraph end as numeric badges with title", () => {
    const sources: SourceLink[] = [
      { url: "https://github.com/camthink-ai/wiki/blob/main/overview.md", title: "overview", type: "github" },
      { url: "https://github.com/camthink-ai/wiki/blob/main/specs.md", title: "specs", type: "github" },
    ];
    const out = renderMarkdownSafe("NE503 has 20 TOPS [1][2]. It supports multi-model inference [1].", sources);
    expect(out).not.toContain("<sup>");
    expect(out).not.toContain("[1]");
    expect(out).toContain('ask-ai-ref');
    // T29:锚点文本 = 引用编号 n(数字徽标,不再是空锚点+logo 背景图)
    expect(out).toContain(">1</a>");
    expect(out).toContain(">2</a>");
    // T29:title 属性 = 来源标题,经白名单保留
    expect(out).toContain('title="overview"');
    expect(out).toContain('title="specs"');
  });

  it("renders multiple badges on one line in appearance order", () => {
    const sources: SourceLink[] = [
      { url: "https://github.com/camthink-ai/wiki/blob/main/a.md", title: "a", type: "github" },
      { url: "https://github.com/camthink-ai/wiki/blob/main/b.md", title: "b", type: "github" },
    ];
    const out = renderMarkdownSafe("Claim [2] then [1] end.", sources);
    const i1 = out.indexOf(">1</a>");
    const i2 = out.indexOf(">2</a>");
    expect(i1).toBeGreaterThanOrEqual(0);
    expect(i2).toBeGreaterThanOrEqual(0);
    // 同行按出现顺序排列:[2] 先出现 → 徽标 2 在前
    expect(i2).toBeLessThan(i1);
  });

  it("allowlists title attribute through DOMPurify", () => {
    const out = sanitizeHtml('<a href="https://github.com/a" title="hint">t</a>');
    expect(out).toContain('title="hint"');
    expect(out).toContain(">t</a>");
  });

  it("escapes malicious source title (quote break-out / HTML injection)", () => {
    const sources: SourceLink[] = [
      {
        url: "https://github.com/camthink-ai/wiki/blob/main/doc.md",
        title: '"><img src=x onerror=alert(1)>',
        type: "github",
      },
    ];
    const out = renderMarkdownSafe("fact [1] end.", sources);
    // 序列化层:引号必转义 → 属性边界不可逃逸
    expect(out).toContain('title="&quot;');
    // DOM 层(末道 DOMPurify 输出挂载后的真实安全属性):
    // 不产生 img 元素,title 为字面文本,href/编号不受影响
    document.body.innerHTML = out;
    const anchor = document.querySelector("a.ask-ai-ref");
    expect(anchor).not.toBeNull();
    expect(document.querySelector("img")).toBeNull();
    expect(anchor!.getAttribute("title")).toBe('"><img src=x onerror=alert(1)>');
    expect(anchor!.getAttribute("href")).toBe("https://github.com/camthink-ai/wiki/blob/main/doc.md");
    expect(anchor!.textContent).toBe("1");
  });

  it("strips [N] when N exceeds sources length", () => {
    const sources: SourceLink[] = [
      { url: "https://github.com/camthink-ai/wiki/blob/main/doc.md", title: "doc", type: "github" },
    ];
    const out = renderMarkdownSafe("text [2] here", sources);
    expect(out).not.toContain("ask-ai-ref");
    expect(out).not.toContain("[2]");
  });
});

describe("isAllowedUrl", () => {
  it("rejects javascript: protocol", () => {
    expect(isAllowedUrl("javascript:alert(1)")).toBe(false);
  });

  it("rejects data: protocol", () => {
    expect(isAllowedUrl("data:text/html,<script>")).toBe(false);
  });

  it("accepts github.com", () => {
    expect(isAllowedUrl("https://github.com/camthink-ai/ne503")).toBe(true);
  });

  it("rejects unknown domain", () => {
    expect(isAllowedUrl("https://evil.com/path")).toBe(false);
  });

  it("accepts camthink.ai subdomain", () => {
    expect(isAllowedUrl("https://docs.camthink.ai/guide")).toBe(true);
  });
});
