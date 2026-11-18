import test from 'node:test';
import assert from 'node:assert/strict';
import { isTop200ForSelection, validateTop200Payload } from '../overlay/workbench-host/top200-group.mjs';

const sourceDate = '2026-11-18';
function payload(count = 200) {
  const top200 = Array.from({ length: count }, (_, index) => ({
    rank: index + 1,
    symbol: `${String(index + 1).padStart(6, '0')}.SZ`,
    name: `样本${index + 1}`,
    source_date: sourceDate,
    close: 10 + index / 100,
    change_pct: index / 10,
    amount_cny: 100000 + index,
  }));
  return {
    data_date: '20261118', top200_count: count, top200,
    RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false,
  };
}

test('accepts a complete, ranked 200-row payload without reordering', () => {
  const source = payload();
  const result = validateTop200Payload(source, sourceDate);
  assert.equal(result.status, 'READY');
  assert.equal(result.count, 200);
  assert.equal(result.rows[0], source.top200[0]);
  assert.equal(result.rows[199].rank, 200);
});

test('marks a valid short response as partial and preserves its ranks', () => {
  const result = validateTop200Payload(payload(199), sourceDate);
  assert.equal(result.status, 'PARTIAL');
  assert.equal(result.count, 199);
  assert.equal(result.rows[198].rank, 199);
});

test('rejects stale dates, duplicate symbols, and non-contiguous ranks', () => {
  assert.equal(validateTop200Payload(payload(), '2026-11-17').status, 'CANNOT_CONFIRM');
  assert.equal(isTop200ForSelection({ source_date: sourceDate }, sourceDate), true);
  assert.equal(isTop200ForSelection({ source_date: '2026-11-17' }, sourceDate), false);
  const duplicate = payload(); duplicate.top200[1].symbol = duplicate.top200[0].symbol;
  assert.equal(validateTop200Payload(duplicate, sourceDate).status, 'CANNOT_CONFIRM');
  const gap = payload(); gap.top200[20].rank = 22;
  assert.equal(validateTop200Payload(gap, sourceDate).status, 'CANNOT_CONFIRM');
});

test('rejects unsafe research flags and reports an empty day explicitly', () => {
  const unsafe = payload(); unsafe.orders_sent = true;
  assert.equal(validateTop200Payload(unsafe, sourceDate).status, 'CANNOT_CONFIRM');
  assert.equal(validateTop200Payload(payload(0), sourceDate).status, 'EMPTY');
  assert.equal(validateTop200Payload({
    status: 'CANNOT_CONFIRM_NOT_MATERIALIZED', source_date: sourceDate, top200: [],
    RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false,
  }, sourceDate).status, 'EMPTY');
});
