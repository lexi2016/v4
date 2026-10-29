const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const api = require('../research-panel/numeric283-panel.js');

const generation = '4787511e6c3125fa043fca9dafd2fdd3fa9496970220a3f0792cfe9732ce1a09';
const inputSha = '4ece54421d52a4ab488f06a06c8598b961c30ffbaf631bc7b9933b74161068b2';
const product = {
  schema_version: 'v4.a_share.daily_product.v1', status: 'PARTIAL_WITH_ROWS', data_date: '20261029',
  source_generation: generation,
  source_identity: {generation, asof: 20261029, input_sha256: inputSha},
  manifest: {path: '/bound/manifest.json', sha256: '01c4e2138b0f88ec6b7b59effc13a1edd572c3318840b170c9402c1e5ff74c56'},
  artifact: {path: '/bound/product.json', sha256: 'ac8f35f0014d3120ef0e8bac5b76f19ce9c2887b338078721753c98ac91afc16'},
  sample_only: false, RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false,
  processed_count: 5808, source_universe_count: 5808,
  processed_universe: Array.from({length: 5808}, (_, i) => String(i).padStart(6, '0') + '.SH'),
  unique_count: 247,
  rows: Array.from({length: 247}, (_, i) => ({
    symbol: String(600000 + i).padStart(6, '0') + '.SH', groups: 'nav_smallk', pending_groups: '',
  })),
  group_counts: {original: 0, nav_smallk: 247, nav_pullback: 0, nav_breakout: 0},
};
product.processed_universe.splice(0, 247, ...product.rows.map(row => row.symbol));

assert.equal(api.validateDatedData(product).length, 247, 'current D29 product accepts the actual 247-row scope');
assert.throws(() => api.validateDatedData({...product, processed_count: 1}));
assert.throws(() => api.validateDatedData({...product, group_counts: {...product.group_counts, nav_smallk: 283}}));
assert.throws(() => api.validateDatedData({...product, sample_only: true}));

function renderedDate(metadata) {
  const document = {createElement() {
    return {ownerDocument: document, children: [], setAttribute() {}, appendChild(child) { this.children.push(child); }};
  }};
  const tbody = document.createElement('tbody');
  api.renderRows(tbody, [product.rows[0]], metadata);
  return tbody.children[0].children[5].textContent;
}
for (const observation_date of [undefined, null, '', 'invalid']) {
  assert.equal(renderedDate({...product, observation_date}), 'D20261029 / 观察未指定',
    'a dated product cannot inherit the frozen snapshot observation date');
}
assert.equal(renderedDate({...product, observation_date: '20261102'}), 'D20261029 / 观察20261102');
assert.equal(renderedDate(api.EXPECTED), 'D20261028 / 观察20261029', 'the original fixed snapshot retains its declared date');

const event = {
  schema_version: 'v4.a_share.daily_completion.v1', event_id: 'a3771f43d3b38c1bdcafe71d7a87275092a26d9e39b9c3228c19a4f96ddb097f',
  data_date: product.data_date, source_generation: generation, input_sha256: inputSha,
  status: product.status, processed_count: 5808, source_universe_count: 5808,
  manifest: product.manifest, artifact: product.artifact,
  RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false,
};
assert.equal(api.validateDailyCompletionEvent(event), event);
assert.equal(api.completionMatchesProduct(event, product), true, 'completion event binds both current immutable refs');
assert.equal(api.completionMatchesProduct({...event, manifest: {...event.manifest, sha256: '0'.repeat(64)}}, product), false);
assert.equal(api.completionMatchesProduct(event, {...product, source_identity: {...product.source_identity, input_sha256: '0'.repeat(64)}}), false);
assert.throws(() => api.validateDailyCompletionEvent({...event, orders_sent: true}));

const checkpoint = {
  symbol: '600025.SH', data_date: '20261029',
  historical_coverage: {evaluated_count: 1, evaluated_dates: ['20261029'], known_full_history: false,
    missing: ['HISTORICAL_FULL_CONDITION_BOOTSTRAP'], historical_PIT: false,
    unknown_by_group: {nav_breakout: 0}},
  statistics: {status: 'DESCRIPTIVE_STATS_COMPUTED', asof: '2026-10-29',
    price_distribution: {
      near_250: {percentile_le: 0.44, n: 250, start_date: '2025-10-29', end_date: '2026-10-29'},
      all_history: {percentile_le: 0.51, n: 2150, start_date: '2017-12-15', end_date: '2026-10-29'},
    },
    groups: [{group_id: 'nav_breakout', identity_status: 'BOUND', rule_sha256: 'e'.repeat(64),
      source_identity: {generation, input: inputSha, formula: api.D29_NUMERIC_FORMULA_SHA256,
        rule_sha256: 'e'.repeat(64), asof: '2026-10-29', market: 'SH', basis: 'QFQ_ASOF', pit_status: 'NONPIT'},
      eligible_event_count: 1, horizons: {d2: {total: 1, valid: 0, positive: 0, negative: 0, flat: 0,
        not_matured: 1, missing_price: 0, mean_return_pct: null, median_return_pct: null,
        cases: [{event_date: '2026-10-29', target_date: '2026-11-02', status: 'not_matured',
          detail_status: 'TARGET_AFTER_ASOF', return_pct: null}]}}}],
  },
};
const presentation = api.statisticsPresentation(checkpoint, checkpoint.symbol, product);
assert.match(presentation.coverageSummary, /1 个日期（2026-10-29）/);
assert.match(presentation.coverageSummary, /HISTORICAL_FULL_CONDITION_BOOTSTRAP/);
assert.match(presentation.coverageSummary, /历史非PIT/);
assert.match(presentation.priceLines[0], /44\.00%.*n=250/);
assert.equal(presentation.groups[0].bound, true);
assert.match(presentation.groups[0].summary, /同条件历史事件 1/);
assert.match(presentation.groups[0].horizons[0].summary, /有效 0\/1.*未成熟 1/);
assert.match(presentation.groups[0].horizons[0].cases[0].target_date, /2026-11-02/);
const wrongFormula = structuredClone(checkpoint);
wrongFormula.statistics.groups[0].source_identity.formula = '9'.repeat(64);
assert.equal(api.statisticsPresentation(wrongFormula, checkpoint.symbol, product).groups[0].bound, false,
  'cross-formula event returns stay unconfirmed');

const noCoverage = api.statisticsPresentation({symbol: '600025.SH'}, '600025.SH', product);
assert.match(noCoverage.coverageSummary, /未绑定；未启动全历史回算/);
assert.match(noCoverage.priceLines[0], /未绑定当前日期产品/);

const csv = api.toCsv([product.rows[0]], product);
assert.match(csv, /manifest_sha256.*artifact_sha256/);
assert.doesNotMatch(csv, /FINAL_NUMERIC_CANDIDATES|20261028|55a65b75/);

const chart = {ts_code: '600025.SH', end_date: '20261029', formula_version: api.CHART_NAMESPACE,
  research_only: true, production_allowed: false, buy_gate_updated: false, orders_sent: false,
  status: 'READY', identity: {generation_id: generation, input_sha256: inputSha, asof_date: 20261029},
  rows: [{ts_code: '600025.SH', trade_date: '20261029'}]};
assert.equal(api.validateDatedChart(chart, '600025.SH', product).status, 'READY');
assert.throws(() => api.validateDatedChart({...chart, identity: {...chart.identity, generation_id: 'e'.repeat(64)}}, '600025.SH', product));
assert.equal(api.validateDatedChart({...chart, status: 'CANNOT_CONFIRM'}, '600025.SH', product).status, 'CANNOT_CONFIRM');

const panelHtml = fs.readFileSync(path.join(__dirname, '../research-panel/daily.html'), 'utf8')
  .split('<section id="dailyNumeric283Panel"')[1].split('</section>')[0];
const panelJs = fs.readFileSync(path.join(__dirname, '../research-panel/numeric283-panel.js'), 'utf8');
const reportsJs = fs.readFileSync(path.join(__dirname, '../research-panel/related-reports.js'), 'utf8');
assert.doesNotMatch(panelHtml, /20261028|固定日期名单|FINAL_NUMERIC_CANDIDATES/);
assert.doesNotMatch(panelJs, /numeric283-candidates\.json|setInterval\s*\(/);
assert.match(panelJs, /new windowObject\.EventSource\("\/api\/v4\/research\/events"\)/);
assert.match(reportsJs, /\/api\/v4\/research\/pdf-relations/);
assert.match(reportsJs, /\/api\/v4\/research\/pdf-documents\//);
assert.doesNotMatch(reportsJs, /\/api\/v3\//);

console.log('D29 247-row binding, exact completion refs, stored cache display, no-poll refresh, and report API assertions PASS');
