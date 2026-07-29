/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite 配置:IIFE 打包,生成可嵌入第三方网站的 widget.js
// test 配置:vitest 使用 jsdom 环境(DOMPurify 需要 DOM)
export default defineConfig({
  plugins: [react()],
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
});
