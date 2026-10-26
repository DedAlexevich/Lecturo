import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/media": "http://localhost:80",
      "/files": "http://localhost:8080",
    },
  },
});
