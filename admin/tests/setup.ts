import "@testing-library/jest-dom/vitest";

// jsdom 无 ResizeObserver;Radix Switch(ui/switch.tsx,radix use-size)挂载时依赖。
// 受保护 stub:宿主已有实现时不覆盖(v1.6.3 Wave 1 Track B 测试基建,零产品影响)。
if (typeof globalThis.ResizeObserver === "undefined") {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver =
    ResizeObserverStub;
}
