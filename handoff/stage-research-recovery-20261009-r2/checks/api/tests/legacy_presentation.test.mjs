import assert from "node:assert/strict";
import test from "node:test";
import { base, market, primary, render, text } from "./ssr_harness.mjs";

test("new response shows A result and quote gap while HK stays before its algorithm", async () => {
  const html = primary(await render(base()));
  assert.match(market(html, "A_SHARE"), /已计算 10 只/);
  assert.match(market(html, "A_SHARE"), /行情 205 \/ 216 只，缺 11 只/);
  assert.match(market(html, "A_SHARE"), /选股产物计数/);
  assert.match(market(html, "HK_CONNECT"), /预选池未就绪，未进入算法/);
  assert.doesNotMatch(market(html, "HK_CONNECT"), /已计算|已保存空结果/);
});

test("independent selection result remains visible when the receipt is missing", async () => {
  const evidence = base();
  Object.assign(evidence, { markets: {}, attempt_mode: null, due_status: null,
    status: "EXECUTION_RECEIPT_MISSING", cannot_confirm: ["EXACT_DATE_STAGE_RECEIPT_MISSING"] });
  const html = primary(await render(evidence));
  assert.match(market(html, "A_SHARE"), /已计算 10 只/);
  assert.match(market(html, "A_SHARE"), /行情 205 \/ 216 只，缺 11 只/);
  assert.match(text(html), /运行方式（回执声明） 未记录/);
  assert.match(text(html), /自然时段验收 尚未验证/);
});

test("verified empty result is an explicit zero instead of an unknown count", async () => {
  const evidence = base();
  evidence.selection_results.A_SHARE = { status: "VERIFIED_EMPTY_RESULT", selected_rows: 0,
    requested_rows: 0, source_rows: 0, missing_quote_rows: 0, quote_coverage_ratio: null };
  const lane = market(primary(await render(evidence)), "A_SHARE");
  assert.match(lane, /已保存空结果（0 只）/);
  assert.match(lane, /行情 0 \/ 0 只，缺 0 只/);
});

test("null quote counters remain unknown and cannot become zero", async () => {
  const evidence = base();
  Object.assign(evidence.selection_results.A_SHARE, { requested_rows: null, source_rows: null,
    missing_quote_rows: null, quote_coverage_ratio: null });
  const lane = market(primary(await render(evidence)), "A_SHARE");
  assert.match(lane, /行情 未知 \/ 未知 只；缺口数量未知/);
  assert.doesNotMatch(lane, /行情 0|缺 0/);
});

for (const invalid of [-1, 1.5, NaN, Infinity, true]) {
  test(`invalid quote counter ${String(invalid)} is not displayed as an observation`, async () => {
    const evidence = base();
    Object.assign(evidence.selection_results.A_SHARE, { source_rows: invalid, missing_quote_rows: null });
    const lane = market(primary(await render(evidence)), "A_SHARE");
    assert.match(lane, /行情 未知 \/ 216 只；缺口数量未知/);
    assert.doesNotMatch(lane, /缺 0 只|缺 -/);
  });
}

test("source count larger than requested is presented as a conflict", async () => {
  const evidence = base();
  Object.assign(evidence.selection_results.A_SHARE, { source_rows: 217, missing_quote_rows: null });
  const lane = market(primary(await render(evidence)), "A_SHARE");
  assert.match(lane, /行情计数待核对/);
  assert.doesNotMatch(lane, /缺 -1/);
});

test("conflicting declared gap is not silently accepted as full coverage", async () => {
  const evidence = base();
  evidence.selection_results.A_SHARE.missing_quote_rows = 0;
  const lane = market(primary(await render(evidence)), "A_SHARE");
  assert.match(lane, /行情计数待核对/);
  assert.doesNotMatch(lane, /缺 0 只/);
});

test("old bound selection can show computed rows but quote counts remain receipt declarations", async () => {
  const evidence = base();
  delete evidence.selection_results;
  const html = primary(await render(evidence));
  assert.match(market(html, "A_SHARE"), /已计算 10 只/);
  assert.match(market(html, "A_SHARE"), /行情 205 \/ 216 只，缺 11 只/);
  assert.match(market(html, "A_SHARE"), /回执记录计数/);
  assert.match(market(html, "HK_CONNECT"), /预选池未就绪，未进入算法/);
});

test("old unbound selection declaration does not claim calculation", async () => {
  const evidence = base();
  delete evidence.selection_results;
  evidence.markets.A_SHARE.selection_binding = "NO_VERIFIED_SELECTION_BINDING";
  const lane = market(primary(await render(evidence)), "A_SHARE");
  assert.match(lane, /选股结果待核对/);
  assert.doesNotMatch(lane, /已计算 10 只/);
  assert.match(lane, /回执记录计数/);
});

test("new no-result verdict cannot be upgraded by an old bound receipt", async () => {
  const evidence = base();
  evidence.selection_results.A_SHARE.status = "NO_VERIFIED_RESULT";
  const lane = market(primary(await render(evidence)), "A_SHARE");
  assert.match(lane, /选股结果待核对/);
  assert.doesNotMatch(lane, /已计算 10 只|行情 205/);
});

for (const partial of [{}, { HK_CONNECT: { status: "NO_VERIFIED_RESULT" } }]) {
  test(`new summary map missing A cannot fall back to old bound counts (${Object.keys(partial).join() || "empty"})`, async () => {
    const evidence = base();
    evidence.selection_results = partial;
    const lane = market(primary(await render(evidence)), "A_SHARE");
    assert.match(lane, /选股结果待核对/);
    assert.match(lane, /行情 未知 \/ 未知 只；缺口数量未知/);
    assert.doesNotMatch(lane, /已计算 10 只|行情 205|回执记录计数/);
  });
}

test("legacy observed_rows fallback is labeled as receipt evidence", async () => {
  const evidence = base();
  delete evidence.selection_results;
  Object.assign(evidence.markets.A_SHARE, { source_rows: null, observed_rows: 206 });
  const lane = market(primary(await render(evidence)), "A_SHARE");
  assert.match(lane, /行情 206 \/ 216 只，缺 10 只/);
  assert.match(lane, /回执记录计数/);
});

test("NATURAL plus owner binding is still distinct from natural acceptance", async () => {
  const evidence = base();
  Object.assign(evidence, { attempt_mode: "NATURAL", due_status: "DUE",
    receipt_history_binding: "OWNER_HISTORY_SHA_BOUND", record_time_status: "OWNER_WRITE_CLOCK_RECORDED",
    recorded_at: "2026-10-09T01:45:09+00:00" });
  evidence.selection_artifact_bindings.A_SHARE = { status: "BOUND_TO_VERIFIED_SELECTION_TRIO" };
  const value = text(primary(await render(evidence)));
  assert.match(value, /运行方式（回执声明） 自然触发（NATURAL）/);
  assert.match(value, /原执行方历史记录 已核对/);
  assert.match(value, /自然时段验收 尚未验证/);
  assert.doesNotMatch(value, /自然.*已通过|自然.*已验证/);
  assert.match(value, /记录时间 2026-10-09T01:45:09\+00:00/);
});

test("owner history conflict is shown without hiding the verified result", async () => {
  const evidence = base();
  Object.assign(evidence, { receipt_history_binding: "OWNER_HISTORY_CONFLICT",
    record_time_status: "RECEIPT_RECORD_TIME_NOT_VERIFIED", recorded_at: "2026-10-09T01:45:09+00:00" });
  const html = primary(await render(evidence));
  assert.match(market(html, "A_SHARE"), /已计算 10 只/);
  assert.match(text(html), /原执行方历史记录 身份冲突，待核对/);
  assert.match(text(html), /记录时间 待核对/);
  assert.doesNotMatch(text(html), /2026-10-09T01:45:09/);
});

test("selection-to-receipt identity conflict is explicit while stored result remains visible", async () => {
  const evidence = base();
  evidence.selection_artifact_bindings.A_SHARE = { status: "SELECTION_TRIO_CONFLICT" };
  const lane = market(primary(await render(evidence)), "A_SHARE");
  assert.match(lane, /已计算 10 只/);
  assert.match(lane, /结果与运行记录的身份冲突/);
});

test("missing record time is not inferred from date, stage, due status or current clock", async () => {
  const evidence = base();
  const value = text(primary(await render(evidence)));
  assert.match(value, /记录时间 原回执未记录/);
  assert.doesNotMatch(value, /09:25:05|01:25:05/);
});

test("only the HK lane is rendered for the HK-only late stage", async () => {
  const evidence = base();
  evidence.stage_id = "STAGE_1545_1555";
  const html = primary(await render(evidence));
  assert.equal(market(html, "A_SHARE"), "");
  assert.match(market(html, "HK_CONNECT"), /预选池未就绪/);
});

test("raw reason codes and identifiers remain inside closed technical details", async () => {
  const html = await render(base());
  assert.match(html, /<details/);
  assert.doesNotMatch(html, /<details[^>]*\sopen/);
  assert.match(html, /NO_INDEPENDENT_RUN_RECEIPT_SHA_BINDING/);
  assert.doesNotMatch(primary(html), /NO_INDEPENDENT_RUN_RECEIPT_SHA_BINDING/);
});
