import { describe, it, expect } from "vitest";
import {
  GENERATION_STATUS_LABELS,
  generationStatusLabel,
  syncIncidentSeverity,
  syncIncidentTypeLabel,
  generationEventSeverity,
  generationEventTypeLabel,
} from "./generationStatus";

/** #51 B2:P 轴生成状态 → 运营标签/严重度映射(自有模块,零网络)。 */
describe("generationStatus P 轴映射", () => {
  it("P 轴五词表全覆盖人类标签", () => {
    expect(Object.keys(GENERATION_STATUS_LABELS).sort()).toEqual(
      ["failed", "pending", "processing", "ready", "retired"].sort(),
    );
    expect(generationStatusLabel("pending")).toBe("待构建");
    expect(generationStatusLabel("processing")).toBe("构建中");
    expect(generationStatusLabel("ready")).toBe("已就绪");
    expect(generationStatusLabel("failed")).toBe("生成失败");
    expect(generationStatusLabel("retired")).toBe("已退役");
  });

  it("未知状态原样透传(不虚构翻译)", () => {
    expect(generationStatusLabel("some_new_state")).toBe("some_new_state");
  });

  it("同步事件严重度:failed=error / interrupted=warning", () => {
    expect(syncIncidentSeverity("failed")).toBe("error");
    expect(syncIncidentSeverity("interrupted")).toBe("warning");
    expect(syncIncidentTypeLabel("failed")).toBe("同步失败");
    expect(syncIncidentTypeLabel("interrupted")).toBe("同步中断");
  });

  it("生成事件严重度:failed=error / retired=info(retired 非失败)", () => {
    expect(generationEventSeverity("failed")).toBe("error");
    expect(generationEventSeverity("retired")).toBe("info");
    expect(generationEventTypeLabel("retired")).toBe("已退役");
  });
});
