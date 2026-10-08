import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { expect, it } from 'vitest';

const projectRoot = process.env.V4_TEST_SOURCE_ROOT || resolve(process.cwd(), '../..');
const python = process.env.V4_TEST_PYTHON || 'python3';
const ownerFixture = resolve(projectRoot, 'tests/manager_daily_ui_owner_fixture.py');

it('review probe: completed actual-owner DTO without required readback is rejected', async () => {
  const text = execFileSync(python, [ownerFixture, '--fixture'], {
    cwd: projectRoot, encoding: 'utf8', timeout: 30_000, maxBuffer: 2 * 1024 * 1024,
    env: { ...process.env, PYTHONPATH: `${projectRoot}:${projectRoot}/upstreams:${projectRoot}/tests` },
  });
  const value = JSON.parse(text);
  const daily = value.us_mapping_research.daily_run;
  expect(daily.status).toBe('COMPLETED');
  expect(daily.run_readback.status).toBe('VERIFIED');
  delete daily.run_readback;
  const api = await import(resolve(projectRoot, 'apps/web/src/api/managerWorkspace.ts'));
  expect(() => api.validateManagerWorkspace(value, '20261008')).toThrow();
});
