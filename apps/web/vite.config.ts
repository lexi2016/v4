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
        v45Selection: resolve(__dirname, "v45/selection/index.html"),
        v45Research: resolve(__dirname, "v45/research/index.html"),
        v45Review: resolve(__dirname, "v45/review/index.html"),
      },
    },
  },
});
