"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const panel = require("./numeric283-panel.js");

const dataPath = process.env.NUMERIC283_CANDIDATES_PATH
  ? path.resolve(process.env.NUMERIC283_CANDIDATES_PATH)
  : path.resolve(__dirname, "../../../../prepared/chart_r1/numeric283-candidates.json");
const data = JSON.parse(fs.readFileSync(dataPath, "utf8"));

function makeElement(tag, ownerDocument) {
  return {
    tag,
    ownerDocument,
    children: [],
    firstChild: null,
    textContent: "",
    attributes: {},
    listeners: {},
    disabled: false,
    appendChild(child) {
      this.children.push(child);
      this.firstChild = this.children[0] || null;
      return child;
    },
    setAttribute(key, value) { this.attributes[key] = value; },
    addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); },
    dispatch(type, event = {}) { for (const listener of this.listeners[type] || []) listener(event); },
    click() {
      if (this.disabled) return;
      this.onclick?.({});
      this.dispatch("click", {});
    },
    replaceChildren(...children) { this.children = children; this.firstChild = children[0] || null; },
    scrollIntoView() { this.scrolledIntoView = true; },
    removeChild(child) {
      this.children = this.children.filter((item) => item !== child);
      this.firstChild = this.children[0] || null;
    },
  };
}

function makeDocument() {
  const document = { createElement(tag) { return makeElement(tag, document); } };
  return document;
}

function makePanelDocument() {
  const document = makeDocument();
  const ids = [
    "dailyNumeric283Panel", "dailyNumeric283Status", "dailyNumeric283Count", "dailyNumeric283Group",
    "dailyNumeric283Search", "dailyNumeric283Rows", "dailyNumeric283Download", "dailyNumeric283ChartPanel",
    "dailyNumeric283ChartTitle", "dailyNumeric283ChartStatus", "numeric283prevWindow", "numeric283nextWindow",
    "numeric283dateSelect", "numeric283panRange",
  ];
  const elements = new Map(ids.map((id) => [id, makeElement(id, document)]));
  const chartWindowControls = [60, 180].map((count) => {
    const control = makeElement("button", document);
    control.dataset = { numeric283Window: String(count) };
    return control;
  });
  elements.get("dailyNumeric283Group").value = "all";
  elements.get("dailyNumeric283Search").value = "";
  document.getElementById = (id) => elements.get(id) || null;
  document.querySelectorAll = (selector) => selector === "[data-numeric283-window]" ? chartWindowControls : [];
  document.currentScript = { src: "http://127.0.0.1/research-panel/numeric283-panel.js" };
  document.elements = elements;
  document.chartWindowControls = chartWindowControls;
  return document;
}

function numeric283ChartControls(document) {
  return [
    ...document.chartWindowControls,
    document.elements.get("numeric283prevWindow"),
    document.elements.get("numeric283nextWindow"),
    document.elements.get("numeric283dateSelect"),
    document.elements.get("numeric283panRange"),
  ];
}

function numeric283ControlsReady(document) {
  return [
    ...document.chartWindowControls,
    document.elements.get("numeric283dateSelect"),
    document.elements.get("numeric283panRange"),
  ].every((control) => !control.disabled);
}

function setRendererWindowBoundaries(document, stock) {
  const count = Math.min(180, stock.chartRows.length);
  const start = Math.max(0, stock.chartRows.length - count);
  document.elements.get("numeric283prevWindow").disabled = start === 0;
  document.elements.get("numeric283nextWindow").disabled = start + count >= stock.chartRows.length;
}

function makeReadyAnswerWith181Rows(symbol) {
  const firstDate = Date.UTC(2026, 4, 1);
  const rows = Array.from({ length: 181 }, (_, index) => {
    const tradeDate = new Date(firstDate + index * 86400000).toISOString().slice(0, 10).replaceAll("-", "");
    return {
      ts_code: symbol,
      trade_date: tradeDate,
      open: 10,
      high: 11,
      low: 9,
      close: 10.5,
      volume: 100,
      zge_white_line: 10,
      zge_yellow_line: 9.8,
      BBI: 10.1,
      J: 50,
    };
  });
  return makeReadyAnswer(symbol, { rows });
}

function makeReadyAnswer(symbol, overrides = {}) {
  return {
    schema_version: "v4.a_share_numeric283_chart.v1",
    ts_code: symbol,
    start_date: "20260101",
    end_date: "20261028",
    formula_version: panel.CHART_PROFILE,
    profile_id: panel.CHART_PROFILE,
    signal_namespace: panel.CHART_NAMESPACE,
    status: "READY",
    research_only: true,
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
    identity: {
      generation_id: data.source_generation,
      artifact_sha256: panel.EXPECTED.source_artifact_sha256,
      asof_date: 20261028,
      profile_namespace: panel.CHART_NAMESPACE,
      numeric283_scope_count: 283,
      numeric283_source_generation: data.source_generation,
      numeric283_source_artifact_sha256: panel.EXPECTED.source_artifact_sha256,
      ...overrides.identity,
    },
    rows: [
      { ts_code: symbol, trade_date: "20261027", open: 10, high: 11, low: 9, close: 10.5, volume: 100, zge_white_line: 10, zge_yellow_line: 9.8, BBI: 10.1, J: 50 },
      { ts_code: symbol, trade_date: "20261028", open: 10.5, high: 12, low: 10, close: 11.5, volume: 120, zge_white_line: 10.2, zge_yellow_line: 10, BBI: 10.3, J: 60 },
    ],
    ...overrides,
  };
}

const flush = () => new Promise((resolve) => setImmediate(resolve));

test("the frozen payload is exactly 283 unique rows with the four overlapping group counts", () => {
  const rows = panel.validateData(data);
  assert.equal(rows.length, 283);
  assert.equal(new Set(rows.map((row) => row.symbol)).size, 283);
  assert.deepEqual(data.group_counts, { original: 37, nav_smallk: 163, nav_pullback: 130, nav_breakout: 31 });
});

test("all rows are accessible and group and code/name filters return the full matching set", () => {
  const rows = panel.validateData(data);
  assert.equal(panel.filterRows(rows, "all", "").length, 283);
  assert.equal(panel.filterRows(rows, "original", "").length, 37);
  assert.equal(panel.filterRows(rows, "nav_smallk", "").length, 163);
  assert.equal(panel.filterRows(rows, "nav_pullback", "").length, 130);
  assert.equal(panel.filterRows(rows, "nav_breakout", "").length, 31);
  const first = rows[0];
  assert.deepEqual(panel.filterRows(rows, "all", first.symbol), [first]);
  if (first.display_name) assert.deepEqual(panel.filterRows(rows, "all", first.display_name), [first]);
  const document = makeDocument();
  const tbody = makeElement("tbody", document);
  panel.renderRows(tbody, rows, data);
  assert.equal(tbody.children.length, 283);
  assert.ok(tbody.children.every((tr) => tr.children.length === 7));
});

test("fixed dates reject later or malformed snapshots", () => {
  for (const [field, value] of [["data_date", "20261029"], ["observation_date", "20261030"], ["source_generation", "changed"]]) {
    assert.throws(() => panel.validateData({ ...data, [field]: value }), /固定日期/);
  }
  const badPending = structuredClone(data);
  badPending.rows[0].pending_groups = "unrecognized";
  assert.throws(() => panel.validateData(badPending), /待核组别/);
});

test("each row shows passed and pending groups, reasons, anchor, both dates, source, and pending chart review", () => {
  const document = makeDocument();
  const tbody = makeElement("tbody", document);
  const row = data.rows.find((item) => item.reasons);
  assert.ok(row);
  panel.renderRows(tbody, [row], data);
  const cells = tbody.children[0].children;
  assert.equal(cells[2].textContent, panel.displayGroups(row.groups));
  assert.equal(cells[3].children[0].textContent, `其他待核组：${panel.displayPendingGroups(row.pending_groups)}`);
  assert.equal(cells[3].children[1].textContent, `待核原因：${row.reasons}`);
  assert.equal(cells[3].children[2].textContent, `risk_clear：${row.risk_clear}`);
  assert.equal(cells[4].textContent, panel.displayAnchor(row.latest_new_anchor));
  assert.equal(cells[5].textContent, "D20261028 / 观察20261029");
  const details = cells[6].children[0];
  assert.equal(details.children[0].textContent, "FINAL_NUMERIC_CANDIDATES.csv · 图审待进行");
  assert.ok(details.children.some((line) => line.textContent === `CSV SHA-256：${data.source_csv_sha256}`));
  assert.ok(details.children.some((line) => line.textContent === `来源代次：${data.source_generation}`));
  assert.ok(details.children.some((line) => line.textContent === "图形复核：待进行"));

  const missingName = data.rows.find((item) => item.symbol === "689009.SH");
  const missingNameBody = makeElement("tbody", document);
  panel.renderRows(missingNameBody, [missingName], data);
  assert.equal(missingNameBody.children[0].children[1].children[0].textContent, "名称待核");
  assert.deepEqual(panel.filterRows(data.rows, "all", "689009.SH"), [missingName]);
});

test("a row-level XSS string is emitted only as textContent", () => {
  const document = makeDocument();
  const tbody = makeElement("tbody", document);
  const hostileName = '<img src=x onerror="alert(1)">';
  panel.renderRows(tbody, [{
    symbol: "000001.SZ",
    display_name: hostileName,
    groups: "original",
    pending_groups: "",
    latest_new_anchor: "20261028",
    reasons: "",
    risk_clear: "TRUE",
  }], data);
  assert.equal(tbody.children.length, 1);
  assert.equal(tbody.children[0].children[1].children[0].textContent, hostileName);
  assert.equal(Object.hasOwn(tbody.children[0].children[1].children[0], "innerHTML"), false);
});

test("CSV export retains source columns, dated context, and quoted text", () => {
  const row = data.rows.find((item) => item.symbol === "689009.SH");
  assert.ok(row);
  assert.equal(row.display_name, "");
  const csv = panel.toCsv([row], data);
  assert.match(csv, /"data_date","observation_date","symbol","display_name"/);
  assert.match(csv, /"source_file","source_csv_sha256","source_generation","chart_review_status"/);
  assert.match(csv, /"20261028","20261029","689009\.SH",""/);
  assert.match(csv, /"FINAL_NUMERIC_CANDIDATES\.csv","55a65b75d3a03fd767a44d61da8d3d909cbe6c37450fe9796d82980a99a4fefe"/);
  assert.match(csv, /"PENDING"/);
});

test("code and name buttons select the same stock without interpolating row text", () => {
  const document = makeDocument();
  const tbody = makeElement("tbody", document);
  const row = data.rows.find((item) => item.symbol === "600025.SH");
  const selected = [];
  panel.renderRows(tbody, [row], data, (...args) => selected.push(args));
  const cells = tbody.children[0].children;
  assert.equal(cells[0].children[0].textContent, row.symbol);
  assert.equal(cells[1].children[0].textContent, row.display_name || "名称待核");
  cells[0].children[0].click();
  cells[1].children[0].click();
  assert.deepEqual(selected, [[row.symbol, row.display_name || "名称待核"], [row.symbol, row.display_name || "名称待核"]]);
});

test("chart profile rejects wrong symbol, date, namespace, generation, artifact, and incomplete D28 data", () => {
  const good = makeReadyAnswer("600025.SH");
  assert.equal(panel.validateChart(good, "600025.SH").status, "READY");
  for (const bad of [
    { ...good, ts_code: "300071.SZ" },
    { ...good, start_date: "20260102" },
    { ...good, end_date: "20261027" },
    { ...good, schema_version: "v4.a_share_original_formula_history.v1" },
    { ...good, signal_namespace: "R19_51_VALUES_22_DRAWINGS_NO_USER_V1" },
    { ...good, identity: { ...good.identity, generation_id: "changed" } },
    { ...good, identity: { ...good.identity, artifact_sha256: "0".repeat(64) } },
    { ...good, rows: good.rows.slice(0, 1) },
  ]) assert.throws(() => panel.validateChart(bad, "600025.SH"));
});

test("click clears stale chart, shows selected identity, and rejects a bad artifact response", async () => {
  const document = makePanelDocument();
  const chartCalls = { clears: 0, stocks: [] };
  const windowObject = {
    location: { href: "http://127.0.0.1/research-panel/daily.html" },
    Numeric283Chart: {
      clear() { chartCalls.clears += 1; },
      setStock(stock) {
        chartCalls.stocks.push(stock);
        setRendererWindowBoundaries(document, stock);
      },
    },
    fetch(url) {
      if (url.endsWith("numeric283-candidates.json")) return Promise.resolve({ ok: true, json: async () => data });
      return Promise.resolve({ ok: true, json: async () => makeReadyAnswer("600025.SH", { identity: { artifact_sha256: "0".repeat(64) } }) });
    },
  };
  panel.mount(document, windowObject);
  assert.ok(numeric283ChartControls(document).every((control) => control.disabled));
  await flush();
  const row = data.rows.find((item) => item.symbol === "600025.SH");
  const button = document.elements.get("dailyNumeric283Rows").children[data.rows.indexOf(row)].children[0].children[0];
  button.click();
  assert.equal(chartCalls.clears, 1);
  assert.ok(numeric283ChartControls(document).every((control) => control.disabled));
  assert.equal(document.elements.get("dailyNumeric283ChartTitle").textContent, `600025.SH · ${row.display_name || "名称待核"}`);
  assert.match(document.elements.get("dailyNumeric283ChartStatus").textContent, /旧图已清空/);
  assert.equal(document.elements.get("dailyNumeric283ChartPanel").scrolledIntoView, true);
  await flush();
  assert.equal(chartCalls.stocks.length, 0);
  assert.match(document.elements.get("dailyNumeric283ChartStatus").textContent, /读取未确认/);
  assert.equal(chartCalls.clears, 2);
  assert.ok(numeric283ChartControls(document).every((control) => control.disabled));
  for (const id of ["dailyNumeric283Group", "dailyNumeric283Search", "dailyNumeric283Download"]) {
    assert.equal(document.elements.get(id).disabled, false);
  }
});

test("chart controls enable only after a successful current history response and disable again on error", async () => {
  const document = makePanelDocument();
  const chartCalls = { clears: 0, stocks: [] };
  let historyCalls = 0;
  const windowObject = {
    location: { href: "http://127.0.0.1/research-panel/daily.html" },
    Numeric283Chart: {
      clear() { chartCalls.clears += 1; },
      setStock(stock) {
        chartCalls.stocks.push(stock);
        setRendererWindowBoundaries(document, stock);
      },
    },
    fetch(url) {
      if (url.endsWith("numeric283-candidates.json")) return Promise.resolve({ ok: true, json: async () => data });
      historyCalls += 1;
      if (historyCalls === 1) return Promise.resolve({ ok: true, json: async () => makeReadyAnswerWith181Rows("600025.SH") });
      return Promise.reject(new Error("offline"));
    },
  };
  panel.mount(document, windowObject);
  const controls = numeric283ChartControls(document);
  assert.ok(controls.every((control) => control.disabled));
  await flush();
  const tbody = document.elements.get("dailyNumeric283Rows");
  const row = tbody.children.find((tr) => tr.children[0].children[0].textContent === "600025.SH");
  row.children[0].children[0].click();
  assert.ok(controls.every((control) => control.disabled));
  await flush();
  assert.equal(chartCalls.stocks.length, 1);
  assert.ok(numeric283ControlsReady(document));
  assert.equal(document.elements.get("numeric283prevWindow").disabled, false);
  assert.equal(document.elements.get("numeric283nextWindow").disabled, true);
  row.children[0].children[0].click();
  assert.ok(controls.every((control) => control.disabled));
  await flush();
  assert.ok(controls.every((control) => control.disabled));
  assert.match(document.elements.get("dailyNumeric283ChartStatus").textContent, /offline/);
  for (const id of ["dailyNumeric283Group", "dailyNumeric283Search", "dailyNumeric283Download"]) {
    assert.equal(document.elements.get(id).disabled, false);
  }
});

test("newer chart click wins a raced history response and aborts the stale request", async () => {
  const document = makePanelDocument();
  const chartCalls = { clears: 0, stocks: [] };
  const requests = [];
  const windowObject = {
    location: { href: "http://127.0.0.1/research-panel/daily.html" },
    Numeric283Chart: {
      clear() { chartCalls.clears += 1; },
      setStock(stock) {
        chartCalls.stocks.push(stock);
        setRendererWindowBoundaries(document, stock);
      },
    },
    fetch(url, options) {
      if (url.endsWith("numeric283-candidates.json")) return Promise.resolve({ ok: true, json: async () => data });
      return new Promise((resolve) => requests.push({ url, options, resolve }));
    },
  };
  panel.mount(document, windowObject);
  await flush();
  const tbody = document.elements.get("dailyNumeric283Rows");
  const first = tbody.children.find((tr) => tr.children[0].children[0].textContent === "600025.SH");
  const second = tbody.children.find((tr) => tr.children[0].children[0].textContent === "300071.SZ");
  first.children[0].children[0].click();
  second.children[0].children[0].click();
  assert.equal(requests.length, 2);
  assert.ok(numeric283ChartControls(document).every((control) => control.disabled));
  assert.equal(requests[0].options.signal.aborted, true);
  assert.match(requests[1].url, /formula_version=V4_DAILY_NUMERIC283_CHART_20261029_R1/);
  requests[1].resolve({ ok: true, json: async () => makeReadyAnswer("300071.SZ") });
  await flush();
  assert.equal(chartCalls.stocks.length, 1);
  assert.equal(chartCalls.stocks[0].symbol, "300071.SZ");
  assert.ok(numeric283ControlsReady(document));
  assert.equal(document.elements.get("numeric283prevWindow").disabled, true);
  assert.equal(document.elements.get("numeric283nextWindow").disabled, true);
  requests[0].resolve({ ok: true, json: async () => makeReadyAnswer("600025.SH") });
  await flush();
  assert.equal(chartCalls.stocks.length, 1);
  assert.equal(chartCalls.clears, 2);
  assert.ok(numeric283ControlsReady(document));
  assert.equal(document.elements.get("numeric283prevWindow").disabled, true);
  assert.equal(document.elements.get("numeric283nextWindow").disabled, true);
});
