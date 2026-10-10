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
      // Session endpoints: same path shape as the Vercel rewrite in vercel.json.
      "/api": { target: BACKEND_URL, changeOrigin: true, rewrite: (path) => path.replace(/^\/api/, "") },
      "/auth": api,
      "/chat": api,
      "/documents": api,
      "/me": api,
      "/org": api,
      "/collections": api,
      "/account": api,
      "/insights": api,
      "/home": api,
      "/verified": api,
      "/ping": api,
    },
  },
});
