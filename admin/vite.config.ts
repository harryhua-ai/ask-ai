/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, "");
  return {
    base: "/admin/",
    plugins: [react()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
        "@widget": path.resolve(__dirname, "../widget/src"),
      },
    },
    optimizeDeps: {
      include: ["dompurify"],
    },
    server: {
      port: 5174,
      proxy: {
        "/api": {
          target: env.VITE_API_TARGET ?? "http://localhost:8000",
          changeOrigin: true,
          secure: false,
        },
      },
    },
    build: {
      outDir: "dist",
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./tests/setup.ts"],
      exclude: [
        "**/node_modules/**",
        "**/dist/**",
        "**/.claude/**",
      ],
    },
  };
});
