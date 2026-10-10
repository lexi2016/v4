import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { validateManagerWorkspace } from '../candidate/app/apps/web/src/api/managerWorkspace.ts';

const fixturePath = '/Users/lexi/Desktop/学习/agents调试/V4_SELECTION_REUSE_REPAIR_MAC_20261010_R1/evidence/final-workspace-readback-1.json';
const requestedBindings = { selection_date: '20261009', announcement_date: '20261008' };
const readFixture = (): Record<string, any> => JSON.parse(readFileSync(fixturePath, 'utf8'));

describe('R3 saved 20261009 workspace readback contract', () => {
  it('accepts the saved workspace when trend refs use the shared daily-supplement artifact identity', () => {
    const raw = readFixture();
    const firstTrend = raw.research_attention.cards
      .find((card: any) => card.symbol === 'HK.00175')
      .evidence.find((row: any) => row.evidence_lane === 'TREND_CONTINUATION');
    expect(firstTrend.source_refs.some((ref: any) => ref.artifact_path && ref.artifact_sha256)).toBe(true);
    expect(() => validateManagerWorkspace(raw, '20261009', requestedBindings)).not.toThrow();
  });

  it('still rejects a malformed artifact identity in trend provenance', () => {
    const raw = readFixture();
    const firstTrend = raw.research_attention.cards
      .find((card: any) => card.symbol === 'HK.00175')
      .evidence.find((row: any) => row.evidence_lane === 'TREND_CONTINUATION');
    const artifactRef = firstTrend.source_refs.find((ref: any) => ref.artifact_path);
    artifactRef.artifact_sha256 = 'not-a-sha256';
    expect(() => validateManagerWorkspace(raw, '20261009', requestedBindings))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');
  });

  it('keeps exact requested-date bindings fail-closed', () => {
    const raw = readFixture();
    raw.date_bindings.plan_date = '20261008';
    expect(() => validateManagerWorkspace(raw, '20261009', requestedBindings))
      .toThrow('WORKSPACE_DAILY_DATE_BINDING_MISMATCH');
  });

  it('keeps research-only safety flags fail-closed', () => {
    const raw = readFixture();
    raw.production_allowed = true;
    expect(() => validateManagerWorkspace(raw, '20261009', requestedBindings))
      .toThrow('WORKSPACE_SAFETY_INVALID');
  });
});
