import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

const shellPath = new URL('../../apps/web/public/research-panel/workbench-host/dot/shell/workbench.local.mjs', import.meta.url);
const shell = await readFile(shellPath, 'utf8');
const labelSource = shell.slice(shell.indexOf('function observationCoverageLabel('), shell.indexOf('const observationHeader='));
const responseStart = shell.indexOf('function validateObservationResponse(');
const responseEnd = shell.indexOf('const f10Cards=', responseStart);
const responseSource = shell.slice(responseStart, responseEnd);
const loadFunctions = new Function('validateSnapshot', `${labelSource}\n${responseSource}\nreturn {observationCoverageLabel,validateObservationResponse};`);

const FLAGS = {RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false};
const DAY = {
  source_date: '2026-11-13', observation_date: '2026-11-16', generation: 'a'.repeat(64),
  input_sha256: 'b'.repeat(64), numeric_manifest: {path: '/fixture/manifest.json', sha256: 'c'.repeat(64)},
  rows: [{symbol: '600001.SH', eligible_candidate: true}, {symbol: '000001.SZ', eligible_candidate: true}],
};

function coverage(status, counts, reasons = []) {
  return {
    schema: 'V4_WORKBENCH_OBSERVATION_COVERAGE_V1', scope_kind: 'SOURCE_PRODUCT', status,
    source_date: DAY.source_date, observation_date: DAY.observation_date, generation: DAY.generation,
    input_sha256: DAY.input_sha256, numeric_manifest: DAY.numeric_manifest, ...counts, reasons, ...FLAGS,
  };
}

function snapshot(rows) {
  return {
    schema: 'OBSERVATION_SNAPSHOT_VIEW_V1', source_date: DAY.source_date, observation_date: DAY.observation_date,
    source_generation: DAY.generation, input_sha256: DAY.input_sha256,
    parent_admission_sha256: DAY.generation, daily_contract_sha256: 'd'.repeat(64), rows,
    context: {}, context_sha256: null, snapshot_sha256: 'f'.repeat(64),
    analysis_admission: 'NOT_GRANTED', formula_review: 'PENDING', ...FLAGS,
  };
}

function response(latest, coverageValue, status = latest ? 'STORED_ONLY' : 'UNKNOWN_NO_BOUND_INTRADAY_SNAPSHOT', includeDates = true) {
  const value = {latest, status, ...FLAGS, coverage: coverageValue};
  if (includeDates) Object.assign(value, {source_date: DAY.source_date, observation_date: DAY.observation_date});
  return value;
}

test('source-product coverage validates broader saved scope and projects only the two visible symbols', () => {
  const sourceRows = [
    {symbol: '600001.SH', price: 10},
    {symbol: '600999.SH', price: 99},
  ];
  const saved = snapshot(sourceRows);
  const savedCoverage = coverage('PARTIAL', {
    expected_count: 4, observed_count: 2, valid_count: 2, missing_count: 2,
  }, ['MISSING_CANDIDATE_OBSERVATION_ROWS']);
  const {validateObservationResponse} = loadFunctions(() => {
    throw new Error('source-product rows must not pass through the legacy exact-visible-roster validator');
  });

  const result = validateObservationResponse(response(saved, savedCoverage, 'STORED_ONLY', false), DAY);

  assert.equal(saved.rows.length, 2, 'the original saved payload remains intact');
  assert.equal(result.coverage.expected_count, 4, 'the source-product denominator remains intact');
  assert.equal(result.snapshot, saved, 'the source snapshot remains available for scope-level context');
  assert.deepEqual(result.visibleSnapshot.rows.map(row => row.symbol), ['600001.SH', '000001.SZ']);
  assert.equal(result.visibleSnapshot.rows[0], sourceRows[0]);
  assert.equal(result.visibleSnapshot.rows[1].price, null);
  assert.equal(result.missingVisibleSymbols.has('000001.SZ'), true);
  assert.equal(result.missingVisibleSymbols.has('600999.SH'), false);
});

test('source-product coverage keeps date, generation, input, manifest, and snapshot hash bindings', () => {
  const sourceRows = [{symbol: '600001.SH', price: 10}, {symbol: '600999.SH', price: 99}];
  const validSnapshot = snapshot(sourceRows);
  const validCoverage = coverage('PARTIAL', {
    expected_count: 4, observed_count: 2, valid_count: 2, missing_count: 2,
  }, ['MISSING_CANDIDATE_OBSERVATION_ROWS']);
  const {validateObservationResponse} = loadFunctions(() => {
    throw new Error('source-product validation must not use the exact-roster validator');
  });

  for (const [field, value] of [
    ['source_date', '2026-11-12'], ['observation_date', '2026-11-17'],
    ['source_generation', '9'.repeat(64)], ['input_sha256', '8'.repeat(64)],
    ['parent_admission_sha256', '7'.repeat(64)], ['daily_contract_sha256', 'not-a-sha'],
    ['context_sha256', 'not-a-sha'], ['snapshot_sha256', 'not-a-sha'],
  ]) {
    const tampered = {...validSnapshot, [field]: value};
    assert.throws(() => validateObservationResponse(response(tampered, validCoverage), DAY),
      /OBSERVATION_COVERAGE_SNAPSHOT_IDENTITY/, `must reject changed ${field}`);
  }
  for (const [field, value] of [
    ['source_date', '2026-11-12'], ['observation_date', '2026-11-17'],
  ]) {
    const tampered = {...response(validSnapshot, validCoverage), [field]: value};
    assert.throws(() => validateObservationResponse(tampered, DAY),
      /OBSERVATION_COVERAGE_BINDING/, `must reject changed response ${field}`);
  }
  for (const [field, value] of [
    ['generation', '9'.repeat(64)], ['input_sha256', '8'.repeat(64)],
    ['numeric_manifest', {path: DAY.numeric_manifest.path, sha256: '7'.repeat(64)}],
  ]) {
    const tampered = {...validCoverage, [field]: value};
    assert.throws(() => validateObservationResponse(response(validSnapshot, tampered), DAY),
      /OBSERVATION_COVERAGE_BINDING/, `must reject changed coverage ${field}`);
  }
  for (const counts of [
    {...validCoverage, observed_count: 1},
    {...validCoverage, valid_count: 3},
    {...validCoverage, missing_count: 3},
  ]) {
    assert.throws(() => validateObservationResponse(response(validSnapshot, counts), DAY),
      /OBSERVATION_COVERAGE_COUNTS_CONFLICT/);
  }
});

test('unknown coverage stays unknown and keeps every visible symbol unavailable', () => {
  const savedCoverage = coverage('UNKNOWN_MISSING', {
    expected_count: null, observed_count: null, valid_count: null, missing_count: null,
  }, ['NO_BOUND_INTRADAY_SNAPSHOT']);
  const {validateObservationResponse} = loadFunctions(() => { throw new Error('must not validate a missing snapshot'); });

  const result = validateObservationResponse(response(null, savedCoverage), DAY);

  assert.equal(result.snapshot, null);
  assert.deepEqual([...result.missingVisibleSymbols], ['600001.SH', '000001.SZ']);
  assert.ok(result.visibleSnapshot.rows.every(row => row.price === null));
});

test('zero-valid and empty snapshots remain distinct from a missing snapshot', () => {
  const sourceError = 'CANNOT_CONFIRM_INTRADAY_SOURCE: original owner has no date-certified cumulative quote';
  const errorPayload = {...snapshot([
    {symbol: '600001.SH', error: sourceError},
    {symbol: '000001.SZ', error: sourceError},
  ]), context: {}, snapshot_sha256: 'd'.repeat(64)};
  const emptyPayload = {...snapshot([]), context: {}, snapshot_sha256: 'e'.repeat(64)};
  const {validateObservationResponse} = loadFunctions(() => { throw new Error('empty snapshots use their identity guard'); });
  const zero = validateObservationResponse(response(errorPayload, coverage('ZERO_VALID', {
    expected_count: 3, observed_count: 2, valid_count: 0, missing_count: 3,
  }, ['ZERO_VALID_OBSERVATION_ROWS', sourceError])), DAY);
  const empty = validateObservationResponse(response(emptyPayload, coverage('EMPTY', {
    expected_count: 0, observed_count: 0, valid_count: 0, missing_count: 0,
  }, ['EMPTY_EXPECTED_CANDIDATE_SCOPE'])), DAY);

  assert.equal(zero.snapshot, errorPayload);
  assert.equal(zero.coverage.status, 'ZERO_VALID');
  assert.equal(empty.coverage.status, 'EMPTY');
  assert.equal(zero.coverage.observed_count, 2);
  assert.equal(zero.coverage.valid_count, 0);
  assert.ok(zero.missingVisibleSymbols.has('600001.SH'));
  assert.ok(zero.visibleSnapshot.rows.every(row=>row.status==='UNKNOWN_SOURCE_OBSERVATION_ERROR'));
  assert.ok(zero.visibleSnapshot.rows.every(row => row.price === null));
  assert.ok(empty.visibleSnapshot.rows.every(row => row.price === null));
  assert.ok(loadFunctions(() => {}).observationCoverageLabel(zero.coverage).includes(sourceError));
});

test('coverage labels retain counts and the reason for every state', () => {
  const {observationCoverageLabel} = loadFunctions(() => {});
  const cases = [
    [coverage('UNKNOWN_MISSING', {expected_count: 2, valid_count: null, missing_count: null}, ['NO_BOUND_INTRADAY_SNAPSHOT']), '源产品观察范围覆盖 未知，有效未知 / 应有 2', '当日快照未绑定'],
    [coverage('ZERO_VALID', {expected_count: 2, valid_count: 0, missing_count: 2}, ['ZERO_VALID_OBSERVATION_ROWS','CANNOT_CONFIRM_INTRADAY_SOURCE: no bound cumulative quote']), '源产品观察范围覆盖 0 有效 / 应有 2', '没有已绑定行'],
    [coverage('PARTIAL', {expected_count: 2, valid_count: 1, missing_count: 1}, ['MISSING_CANDIDATE_OBSERVATION_ROWS']), '源产品观察范围覆盖 部分，有效 1 / 应有 2', '源产品观察范围未全覆盖'],
    [coverage('COMPLETE', {expected_count: 2, valid_count: 2, missing_count: 0}), '源产品观察范围覆盖 完整，有效 2 / 应有 2', ''],
    [coverage('EMPTY', {expected_count: 0, valid_count: 0, missing_count: 0}, ['EMPTY_EXPECTED_CANDIDATE_SCOPE']), '空范围 0 / 应有 0', '源产品候选范围为空'],
  ];
  for (const [value, count, reason] of cases) {
    const label = observationCoverageLabel(value);
    assert.ok(label.includes(count), label);
    if (reason) assert.ok(label.includes(reason), label);
  }
  assert.ok(observationCoverageLabel(coverage('ZERO_VALID', {
    expected_count: 2, valid_count: 0, missing_count: 2,
  }, ['ZERO_VALID_OBSERVATION_ROWS','CANNOT_CONFIRM_INTRADAY_SOURCE: no bound cumulative quote'])
  ).includes('CANNOT_CONFIRM_INTRADAY_SOURCE: no bound cumulative quote'));
});

test('legacy responses without coverage keep the old strict validator path', () => {
  const saved = snapshot(DAY.rows);
  let receivedDay;
  const {validateObservationResponse} = loadFunctions((value, day) => {
    receivedDay = day;
    return value;
  });

  const result = validateObservationResponse({latest: saved}, DAY);

  assert.equal(receivedDay, DAY);
  assert.equal(result.snapshot, saved);
  assert.equal(result.visibleSnapshot, saved);
  assert.equal(result.coverage, null);
});
