// vitest/config, not vite: it is the one that knows about the `test` key.
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

// Paths the API owns. Proxying them in dev keeps the browser on one origin, so
// the HttpOnly session cookie behaves exactly as it does in production, where
// FastAPI serves this build itself.
const API_PATHS = [
  "/assets",
  "/auth",
  "/campaigns",
  "/health",
  "/openapi.json",
  "/sender-addresses",
  "/templates",
];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Mirrors the "@/*" path mapping in tsconfig.app.json. TypeScript resolves
  // it on its own; the bundler needs telling.
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  // Built files are served from /static by the API process. The app's *pages*
  // live under /app — the API owns the root namespace, so the campaign list
  // page cannot sit at /campaigns alongside the endpoint of the same name.
  base: "/static/",
  build: {
    outDir: "../static",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // The editor libraries are most of the weight and change rarely.
        // Splitting them keeps the app chunk small and lets a browser reuse
        // them across deploys.
        manualChunks: {
          // CodeMirror is deliberately absent: naming it here would pull it
          // back into the entry's preload graph and undo the lazy import in
          // CampaignBodyEditor. Vite splits it on the dynamic import instead.
          tiptap: [
            "@tiptap/react",
            "@tiptap/starter-kit",
            "@tiptap/extension-image",
            "@tiptap/extension-link",
            "@tiptap/extension-text-align",
            "@tiptap/extension-underline",
          ],
          react: ["react", "react-dom", "react-router-dom"],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      API_PATHS.map((path) => [
        path,
        { target: "http://localhost:8000", changeOrigin: false },
      ]),
    ),
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
