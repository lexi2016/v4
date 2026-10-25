import { defineConfig } from "vitest/config";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import vue from "@vitejs/plugin-vue";

const webRoot = fileURLToPath(new URL(".", import.meta.url));
export default defineConfig({
  plugins: [vue()],
  test: { environment: "jsdom" },
  build: {
    rollupOptions: {
      input: {
        main: resolve(webRoot, "index.html"),
        dailyResearchCommand: resolve(webRoot, "daily-research-command/index.html"),
        managerSelection: resolve(webRoot, "manager-selection/index.html"),
        announcementTest: resolve(webRoot, "announcement-test.html"),
      },
    },
  },
});
