import assert from 'node:assert/strict';
import test from 'node:test';
import { appVnodes, compileFacts, evidenceHtml, findVnode, hkColumnCount, makeShell, market,
  primary, renderApp, renderShell, runtimeAst, text, vnodeText, vue, workbench } from './actual_app_harness.mjs';

const visibleEvidence = html => primary(evidenceHtml(html));
const click = (tree, label, event = {}) => {
  const button = findVnode(tree, node => node.type === 'button' && vnodeText(node).trim() === label);
  assert.ok(button, 'existing button: ' + label);
  assert.equal(typeof button.props.onClick, 'function');
  button.props.onClick(event);
};

test('current App imports and SSR executes the delivered panel with current HK counts', async () => {
  const app = compileFacts.find(item => item.filename.endsWith('/App.vue') && item.useSsr);
  assert.ok(app.imports.includes('./components/review/StageExecutionEvidencePanel.vue'));
  const html = await renderApp();
  assert.match(market(visibleEvidence(html), 'HK_CONNECT'), /已计算 10 只/);
  assert.match(hkColumnCount(html), /已计算 10 只/);
  assert.match(text(html.match(/<section[^>]*timeline-panel[\s\S]*?<\/section>/)?.[0] ?? ''), /港股 已计算 10 只/);
});

test('current App renders research-only evidence flags without altering the received payload', async () => {
  const payload = workbench();
  const before = JSON.stringify(payload);
  const visible = text(visibleEvidence(await renderApp(payload)));
  assert.match(visible, /RESEARCH_ONLY=true/);
  for (const key of ['production_allowed', 'buy_gate_updated', 'orders_sent']) assert.match(visible, new RegExp(key + '=false'));
  assert.equal(JSON.stringify(payload), before);
});

test('missing or conflicting safety declarations remain CANNOT_CONFIRM', async () => {
  const payload = workbench();
  delete payload.execution_evidence.RESEARCH_ONLY;
  payload.execution_evidence.production_allowed = true;
  delete payload.execution_evidence.buy_gate_updated;
  payload.execution_evidence.orders_sent = true;
  const visible = text(visibleEvidence(await renderApp(payload)));
  for (const key of ['RESEARCH_ONLY', 'production_allowed', 'buy_gate_updated', 'orders_sent']) {
    assert.match(visible, new RegExp(key + '=CANNOT_CONFIRM'));
  }
});

for (const [field, next] of [['selectedDate', '20261008'], ['selectedStage', 'STAGE_0925'],
  ['stageLoading', true], ['stageError', '读取失败']]) {
  test(`changing ${field} stops rendering old same-run evidence immediately`, async () => {
    const shell = makeShell(workbench());
    assert.match(market(visibleEvidence(await renderShell(shell)), 'HK_CONNECT'), /已计算 10 只/);
    shell.state[field].value = next;
    const html = await renderShell(shell);
    assert.equal(evidenceHtml(html), '');
    assert.doesNotMatch(hkColumnCount(html), /已计算 10 只/);
  });
}

for (const field of ['trade_date', 'stage_id']) {
  test(`a stale workbench ${field} cannot supply the current evidence panel`, async () => {
    const payload = workbench();
    assert.ok(evidenceHtml(await renderApp(payload)));
    if (field === 'trade_date') payload.trade_date = '20261008';
    else payload.stage.stage_id = 'STAGE_0925';
    assert.equal(evidenceHtml(await renderApp(payload)), '');
  });
}

for (const field of ['artifact_id', 'algorithm_sha256']) {
  test(`current App refuses a summary with a different ${field}`, async () => {
    const payload = workbench();
    payload.execution_evidence.selection_results.HK_CONNECT[field] = field.endsWith('sha256') ? 'e'.repeat(64) : 'other-artifact';
    const html = await renderApp(payload);
    assert.doesNotMatch(hkColumnCount(html), /已计算 10 只/);
    assert.match(market(visibleEvidence(html), 'HK_CONNECT'), /结果身份待核对/);
    assert.doesNotMatch(market(visibleEvidence(html), 'HK_CONNECT'), /已计算 10 只|行情 206/);
  });
}

test('matching malformed SHA strings are not accepted as a run identity', async () => {
  const payload = workbench();
  payload.execution_evidence.selection_results.HK_CONNECT.raw_artifact_sha256 = 'not-a-sha';
  payload.markets.HK.raw_artifact_sha256 = 'not-a-sha';
  assert.match(market(visibleEvidence(await renderApp(payload)), 'HK_CONNECT'), /结果身份待核对/);
});

test('row count disagreement does not upgrade existing observations into calculated results', async () => {
  const payload = workbench();
  payload.unified_rows.pop();
  const html = await renderApp(payload);
  assert.doesNotMatch(hkColumnCount(html), /已计算/);
  assert.match(market(visibleEvidence(html), 'HK_CONNECT'), /结果身份待核对/);
  assert.match(text(html), /现有港股9/);
});

test('an HK identity conflict preserves independently bound A-share counts and quote gap', async () => {
  const payload = workbench();
  const aResult = { status: 'RESULT_AVAILABLE', selected_rows: 2, requested_rows: 216, source_rows: 205,
    missing_quote_rows: 11, trade_date: payload.trade_date, stage_id: payload.stage.stage_id,
    market: 'A_SHARE', run_id: 'run-a-only', artifact_id: 'selection-a-only',
    algorithm_sha256: '1'.repeat(64), raw_artifact_sha256: '2'.repeat(64) };
  payload.execution_evidence.selection_results.A_SHARE = aResult;
  payload.markets.A = { ...aResult };
  payload.unified_rows.push({ market: 'A', code: '000001', name: '现有A股1' }, { market: 'A', code: '000002', name: '现有A股2' });
  payload.execution_evidence.selection_results.HK_CONNECT.run_id = 'conflicting-hk';
  const html = await renderApp(payload);
  assert.match(market(visibleEvidence(html), 'A_SHARE'), /已计算 2 只/);
  assert.match(market(visibleEvidence(html), 'A_SHARE'), /行情 205 \/ 216 只，缺 11 只/);
  assert.doesNotMatch(market(visibleEvidence(html), 'HK_CONNECT'), /已计算 10 只|行情 206/);
});

test('verified empty same-run result requires explicit empty workbench rows', async () => {
  const payload = workbench();
  Object.assign(payload.execution_evidence.selection_results.HK_CONNECT, { status: 'VERIFIED_EMPTY_RESULT',
    selected_rows: 0, requested_rows: 0, source_rows: 0, missing_quote_rows: 0 });
  payload.unified_rows = [];
  const html = await renderApp(payload);
  assert.match(market(visibleEvidence(html), 'HK_CONNECT'), /已保存空结果（0 只）/);
  assert.match(market(visibleEvidence(html), 'HK_CONNECT'), /行情 0 \/ 0 只，缺 0 只/);
  delete payload.unified_rows;
  const absentRows = await renderApp(payload);
  assert.doesNotMatch(market(visibleEvidence(absentRows), 'HK_CONNECT'), /已保存空结果/);
  assert.match(market(visibleEvidence(absentRows), 'HK_CONNECT'), /结果身份待核对/);
});

test('missing execution evidence leaves an explicit current-scope CANNOT_CONFIRM notice', async () => {
  const payload = workbench();
  delete payload.execution_evidence;
  const html = await renderApp(payload);
  assert.equal(evidenceHtml(html), '');
  assert.match(text(html), /CANNOT_CONFIRM：当前日期与阶段没有可绑定的执行证据/);
});

test('manager selection remains wired to the existing app-shell action', () => {
  const shell = makeShell(workbench());
  click(appVnodes(shell), '经理选股工作台');
  assert.deepEqual(shell.events, [['openManagerSelection']]);
});

test('existing stage recovery and forced materialization actions keep their arguments', () => {
  const shell = makeShell(workbench());
  const tree = appVnodes(shell);
  click(tree, '运行 / 恢复当前阶段');
  click(tree, '强制重新物化');
  assert.deepEqual(shell.events, [['ensureStage', false], ['ensureStage', true]]);
});

test('existing snapshot refresh keeps the original stage action', () => {
  const shell = makeShell(workbench());
  click(appVnodes(shell), '刷新快照');
  assert.deepEqual(shell.events, [['loadStage']]);
});

test('date input and stage selection retain their existing handlers', () => {
  const shell = makeShell(workbench());
  const tree = appVnodes(shell);
  const event = { target: { value: '2026-10-08' } };
  const date = findVnode(tree, node => node.type === 'input' && node.props?.type === 'date');
  date.props.onChange(event);
  const select = findVnode(tree, node => node.type === 'select');
  select.props['onUpdate:modelValue']('STAGE_0925');
  select.props.onChange({});
  assert.equal(shell.state.selectedStage.value, 'STAGE_0925');
  assert.deepEqual(shell.events, [['onDateInputChange', event], ['loadStage']]);
});

test('research, task and review navigation still call the existing app-shell actions', () => {
  const shell = makeShell(workbench());
  const tree = appVnodes(shell);
  click(tree, '研报决策台');
  click(tree, '任务状态');
  click(tree, 'A股复盘');
  click(tree, '研究复盘');
  assert.deepEqual(shell.events, [['openResearch'], ['openTaskStatus'], ['loadCloseReview', 'A'], ['loadCloseReview', 'research']]);
});

for (const [field, view] of [['taskStatusActive', 'TaskStatusView'], ['researchActive', 'ResearchView'], ['closeReviewActive', 'ReviewView']]) {
  test(`existing ${view} route does not render stage execution evidence`, async () => {
    const html = await renderApp(workbench(), { [field]: vue.ref(true), closeReviewPayload: vue.ref({ trade_date: '20261009' }) });
    assert.match(html, new RegExp('data-view="' + view + '"'));
    assert.equal(evidenceHtml(html), '');
    assert.match(text(html), /经理选股工作台/);
  });
}

test('existing candidate cards, pool and lineage remain alongside the new evidence', async () => {
  const payload = workbench();
  payload.stage_lineage = { natural: { label: '原自然运行', status: 'CANNOT_CONFIRM', receipt_sha256: 'd'.repeat(64), write_performed: false } };
  const html = await renderApp(payload, { preselectionGroups: vue.ref([{ pool_id: 'a_all_pool_summary',
    display_name: '原A股预选池', rows: [{ code: '600001', name: '原池股票', signal_date: '20261008' }] }]) });
  const visible = text(primary(html));
  for (const label of ['现有港股1', '现有港股10', '原A股预选池', '原池股票', '原自然运行', '现有阶段状态保留']) assert.match(visible, new RegExp(label));
  assert.match(market(visibleEvidence(html), 'HK_CONNECT'), /已计算 10 只/);
});

test('actual App cannot turn an explicit research replay into natural acceptance', async () => {
  const payload = workbench();
  payload.execution_evidence.attempt_mode = 'NATURAL';
  payload.execution_evidence.due_status = 'DUE';
  const visible = text(visibleEvidence(await renderApp(payload)));
  assert.match(visible, /补验 \/ 回放/);
  assert.match(visible, /自然时段验收 尚未验证/);
  assert.doesNotMatch(visible, /自然触发（NATURAL）/);
});

test('current runtime contract parses with existing task types and added evidence types', () => {
  const names = runtimeAst.program.body.filter(node => node.type === 'ExportNamedDeclaration')
    .map(node => node.declaration?.id?.name);
  for (const name of ['LogicalWorkloadStatus', 'RuntimeIdentityRow', 'TaskRegistrationStatus', 'TaskStatusResponse',
    'StageResearchSource', 'StageExecutionEvidenceReadback']) assert.ok(names.includes(name), name);
});
