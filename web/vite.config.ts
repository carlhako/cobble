/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The build emits the static bundle straight into the Python package so the
// FastAPI process can serve it (design.md D2). `npm run dev` proxies API and
// SSE calls to a locally running `python -m cobble`.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/cobble/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/health": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
