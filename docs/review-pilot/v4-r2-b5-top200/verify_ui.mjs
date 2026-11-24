import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {classificationText, matchesClassification} from './ui-overlay/workbench-host/classification-local.mjs';

const shell = readFileSync(new URL('./ui-overlay/workbench-host/dot/shell/workbench.local.mjs', import.meta.url), 'utf8');
const start = shell.indexOf('const formulaGroupLabels=');
const end = shell.indexOf('function validMarketContextSnapshot', start);
assert(start >= 0 && end > start);
const validate = runInNewContext(shell.slice(start, end) + '\nvalidateWorkbenchDay', {
  validateDay: value => value,
  preview: false,
});

const alias = {
  eligible_candidate: true,
  group_states: {b23_entry: 'TRUE', pb2_confirm: 'FALSE'},
  classification: {identity_status: 'BOUND_SAME_ENTITY_ST_NAME', classification: {main_industry: '教育'}},
};
const conflict = {
  eligible_candidate: false,
  group_states: {b23_entry: 'UNKNOWN', pb2_confirm: 'UNKNOWN'},
  classification: {identity_status: 'IDENTITY_CONFLICT_NAME', classification: null},
};
const day = {
  rows: [alias, conflict],
  formula_groups: {
    labels: {b23_entry: '192选股', pb2_confirm: '回测选股'},
    group_counts: {b23_entry: 1, pb2_confirm: 0},
    quarantined_identity_count: 1,
    status: 'READY',
  },
};

assert.equal(classificationText(alias), '教育');
assert.equal(matchesClassification(alias, {query: '教育'}), true);
assert.equal(classificationText(conflict), '');
assert.equal(matchesClassification(conflict, {query: '教育'}), false);
assert.equal(validate(day), day);
const empty = {rows: [conflict], formula_groups: {
  ...day.formula_groups, group_counts: {b23_entry: 0, pb2_confirm: 0}, status: 'READY_EMPTY',
}};
assert.equal(validate(empty), empty);
assert.equal(validate({...day, rows: [alias, {...conflict, group_states: alias.group_states}]}).formula_groups.status,
  'CANNOT_CONFIRM_NOT_MATERIALIZED');
assert.equal(validate({...day, formula_groups: {...day.formula_groups, quarantined_identity_count: 0}}).formula_groups.status,
  'CANNOT_CONFIRM_NOT_MATERIALIZED');
console.log('PASS_UI_SAME_ENTITY_FILTER_AND_MIXED_DAY_VALIDATION');

function shellSection(from, to) {
  const begin = shell.indexOf(from);
  const end = shell.indexOf(to, begin + from.length);
  assert(begin >= 0 && end > begin, from);
  return shell.slice(begin, end);
}

const date = '2026-11-23';
const identity = {source_date: date, observation_date: '2026-11-24', generation: 'source', input_sha256: 'input'};
const prior = {...alias, symbol: '002936.SZ', group_states: {b23_entry: 'FALSE', pb2_confirm: 'TRUE'}};
const isolated = {...conflict, symbol: prior.symbol};
const ordinary = {...alias, symbol: '300010.SZ'};
const ready = {...identity, rows: [prior, ordinary], formula_groups: {...day.formula_groups,
  group_counts: {b23_entry: 1, pb2_confirm: 1}, quarantined_identity_count: 0}};
const quarantined = {...identity, ...day, rows: [isolated, ordinary]};

function node(tag, textContent) {
  return {
    tag, textContent, children: [], dataset: {}, hidden: false,
    setAttribute() {}, removeAttribute() {}, after() {}, classList: {toggle() {}},
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
  };
}
const nodes = new Map();
const element = id => {
  if (!nodes.has(id)) nodes.set(id, node(id, ''));
  return nodes.get(id);
};
Object.assign(element('scope'), {value: 'all', options: [{}, {}]});
element('groupChips').append(node('span', '回测选股'));
element('stateLabels').append(node('p', '回测选股：TRUE'));
element('chartDetails').textContent = 'old chart';
const calls = [];
let completion;
let response = quarantined;
const host = {
  installCompletion(value) { completion = value; },
  bindDay() {},
  paintContext() {},
  paintClassificationCoverage() {},
  clearCompany() { calls.push('clear company and score'); },
  preserveChart() { calls.push('preserve chart'); },
};
const context = {
  node, $: element, day: ready, selected: prior, group: 'all', stockToken: 1,
  GROUPS: day.formula_groups.labels,
  window: {StockPanelHost: host}, document: {querySelectorAll: () => []},
  validateDay: value => value, preview: false,
  name: row => row.symbol, stateLabel: state => state,
  groupLabels: row => Object.entries(day.formula_groups.labels)
    .filter(([key]) => row.group_states[key] === 'TRUE').map(([, label]) => label),
  selection: () => ({date}), endpoint: part => part, loadJson: async () => response,
  configureDayGroups() {}, refreshV192Group: async () => {},
  renderSecondary() {}, selectedObservation() {},
  renderClassification() {},
  renderList() {
    // The all-ledger scope keeps the selected symbol when it is quarantined.
    assert.equal(element('scope').value, 'all');
    assert(context.day.rows.some(row => row.symbol === context.selected.symbol));
  },
  showChart() { calls.push('show chart'); },
  loadInteractive() { calls.push('load chart and score'); },
  clearInteractive() { calls.push('clear chart and statistics'); },
  loadCompany() { calls.push('load company'); },
  f10Cards: {
    cancel() { calls.push('cancel F10'); },
    show() { calls.push('load F10'); },
    refresh() { calls.push('refresh F10'); },
  },
  isFormulaF10Completion: () => true,
  top200FilterLabel: () => 'Top200', v192Summary: () => '',
};
runInNewContext([
  shell.slice(start, end),
  shellSection('function renderFilters()', 'function renderTop200List'),
  shellSection('function selectStock(r)', 'function showChart'),
  shellSection('function refreshSelectedProjection', 'let completionSerial'),
  'let completionSerial=0;',
  shellSection('window.StockPanelHost.installCompletion({', 'const originalRefresh='),
].join('\n'), context);

await completion.modules(['classification'], identity);
assert.equal(context.selected, isolated);
assert.equal(context.stockToken, 2);
assert.deepEqual(calls, ['clear chart and statistics', 'cancel F10', 'clear company and score']);
assert(!element('groupChips').children.some(child => child.textContent === '回测选股'));
assert(element('stateLabels').children.every(child => child.textContent.endsWith('UNKNOWN')));
assert.equal(element('interactivePanel').hidden, true);
assert.equal(element('chartDetails').textContent, '');
assert.equal(element('scope').options[0].textContent, '数值候选 · 1只');
assert.equal(element('scope').options[1].textContent, '已接入台账（仅冻结候选）· 2只');

await completion.modules(['list', 'classification'], identity);
await completion.modules(['f10'], identity);
assert.equal(calls.length, 3);

response = ready;
await completion.modules(['classification'], identity);
assert.equal(context.selected, prior);
assert.equal(context.stockToken, 3);
assert.deepEqual(calls.slice(3), ['show chart', 'load chart and score', 'load company', 'load F10']);
assert(element('groupChips').children.some(child => child.textContent === '回测选股'));
assert(element('stateLabels').children.some(child => child.textContent === '回测选股：TRUE'));
assert.equal(element('scope').options[0].textContent, '数值候选 · 2只');
console.log('PASS_UI_CLASSIFICATION_REFRESH_CLEARS_AND_RESTORES_SELECTED_DETAILS');
