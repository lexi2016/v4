import { describe, expect, it } from 'vitest';
import { validateManagerWorkspace, type JsonObject } from './managerWorkspace';
import { workspaceFixture } from '../manager-selection/dailyChannels.testHelper';

// Synthetic contract data: the diagnostic must never override the existing
// workspace/owner readback decision or claim evidence for an unrelated input.
const bindings = { plan_date: '20261009', selection_date: '20261009', announcement_date: '20261008' };
const source = { source_id: 'V35_RESEARCH_DATA_ROOT', source_date: '20261008',
  source_root_sha256: '1'.repeat(64), payload_path: 'research/archive/20261008.json',
  receipt_path: 'research/archive/20261008.receipt.json', slot: '', mode: 'REPLAY' };
function fixture(status: 'MATCH'|'CHANGED'|'CANNOT_CONFIRM' = 'CHANGED'): JsonObject {
  const value = workspaceFixture(bindings) as JsonObject;
  const diagnostic: JsonObject = { schema_version: 'v4.manager_input_identity_diagnostic.v1', status,
    saved_input_identity: status === 'CANNOT_CONFIRM' ? null : (status === 'MATCH' ? 'a' : 'b').repeat(64),
    current_input_identity: 'a'.repeat(64), reason_codes: status === 'CANNOT_CONFIRM' ? ['SAVED_COMPONENT_METADATA_MISSING'] : [],
    changed_components: status === 'CHANGED' ? [{ component_id: 'artifact:synthetic-consumed-leaf', change: 'CHANGED',
      saved_sha256: 'c'.repeat(64), current_sha256: 'd'.repeat(64), source: { ...source } }] : [],
    provenance_changes: [] };
  value.plan_product = { status: status === 'MATCH' ? 'CURRENT' : 'STALE_INPUTS_CHANGED',
    consumed: status === 'MATCH', input_identity_diagnostic: diagnostic };
  return value;
}
const diagnostic = (value: JsonObject) => (value.plan_product as JsonObject).input_identity_diagnostic as JsonObject;

describe('source-bound plan identity diagnostics at the workspace boundary', () => {
  it.each(['MATCH','CHANGED','CANNOT_CONFIRM'] as const)('accepts the supported %s transition without changing the workspace', status => {
    const value = fixture(status); const before = JSON.stringify(value);
    expect(validateManagerWorkspace(value, bindings.plan_date, bindings)).toBe(value);
    expect(JSON.stringify(value)).toBe(before);
  });
  it('preserves an older DTO without optional diagnostic metadata', () => {
    const value = fixture(); delete (value.plan_product as JsonObject).input_identity_diagnostic;
    expect(validateManagerWorkspace(value, bindings.plan_date)).toBe(value);
  });
  it('accepts a provenance-only difference while semantic inputs match', () => {
    const value = fixture('MATCH'); diagnostic(value).provenance_changes = [{
      component_id: 'artifact:synthetic-consumed-leaf', source: { ...source },
      saved_manifest_sha256: 'e'.repeat(64), current_manifest_sha256: 'f'.repeat(64) }];
    expect(validateManagerWorkspace(value, bindings.plan_date)).toBe(value);
  });
  it('accepts separately guarded date changes even when semantic hashes match', () => {
    const value = fixture(); const d = diagnostic(value); d.saved_input_identity = d.current_input_identity;
    d.changed_components = [{ component_id: 'date_bindings', change: 'CHANGED', saved_sha256: 'c'.repeat(64), current_sha256: 'd'.repeat(64) }];
    expect(validateManagerWorkspace(value, bindings.plan_date)).toBe(value);
  });
  it.each([
    ['unknown schema', (d: JsonObject) => { d.schema_version = 'diagnostic.v0'; }],
    ['unknown status', (d: JsonObject) => { d.status = 'READY'; }],
    ['unbound current identity', (d: JsonObject) => { d.current_input_identity = 'e'.repeat(64); }],
    ['invalid saved identity', (d: JsonObject) => { d.saved_input_identity = 'not-a-sha'; }],
    ['false MATCH', (d: JsonObject) => { d.status = 'MATCH'; d.changed_components = []; }],
    ['missing changed evidence', (d: JsonObject) => { d.changed_components = []; }],
    ['non-list changed evidence', (d: JsonObject) => { d.changed_components = {}; }],
    ['duplicate component', (d: JsonObject) => { (d.changed_components as JsonObject[]).push({ ...(d.changed_components as JsonObject[])[0] }); }],
    ['equal changed fingerprints', (d: JsonObject) => { const c = (d.changed_components as JsonObject[])[0]; c.current_sha256 = c.saved_sha256; }],
    ['unsupported added fingerprint', (d: JsonObject) => { (d.changed_components as JsonObject[])[0].change = 'ADDED'; }],
    ['bad source date', (d: JsonObject) => { ((d.changed_components as JsonObject[])[0].source as JsonObject).source_date = '20260230'; }],
    ['source path traversal', (d: JsonObject) => { ((d.changed_components as JsonObject[])[0].source as JsonObject).payload_path = '../other.json'; }],
    ['source root unbound', (d: JsonObject) => { ((d.changed_components as JsonObject[])[0].source as JsonObject).source_root_sha256 = null; }],
    ['unexplained uncertainty', (d: JsonObject) => { d.status = 'CANNOT_CONFIRM'; d.changed_components = []; d.reason_codes = []; }],
  ])('rejects %s rather than rendering a misleading source diagnosis', (_label, mutate) => {
    const value = fixture(); mutate(diagnostic(value));
    expect(() => validateManagerWorkspace(value, bindings.plan_date)).toThrow(/WORKSPACE_INPUT_IDENTITY_DIAGNOSTIC/);
  });
  it('rejects consumption when the component evidence reports a changed input', () => {
    const value = fixture(); (value.plan_product as JsonObject).consumed = true;
    expect(() => validateManagerWorkspace(value, bindings.plan_date)).toThrow(/WORKSPACE_INPUT_IDENTITY_DIAGNOSTIC/);
  });
  it('rejects a malformed provenance fingerprint even when semantic inputs match', () => {
    const value = fixture('MATCH'); diagnostic(value).provenance_changes = [{
      component_id: 'artifact:synthetic-consumed-leaf', source: { ...source },
      saved_manifest_sha256: 'e'.repeat(64), current_manifest_sha256: 'unknown' }];
    expect(() => validateManagerWorkspace(value, bindings.plan_date)).toThrow(/WORKSPACE_INPUT_IDENTITY_DIAGNOSTIC/);
  });
  it('still rejects an unsafe workspace carrying a valid diagnosis', () => {
    const value = fixture('MATCH'); value.orders_sent = true;
    expect(() => validateManagerWorkspace(value, bindings.plan_date)).toThrow('WORKSPACE_SAFETY_INVALID');
  });
});
