import { defineConfig } from "vitest/config";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import vue from "@vitejs/plugin-vue";

const root = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  root,
  plugins: [vue()],
  cacheDir: resolve(root, ".test-cache"),
  test: {
    environment: "jsdom",
    include: ["src/App.hk-research-rows.spec.ts"],
  },
});
