import { defineConfig } from "vitest/config";
import { resolve } from "node:path";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  test: { environment: "jsdom" },
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        dailyResearchCommand: resolve(__dirname, "daily-research-command/index.html"),
        managerSelection: resolve(__dirname, "manager-selection/index.html"),
      },
    },
  },
});
