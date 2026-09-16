// Issue #48 RED evidence — citation badge linkability guard missing.
//
// Defect site (main): widget/src/utils/sanitize.ts:84 renders the [N] source
// badge as `<a href="${escapeHtml(src.url)}">` WITHOUT the isAllowedUrl gate
// applied to markdown links (line 51) and WITHOUT an empty-URL guard. The
// backend serializes first-party knowledge-case sources with url="" (rag.py
// _extract_sources knowledge-case branch), so the widget currently renders a
// clickable `<a href="" target="_blank">` — self-navigation fake navigability.
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
import type { SourceLink } from "../../types";

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

// ---------------------------------------------------------------------------
// Track C C-3:state-driven rendering contract(GREEN 侧;后端词表见
// backend/pipeline/rag.py::_derive_link_state,跨源链路套件见
// tests/pipeline/test_issue48_linkability_chain.py —— 两侧 fixture 同源)。
// ---------------------------------------------------------------------------
describe("issue48: widget renders per explicit backend link state (C-3)", () => {
  const chainFixtures: Array<[string, SourceLink, { clickable: boolean; href?: string }]> = [
    // [case, API citation JSON(与后端 chain 套件同源), expected rendering]
    [
      "github-public",
      { url: "https://github.com/camthink-ai/neoruntime/blob/main/docker/dev/build.sh", title: "build", type: "github", link_state: "external" },
      { clickable: true, href: "https://github.com/camthink-ai/neoruntime/blob/main/docker/dev/build.sh" },
    ],
    [
      "wiki-canonical",
      { url: "https://wiki.camthink.ai/docs/neoeyes-ne301-series/overview", title: "0-overview", type: "github", link_state: "external" },
      { clickable: true, href: "https://wiki.camthink.ai/docs/neoeyes-ne301-series/overview" },
    ],
    [
      "github-private",
      { url: "https://github.com/camthink-ai/some-private-repo/blob/main/docs/x.md", title: "private-doc", type: "github", link_state: "private" },
      { clickable: false },
    ],
    [
      "wiki-stale-legacy-blob",
      { url: "https://github.com/camthink-ai/wiki-documents/blob/main/docs/6-neoeyes-ne503-series/4-application-guide/1-app-development/reference/2-sdk-reference.md", title: "2-sdk-reference", type: "github", link_state: "stale" },
      { clickable: false },
    ],
    [
      "knowledge-case-none",
      { url: "", title: "knowledge-case-a", type: "filesystem", link_state: "none" },
      { clickable: false },
    ],
  ];

  for (const [name, source, expected] of chainFixtures) {
    it(`chain fixture ${name}: renders ${expected.clickable ? "clickable canonical href" : "non-clickable static badge"}`, () => {
      const html = renderMarkdownSafe(ANSWER, [source]);
      if (expected.clickable) {
        expect(html).toContain(`<a href="${expected.href}"`);
        expect(html).toMatch(/<a\s[^>]*class="ask-ai-ref"/);
        expect(html).toContain('target="_blank"');
      } else {
        // 非 external 状态:绝无 <a> 伪造 —— 无自导航、无死链、无 off-host
        expect(html).not.toMatch(/<a\s[^>]*class="ask-ai-ref"/);
        expect(html).not.toContain('href=""');
        expect(html).not.toMatch(new RegExp(`href="${source.url.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\$&")}"`));
        // 真值呈现:静态徽标保留编号语义(C-3 truthful representation)
        expect(html).toMatch(/<span[^>]*class="ask-ai-ref[^"]*"[^>]*>1<\/span>/);
      }
    });
  }

  it("external state with off-host URL must not render clickable (defense in depth; isAllowedUrl only downgrades)", () => {
    const html = renderMarkdownSafe(ANSWER, [
      { url: "https://evil.example.com/payload.md", title: "off-host", type: "github", link_state: "external" },
    ]);
    expect(html).not.toMatch(/href="https:\/\/evil\.example\.com/);
    expect(html).toMatch(/<span[^>]*class="ask-ai-ref[^"]*"[^>]*>1<\/span>/);
  });
});
