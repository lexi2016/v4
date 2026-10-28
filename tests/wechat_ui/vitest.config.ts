// Isolated component harness, NOT a replacement apps/web package or V4 app.
import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  root: fileURLToPath(new URL('.', import.meta.url)),
  plugins: [vue()],
  resolve: { alias: { vue: fileURLToPath(new URL('./node_modules/vue/dist/vue.runtime.esm-bundler.js', import.meta.url)) } },
  test: { environment: 'jsdom', include: ['WechatResearchPanel.spec.ts'], restoreMocks: true },
});
