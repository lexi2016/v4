import { resolve } from 'node:path';
import vue from '/workspace/scratch/0e089a11ee60/work/web_runtime/node_modules/@vitejs/plugin-vue/dist/index.mjs';
const sourceRoot = process.env.V4_TEST_SOURCE_ROOT;
const cacheDir = process.env.V4_TEST_CACHE_DIR;
if (!sourceRoot || !cacheDir) throw new Error('Specify isolated V4_TEST_SOURCE_ROOT and V4_TEST_CACHE_DIR');
export default {
  root: resolve(sourceRoot, 'apps/web'),
  cacheDir: resolve(cacheDir),
  plugins: [vue()],
  test: { environment: 'jsdom', globals: false, maxWorkers: 1, minWorkers: 1, fileParallelism: false },
};
