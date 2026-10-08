import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const BACKEND_URL = "http://127.0.0.1:8001";

// API paths share names with app pages (/chat, /documents, /auth/callback).
// Page loads in the browser get the app; fetches go to the API.
const api = {
  target: BACKEND_URL,
  bypass: (req) => (req.headers.accept?.includes("text/html") ? "/index.html" : undefined),
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      "/auth": api,
      "/chat": api,
      "/documents": api,
      "/me": api,
    },
  },
});
