import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const projectRoot = process.env.V4_TEST_SOURCE_ROOT || resolve(process.cwd(), '../..');
const python = process.env.V4_TEST_PYTHON || 'python3';
const routeFixture = resolve(projectRoot, 'tests/manager_daily_ui_route_fixture.py');

describe('independent actual route → saved-plan projector contract', () => {
  it('accepts only the exact ordinary-page GET DTO and its real post-generation read time', async () => {
    const output = execFileSync(python, [routeFixture], {
      cwd: projectRoot,
      encoding: 'utf8',
      timeout: 30_000,
      maxBuffer: 2 * 1024 * 1024,
      env: {
        ...process.env,
        PYTHONPATH: `${projectRoot}:${projectRoot}/upstreams:${projectRoot}/tests`,
        MANAGER_TEST_SOURCE_ROOT: projectRoot,
      },
    });
    const dto = JSON.parse(output);
    const apiPath = resolve(projectRoot, 'apps/web/src/api/managerWorkspace.ts');
    const projectionPath = resolve(projectRoot, 'apps/web/src/manager-selection/dailyResearchRun.ts');
    const api = await import(apiPath);
    const projector = await import(projectionPath);
    const target = '20261008';
    const bindings = { plan_date: target, selection_date: target, announcement_date: '20261007' };

    expect(() => api.validateManagerWorkspace(dto, target, bindings)).not.toThrow();
    const projected = projector.projectDailyResearchSummary(dto, bindings);
    const product = dto.plan_product;
    const readback = product.run_readback;
    expect(product.status).toBe('CURRENT');
    expect(product.consumed).toBe(true);
    expect(projected.plan.status).toBe('VERIFIED_SAVED');
    expect(projected.plan.runId).toBe(product.run_id);
    expect(projected.plan.generatedAt).toBe(product.generated_at);
    expect(projected.plan.readAt).toBe(readback.read_at);
    expect(Date.parse(readback.read_at)).toBeGreaterThanOrEqual(Date.parse(product.generated_at));
    expect(Date.parse(readback.read_at)).toBeGreaterThanOrEqual(Date.parse(readback.owner_finished_at));
  });
});
