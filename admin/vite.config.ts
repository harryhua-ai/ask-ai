/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  // 生产环境下 SPA 由 FastAPI 挂载在 /admin/ 路径下,
  // base 必须与之一致,否则浏览器请求 /assets/... 会 404。
  base: "/admin/",
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      // 共享 widget 聊天组件(admin login 页嵌入,单一聊天窗口来源)
      "@widget": path.resolve(__dirname, "../widget/src"),
    },
  },
  server: {
    port: 5174,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
  },
});
