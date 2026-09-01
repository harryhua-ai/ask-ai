import { describe, it, expect, vi } from "vitest";
import { fetchSiteConfig, resolveStarters } from "../siteConfig";
import type { SiteExperienceConfig } from "../../types";

describe("resolveStarters", () => {
  const DEFAULTS = ["默认一", "默认二"];

  it("站点 starters 有效时优先于默认", () => {
    const site: SiteExperienceConfig = { site_id: "s", starters: ["A", "B"] };
    expect(resolveStarters(site, DEFAULTS)).toEqual(["A", "B"]);
  });

  it("无站点配置 → 回退默认(legacy 行为)", () => {
    expect(resolveStarters(null, DEFAULTS)).toEqual(DEFAULTS);
  });

  it("starters 为空数组/非数组 → 回退默认", () => {
    expect(resolveStarters({ site_id: "s", starters: [] }, DEFAULTS)).toEqual(DEFAULTS);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect(resolveStarters({ site_id: "s", starters: "x" as any }, DEFAULTS)).toEqual(DEFAULTS);
  });

  it("starters 截断到 8 条上限", () => {
    const site: SiteExperienceConfig = {
      site_id: "s",
      starters: Array.from({ length: 12 }, (_, i) => `q${i}`),
    };
    expect(resolveStarters(site, DEFAULTS)).toHaveLength(8);
  });
});

describe("fetchSiteConfig", () => {
  it("200 → 解析站点体验配置", async () => {
    const payload = { site_id: "camthink-store", starters: ["q1"] };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(payload), { status: 200 })),
    );
    const cfg = await fetchSiteConfig("http://api", "camthink-store");
    expect(cfg.site_id).toBe("camthink-store");
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe(
      "http://api/api/widget/site-config?site_id=camthink-store",
    );
    vi.unstubAllGlobals();
  });

  it("403(fail-safe)→ 抛错,由调用方回退默认体验", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("", { status: 403 })),
    );
    await expect(fetchSiteConfig("http://api", "camthink-store")).rejects.toThrow("403");
    vi.unstubAllGlobals();
  });
});
