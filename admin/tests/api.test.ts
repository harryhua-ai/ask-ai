import { describe, it, expect } from "vitest";
import { formatApiDetail } from "@/lib/api";

describe("formatApiDetail(T27:422 detail 扁平化)", () => {
  it("FastAPI 422 detail 数组 → msg 文本拼接", () => {
    const detail = [
      { loc: ["body", "config", "api_base"], msg: "Value error, api_base 主机 evil.example.net 不在 allowlist（通过 LLM_ALLOWED_HOSTS 配置）" },
      { loc: ["body", "config", "model"], msg: "Field required" },
    ];
    expect(formatApiDetail(detail)).toBe(
      "Value error, api_base 主机 evil.example.net 不在 allowlist（通过 LLM_ALLOWED_HOSTS 配置）; Field required",
    );
  });

  it("字符串 detail 原样返回", () => {
    expect(formatApiDetail("供应商不存在")).toBe("供应商不存在");
  });

  it("空值回退默认文案,其他对象 JSON 化", () => {
    expect(formatApiDetail(null)).toBe("请求失败");
    expect(formatApiDetail({ code: 1 })).toBe('{"code":1}');
  });
});
