import assert from 'node:assert/strict';
import test from 'node:test';
import { appSource, beforeAppSource, beforeRuntimeSource, browser, evidenceHtml,
  findVnode, market, parseScript, primary, renderApp, runtimeSource, text, vnodeText, workbench } from './live_app_harness.mjs';

// Removing the R3 result derivation or replacing the live App by canonical
// bytes must fail these tests: user-visible evidence and existing events are
// exercised through actual Vue compiler output, not a recreated view model.
test('compiled live Stage renders both R3 research results with their distinct quote counts', async () => {
  const { html, state } = await renderApp();
  const panel = primary(evidenceHtml(html));
  assert.match(market(panel, 'A_SHARE'), /已计算 10 只.*行情 206 \/ 216 只，缺 10 只/);
  assert.match(market(panel, 'HK_CONNECT'), /已计算 10 只.*行情 695 \/ 695 只，缺 0 只/);
  assert.match(market(panel, 'HK_CONNECT'), /非正式 D1.*港股通资格待确认.*20261008.*2026-10-09T15:38:41\+08:00/);
  assert.match(text(panel), /自然时段验收 尚未验证/);
  assert.match(text(panel), /RESEARCH_ONLY=true · production_allowed=false · buy_gate_updated=false · orders_sent=false/);
  assert.equal(state.candidateColumnCountLabel('A'), '已计算 10 只');
  assert.equal(state.candidateColumnCountLabel('HK'), '已计算 10 只');
  assert.match(state.stageContextCounts('STAGE_0930_0935'), /A股 已计算 10 只.*港股 已计算 10 只/);
  assert.match(html, /港股通观察行/);
  assert.match(html, /正式 D1\/PIT 及资格待确认/);
});

for (const [label, mutate] of [
  ['workbench date', p => { p.trade_date = '20261008'; }],
  ['workbench stage', p => { p.stage.stage_id = 'STAGE_0925'; }],
  ['evidence date', p => { p.execution_evidence.trade_date = '20261008'; }],
  ['evidence stage', p => { p.execution_evidence.stage_id = 'STAGE_0925'; }],
]) test('compiled live Stage suppresses evidence from another ' + label, async () => {
  const payload = workbench(); mutate(payload);
  const { html, state } = await renderApp(payload);
  assert.equal(evidenceHtml(html), '');
  assert.doesNotMatch(html, /class="execution-evidence"/);
  assert.doesNotMatch(state.candidateColumnCountLabel('HK'), /已计算/);
  assert.match(html, /CANNOT_CONFIRM：当前日期与阶段没有可绑定的执行证据/);
});

for (const [label, mutate] of [
  ['date', r => { r.trade_date = '20261008'; }], ['stage', r => { r.stage_id = 'STAGE_0925'; }],
  ['market', r => { r.market = 'A_SHARE'; }], ['run', r => { r.run_id = 'other-run'; }],
  ['artifact', r => { r.artifact_id = 'other-artifact'; }],
  ['algorithm SHA', r => { r.algorithm_sha256 = 'f'.repeat(64); }],
  ['artifact SHA', r => { r.raw_artifact_sha256 = 'f'.repeat(64); }],
  ['count', r => { r.selected_rows = 9; }],
]) test('compiled live Stage keeps rows while rejecting conflicting result ' + label, async () => {
  const payload = workbench(); mutate(payload.execution_evidence.selection_results.HK_CONNECT);
  const original = structuredClone(payload);
  const { html, state } = await renderApp(payload);
  assert.match(market(primary(evidenceHtml(html)), 'HK_CONNECT'), /选股结果身份待核对/);
  assert.doesNotMatch(market(primary(evidenceHtml(html)), 'HK_CONNECT'), /已计算|已保存空结果/);
  assert.doesNotMatch(state.candidateColumnCountLabel('HK'), /已计算/);
  assert.equal(state.hkCandidateRows.value.length, 10);
  assert.deepEqual(payload, original);
});

test('same malformed SHA cannot bind a result even when both response fields agree', async () => {
  const payload = workbench();
  payload.execution_evidence.selection_results.HK_CONNECT.raw_artifact_sha256 = 'malformed';
  payload.markets.HK.raw_artifact_sha256 = 'malformed';
  const { html } = await renderApp(payload);
  assert.match(market(primary(evidenceHtml(html)), 'HK_CONNECT'), /选股结果身份待核对/);
});

test('same run and artifact can display a verified zero without inventing unavailable zeroes', async () => {
  const payload = workbench();
  payload.unified_rows = payload.unified_rows.filter(row => row.market !== 'HK');
  Object.assign(payload.execution_evidence.selection_results.HK_CONNECT,
    { status: 'VERIFIED_EMPTY_RESULT', selected_rows: 0, requested_rows: 0, source_rows: 0, missing_quote_rows: 0 });
  const { html, state } = await renderApp(payload);
  assert.match(market(primary(evidenceHtml(html)), 'HK_CONNECT'), /已保存空结果（0 只）/);
  assert.equal(state.candidateColumnCountLabel('HK'), '已保存空结果（0 只）');
});

test('full unified rows bind counts even when existing A card view is capped at 12', async () => {
  const payload = workbench();
  const extra = Array.from({ length: 3 }, (_, index) => ({ market: 'A', code: '80000' + index, rank: 11 + index }));
  payload.unified_rows.push(...extra);
  payload.execution_evidence.selection_results.A_SHARE.selected_rows = 13;
  payload.selected_a_rows = 13;
  const { state, html } = await renderApp(payload);
  assert.equal(state.aCandidateRows.value.length, 12);
  assert.match(market(primary(evidenceHtml(html)), 'A_SHARE'), /已计算 13 只/);
  assert.equal(payload.unified_rows.filter(row => row.market === 'A').length, 13);
});

for (const [label, override] of [['loading', { stageLoading: true }], ['failed request', { stageError: 'request failed' }]]) {
  test('old evidence is hidden during ' + label, async () => {
    const { html } = await renderApp(workbench(), override);
    assert.equal(evidenceHtml(html), '');
    assert.doesNotMatch(html, /class="execution-evidence"/);
  });
}

test('current HK-only Stage keeps A inapplicable and shows only the HK result panel', async () => {
  const payload = workbench(); payload.stage.stage_id = 'STAGE_1545_1555';
  payload.execution_evidence.stage_id = 'STAGE_1545_1555';
  for (const result of Object.values(payload.execution_evidence.selection_results)) result.stage_id = 'STAGE_1545_1555';
  const { html, state } = await renderApp(payload, { selectedStage: 'STAGE_1545_1555' });
  assert.equal(market(primary(evidenceHtml(html)), 'A_SHARE'), '');
  assert.match(market(primary(evidenceHtml(html)), 'HK_CONNECT'), /已计算 10 只/);
  assert.match(html, /A股：不适用/);
  assert.equal(state.timelineStageMarketCount('STAGE_1545_1555', 'A'), '不适用');
});

test('current manager button executes its original exact-date navigation callback', async () => {
  const { vnode } = await renderApp();
  const io = browser();
  const button = findVnode(vnode, node => node.type === 'button' && vnodeText(node) === '经理选股工作台');
  assert.ok(button); button.props.onClick();
  assert.deepEqual(io.assignments, ['/manager-selection/?date=20261009']);
});

test('task status and research entry events retain the full live App state transitions', async () => {
  const { vnode, state } = await renderApp();
  const io = browser();
  findVnode(vnode, node => node.type === 'button' && vnodeText(node) === '任务状态').props.onClick();
  assert.equal(state.taskStatusActive.value, true);
  assert.equal(state.researchActive.value, false);
  findVnode(vnode, node => node.type === 'button' && vnodeText(node) === '研报决策台').props.onClick();
  assert.equal(state.researchActive.value, true);
  assert.equal(state.taskStatusActive.value, false);
  assert.deepEqual(io.navigations, ['/?date=20261009&view=research']);
});

test('normal and exact backfill route construction retain all original request identities', async () => {
  const { state } = await renderApp();
  assert.equal(state.stageWorkbenchUrl('20261009', 'STAGE_0930_0935'),
    '/api/v3/workbench/stage?date=20261009&stage=STAGE_0930_0935&limit=50');
  state.backfillRunId.value = 'frozen-test-run'; state.backfillMarket.value = 'HK_CONNECT';
  assert.equal(state.stageWorkbenchUrl('20260928', 'STAGE_0930_0935'),
    '/api/v3/workbench/stage?date=20260928&stage=STAGE_0930_0935&limit=50&backfill_run_id=frozen-test-run&market=HK_CONNECT');
});

test('existing exact request and backfill safety validators retain their rejection behavior', async () => {
  const { state } = await renderApp();
  const payload = workbench();
  assert.doesNotThrow(() => state.assertExactStagePayload(payload, '20261009', 'STAGE_0930_0935'));
  assert.throws(() => state.assertExactStagePayload(payload, '20261008', 'STAGE_0930_0935'));
  assert.throws(() => state.assertExactStagePayload(payload, '20261009', 'STAGE_0925'));
  assert.throws(() => state.assertBackfillStagePayload(payload, '20261009', 'STAGE_0930_0935', 'x', 'HK_CONNECT'));
});

test('all pre-existing live functions except the two reviewed display count functions retain exact AST bytes', () => {
  const functions = source => {
    const content = source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1];
    return new Map(parseScript(source).program.body.filter(node => node.type === 'FunctionDeclaration')
      .map(node => [node.id.name, content.slice(node.start, node.end)]));
  };
  const before = functions(beforeAppSource), after = functions(appSource);
  assert.ok(before.size > 80, 'the complete live manager App must be used');
  for (const [name, content] of before) {
    assert.ok(after.has(name), 'missing existing function: ' + name);
    if (!['candidateColumnCountLabel', 'timelineStageMarketCount'].includes(name)) assert.equal(after.get(name), content, name);
  }
});

test('all live template event handlers and runtime task-status types remain exact', () => {
  const events = source => source.match(/@[\w:.-]+="[^"]*"/g);
  assert.deepEqual(events(appSource), events(beforeAppSource));
  const runtimePrefix = source => source.slice(0, source.indexOf('\n\nexport type Stage'));
  assert.equal(runtimePrefix(runtimeSource), runtimePrefix(beforeRuntimeSource));
});
