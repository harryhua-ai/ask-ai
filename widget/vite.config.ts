/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite 配置:IIFE 打包,生成可嵌入第三方网站的 widget.js
// test 配置:vitest 使用 jsdom 环境(DOMPurify 需要 DOM)
// NODE_ENV define 仅作用于 build:测试需要 development React(提供 act 等
// 测试入口;Issue #33 首绘时序测试依赖)。产物字节面不受影响。
export default defineConfig(({ command }) => ({
  plugins: [react()],
  ...(command === "build"
    ? { define: { "process.env.NODE_ENV": JSON.stringify("production") } }
    : {}),
  build: {
    lib: {
      entry: "src/index.tsx",
      name: "AskAIWidget",
      fileName: () => "widget.js",
      formats: ["iife"],
    },
    cssCodeSplit: false,
  },
  test: {
    environment: "jsdom",
  },
}));
