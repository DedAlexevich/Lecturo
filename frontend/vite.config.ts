import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  worker: { format: "es" },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/files": "http://localhost:8080",
    },
  },
});
