import assert from 'node:assert/strict';
import test from 'node:test';
import {priorCompanyCardContent, priorF10CardContent, validatePriorCompanySnapshot,
  validatePriorF10Snapshot} from '../../apps/web/public/research-panel/workbench-host/dot/shell/formula-company-prior.mjs';

const ref = (path, fill) => ({path, sha256:fill.repeat(64)});
const day = {
  source_date: '2026-11-20', observation_date: '2026-11-23',
  generation: 'e'.repeat(64), input_sha256: 'f'.repeat(64),
  numeric_manifest: ref('/products/20261120.json', 'b'),
};
const prior = (sourceDate='20261119') => ({
  schema: 'V4_FORMULA_PRIOR_COMPANY_SNAPSHOT_V1', status: 'PRIOR_AVAILABLE',
  symbol: '000610.SZ', selected_source_date: day.source_date, source_date: sourceDate,
  observation_date: day.observation_date, received_at: '2026-11-19T23:45:51.227370+08:00',
  selected_asof_cutoff: '2026-11-20T23:59:59.999999+08:00',
  current_candidate_identity: {
    data_date: '20261120', source_generation: day.generation,
    input_sha256: day.input_sha256, numeric_manifest: day.numeric_manifest,
  },
  material_identity: {
    data_date: sourceDate, source_generation: '1'.repeat(64), input_sha256: '2'.repeat(64),
    numeric_manifest: ref('/products/20261119.json', '3'),
  },
  materials_manifest: ref('/company/index.json', 'd'),
  material_ref: ref('/company/000610.SZ.json', 'c'),
  business_reported: {value:'历史主营'}, financials_reported:{latest_report_period:'2026-09-30'},
  shareholders_reported:{holder_count:12345}, report_catalog:[],
  material_lifecycle:{view_mode:'HISTORICAL_ASOF',historical_PIT_safe:false,
    asof_cutoff:'2026-11-20T23:59:59.999999+08:00',reader_asof_cutoff:'2026-11-20T23:59:59.999999+08:00'},
  RESEARCH_ONLY:true, production_allowed:false, buy_gate_updated:false, orders_sent:false,
});

test('a same-symbol older company snapshot is accepted only with its original dates and refs', () => {
  const accepted = validatePriorCompanySnapshot(prior(), day, '000610.SZ');
  const content = priorCompanyCardContent(accepted, 'NOT_MATERIALIZED');

  assert.match(content.company[0], /原来源日 20261119/);
  assert.match(content.company[0], /本地接收 2026-11-19T23:45:51/);
  assert.match(content.company[1], /历史主营/);
  assert.match(content.company[2], /本日 F10 尚未物化/);
  assert.match(content.company[3], /旧日二筛、行情和观察结论未带入/);
  assert.match(content.financial[0], /2026-09-30/);
});

test('a later source date is rejected for an older selected date', () => {
  const priorDay = {...day, source_date:'2026-11-19', observation_date:'2026-11-20'};
  const futureForSelection = prior('20261120');
  futureForSelection.selected_source_date = priorDay.source_date;
  futureForSelection.observation_date = priorDay.observation_date;
  futureForSelection.current_candidate_identity.data_date = '20261119';

  assert.throws(() => validatePriorCompanySnapshot(futureForSelection, priorDay, '000610.SZ'),
    /FORMULA_PRIOR_COMPANY_IDENTITY_CONFLICT/);
});

test('a changed symbol, current-source snapshot, or research payload cannot pass as prior', () => {
  const wrongSymbol = prior(); wrongSymbol.symbol = '000001.SZ';
  const sameDay = prior('20261120');
  const contaminated = prior(); contaminated.secondary_screen = {received_record:{}};

  assert.throws(() => validatePriorCompanySnapshot(wrongSymbol, day, '000610.SZ'));
  assert.throws(() => validatePriorCompanySnapshot(sameDay, day, '000610.SZ'));
  assert.throws(() => validatePriorCompanySnapshot(contaminated, day, '000610.SZ'));
});

test('prior receipt timestamps require an explicit zone and stay within selected and reader cutoffs', () => {
  const naive = prior(); naive.received_at = '2026-11-19T23:45:51.227370';
  const afterSelected = prior(); afterSelected.received_at = '2026-11-21T00:00:00+08:00';
  const afterReader = prior(); afterReader.received_at = '2026-11-20T13:00:00+08:00';
  afterReader.material_lifecycle.asof_cutoff = '2026-11-20T12:00:00+08:00';
  afterReader.material_lifecycle.reader_asof_cutoff = '2026-11-20T12:00:00+08:00';
  const exact = prior(); exact.received_at = '2026-11-20T23:59:59.999999+08:00';
  const laterReaderCutoff = prior();
  laterReaderCutoff.material_lifecycle.asof_cutoff = '2026-11-21T00:10:00+08:00';
  laterReaderCutoff.material_lifecycle.reader_asof_cutoff = '2026-11-21T00:10:00+08:00';

  assert.throws(() => validatePriorCompanySnapshot(naive, day, '000610.SZ'));
  assert.throws(() => validatePriorCompanySnapshot(afterSelected, day, '000610.SZ'));
  assert.throws(() => validatePriorCompanySnapshot(afterReader, day, '000610.SZ'));
  assert.equal(validatePriorCompanySnapshot(exact, day, '000610.SZ'), exact);
  assert.equal(validatePriorCompanySnapshot(laterReaderCutoff, day, '000610.SZ'), laterReaderCutoff);
  assert.throws(() => validatePriorCompanySnapshot({...prior(),
    selected_asof_cutoff:'2026-11-21T23:59:59.999999+08:00'}, day, '000610.SZ'));
});

test('an earlier owner F10 receipt remains visible with its original source date', () => {
  const value = {
    schema:'V4_FORMULA_PRIOR_F10_SNAPSHOT_V1', status:'PRIOR_AVAILABLE',
    symbol:'000610.SZ', selected_source_date:day.source_date,
    selected_observation_date:day.observation_date, source_date:'20261119',
    receipt:ref('/f10/20261119/receipt.json','a'), stock_ref:ref('/f10/20261119/stock.json','b'),
    current_candidate_identity:{data_date:'20261120',source_generation:day.generation,
      input_sha256:day.input_sha256,numeric_manifest:day.numeric_manifest},
    material_identity:{data_date:'20261119',source_generation:'1'.repeat(64),input_sha256:'2'.repeat(64),
      numeric_manifest:ref('/products/20261119.json','3')},
    f10:{symbol:'000610.SZ',status:'OBSERVED',historical_PIT:false,
      captured_at:'2026-11-19T22:00:00+08:00',source_updated_date:'2026-11-19',
      finance_updated_date:'2026-11-19',source_text_sha256:'4'.repeat(64),
      source_detail:{main_business:'历史 F10 主营'},financials:{holder_count:10000},
      RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false},
    historical_PIT:false,RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false,
  };
  const accepted = validatePriorF10Snapshot(value, day, '000610.SZ');
  const content = priorF10CardContent(accepted, 'CANNOT_CONFIRM_SOURCE_GAP');

  assert.match(content.company[0], /来源日 20261119/);
  assert.match(content.company[1], /历史 F10 主营/);
  assert.match(content.company[3], /本日 F10 有回执，本股缺少快照/);
  assert.match(content.financial[0], /旧 F10 报告期/);
});

test('an F10 receipt from after the selected date is rejected', () => {
  const historicalDay = {...day, source_date:'2026-11-19', observation_date:'2026-11-20'};
  const future = {
    schema:'V4_FORMULA_PRIOR_F10_SNAPSHOT_V1', status:'PRIOR_AVAILABLE',
    symbol:'000610.SZ', selected_source_date:historicalDay.source_date,
    selected_observation_date:historicalDay.observation_date, source_date:'20261120',
    receipt:ref('/f10/20261120/receipt.json','a'), stock_ref:ref('/f10/20261120/stock.json','b'),
    current_candidate_identity:{data_date:'20261119',source_generation:day.generation,
      input_sha256:day.input_sha256,numeric_manifest:day.numeric_manifest},
    material_identity:{data_date:'20261120',source_generation:'1'.repeat(64),input_sha256:'2'.repeat(64),
      numeric_manifest:ref('/products/20261120.json','3')},
    f10:{symbol:'000610.SZ',status:'OBSERVED',historical_PIT:false,
      captured_at:'2026-11-20T20:00:00+08:00',source_text_sha256:'4'.repeat(64),
      RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false},
    historical_PIT:false,RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false,
  };

  assert.throws(() => validatePriorF10Snapshot(future, historicalDay, '000610.SZ'),
    /FORMULA_PRIOR_F10_IDENTITY_CONFLICT/);
});
