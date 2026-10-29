"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const panel = require("./numeric283-panel.js");

const dataPath = process.env.NUMERIC283_CANDIDATES_PATH
  ? path.resolve(process.env.NUMERIC283_CANDIDATES_PATH)
  : path.resolve(__dirname, "../../../../prepared/daily_numeric283_20261029_r2/numeric283-candidates.json");
const data = JSON.parse(fs.readFileSync(dataPath, "utf8"));

function makeElement(tag, ownerDocument) {
  return {
    tag,
    ownerDocument,
    children: [],
    firstChild: null,
    textContent: "",
    appendChild(child) {
      this.children.push(child);
      this.firstChild = this.children[0] || null;
      return child;
    },
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
  assert.equal(missingNameBody.children[0].children[1].textContent, "名称待核");
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
  assert.equal(tbody.children[0].children[1].textContent, hostileName);
  assert.equal(Object.hasOwn(tbody.children[0].children[1], "innerHTML"), false);
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
