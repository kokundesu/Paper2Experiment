import {defineConfig} from "vite";
import tailwindcss from "@tailwindcss/vite";
import {fileURLToPath} from "node:url";

// `npm run dev` proxies the API to `p2e demo serve` (port 8780); `npm run build` writes dist/, which that server serves.
// "@/" is the chat module root in the files copied from Alex (src/alex), as in Alex itself, so they stay as they are.
export default defineConfig({
  plugins: [tailwindcss()],
  resolve: {alias: {"@": fileURLToPath(new URL("./src/alex/modules/chat", import.meta.url))}},
  esbuild: {jsx: "automatic"},
  server: {proxy: {"/api": "http://127.0.0.1:8780"}},
  build: {
    rollupOptions: {
      // radix-ui and motion ship "use client" directives for React Server Components; a client bundle drops them
      onwarn(warning, warn) {
        if (warning.code !== "MODULE_LEVEL_DIRECTIVE") warn(warning);
      },
    },
  },
});
