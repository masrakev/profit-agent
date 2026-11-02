/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

import { BRAND } from "./src/brand.ts";

// The API is served same-origin through the dev server's proxy, so the session cookie (path
// `/api`, SameSite=Lax) and the CSRF check (Origin = APP_BASE_URL, http://localhost:3000 by
// default) work as in production, where the platform and the API share one origin.
const API_TARGET = process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000";
const MAILPIT_TARGET = process.env.VITE_MAILPIT_TARGET ?? "http://127.0.0.1:8025";

/** The page title comes from the one brand constant, like every visible mention of the name. */
const brandTitle: Plugin = {
  name: "brand-title",
  transformIndexHtml: (html) => html.replace("%BRAND_NAME%", BRAND.name),
};

export default defineConfig({
  plugins: [react(), tailwindcss(), brandTitle],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 3000,
    strictPort: true,
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: false },
      // Development only: the "use demo store" sign-in reads the link from Mailpit's inbox.
      "/__mailpit": {
        target: MAILPIT_TARGET,
        rewrite: (path) => path.replace(/^\/__mailpit/, ""),
      },
    },
  },
  preview: { port: 3000, strictPort: true },
  build: {
    target: "es2022",
    sourcemap: "hidden", // for error reports; not linked from the served bundles
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    restoreMocks: true,
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/api/schema.d.ts", "src/main.tsx", "src/test/**", "src/**/*.test.{ts,tsx}"],
      thresholds: { lines: 90, functions: 90, branches: 85, statements: 90 },
    },
  },
});
