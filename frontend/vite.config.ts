/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // Proxy API calls to the backend in dev so the browser talks same-origin.
    // Overridden by VITE_API_BASE_URL when set (see api/client.ts).
    // NOTE: target is 127.0.0.1, NOT localhost — uvicorn binds IPv4 while
    // "localhost" can resolve to ::1 first (e.g. Docker's wslrelay answers
    // there and 404s). IPv4 is unambiguous.
    proxy: {
      "/filings": "http://127.0.0.1:8000",
      "/query": "http://127.0.0.1:8000",
      "/eval": "http://127.0.0.1:8000",
      "/stats": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
