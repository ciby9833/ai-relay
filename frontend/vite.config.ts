import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const apiTarget = process.env.VITE_API_TARGET ?? "http://localhost:8098";
const proxy = {
  "/api": apiTarget,
  // Keep /blog and /blog/ in React; all article documents/media come from PostgreSQL via API.
  "^/blog/[^/?]": apiTarget,
};

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy },
  preview: { proxy },
});
