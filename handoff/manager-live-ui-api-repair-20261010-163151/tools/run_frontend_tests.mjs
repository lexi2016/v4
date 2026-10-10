#!/usr/bin/env node
/** Assemble the supplied before|after frontend in a temporary test directory. No live API. */
import { copyFile, cp, mkdir, mkdtemp, rm } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

const [variant = 'after', ...extra] = process.argv.slice(2);
if (!['before', 'after'].includes(variant) || extra.length) {
  console.error('Usage: node delivery/tools/run_frontend_tests.mjs before|after');
  process.exitCode = 2;
} else {
  const deliveryRoot = path.resolve(import.meta.dirname, '..');
  const supportRoot = path.join(deliveryRoot, 'test_support/frontend/src');
  const testFile = path.join(deliveryRoot, 'tests/frontend/runtime.test.mjs');
  const changedModules = ['catalystObservationPanel.ts', 'dailyChannels.ts', 'businessStatus.ts', 'researchAttention.ts'];
  let temporary;
  try {
    temporary = await mkdtemp(path.join(os.tmpdir(), 'manager-frontend-regression-'));
    const sourceRoot = path.join(temporary, 'apps/web/src');
    await cp(supportRoot, sourceRoot, { recursive: true });
    for (const filename of changedModules) {
      const relative = path.join('manager-selection', filename);
      const destination = path.join(sourceRoot, relative);
      await mkdir(path.dirname(destination), { recursive: true });
      await copyFile(path.join(deliveryRoot, variant, 'apps/web/src', relative), destination);
    }
    const env = {
      ...process.env,
      FRONTEND_SOURCE_ROOT: sourceRoot,
      FRONTEND_SUPPORT_ROOT: supportRoot,
      FRONTEND_RUNTIME_DEPS: process.env.FRONTEND_RUNTIME_DEPS || path.join(deliveryRoot, 'test_support/frontend'),
      FRONTEND_BROWSER_CACHE: process.env.FRONTEND_BROWSER_CACHE || path.join(temporary, 'browser-cache'),
    };
    if (env.FRONTEND_ARTIFACT_DIR) env.FRONTEND_ARTIFACT_DIR = path.resolve(env.FRONTEND_ARTIFACT_DIR);
    console.log(`SYNTHETIC_OFFLINE_TEST_ONLY: ${variant}; no live API, market capture, owner run, or application state writes.`);
    const exitCode = await new Promise((resolve, reject) => {
      const child = spawn(process.execPath, ['--test', '--test-concurrency=1', testFile], { env, stdio: 'inherit' });
      child.once('error', reject);
      child.once('exit', (code, signal) => {
        if (signal) reject(new Error(`Frontend test process ended by ${signal}`));
        else resolve(code ?? 1);
      });
    });
    process.exitCode = exitCode;
  } catch (error) {
    console.error(error);
    process.exitCode = 1;
  } finally {
    if (temporary) await rm(temporary, { recursive: true, force: true });
  }
}
