import { fileURLToPath, URL } from "node:url";

import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { VitePWA } from "vite-plugin-pwa";

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        name: "NekoMail",
        short_name: "NekoMail",
        description: "A cute, self-hosted email client",
        theme_color: "#f5a3c7",
        background_color: "#fff5f9",
        display: "standalone",
        start_url: "/",
        icons: [
          { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
        ],
      },
      workbox: {
        // App-shell caching only — mail data still requires network. Icons
        // included so the installed app's own chrome (splash/icon) renders
        // even fully offline, not just the JS/CSS/HTML bundle.
        globPatterns: ["**/*.{js,css,html,png,svg}"],
        // Backend routes that do real full-page navigations (e.g. the Outlook
        // OAuth start/callback redirects) must reach the network, not the
        // cached SPA shell — without this the service worker silently
        // swallows every /api navigation once installed.
        navigateFallbackDenylist: [/^\/api\//],
      },
    }),
  ],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
});
