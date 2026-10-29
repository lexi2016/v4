(function (root) {
  "use strict";

  const EXPECTED = Object.freeze({
    schema_version: "v4.numeric283.daily.v1",
    data_date: "20261028",
    observation_date: "20261029",
    source_generation: "31d40c5900ced1b2ff637cfbeaa73688ad921d713e3ea748f83ccbca84463c29",
    source_csv_sha256: "55a65b75d3a03fd767a44d61da8d3d909cbe6c37450fe9796d82980a99a4fefe",
    unique_count: 283,
    group_counts: Object.freeze({ original: 37, nav_smallk: 163, nav_pullback: 130, nav_breakout: 31 }),
  });

  const GROUP_LABELS = Object.freeze({
    original: "原始公式",
    nav_smallk: "小K",
    nav_pullback: "回踩",
    nav_breakout: "突破",
  });
  const CSV_FIELDS = Object.freeze([
    "symbol",
    "display_name",
    "groups",
    "pending_groups",
    "latest_new_anchor",
    "reasons",
    "risk_clear",
  ]);

  function groupTokens(value) {
    if (typeof value !== "string") return [];
    return value.split("|").filter(Boolean);
  }

  function validateData(payload) {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new Error("数据格式不正确");
    }
    for (const key of ["schema_version", "data_date", "observation_date", "source_generation", "source_csv_sha256"]) {
      if (payload[key] !== EXPECTED[key]) throw new Error("名单身份与固定日期不符");
    }
    if (payload.unique_count !== EXPECTED.unique_count || !Array.isArray(payload.rows) || payload.rows.length !== EXPECTED.unique_count) {
      throw new Error("候选名单数量不符");
    }

    const seen = new Set();
    const counts = Object.fromEntries(Object.keys(GROUP_LABELS).map((key) => [key, 0]));
    for (const row of payload.rows) {
      if (!row || typeof row !== "object" || Array.isArray(row)) throw new Error("名单行格式不正确");
      if (typeof row.symbol !== "string" || !/^\d{6}\.(?:SZ|SH|BJ)$/.test(row.symbol) || seen.has(row.symbol)) {
        throw new Error("股票代码缺失或重复");
      }
      seen.add(row.symbol);
      if (typeof row.display_name !== "string" || typeof row.groups !== "string") throw new Error("名单字段不完整");
      if (typeof row.pending_groups !== "string" || typeof row.reasons !== "string" || typeof row.risk_clear !== "string") {
        throw new Error("名单字段不完整");
      }
      if (typeof row.latest_new_anchor !== "string" || !/^\d{8}$/.test(row.latest_new_anchor)) {
        throw new Error("锚点日期不正确");
      }
      const tokens = groupTokens(row.groups);
      if (!tokens.length || new Set(tokens).size !== tokens.length || tokens.some((token) => !Object.hasOwn(GROUP_LABELS, token))) {
        throw new Error("候选组别不正确");
      }
    const pending = groupTokens(row.pending_groups);
    if (new Set(pending).size !== pending.length || pending.some((token) => !Object.hasOwn(GROUP_LABELS, token))) {
      throw new Error("待核组别不正确");
    }
      for (const token of tokens) counts[token] += 1;
    }

    if (Object.keys(EXPECTED.group_counts).some((key) => counts[key] !== EXPECTED.group_counts[key])) {
      throw new Error("分组人数与固定名单不符");
    }
    if (!payload.group_counts || Object.keys(EXPECTED.group_counts).some((key) => payload.group_counts[key] !== counts[key])) {
      throw new Error("分组统计与名单不符");
    }
    return payload.rows;
  }

  function filterRows(rows, selectedGroup, query) {
    const group = selectedGroup || "all";
    const needle = String(query || "").trim().toLowerCase();
    return rows.filter((row) => {
      if (group !== "all" && !groupTokens(row.groups).includes(group)) return false;
      if (!needle) return true;
      return row.symbol.toLowerCase().includes(needle) || row.display_name.toLowerCase().includes(needle);
    });
  }

  function displayGroups(value) {
    return groupTokens(value).map((token) => GROUP_LABELS[token]).join("、");
  }

  function displayPendingGroups(value) {
    const labels = displayGroups(value);
    return labels || "无";
  }

  function displayAnchor(value) {
    return typeof value === "string" && /^\d{8}$/.test(value)
      ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
      : "待核";
  }

  function appendTextLine(parent, document, text) {
    const line = document.createElement("div");
    line.textContent = text;
    parent.appendChild(line);
  }

  function renderRows(tbody, rows, metadata) {
    const source = metadata || EXPECTED;
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
    for (const row of rows) {
      const tr = tbody.ownerDocument.createElement("tr");
      const document = tbody.ownerDocument;
      const basicValues = [row.symbol, row.display_name || "名称待核", displayGroups(row.groups)];
      for (const value of basicValues) {
        const td = tbody.ownerDocument.createElement("td");
        td.textContent = value;
        tr.appendChild(td);
      }

      const pendingCell = document.createElement("td");
      appendTextLine(pendingCell, document, `其他待核组：${displayPendingGroups(row.pending_groups)}`);
      appendTextLine(pendingCell, document, `待核原因：${row.reasons || "未记录"}`);
      appendTextLine(pendingCell, document, `risk_clear：${row.risk_clear}`);
      tr.appendChild(pendingCell);

      const anchorCell = document.createElement("td");
      anchorCell.textContent = displayAnchor(row.latest_new_anchor);
      tr.appendChild(anchorCell);

      const dateCell = document.createElement("td");
      dateCell.textContent = `D${source.data_date || EXPECTED.data_date} / 观察${source.observation_date || EXPECTED.observation_date}`;
      tr.appendChild(dateCell);

      const sourceCell = document.createElement("td");
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "FINAL_NUMERIC_CANDIDATES.csv · 图审待进行";
      details.appendChild(summary);
      appendTextLine(details, document, "来源：FINAL_NUMERIC_CANDIDATES.csv");
      appendTextLine(details, document, `CSV SHA-256：${source.source_csv_sha256 || EXPECTED.source_csv_sha256}`);
      appendTextLine(details, document, `来源代次：${source.source_generation || EXPECTED.source_generation}`);
      appendTextLine(details, document, "图形复核：待进行");
      sourceCell.appendChild(details);
      tr.appendChild(sourceCell);
      tbody.appendChild(tr);
    }
  }

  function csvCell(value) {
    const text = String(value == null ? "" : value);
    return `"${text.replace(/"/g, '""')}"`;
  }

  function toCsv(rows, metadata) {
    const source = metadata || EXPECTED;
    const fields = ["data_date", "observation_date", ...CSV_FIELDS, "source_file", "source_csv_sha256", "source_generation", "chart_review_status"];
    const lines = [fields.map(csvCell).join(",")];
    for (const row of rows) {
      lines.push([
        source.data_date || EXPECTED.data_date,
        source.observation_date || EXPECTED.observation_date,
        ...CSV_FIELDS.map((field) => row[field]),
        "FINAL_NUMERIC_CANDIDATES.csv",
        source.source_csv_sha256 || EXPECTED.source_csv_sha256,
        source.source_generation || EXPECTED.source_generation,
        "PENDING",
      ].map(csvCell).join(","));
    }
    return `\uFEFF${lines.join("\r\n")}\r\n`;
  }

  function mount(document, windowObject) {
    const panel = document.getElementById("dailyNumeric283Panel");
    if (!panel) return;
    const status = document.getElementById("dailyNumeric283Status");
    const count = document.getElementById("dailyNumeric283Count");
    const groupSelect = document.getElementById("dailyNumeric283Group");
    const search = document.getElementById("dailyNumeric283Search");
    const tbody = document.getElementById("dailyNumeric283Rows");
    const download = document.getElementById("dailyNumeric283Download");
    let payloadMetadata = EXPECTED;
    const scriptUrl = document.currentScript && document.currentScript.src
      ? document.currentScript.src
      : windowObject.location.href;
    const dataUrl = new URL("numeric283-candidates.json", scriptUrl);

    function refresh(rows) {
      const filtered = filterRows(rows, groupSelect.value, search.value);
      renderRows(tbody, filtered, payloadMetadata);
      count.textContent = `${filtered.length}只 / ${rows.length}只；组别可重叠。`;
      status.textContent = "固定日期名单已载入。研究用途；尚未进行本卡图形复核。";
    }

    fetch(dataUrl.href, { cache: "force-cache" })
      .then((response) => {
        if (!response.ok) throw new Error("static data unavailable");
        return response.json();
      })
      .then((payload) => {
        const rows = validateData(payload);
        payloadMetadata = payload;
        refresh(rows);
        groupSelect.addEventListener("change", () => refresh(rows));
        search.addEventListener("input", () => refresh(rows));
        download.addEventListener("click", () => {
          const filtered = filterRows(rows, groupSelect.value, search.value);
          const blob = new windowObject.Blob([toCsv(filtered, payloadMetadata)], { type: "text/csv;charset=utf-8" });
          const url = windowObject.URL.createObjectURL(blob);
          const anchor = document.createElement("a");
          anchor.href = url;
          anchor.download = "numeric-candidates-D20261028.csv";
          anchor.click();
          windowObject.setTimeout(() => windowObject.URL.revokeObjectURL(url), 0);
        });
      })
      .catch(() => {
        status.textContent = "名单未通过日期或完整性核验；请使用下方来源链接查看原始交付。";
        count.textContent = "名单暂不可用。";
        download.disabled = true;
      });
  }

  const api = Object.freeze({
    EXPECTED,
    GROUP_LABELS,
    CSV_FIELDS,
    validateData,
    filterRows,
    displayGroups,
    displayPendingGroups,
    displayAnchor,
    renderRows,
    toCsv,
    mount,
  });
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root && root.document && typeof root.fetch === "function") mount(root.document, root);
})(typeof globalThis !== "undefined" ? globalThis : this);
