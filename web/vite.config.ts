/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The build emits the static bundle straight into the Python package so the
// FastAPI process can serve it (design.md D2). `npm run dev` proxies API and
// SSE calls to a locally running `python -m cobble`.
//
// Cobble's default port is 80, which needs privileges the dev machine usually
// does not hand out. Run the backend on an unprivileged port and point the
// proxy at it with the same variable:
//   COBBLE_PORT=8000 python -m cobble
//   COBBLE_PORT=8000 npm run dev
const backend = `http://127.0.0.1:${process.env.COBBLE_PORT ?? "80"}`;

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/cobble/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": {
        target: backend,
        changeOrigin: true,
      },
      "/health": backend,
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
