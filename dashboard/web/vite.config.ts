import path from "path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

// https://vite.dev/config/
export default defineConfig({
  define: {
    // visible build marker so a stale cache is obvious at a glance
    __BUILD_ID__: JSON.stringify(new Date().toISOString().slice(5, 16).replace("T", " ")),
  },
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    // dev: proxy the Flask JSON API (and SSE streams) so the SPA can call /api/*
    proxy: {
      "/api": { target: "http://127.0.0.1:8080", changeOrigin: true },
    },
  },
})
