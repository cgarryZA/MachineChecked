import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { readFileSync } from "node:fs";

// The site is static and served from any path, so every asset URL is relative. It is built into
// the Python package, which ships it: users of `prooflens` need no Node. KaTeX's .woff and .ttf
// fonts are dropped; every browser that runs the app loads the .woff2 listed first.
export default defineConfig({
  base: "./",
  plugins: [
    // An accessibility warning fails the build, so that a new one cannot hide among others.
    svelte({
      onwarn(warning, warn) {
        if (warning.code?.startsWith("a11y")) throw new Error(`${warning.filename}:${warning.start?.line}: ${warning.message}`);
        warn(warning);
      },
    }),
    {
      name: "woff2-only",
      generateBundle(_, bundle) {
        for (const k of Object.keys(bundle)) if (/\.(woff|ttf)$/.test(k)) delete bundle[k];
      },
    },
    {
      // The colour and type variables also ship as theme.css, unhashed, for the website's pages.
      name: "theme-css",
      generateBundle() {
        this.emitFile({ type: "asset", fileName: "theme.css", source: readFileSync("src/theme.css", "utf8") });
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
