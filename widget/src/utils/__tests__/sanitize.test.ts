import { describe, it, expect } from "vitest";
import { renderMarkdownSafe } from "../sanitize";
import { isAllowedUrl } from "../urlPolicy";
import type { SourceLink } from "../../types";

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

  it("consolidates [N] citations to paragraph end as source titles", () => {
    const sources: SourceLink[] = [
      { url: "https://github.com/camthink-ai/wiki/blob/main/overview.md", title: "overview", type: "github" },
      { url: "https://github.com/camthink-ai/wiki/blob/main/specs.md", title: "specs", type: "github" },
    ];
    const out = renderMarkdownSafe("NE503 has 20 TOPS [1][2]. It supports multi-model inference [1].", sources);
    expect(out).not.toContain("<sup>");
    expect(out).not.toContain("[1]");
    expect(out).toContain('ask-ai-ref');
    expect(out).toContain("overview");
    expect(out).toContain("specs");
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
