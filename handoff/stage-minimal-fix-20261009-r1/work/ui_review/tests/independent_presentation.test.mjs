import assert from 'node:assert/strict';
import test from 'node:test';
import { fixture, lane, render, text, visible } from './component_harness.mjs';

test('a real selection summary survives completely absent execution receipt lanes', async () => {
  const data = fixture();
  data.markets = {};
  data.status = 'EXECUTION_RECEIPT_MISSING';
  data.attempt_mode = null;
  const html = visible(await render(data));
  assert.match(lane(html, 'A_SHARE'), /已计算 10 只/);
  assert.match(lane(html, 'A_SHARE'), /行情 206 \/ 216 只，缺 10 只/);
  assert.match(lane(html, 'A_SHARE'), /选股产物计数/);
  assert.match(text(html), /自然时段验收 尚未验证/);
});

test('current verified HK result remains above an older blocked execution declaration', async () => {
  const data = fixture();
  data.selection_results.HK_CONNECT = { status: 'RESULT_AVAILABLE', selected_rows: 10,
    requested_rows: 100, source_rows: 98, missing_quote_rows: 2, quote_coverage_ratio: 0.98 };
  const result = lane(visible(await render(data)), 'HK_CONNECT');
  assert.match(result, /已计算 10 只/);
  assert.match(result, /行情 98 \/ 100 只，缺 2 只/);
  assert.match(result, /当前回执：预选池未就绪，未进入算法/);
  assert.ok(result.indexOf('已计算') < result.indexOf('当前回执'));
});

test('a new negative result summary is never replaced by old bound receipt counts', async () => {
  const data = fixture();
  data.selection_results.A_SHARE = { status: 'NO_VERIFIED_RESULT', selected_rows: 10,
    requested_rows: 216, source_rows: 206, missing_quote_rows: 10 };
  const result = lane(visible(await render(data)), 'A_SHARE');
  assert.match(result, /选股结果待核对/);
  assert.doesNotMatch(result, /已计算|行情 206|选股产物计数|回执记录计数/);
});

test('a present null new summary is not downgraded to a receipt-based selection', async () => {
  const data = fixture();
  data.selection_results.A_SHARE = null;
  const result = lane(visible(await render(data)), 'A_SHARE');
  assert.match(result, /选股结果待核对/);
  assert.doesNotMatch(result, /已计算|行情 206/);
});

test('an explicitly new result map with a missing market does not use older receipt rows', async () => {
  const data = fixture();
  delete data.selection_results.A_SHARE;
  const result = lane(visible(await render(data)), 'A_SHARE');
  assert.match(result, /选股结果待核对/);
  assert.doesNotMatch(result, /已计算|行情 206/);
});

for (const status of ['UNKNOWN', 'READY', [], null]) {
  test(`unrecognized summary status ${JSON.stringify(status)} cannot display verified rows`, async () => {
    const data = fixture();
    data.selection_results.A_SHARE.status = status;
    const result = lane(visible(await render(data)), 'A_SHARE');
    assert.match(result, /选股结果待核对/);
    assert.doesNotMatch(result, /已计算|已保存空结果/);
  });
}

for (const badSelected of [null, -1, 0, 0.5, true, '10', Number.MAX_SAFE_INTEGER + 1]) {
  test(`nonpositive or invalid nonempty-result selected count ${String(badSelected)} is not confirmed`, async () => {
    const data = fixture();
    data.selection_results.A_SHARE.selected_rows = badSelected;
    const result = lane(visible(await render(data)), 'A_SHARE');
    assert.match(result, /选股结果待核对/);
    assert.doesNotMatch(result, /已计算|已保存空结果/);
  });
}

test('verified empty has an explicit zero but missing acquisition counts stay unknown', async () => {
  const data = fixture();
  data.selection_results.A_SHARE = { status: 'VERIFIED_EMPTY_RESULT', selected_rows: 0,
    requested_rows: null, source_rows: null, missing_quote_rows: null };
  const result = lane(visible(await render(data)), 'A_SHARE');
  assert.match(result, /已保存空结果（0 只）/);
  assert.match(result, /行情 未知 \/ 未知 只/);
  assert.doesNotMatch(result, /行情 0|缺 0 只/);
});

test('current null acquisition counters never take old fully populated receipt values', async () => {
  const data = fixture();
  Object.assign(data.selection_results.A_SHARE, { requested_rows: null, source_rows: null, missing_quote_rows: null });
  const result = lane(visible(await render(data)), 'A_SHARE');
  assert.match(result, /已计算 10 只/);
  assert.match(result, /行情 未知 \/ 未知 只/);
  assert.doesNotMatch(result, /行情 206|回执记录计数|缺 0 只/);
});

test('legacy reference fallback is allowed only with its exact verified selection binding', async () => {
  const data = fixture();
  delete data.selection_results;
  data.markets.A_SHARE.selection_binding = 'SELECTION_IDENTITY_CONFLICT';
  const result = lane(visible(await render(data)), 'A_SHARE');
  assert.match(result, /选股结果待核对/);
  assert.match(result, /身份冲突/);
  assert.match(result, /回执记录计数/);
  assert.doesNotMatch(result, /已计算/);
});

test('legacy observed rows fallback remains a declared quote count, never a selected count', async () => {
  const data = fixture();
  delete data.selection_results;
  data.markets.A_SHARE.source_rows = null;
  data.markets.A_SHARE.observed_rows = 205;
  data.markets.A_SHARE.selected_rows = null;
  const result = lane(visible(await render(data)), 'A_SHARE');
  assert.match(result, /选股结果待核对/);
  assert.match(result, /行情 205 \/ 216 只，缺 11 只/);
  assert.match(result, /回执记录计数/);
  assert.doesNotMatch(result, /已计算 205/);
});

test('owner history and declared NATURAL do not satisfy execution acceptance', async () => {
  const data = fixture();
  data.receipt_history_binding = 'OWNER_HISTORY_SHA_BOUND';
  data.record_time_status = 'OWNER_WRITE_CLOCK_RECORDED';
  data.recorded_at = '2026-10-09T03:45:00+00:00';
  data.selection_artifact_bindings.A_SHARE = { status: 'BOUND_TO_VERIFIED_SELECTION_TRIO' };
  const value = text(visible(await render(data)));
  assert.match(value, /自然触发（NATURAL）/);
  assert.match(value, /原执行方历史记录 已核对/);
  assert.match(value, /自然时段验收 尚未验证/);
  assert.doesNotMatch(value, /自然时段验收 已|执行过程已验证/);
});

test('a recorded-time declaration without owner history is not displayed as verified time', async () => {
  const data = fixture();
  data.record_time_status = 'OWNER_WRITE_CLOCK_RECORDED';
  data.recorded_at = '1999-01-01T00:00:00+00:00';
  const value = text(visible(await render(data)));
  assert.match(value, /记录时间 待核对/);
  assert.doesNotMatch(value, /1999-01-01/);
});

test('an unsafe counter range gives a count conflict rather than a negative missing quote count', async () => {
  const data = fixture();
  data.selection_results.A_SHARE.source_rows = 217;
  data.selection_results.A_SHARE.missing_quote_rows = -1;
  const result = lane(visible(await render(data)), 'A_SHARE');
  assert.match(result, /行情计数待核对/);
  assert.doesNotMatch(result, /缺 -1/);
});

test('HK-only stage never gains a fabricated A lane from stale receipt data', async () => {
  const data = fixture();
  data.stage_id = 'STAGE_1545_1555';
  const html = visible(await render(data));
  assert.equal(lane(html, 'A_SHARE'), '');
  assert.match(lane(html, 'HK_CONNECT'), /预选池未就绪/);
});

test('display escaping and technical details retain untrusted diagnostic text without executing markup', async () => {
  const data = fixture();
  data.error = '<img src=x onerror="alert(1)">';
  data.markets.HK_CONNECT.reasons.push('<script>alert(2)</script>');
  const html = await render(data);
  assert.doesNotMatch(html, /<img\b|<script\b/);
  assert.match(html, /&lt;img/);
  assert.doesNotMatch(visible(html), /alert\(1\)|alert\(2\)/);
});
