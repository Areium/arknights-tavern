import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// 截图验证专用配置：端口 5174，API 代理到 5001（独立后端实例）
export default defineConfig({
  plugins: [react()],
  base: "./",
  resolve: {
    alias: { "@": path.resolve(__dirname, "src"), url: "url/url.js" },
  },
  optimizeDeps: {
    include: ["pixi.js", "@pixi-spine/base", "@pixi-spine/runtime-3.8", "@pixi/utils", "@pixi/core"],
  },
  server: {
    port: 5174,
    strictPort: true,
    proxy: { "/api": { target: "http://127.0.0.1:5001", changeOrigin: true } },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
