import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const sourceRoot = process.env.V4_TEST_SOURCE_ROOT;
const cacheDir = process.env.V4_TEST_CACHE_DIR;
const dependencyRoot = process.env.V4_TEST_DEPENDENCIES_ROOT;
if (!sourceRoot || !cacheDir || !dependencyRoot) {
  throw new Error('Specify isolated V4_TEST_SOURCE_ROOT, V4_TEST_CACHE_DIR and V4_TEST_DEPENDENCIES_ROOT');
}
const { default: vue } = await import(pathToFileURL(resolve(dependencyRoot, '@vitejs/plugin-vue/dist/index.mjs')).href);
export default {
  root: resolve(sourceRoot, 'apps/web'),
  cacheDir: resolve(cacheDir),
  plugins: [vue()],
  test: { environment: 'jsdom', globals: false, maxWorkers: 1, minWorkers: 1, fileParallelism: false },
};
