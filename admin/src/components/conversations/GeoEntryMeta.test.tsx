import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GeoEntryMeta } from "./GeoEntryMeta";

describe("GeoEntryMeta (#68 Conversation Review Country/Entry 元数据)", () => {
  it("权威值原样呈现:国家码 + 站点权威标签,title 携带完整值", () => {
    render(
      <GeoEntryMeta
        country="US"
        entry={{ site_id: "site-a", display_name: "官网" }}
      />,
    );
    const node = screen.getByText("US · 官网");
    expect(node.getAttribute("data-geo-entry")).not.toBeNull();
    expect(node.getAttribute("title") ?? "").toContain("国家/地区：US");
    expect(node.getAttribute("title") ?? "").toContain("访问入口：官网（site-a）");
  });

  it("无权威国家与无站点身份呈现中性 Unknown,不从 channel/URL 猜测", () => {
    render(<GeoEntryMeta country={null} entry={null} />);
    const node = screen.getByText("未知 · 未知");
    expect(node.getAttribute("data-geo-entry")).not.toBeNull();
    expect(node.getAttribute("title") ?? "").toContain("国家/地区：未知");
    expect(node.getAttribute("title") ?? "").toContain("访问入口：未知");
  });

  it("维度相互独立:国家已知但无站点身份时只对入口呈现 Unknown", () => {
    render(<GeoEntryMeta country="DE" entry={null} />);
    expect(screen.getByText("DE · 未知").getAttribute("data-geo-entry")).not.toBeNull();
  });
});
