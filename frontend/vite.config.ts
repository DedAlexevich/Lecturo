import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "prompt",
      injectRegister: false,
      manifest: {
        id: "/",
        name: "Lecturo",
        short_name: "Lecturo",
        description: "Конспекты, главы и квизы по записям лекций",
        lang: "ru",
        start_url: "/",
        scope: "/",
        display: "standalone",
        orientation: "any",
        background_color: "#f6f3ec",
        theme_color: "#f6f3ec",
        icons: [
          { src: "/pwa-192x192.png", sizes: "192x192", type: "image/png", purpose: "any" },
          { src: "/pwa-512x512.png", sizes: "512x512", type: "image/png", purpose: "any" },
          { src: "/maskable-512x512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,mjs,css,html,svg,png,ico,woff2,wasm}"],
        maximumFileSizeToCacheInBytes: 64 * 1024 * 1024,
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//, /^\/files\//, /^\/media\//],
        cleanupOutdatedCaches: true,
      },
    }),
  ],
  worker: { format: "es" },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/media": "http://localhost:80",
      "/files": "http://localhost:8080",
    },
  },
});
