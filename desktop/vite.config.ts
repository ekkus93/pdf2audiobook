/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";
import { defineConfig, runnerImport, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import process from "node:process";
const host = process.env.TAURI_DEV_HOST;

/**
 * `virtual:m3-theme.css`: the Material 3 colour variables, generated from the seeds in
 * src/theme/scheme.ts each time the app is built or served (spec D11.b).
 */
function materialTheme(): Plugin {
  const id = "virtual:m3-theme.css";
  const resolved = `\0${id}`;
  const source = fileURLToPath(new URL("./src/theme/scheme.ts", import.meta.url));
  return {
    name: "m3-theme",
    resolveId(request) {
      return request === id ? resolved : undefined;
    },
    async load(request) {
      if (request !== resolved) return undefined;
      const { module } = await runnerImport<typeof import("./src/theme/scheme")>(source, {
        // Its imports omit file extensions, which Node's own resolver rejects; transform it.
        environments: { inline: { resolve: { noExternal: ["@material/material-color-utilities"] } } },
      });
      return module.themeCss();
    },
  };
}

// https://vite.dev/config/
export default defineConfig(() => ({
  plugins: [react(), materialTheme()],

  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    restoreMocks: true,
    // Its imports omit file extensions, which Node's own resolver rejects.
    server: { deps: { inline: ["@material/material-color-utilities"] } },
  },

  // Vite options tailored for Tauri development and only applied in `tauri dev` or `tauri build`
  //
  // 1. prevent Vite from obscuring rust errors
  clearScreen: false,
  // 2. tauri expects a fixed port, fail if that port is not available
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host
      ? {
          protocol: "ws",
          host,
          port: 1421,
        }
      : undefined,
    watch: {
      // 3. tell Vite to ignore watching `src-tauri`
      ignored: ["**/src-tauri/**"],
    },
  },
}));
