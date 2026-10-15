import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// The site is static and served from any path, so every asset URL is relative. It is built into
// the Python package, which ships it: users of `prooflens` need no Node. KaTeX's .woff and .ttf
// fonts are dropped; every browser that runs the app loads the .woff2 listed first.
export default defineConfig({
  base: "./",
  plugins: [
    svelte(),
    {
      name: "woff2-only",
      generateBundle(_, bundle) {
        for (const k of Object.keys(bundle)) if (/\.(woff|ttf)$/.test(k)) delete bundle[k];
      },
    },
  ],
  build: {
    target: "es2022",
    chunkSizeWarningLimit: 2000,
    outDir: "../engine/python/prooflens/web",
    emptyOutDir: true,
  },
});
