import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The FastAPI app mounts the built bundle at /assets and falls back to
// index.html for every other path, so the SPA can use history routing.
// `server.proxy` lets `npm run dev` talk to a locally running dashboard.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    assetsDir: "assets",
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8010",
      "/auth": "http://127.0.0.1:8010",
      "/healthz": "http://127.0.0.1:8010",
    },
  },
});
