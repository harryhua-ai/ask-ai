import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite 配置:IIFE 打包,生成可嵌入第三方网站的 widget.js
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
});
