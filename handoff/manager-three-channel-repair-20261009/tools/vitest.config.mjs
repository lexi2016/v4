import { resolve } from 'node:path';
const sourceRoot = process.env.V4_TEST_SOURCE_ROOT;
if (!sourceRoot) throw new Error('V4_TEST_SOURCE_ROOT must identify the isolated application source');
export default {
  root: resolve(sourceRoot, 'apps/web'),
  test: { environment: 'jsdom', globals: false, maxWorkers: 1, minWorkers: 1,
    fileParallelism: false },
};
