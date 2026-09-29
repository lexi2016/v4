// Synthetic scalar contracts. No browser or historical-data acceptance.
// Run: node --experimental-strip-types --test src/app_shell/formatters.stage.contract.mjs
import assert from 'node:assert/strict';
import test from 'node:test';
import { aShareChangePct, formatPercent } from './formatters.ts';

test('explicit null cannot become last/open or yesterday change', () => {
  assert.equal(aShareChangePct({current_change_pct: null, open_price: 10, last_price: 10, d1_change_pct: 9}), null);
  assert.equal(formatPercent(aShareChangePct({current_change_pct: null, open_price: 10, last_price: 11})), '未知（缺比较依据）');
});
test('real zero stays zero and legacy absent field retains fallback', () => {
  assert.equal(aShareChangePct({current_change_pct: 0, open_price: 10, last_price: 11}), 0);
  assert.equal(formatPercent(0), '0%');
  assert.ok(Math.abs(aShareChangePct({open_price: 10, last_price: 11}) - 10) < 1e-8);
});

// Static SFC contract only; actual Vue rendering remains a Mac acceptance item.
import { readFileSync } from 'node:fs';
test('HK-only stage retains an explicit A not-applicable template branch', () => {
  const template = readFileSync(new URL('../App.vue', import.meta.url), 'utf8');
  assert.match(template, /v-if="selectedStage === 'STAGE_1545_1555'" class="empty-card" aria-label="A股不适用"/);
  assert.match(template, /不适用：15:45–15:55 仅适用于港股/);
  assert.match(template, /v-else-if="!aRows.length"/);
});
