import { resolve } from 'node:path';
const sourceRoot = process.env.V4_TEST_SOURCE_ROOT;
const cacheDir = process.env.V4_TEST_CACHE_DIR;
if (!sourceRoot) throw new Error('V4_TEST_SOURCE_ROOT must identify the isolated application source');
if (!cacheDir) throw new Error('V4_TEST_CACHE_DIR must identify isolated temporary Vite cache storage');
export default {
  root: resolve(sourceRoot, 'apps/web'),
  cacheDir: resolve(cacheDir),
  test: { environment: 'jsdom', globals: false, maxWorkers: 1, minWorkers: 1,
    fileParallelism: false },
};
