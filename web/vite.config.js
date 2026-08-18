import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const BACKEND_URL = "http://127.0.0.1:8001";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      "/auth": BACKEND_URL,
      "/chat": BACKEND_URL,
      "/documents": BACKEND_URL,
      "/me": BACKEND_URL,
    },
  },
});
