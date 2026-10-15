import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// The site is static and served from any path, so every asset URL is relative.
export default defineConfig({
  base: "./",
  plugins: [svelte()],
  build: { target: "es2022", chunkSizeWarningLimit: 2000 },
});
