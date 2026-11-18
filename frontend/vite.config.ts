import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Em desenvolvimento, /api é encaminhado para o FastAPI (porta 8000).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.VITE_API_URL ?? "http://127.0.0.1:8000", changeOrigin: true } },
  },
  build: { chunkSizeWarningLimit: 5000 },
});
