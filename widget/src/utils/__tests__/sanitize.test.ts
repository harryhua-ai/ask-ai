import { describe, it, expect } from "vitest";
import { renderMarkdownSafe } from "../sanitize";
import { isAllowedUrl } from "../urlPolicy";

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
