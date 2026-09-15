// Issue #48 RED evidence — citation badge linkability guard missing.
//
// Defect site (main): widget/src/utils/sanitize.ts:84 renders the [N] source
// badge as `<a href="${escapeHtml(src.url)}">` WITHOUT the isAllowedUrl gate
// applied to markdown links (line 51) and WITHOUT an empty-URL guard. The
// backend serializes first-party knowledge-case sources with url="" (rag.py
// _collect_public_sources), so the widget currently renders a clickable
// `<a href="" target="_blank">` — self-navigation fake navigability.
//
// Frozen direction: v1.6.4 Track C contract §1 C-2 (no fake navigability) and
// C-3 (widget renders per explicit link state; never from string shape).
//
// Characterization on main (2026-09-15, vitest probe):
//   url=""    -> `<a href="" ... class="ask-ai-ref" ...>`   (RED: fake link)
//   file://   -> href stripped by DOMPurify fallback        (incidentally safe)
//   off-host  -> `<a href="https://evil.example.com/...">`  (RED: bypasses policy)
import { describe, expect, it } from "vitest";
import { renderMarkdownSafe } from "../sanitize";

const ANSWER = "NE503 SDK 由该仓库维护 [1]。";

describe("issue48: citation badge linkability guard (Track C C-2/C-3)", () => {
  it("RED: empty citation url must not render a clickable anchor (no fake navigability)", () => {
    const html = renderMarkdownSafe(ANSWER, [
      { url: "", title: "knowledge-case-a", type: "filesystem" },
    ]);
    expect(html).not.toContain('href=""');
    expect(html).not.toMatch(/<a\s[^>]*class="ask-ai-ref"[^>]*>/);
  });

  it("RED: badge href must pass the same URL policy as markdown links", () => {
    const html = renderMarkdownSafe(ANSWER, [
      { url: "https://evil.example.com/payload.md", title: "off-host", type: "github" },
    ]);
    expect(html).not.toMatch(/href="https:\/\/evil\.example\.com/);
  });

  it("characterization: file:// badge must not expose a navigable href", () => {
    const html = renderMarkdownSafe(ANSWER, [
      { url: "file:///repo/docs/x.md", title: "local-git", type: "local_git" },
    ]);
    expect(html).not.toMatch(/<a\s[^>]*href=/);
  });
});
