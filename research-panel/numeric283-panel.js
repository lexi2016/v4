(function (root) {
  "use strict";

  const EXPECTED = Object.freeze({
    schema_version: "v4.numeric283.daily.v1",
    data_date: "20261028",
    observation_date: "20261029",
    source_generation: "31d40c5900ced1b2ff637cfbeaa73688ad921d713e3ea748f83ccbca84463c29",
    source_csv_sha256: "55a65b75d3a03fd767a44d61da8d3d909cbe6c37450fe9796d82980a99a4fefe",
    source_artifact_sha256: "28e577a67e5b5b00a04ac181632d7e1e4e6cc0e4f34e1283f69d28896ec893fb",
    unique_count: 283,
    group_counts: Object.freeze({ original: 37, nav_smallk: 163, nav_pullback: 130, nav_breakout: 31 }),
  });

  const CHART_PROFILE = "V4_DAILY_NUMERIC283_CHART_20261029_R1";
  const CHART_NAMESPACE = "ACTIVE_MA_USER_20261021_V1";
  const D29_NUMERIC_FORMULA_SHA256 = "d35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac";
  const ORIGINAL_ENGINE_SHA256 = "ae4243ec9582055fb6f2ee796978ad20e17f9dee7a56388063cbdbcb56ef0d1c";

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

  function validateDatedData(payload) {
    if (payload?.schema_version !== "v4.a_share.daily_product.v1" || !["READY", "PARTIAL_WITH_ROWS"].includes(payload.status)
        || !/^\d{8}$/.test(payload.data_date) || !/^[a-f0-9]{64}$/.test(payload.source_generation || "")
        || payload.sample_only !== false || payload.RESEARCH_ONLY !== true || payload.production_allowed !== false
        || payload.buy_gate_updated !== false || payload.orders_sent !== false
        || payload.processed_count !== payload.source_universe_count || payload.processed_universe?.length !== payload.processed_count
        || new Set(payload.processed_universe).size !== payload.processed_count
        || payload.source_identity?.generation !== payload.source_generation || payload.source_identity?.asof !== Number(payload.data_date)
        || !/^[a-f0-9]{64}$/.test(payload.source_identity?.input_sha256 || "")
        || !/^[a-f0-9]{64}$/.test(payload.manifest?.sha256 || "") || !/^[a-f0-9]{64}$/.test(payload.artifact?.sha256 || "")
        || !Array.isArray(payload.rows) || payload.rows.length !== payload.unique_count) throw new Error("日期产品身份或完整处理范围不符");
    const seen = new Set(), counts = Object.fromEntries(Object.keys(GROUP_LABELS).map(g => [g, 0]));
    for (const row of payload.rows) {
      if (!/^\d{6}\.(SH|SZ|BJ)$/.test(row.symbol) || seen.has(row.symbol) || !payload.processed_universe.includes(row.symbol)) throw new Error("日期产品代码冲突");
      seen.add(row.symbol);
      const groups = groupTokens(row.groups);
      if (!groups.length || new Set(groups).size !== groups.length || groups.some(g => !Object.hasOwn(counts,g))) throw new Error("日期产品组别冲突");
      groups.forEach(g => counts[g]++);
      if (groupTokens(row.pending_groups).some(g => !Object.hasOwn(counts,g))) throw new Error("未知组别冲突");
    }
    if (Object.keys(counts).some(g => counts[g] !== payload.group_counts?.[g])) throw new Error("日期产品人数不符");
    return payload.rows;
  }

  function validSha256(value) { return typeof value === "string" && /^[a-f0-9]{64}$/.test(value); }

  function keepCurrentProductBinding(previous, incoming) {
    const same = (a,b) => a?.path===b?.path && validSha256(a?.sha256) && a.sha256===b?.sha256;
    // The initial SSE can re-read the exact product while its chart is loading.
    // Preserve that request's object binding; new versions still get a new token.
    return previous && previous.data_date===incoming.data_date && previous.source_generation===incoming.source_generation
      && previous.source_identity?.input_sha256===incoming.source_identity?.input_sha256
      && same(previous.manifest,incoming.manifest) && same(previous.artifact,incoming.artifact)
      ? Object.assign(previous,incoming) : incoming;
  }

  function validReference(value) {
    return value && typeof value.path === "string" && value.path.length > 0 && validSha256(value.sha256);
  }

  function validateDailyCompletionEvent(event) {
    if (!event || event.schema_version !== "v4.a_share.daily_completion.v1"
        || !["READY", "PARTIAL_WITH_ROWS"].includes(event.status)
        || !/^\d{8}$/.test(event.data_date || "")
        || !validSha256(event.event_id) || !validSha256(event.source_generation)
        || !validSha256(event.input_sha256) || !validReference(event.manifest) || !validReference(event.artifact)
        || !Number.isSafeInteger(event.processed_count) || event.processed_count < 0
        || event.source_universe_count !== event.processed_count
        || event.RESEARCH_ONLY !== true || event.production_allowed !== false
        || event.buy_gate_updated !== false || event.orders_sent !== false) {
      throw new Error("完成事件身份或安全合同不匹配");
    }
    return event;
  }

  function completionMatchesProduct(event, product) {
    validateDailyCompletionEvent(event);
    if (!product || product.schema_version !== "v4.a_share.daily_product.v1"
        || product.data_date !== event.data_date || product.status !== event.status
        || product.source_generation !== event.source_generation
        || product.source_identity?.generation !== event.source_generation
        || product.source_identity?.asof !== Number(event.data_date)
        || product.source_identity?.input_sha256 !== event.input_sha256
        || product.processed_count !== event.processed_count
        || product.source_universe_count !== event.source_universe_count
        || product.RESEARCH_ONLY !== true || product.production_allowed !== false
        || product.buy_gate_updated !== false || product.orders_sent !== false
        || !validReference(product.manifest) || !validReference(product.artifact)) return false;
    return event.manifest.path === product.manifest.path && event.manifest.sha256 === product.manifest.sha256
      && event.artifact.path === product.artifact.path && event.artifact.sha256 === product.artifact.sha256;
  }

  function displayDay(value) {
    const text = String(value || "");
    if (/^\d{8}$/.test(text)) return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`;
    return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : "未知";
  }

  function statisticsPresentation(row, symbol, metadata) {
    const coverage = row?.historical_coverage || {}, dates = coverage.evaluated_dates || [];
    const evaluated = Number.isSafeInteger(coverage.evaluated_count) ? coverage.evaluated_count : dates.length;
    const coverageSummary = `已评估 ${evaluated} 个日期；条件未知日仍保留，不等于标签完整或历史PIT认证。`;
    const stats = row?.statistics, expectedAsOf = displayDay(metadata?.data_date);
    const statsBound = stats?.asof === expectedAsOf && ["DESCRIPTIVE_STATS_COMPUTED", "NO_EVENT_GROUPS"].includes(stats.status);
    const priceLines = [], prices = statsBound ? stats.price_distribution || {} : {};
    for (const [label, key] of [["近250日", "near_250"], ["历史", "all_history"]]) {
      const p = prices[key]; priceLines.push({label, value:Number.isFinite(p?.percentile_le) ? `${(p.percentile_le*100).toFixed(2)}%` : "未知", detail:p || {}});
    }
    const groups = Object.entries(GROUP_LABELS).map(([id,label]) => {
      const group = statsBound ? stats.groups?.find(g=>g.group_id===id) : null, identity=group?.source_identity;
      const bound = group?.identity_status === "BOUND" && identity?.generation===metadata?.source_generation
        && identity?.input===metadata?.source_identity?.input_sha256 && identity?.formula===D29_NUMERIC_FORMULA_SHA256
        && identity?.asof===expectedAsOf && identity?.market===String(symbol).slice(-2) && identity?.basis==="QFQ_ASOF"
        && identity?.pit_status==="NONPIT" && identity?.rule_sha256===group?.rule_sha256;
      const eventCount = bound && Number.isSafeInteger(group.eligible_event_count) ? group.eligible_event_count : null;
      const unknown = Number.isSafeInteger(coverage.unknown_by_group?.[id]) ? coverage.unknown_by_group[id] : null;
      const today = row?.evaluation?.groups?.[id]?.status || (groupTokens(row?.groups).includes(id) ? "TRUE" : groupTokens(row?.pending_groups).includes(id) ? "UNKNOWN" : "FALSE");
      const horizons = ["d2","d5"].map(key=>{
        const v=bound ? group.horizons?.[key] : null, valid=v?.valid;
        const counts = Number.isSafeInteger(valid) && valid>0 && [v?.positive,v?.negative,v?.flat].every(n=>Number.isSafeInteger(n)&&n>=0)
          && v.positive+v.negative+v.flat===valid && Number.isFinite(v.positive_fraction) && Math.abs(v.positive_fraction-v.positive/valid)<1e-10;
        return {key,label:key==="d2"?"D+2":"D+5",rate:counts?`${(v.positive/valid*100).toFixed(2)}%`:"数据不足",
          positive:counts?v.positive:null, valid:counts?valid:null, total:v?.total??null,
          mean:counts&&Number.isFinite(v.mean_return_pct)?`${v.mean_return_pct.toFixed(2)}%`:"未知",
          summary:counts?`${v.positive}胜 / ${valid}次`:(v?.not_matured?`未成熟 ${v.not_matured} 次；暂不可算`:"暂无有效样本"),
          cases:Array.isArray(v?.cases)?v.cases:[], raw:v||{}};
      });
      return {id,label,bound,today,eventCount,unknown,horizons,summary:eventCount>0?`${eventCount}次已知事件`:(unknown===0?"已评估范围未见匹配":"数据不足")};
    });
    return {coverageSummary,priceLines,groups};
  }
  function validateDatedChart(answer, symbol, metadata) {
    if (answer?.ts_code !== symbol || answer.end_date !== metadata.data_date || answer.formula_version !== CHART_NAMESPACE
        || answer.research_only !== true || answer.production_allowed !== false || answer.buy_gate_updated !== false || answer.orders_sent !== false) throw new Error("历史身份冲突");
    if (answer.status !== "READY") return answer;
    if (answer.identity?.generation_id !== metadata.source_generation || answer.identity?.input_sha256 !== metadata.source_identity.input_sha256
        || answer.identity?.asof_date !== Number(metadata.data_date) || !Array.isArray(answer.rows) || !answer.rows.length
        || answer.rows.at(-1).trade_date !== metadata.data_date || answer.rows.some((v,i,a) => v.ts_code !== symbol || v.trade_date > metadata.data_date || (i && v.trade_date <= a[i-1].trade_date))) throw new Error("历史代次或日期不匹配");
    return answer;
  }

  function filterRows(rows, selectedGroup, query) {
    const group = selectedGroup || "all";
    const needle = String(query || "").trim().toLowerCase();
    return rows.filter((row) => {
      if (group !== "all" && !groupTokens(row.groups).includes(group)) return false;
      if (!needle) return true;
      return String(row.symbol).toLowerCase().includes(needle) || (row.display_name || "").toLowerCase().includes(needle);
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

  function renderRows(tbody, rows, metadata, onChartClick) {
    const source = metadata || EXPECTED;
    const observationDate = typeof source.observation_date === "string" && /^\d{8}$/.test(source.observation_date)
      ? source.observation_date : "未指定";
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
    for (const row of rows) {
      const tr = tbody.ownerDocument.createElement("tr");
      const document = tbody.ownerDocument;
      const codeCell = document.createElement("td");
      const codeButton = document.createElement("button");
      codeButton.type = "button";
      codeButton.className = "numeric283-chart-trigger";
      codeButton.textContent = row.symbol;
      codeButton.setAttribute("aria-label", `显示 ${row.symbol} ${row.display_name || "名称待核"} 历史图`);
      codeButton.onclick = () => onChartClick?.(row.symbol, row.display_name || "名称待核");
      codeCell.appendChild(codeButton);
      tr.appendChild(codeCell);

      const nameCell = document.createElement("td");
      const nameButton = document.createElement("button");
      nameButton.type = "button";
      nameButton.className = "numeric283-chart-trigger";
      nameButton.textContent = row.display_name || "名称待核";
      nameButton.setAttribute("aria-label", `显示 ${row.symbol} ${row.display_name || "名称待核"} 历史图`);
      nameButton.onclick = () => onChartClick?.(row.symbol, row.display_name || "名称待核");
      nameCell.appendChild(nameButton);
      tr.appendChild(nameCell);

      const groupsCell = document.createElement("td");
      groupsCell.textContent = displayGroups(row.groups);
      tr.appendChild(groupsCell);

      const pendingCell = document.createElement("td");
      appendTextLine(pendingCell, document, `其他待核组：${displayPendingGroups(row.pending_groups)}`);
      appendTextLine(pendingCell, document, `待核原因：${row.reasons || "未记录"}`);
      appendTextLine(pendingCell, document, `risk_clear：${row.risk_clear}`);
      tr.appendChild(pendingCell);

      const anchorCell = document.createElement("td");
      anchorCell.textContent = displayAnchor(row.latest_new_anchor);
      tr.appendChild(anchorCell);

      const dateCell = document.createElement("td");
      dateCell.textContent = `D${source.data_date || EXPECTED.data_date} / 观察${observationDate}`;
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
    const source = metadata || {};
    const fields = ["data_date", "source_generation", "source_input_sha256", "manifest_sha256", "artifact_sha256", ...CSV_FIELDS, "chart_review_status"];
    const lines = [fields.map(csvCell).join(",")];
    for (const row of rows) {
      lines.push([
        source.data_date || "",
        source.source_generation || "",
        source.source_identity?.input_sha256 || "",
        source.manifest?.sha256 || "",
        source.artifact?.sha256 || "",
        ...CSV_FIELDS.map((field) => row[field]),
        "PENDING",
      ].map(csvCell).join(","));
    }
    return `\uFEFF${lines.join("\r\n")}\r\n`;
  }

  function validateChart(answer, symbol) {
    if (!answer || typeof answer !== "object" || Array.isArray(answer)) throw new Error("响应格式不正确");
    if (answer.schema_version !== "v4.a_share_numeric283_chart.v1"
        || answer.ts_code !== symbol || answer.start_date !== "20260101" || answer.end_date !== EXPECTED.data_date
        || answer.formula_version !== CHART_PROFILE || answer.profile_id !== CHART_PROFILE
        || answer.signal_namespace !== CHART_NAMESPACE) {
      throw new Error("响应schema、代码、日期或图表profile不匹配");
    }
    if (answer.research_only !== true || answer.production_allowed !== false
        || answer.buy_gate_updated !== false || answer.orders_sent !== false) {
      throw new Error("研究安全标志不匹配");
    }
    if (answer.status !== "READY") return answer;
    const identity = answer.identity;
    const rows = answer.rows;
    if (!identity || identity.generation_id !== EXPECTED.source_generation
        || identity.artifact_sha256 !== EXPECTED.source_artifact_sha256
        || identity.asof_date !== 20261028 || identity.profile_namespace !== CHART_NAMESPACE
        || identity.numeric283_scope_count !== EXPECTED.unique_count
        || identity.numeric283_source_generation !== EXPECTED.source_generation
        || identity.numeric283_source_artifact_sha256 !== EXPECTED.source_artifact_sha256
        || !Array.isArray(rows) || rows.length === 0) {
      throw new Error("图表代次或来源工件不匹配");
    }
    const seen = new Set();
    let previousDate = "";
    for (const row of rows) {
      if (!row || row.ts_code !== symbol || typeof row.trade_date !== "string"
          || !/^\d{8}$/.test(row.trade_date) || row.trade_date < "20260101"
          || row.trade_date > EXPECTED.data_date || row.trade_date <= previousDate || seen.has(row.trade_date)) {
        throw new Error("历史行代码、日期或顺序不匹配");
      }
      for (const field of ["open", "high", "low", "close", "volume"]) {
        if (row[field] === null || row[field] === undefined || !Number.isFinite(Number(row[field]))) {
          throw new Error(`历史行缺少${field}数据`);
        }
      }
      seen.add(row.trade_date);
      previousDate = row.trade_date;
    }
    if (rows.at(-1).trade_date !== EXPECTED.data_date) throw new Error("历史图未到达D20261028");
    return answer;
  }

  function validateOriginalChart(answer, symbol, product) {
    const sameRef = (a, b) => a?.path === b?.path && a?.sha256 === b?.sha256;
    if (answer?.status !== "READY") throw new Error((answer?.cannot_confirm || [answer?.status || "原式图未绑定"]).join(" · "));
    if (answer.schema_version !== "v4.a_share.original_chart.v1" || answer.symbol !== symbol || answer.data_date !== product.data_date
        || answer.source_generation !== product.source_generation || answer.input_sha256 !== product.source_identity?.input_sha256
        || answer.formula_sha256 !== D29_NUMERIC_FORMULA_SHA256 || answer.engine_sha256 !== ORIGINAL_ENGINE_SHA256
        || !sameRef(answer.product_manifest, product.manifest) || !sameRef(answer.product_artifact, product.artifact)
        || answer.research_only !== true || answer.production_allowed !== false || answer.buy_gate_updated !== false || answer.orders_sent !== false
        || !Number.isInteger(answer.rows) || answer.rows < 1 || answer.values_per_row !== 51 || answer.drawings_per_row !== 22) {
      throw new Error("原式图与当前代码、日期、来源或公式身份不匹配");
    }
    const asset = answer.assets?.html;
    if (!/^[0-9a-f]{64}$/.test(asset?.sha256 || "") || !asset.url?.startsWith("/api/v4/research/a-share/original-chart/html?")) throw new Error("原式图地址未绑定");
    const url = new URL(asset.url, "http://bound.invalid");
    for (const [key, value] of Object.entries({date: product.data_date, symbol, generation: product.source_generation,
      input_sha256: product.source_identity.input_sha256, sha256: asset.sha256})) {
      if (url.searchParams.get(key) !== value) throw new Error("原式图地址身份冲突");
    }
    return answer;
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
    const chartPanel = document.getElementById("dailyNumeric283ChartPanel");
    const chartTitle = document.getElementById("dailyNumeric283ChartTitle");
    const chartStatus = document.getElementById("dailyNumeric283ChartStatus");
    let chartRequest = 0;
    let chartController;
    let payloadMetadata = null;
    let currentRows = [];
    let productRequest = 0;
    let originalFrame = null;
    let originalObserver = null;

    let selectedSymbol = null, activeGroup = 'original', currentStatistics = null, caseFocus = null;
    const caseReplies = new Map();
    const sameRef=(a,b)=>typeof a?.path==='string'&&a.path===b?.path&&validSha256(a?.sha256)&&a.sha256===b?.sha256;
    const number = value => value === null || value === undefined || value === '' ? null : Number.isFinite(Number(value)) ? Number(value) : null;
    const amount = (value, unit) => { const n=number(value); return n===null?'未提供':unit==='元'?`${(n/1e8).toFixed(2)} 亿`:`${value} ${unit||'单位未提供'}`; };
    const add = (host, tag, text, className) => { const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;host.appendChild(e);return e; };
    function link(host,url,label) { if(typeof url!=='string'||!/^https?:\/\//.test(url))return;const a=add(host,'a',label);a.href=url;a.target='_blank';a.rel='noopener';return a; }
    function sectionDetails(host,label) { const e=add(host,'details');add(e,'summary',label);return e; }
    function setupReaderLayout() {
      if(document.getElementById('dailyReaderSidebar'))return;
      document.body.classList.add('daily-reader-mode');document.body.appendChild(panel);
      const sidebar=add(panel,'aside',undefined,'daily-reader-sidebar');sidebar.id='dailyReaderSidebar';
      add(sidebar,'h1','V4 研究');const searchLabel=add(sidebar,'label','搜索股票代码 / 名称');searchLabel.appendChild(search);
      add(sidebar,'nav').id='dailyReaderGroups';add(sidebar,'div').id='dailyReaderStockList';
      const footer=add(sidebar,'div',undefined,'reader-sidebar-footer');link(footer,'http://127.0.0.1:8873/research-panel/archive/2026-10-27/index.html','历史页与说明');
      link(footer,new URL('/research-panel/code-map/index.html',windowObject.location.origin).href,'开发图谱');
      const collapse=add(footer,'button','收起侧栏');collapse.type='button';collapse.onclick=()=>document.body.classList.toggle('reader-sidebar-collapsed');
      const main=add(panel,'div',undefined,'daily-reader-main');main.id='dailyReaderMain';main.appendChild(chartPanel);
      const header=add(chartPanel,'div',undefined,'reader-stock-header');header.id='dailyReaderHeader';
      const identity=add(header,'div');identity.id='dailyReaderIdentity';identity.appendChild(chartTitle);add(identity,'p').id='dailyReaderDate';
      const controls=add(header,'div',undefined,'reader-chart-controls');controls.innerHTML='<button type="button" class="active">日K</button><button type="button" disabled title="本次仅接入已绑定日K">周K</button><select id="dailyChartBars" aria-label="图窗根数"><option value="60">最近60根</option><option value="120" selected>最近120根</option><option value="250">最近250根</option></select><select id="dailyChartExtent" aria-label="历史区段"><option value="recent">当前区段</option><option value="all">全部历史</option></select><button type="button" id="dailyChartRestore">恢复区间</button><label><input id="dailyChartMarks" type="checkbox" checked>文字标注</label>';
      chartPanel.insertBefore(header,chartPanel.firstChild);const host=add(chartPanel,'div');host.id='dailyOriginalChartHost';header.after(host);
      const focus=add(chartPanel,'p',undefined,'reader-event-focus');focus.id='dailyChartEventFocus';focus.hidden=true;host.after(focus);
      const stats=document.getElementById('dailyEventStatistics');focus.after(stats);
      const cases=add(chartPanel,'details');cases.id='dailyEventCases';cases.hidden=true;stats.after(cases);add(cases,'summary','历史事件');
      const material=add(chartPanel,'section');material.id='dailyCompanyMaterials';cases.after(material);
      const received=add(chartPanel,'details');received.id='dailyReceivedReports';received.hidden=true;material.after(received);add(received,'summary','查看研报目录');
      const reports=document.getElementById('relatedReports');if(reports){received.appendChild(reports);reports.hidden=false;}
      const diagnostic=add(chartPanel,'details');diagnostic.id='dailyReaderDiagnostics';add(diagnostic,'summary','历史案例与数据来源');
      const chartInfo=add(diagnostic,'details');add(chartInfo,'summary','原式51变量、22绘图与图形来源');chartInfo.ontoggle=()=>{if(!originalFrame)return;originalFrame.contentDocument?.body.classList.toggle('reader-full-details',chartInfo.open);originalFrame.style.height=chartInfo.open?'1650px':'460px';};
      diagnostic.appendChild(chartStatus);for(const p of Array.from(chartPanel.children)){if(p.tagName==='P'&&p!==focus)diagnostic.appendChild(p);}
      const reportsIdentity=document.getElementById('relatedReportsIdentity');if(reportsIdentity)reportsIdentity.textContent='正文库为当前知识补充；目录资料与库内匹配分开显示。';
      document.getElementById('dailyChartBars').onchange=e=>{const w=originalFrame?.contentWindow;if(!w?.setOriginalWindow)return;const n=Number(e.target.value);w.document.getElementById('window').value=String(n);w.setOriginalWindow(n,w.RESEARCH_PANEL_STATE.rows.length);};
      document.getElementById('dailyChartExtent').onchange=e=>{const w=originalFrame?.contentWindow;if(w?.setOriginalWindow)w.setOriginalWindow(e.target.value==='all'?0:120,w.RESEARCH_PANEL_STATE.rows.length);};
      document.getElementById('dailyChartRestore').onclick=restoreCurrent;
      document.getElementById('dailyChartMarks').onchange=e=>{const child=originalFrame?.contentDocument,box=child?.getElementById('draw-text');if(box){box.checked=e.target.checked;box.onchange?.();}};
    }
    function refreshReaderList(rows) {
      const host=document.getElementById('dailyReaderStockList');if(!host)return;host.replaceChildren();
      const ordered=[...rows].sort((a,b)=>(b.symbol===selectedSymbol)-(a.symbol===selectedSymbol));
      for(const row of ordered){const b=add(host,'button',undefined,'numeric283-chart-trigger reader-stock'+(row.symbol===selectedSymbol?' active':''));b.type='button';b.dataset.symbol=row.symbol;add(b,'strong',row.symbol);add(b,'span',row.display_name||'名称未提供');b.onclick=()=>loadChart(row.symbol,row.display_name||'名称未提供');}
      const groups=document.getElementById('dailyReaderGroups');groups.replaceChildren();
      for(const [id,label]of [['all','全部'],...Object.entries(GROUP_LABELS)]){const b=add(groups,'button',undefined,groupSelect.value===id?'active':'');b.type='button';add(b,'span',label);add(b,'span',String(id==='all'?currentRows.length:payloadMetadata.group_counts[id]));b.onclick=()=>{groupSelect.value=id;refresh(currentRows);};}
    }
    function restoreCurrent(){caseFocus=null;const f=document.getElementById('dailyChartEventFocus');if(f)f.hidden=true;const w=originalFrame?.contentWindow;if(!w?.setOriginalWindow)return;const s=w.RESEARCH_PANEL_STATE;w.document.getElementById('window').value='120';w.setOriginalWindow(Math.min(120,s.rows.length),s.rows.length);w.choose(s.rows.length-1);w.paint();const bars=document.getElementById('dailyChartBars');if(bars)bars.value='120';const extent=document.getElementById('dailyChartExtent');if(extent)extent.value='recent';}
    function paintCaseOverlay(w){if(!caseFocus)return;const s=w.RESEARCH_PANEL_STATE,g=s?.geometry,cv=w.document.getElementById('chart');if(!g||!s.visible?.length)return;const start=s.rows.findIndex(r=>r.trade_date===Number(caseFocus.event_date.replaceAll('-',''))),target=s.rows.findIndex(r=>r.trade_date===Number(String(caseFocus.target_date||'').replaceAll('-',''))),ratio=w.devicePixelRatio||1,c=cv.getContext('2d');c.save();c.setTransform(ratio,0,0,ratio,0,0);const left=g.L+(start-s.offset)*g.step,right=g.L+((target>=0?target:s.rows.length-1)-s.offset+1)*g.step,x=g.L+(start-s.offset+.5)*g.step;c.beginPath();c.rect(g.L,22,g.pw,g.h-52);c.clip();c.fillStyle='rgba(58,205,208,.10)';c.fillRect(left,22,Math.max(g.step,right-left),g.h-52);c.strokeStyle='#f4c97b';c.lineWidth=2;c.beginPath();c.moveTo(x,22);c.lineTo(x,g.h-30);c.stroke();if(target>=0){const tx=g.L+(target-s.offset+.5)*g.step;c.strokeStyle='#42e5d5';c.beginPath();c.moveTo(tx,22);c.lineTo(tx,g.h-30);c.stroke();}c.restore();}
    function configureOriginalView(frame,child){if(child.getElementById('reader-focus-style'))return;const style=child.createElement('style');style.id='reader-focus-style';style.textContent='body{margin:0!important;background:#07131e!important}body:not(.reader-full-details) header,body:not(.reader-full-details) aside,body:not(.reader-full-details) .toolbar,body:not(.reader-full-details) .charthead .controls,body:not(.reader-full-details) #selected-date,body:not(.reader-full-details) .stats,body:not(.reader-full-details) .tables,body:not(.reader-full-details) details,body:not(.reader-full-details) #status,body:not(.reader-full-details) .foot,body:not(.reader-full-details) #chart-caption{display:none!important}main{display:block!important;max-width:none!important;margin:0!important;min-height:0!important}article{padding:12px!important}.chartbox{border:0!important;padding:0!important}.charthead{margin:0 0 4px!important}canvas{height:405px!important}';child.head.appendChild(style);const w=frame.contentWindow,originalPaint=w.paint;w.paint=function(){originalPaint();paintCaseOverlay(w);const bars=document.getElementById('dailyChartBars'),n=w.RESEARCH_PANEL_STATE.view?.count;if(bars&&n){let option=Array.from(bars.options).find(o=>o.value===String(n));if(!option){option=document.createElement('option');option.value=String(n);option.dataset.dynamic='true';option.textContent=`当前${n}根`;bars.appendChild(option);}bars.value=String(n);}};frame.style.height='460px';w.dispatchEvent(new w.Event('resize'));w.paint();frame.style.height=Math.max(450,Math.ceil(child.querySelector('article').getBoundingClientRect().bottom+8))+'px';}
    function locateEvent(item){const w=originalFrame?.contentWindow,s=w?.RESEARCH_PANEL_STATE;if(!s)return;const i=s.rows.findIndex(r=>r.trade_date===Number(item.event_date.replaceAll('-','')));if(i<0)return;caseFocus=item;w.setOriginalWindow(Math.min(120,s.rows.length),Math.min(s.rows.length,i+84));w.choose(i);w.paint();const info=document.getElementById('dailyChartEventFocus');info.hidden=false;info.replaceChildren();add(info,'span',`事件日 ${item.event_date} → ${item.target_date||'目标日未提供'} · ${Number.isFinite(item.return_pct)?item.return_pct.toFixed(2)+'%':item.status==='not_matured'?'未成熟':'收益未知'}；黄色为事件日，青色为目标日。`);const back=add(info,'button',`返回当前 ${displayDay(payloadMetadata.data_date)}`);back.type='button';back.onclick=restoreCurrent;document.getElementById('dailyOriginalChartHost').scrollIntoView({block:'start'});}
    async function showEventCases(symbol,group,horizon,subset='all'){
      const host=document.getElementById('dailyEventCases');host.hidden=false;host.open=true;host.replaceChildren();add(host,'summary',`${GROUP_LABELS[group]} · ${horizon==='d2'?'D+2':'D+5'} ${subset==='all'?'全部历史同条件事件':'同价格分位事件'}`);const token=chartRequest,key=[payloadMetadata.manifest.sha256,symbol,group,horizon].join('|');
      try{let answer=caseReplies.get(key);if(!answer){const q=new URLSearchParams({date:payloadMetadata.data_date,symbol,group,horizon});answer=await (await windowObject.fetch('/api/v4/research/a-share/event-cases?'+q,{cache:'no-store',signal:chartController.signal})).json();if(token!==chartRequest)return;if(answer.status!=='READY'||answer.symbol!==symbol||!sameRef(answer.numeric_manifest,payloadMetadata.manifest))throw new Error('历史明细尚未物化或身份不匹配');caseReplies.set(key,answer);}
      const cases=subset==='all'?answer.cases:answer.cases.filter(v=>v.percentile_bucket===answer.conditional?.bucket);
      add(host,'p',`${subset==='all'?'总事件':'同分位事件'} ${cases.length} 次；正、负、平、未成熟和缺价均列出。点击任一日期定位原式图。`);
      const wrap=add(host,'div',undefined,'reader-case-table');const table=add(wrap,'table');const head=add(table,'tr');for(const t of ['事件日','目标日','结果','收益','当时近250分位'])add(head,'th',t);
      for(const item of cases){const row=add(table,'tr');const cell=add(row,'td'),button=add(cell,'button',item.event_date);button.type='button';button.onclick=()=>locateEvent(item);add(row,'td',item.target_date||'未知');add(row,'td',({positive:'正',negative:'负',flat:'平',not_matured:'未成熟'})[item.status]||'缺价/未知');add(row,'td',Number.isFinite(item.return_pct)?item.return_pct.toFixed(2)+'%':'—');add(row,'td',Number.isFinite(item.price_percentile)?(item.price_percentile*100).toFixed(2)+'%':'UNKNOWN（不足250有效价）');}
      }catch(e){if(token===chartRequest)add(host,'p',`明细未确认：${e.message}`);}
    }
    function renderStatistics(symbol){const host=document.getElementById('dailyEventStatistics');if(!currentStatistics)return;const p=currentStatistics.presentation,selected=p.groups.find(g=>g.id===activeGroup)||p.groups[0];host.replaceChildren();
      const metric=add(host,'div',undefined,'reader-win-metrics');
      for(const h of selected.horizons){const card=add(metric,'div',undefined,'reader-win-card');const title=add(card,'p',`${selected.label} · ${h.label} 历史总体成功率`,'metric-label');title.title=`${selected.label}；正收益/有效样本，平收益保留分母`;const line=add(card,'div',undefined,'reader-win-line');const total=add(line,'button',h.rate,'reader-rate');total.type='button';total.dataset.horizon=h.key;total.dataset.subset='all';total.onclick=()=>showEventCases(symbol,selected.id,h.key);const summary=add(line,'div');add(summary,'div',h.summary);add(summary,'p',`平均收益 ${h.mean}`);const conditional=currentStatistics.conditional?.[h.key];const sub=add(card,'button',undefined,'reader-conditional');sub.type='button';sub.dataset.subset='conditional';sub.dataset.horizon=h.key;sub.disabled=!conditional;sub.textContent=conditional?`同分位成功率 ${conditional.bucket_label}：${conditional.valid>0?(conditional.positive/conditional.valid*100).toFixed(2)+'%':'样本不足'} · ${conditional.positive??'—'}胜/${conditional.valid??'—'}次`:'同分位成功率：统计未物化';sub.onclick=()=>showEventCases(symbol,selected.id,h.key,'conditional');}
      const price=add(metric,'div',undefined,'reader-price-card');add(price,'p','价格分位','metric-label');for(const q of p.priceLines){const line=add(price,'p');add(line,'span',q.label+' ');add(line,'strong',q.value);}add(price,'small','价格位置，独立于历史胜率');
      add(host,'p','以事件日收盘至D+2/D+5同源交易日收盘计；未成熟/缺价不计胜率，平收益计入有效样本。历史描述，非未来预测。','reader-note');
      const diagnostics=document.getElementById('dailyReaderDiagnostics')||host;let groupHost=document.getElementById('dailyGroupStatistics');if(!groupHost){groupHost=add(diagnostics,'section');groupHost.id='dailyGroupStatistics';}groupHost.replaceChildren();add(groupHost,'h3','四组当前状态与历史样本');const table=add(groupHost,'table'),tr=add(table,'tr');for(const t of ['组别','今日命中','已知历史样本','D+2','D+5','条件未知日'])add(tr,'th',t);
      for(const g of p.groups){const r=add(table,'tr'),cell=add(r,'td'),b=add(cell,'button',g.label);b.type='button';b.onclick=()=>{activeGroup=g.id;renderStatistics(symbol);loadConditionalSummaries(symbol,g.id,chartRequest);};add(r,'td',g.today==='TRUE'?'命中':g.today==='UNKNOWN'?'未知':'未命中');add(r,'td',g.summary);for(const h of g.horizons)add(r,'td',h.rate);add(r,'td',g.unknown===null?'未知':String(g.unknown));}
      add(groupHost,'p',p.coverageSummary);const source=sectionDetails(groupHost,'查看日期覆盖、案例与统计来源');add(source,'pre',JSON.stringify({coverage:currentStatistics.row.historical_coverage,source_generation:payloadMetadata.source_generation,manifest:payloadMetadata.manifest,statistics:currentStatistics.row.statistics},null,2));}
    async function loadConditionalSummaries(symbol,group,token){const values={};await Promise.all(['d2','d5'].map(async h=>{try{const q=new URLSearchParams({date:payloadMetadata.data_date,symbol,group,horizon:h});const a=await(await windowObject.fetch('/api/v4/research/a-share/event-cases?'+q,{cache:'no-store',signal:chartController.signal})).json();if(token!==chartRequest||a.status!=='READY'||!sameRef(a.numeric_manifest,payloadMetadata.manifest))return;caseReplies.set([payloadMetadata.manifest.sha256,symbol,group,h].join('|'),a);if(a.conditional)values[h]=a.conditional;}catch(_){}}));if(token===chartRequest&&currentStatistics&&activeGroup===group){currentStatistics.conditional=values;renderStatistics(symbol);}}
    function sourceLink(host,field,label='来源'){if(field?.source_url)link(host,field.source_url,label);}
    async function showCompanyMaterials(symbol,token){const host=document.getElementById('dailyCompanyMaterials'),reports=document.getElementById('dailyReceivedReports');if(!host)return;const library=document.getElementById('relatedReports');host.textContent='正在读取已整理资料…';reports.replaceChildren();add(reports,'summary','查看研报目录');if(library){reports.appendChild(library);reports.hidden=false;}
      try{const q=new URLSearchParams({date:payloadMetadata.data_date,symbol,generation:payloadMetadata.source_generation,input_sha256:payloadMetadata.source_identity.input_sha256});const a=await(await windowObject.fetch('/api/v4/research/a-share/company-materials?'+q,{cache:'no-store',signal:chartController.signal})).json();if(token!==chartRequest)return;if(a.status!=='PARTIAL_RECEIVED'||a.symbol!==symbol||!sameRef(a.numeric_manifest,payloadMetadata.manifest))throw new Error('已有资料尚未绑定当前产品');const m=a.materials,b=m.business_reported||{},f=m.financials_reported||{},holders=m.shareholders_reported||{},detail=m.provenance_details||{},history=detail.shareholder_count_history||[];const latest=history.find(r=>r.asof_date===holders.holder_asof)||history[0];const catalog=m.report_catalog||[];host.replaceChildren();const grid=add(host,'div',undefined,'reader-material-grid');
      const business=add(grid,'section',undefined,'reader-material-card');const bh=add(business,'h3','基本面');const more=add(bh,'button','查看详情');more.onclick=()=>{document.getElementById('dailyMaterialsDetails').open=true;document.getElementById('dailyMaterialsDetails').scrollIntoView({block:'start'});};add(business,'small','主营业务');const summary=add(business,'p',b.value||'主营业务未提供','reader-business');summary.title=b.value||'';add(business,'p',Number(f.latest_period_months)===9&&f.latest_period_kind==='YTD'?`${String(f.latest_report_period).slice(0,4)}年前三季度`:`${f.latest_report_period||'报告期未提供'} · ${f.latest_period_kind||''}`,'reader-note');const finance=add(business,'div',undefined,'reader-finance');for(const[label,key]of [['营收','latest_revenue'],['归母净利润','latest_net_profit_parent']]){const item=add(finance,'div');add(item,'small',label);add(item,'strong',amount(f[key],f.monetary_unit));}add(business,'p',`财务披露 ${f.latest_disclosed_at||'未提供'} · ${f.monetary_unit||'单位未提供'}`,'reader-note');link(business,f.latest_financial_source_url,'财务原始来源');
      const owner=add(grid,'section',undefined,'reader-material-card');add(owner,'h3','股东变化');const n=number(holders.holder_count);add(owner,'strong',n===null?'数据未提供':`${n.toLocaleString('zh-CN')} 户`,'reader-holder-count');const change=number(holders.holder_change_accounts);add(owner,'p',change===null?'较上期变化未提供':change<0?`较上期减少 ${Math.abs(change).toLocaleString('zh-CN')} 户`:`较上期增加 ${change.toLocaleString('zh-CN')} 户`,'reader-holder-change');add(owner,'p',`统计日 ${holders.holder_asof||'未提供'} · 披露 ${latest?.holder_count?.disclosed_at||'未提供'}`,'reader-note');sourceLink(owner,latest?.holder_count,'股东户数来源');add(owner,'small','户数变化不等于筹码成本分布');
      const report=add(grid,'section',undefined,'reader-material-card');add(report,'h3','研报');add(report,'span',`${catalog.length} 条目录`,'reader-report-count');if(catalog.length){const lead=catalog[0];add(report,'p',lead.title,'reader-report-title');add(report,'p',`${lead.institution||'机构未提供'} · ${String(lead.published_at||'日期未提供').slice(0,10)}`,'reader-note');add(report,'p',lead.full_text_status==='NOT_RETRIEVED_METADATA_ONLY'?'目录资料，正文未取得':lead.full_text_status||'正文状态未提供','reader-note');}else add(report,'p','本股回包未提供研报目录');const open=add(report,'button','查看研报目录');open.type='button';open.onclick=()=>{reports.hidden=false;reports.open=true;reports.scrollIntoView({block:'start'});};
      add(reports,'p',`已整理 ${catalog.length} 条同代码目录；仅目录元数据，不能据此声称正文已读或库内主体匹配。`);for(const r of catalog){const e=add(reports,'article');add(e,'h4',r.title||'标题未提供');add(e,'p',`${r.institution||'机构未提供'} · ${String(r.published_at||'日期未提供').slice(0,10)} · ${r.full_text_status==='NOT_RETRIEVED_METADATA_ONLY'?'正文未取得':r.full_text_status?'正文状态详见来源':'正文状态未提供'}`);link(e,r.report_url,'目录所列研报链接');link(e,r.metadata_source_url,'查看实际目录来源');}
      const known=m.stored_report;if(known?.document&&known?.source_detail_receipt){const e=add(reports,'article');add(e,'h4',known.document.filename||'库中已校验资料');add(e,'p','原件及OCR哈希曾校验；当前知识补充，研报主体关联仍保留原状态。');const source={document_id:known.document.document_id,research_date:known.document.date,receipt_sha256:known.source_detail_receipt.sha256};const body=add(e,'div'),button=add(e,'button','查看已校验OCR正文');button.type='button';button.onclick=()=>windowObject.RelatedReports?.openStoredDocument(source,{verified_pdf_sha256:known.source_detail_receipt.verified_pdf_sha256},body,button);}
      if(library)reports.appendChild(library); // Preserve the successful catalog/body order; node already connected before await.
      let details=document.getElementById('dailyMaterialsDetails');if(!details){details=sectionDetails(document.getElementById('dailyReaderDiagnostics'),'基本面字段、原值、单位与来源');details.id='dailyMaterialsDetails';}details.replaceChildren();add(details,'summary','基本面字段、原值、单位与来源');add(details,'p',`已有资料 ${m.fundamental_state||'PARTIAL'}；字段来源及首次披露/PIT限制原样保留，未作全字段认证。`);sourceLink(details,b,'主营业务公告原文');add(details,'p',`主营业务统计期 ${b.asof_date||'未提供'}；披露 ${b.disclosed_at||'未提供'}；来源状态 ${b.evidence_status||'未提供'}。`);add(details,'pre',JSON.stringify(m,null,2));
      }catch(e){if(token===chartRequest)host.textContent=`已有资料未确认：${e.message}；未要求重新研究或填充缺失值。`;}
    }

    function clearOriginalChart() {
      originalObserver?.disconnect(); originalObserver = null;
      originalFrame?.remove(); originalFrame = null; caseFocus = null;
    }

    function originalMode(active) {
      const legacy = document.getElementById("numeric283chart85Panel"); if (legacy) legacy.hidden = active;
      const unknown = document.getElementById("numeric283chart85Unknown"); if (active && unknown) unknown.hidden = true;
      for (const line of chartPanel.querySelectorAll("p")) {
        if (line.textContent.includes("历史图 API 使用指标命名空间")) line.hidden = active;
      }
    }

    function loadOriginalChart(symbol, token) {
      const product = payloadMetadata;
      const query = new URLSearchParams({date: product.data_date, symbol, generation: product.source_generation,
        input_sha256: product.source_identity.input_sha256});
      windowObject.fetch(`/api/v4/research/a-share/original-chart?${query}`, {signal: chartController.signal, cache: "no-store"})
        .then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })
        .then(answer => {
          if (token !== chartRequest || product !== payloadMetadata) return;
          validateOriginalChart(answer, symbol, product);
          const frame = document.createElement("iframe");
          originalFrame = frame; frame.id = "dailyOriginalFormulaFrame";
          frame.title = `${symbol} · D${answer.data_date} · 原式51变量/22绘图`;
          frame.style.cssText = "width:100%;height:460px;border:0;display:block";
          frame.setAttribute("sandbox", "allow-scripts allow-same-origin");
          const fail = error => {
            if (token !== chartRequest) return;
            clearOriginalChart(); chartStatus.textContent = `原式图未确认，旧图已清空：${error.message}`;
          };
          frame.onload = () => {
            if (token !== chartRequest || product !== payloadMetadata) { frame.remove(); return; }
            try {
              const child = frame.contentDocument;
              if (!child || child.contentType !== "text/html" || !child.getElementById("chart")) throw new Error("原式图文件未通过只读接口校验");
              const ready = () => {
                if (token !== chartRequest || product !== payloadMetadata) { clearOriginalChart(); return; }
                if (child.getElementById("status")?.classList.contains("error")) { fail(new Error("原式图内部身份未确认")); return; }
                if (!child.documentElement.dataset.loaded) return;
                const state = frame.contentWindow.RESEARCH_PANEL_STATE;
                if (state?.symbol !== symbol || state.rows?.at(-1)?.trade_date !== Number(product.data_date) || state.rows.length !== answer.rows) {
                  fail(new Error("原式图实际代码或日期不符")); return;
                }
                originalObserver?.disconnect(); originalObserver = null;
                if(document.getElementById("dailyReaderMain"))configureOriginalView(frame,child);
                chartStatus.textContent = `${symbol} · D${answer.data_date} · 原式 d35c · ${answer.rows}行 · 51数值/22绘图；同源只读产物，非股票完整PASS或原生/PIT认证。`;
              };
              originalObserver = new windowObject.MutationObserver(ready);
              originalObserver.observe(child.documentElement, {attributes: true, subtree: true, childList: true, characterData: true});
              ready();
            } catch (error) { fail(error); }
          };
          frame.src = answer.assets.html.url;
          (document.getElementById("dailyOriginalChartHost") || chartPanel).appendChild(frame);
        }).catch(error => {
          if (token === chartRequest && error.name !== "AbortError") {
            clearOriginalChart(); chartStatus.textContent = `原式图未确认，旧图已清空：${error.message}`;
          }
        });
    }

    function setChartControlsDisabled(disabled) {
      const previousWindow = document.getElementById("numeric283prevWindow");
      const nextWindow = document.getElementById("numeric283nextWindow");
      [
        ...document.querySelectorAll("[data-numeric283-window]"),
        previousWindow,
        nextWindow,
        document.getElementById("numeric283dateSelect"),
        document.getElementById("numeric283panRange"),
      ].filter(Boolean).forEach((control) => {
        // setStock sets these two controls' boundary state; retain it after loading succeeds.
        if (!disabled && (control === previousWindow || control === nextWindow)) return;
        control.disabled = disabled;
      });
    }

    setChartControlsDisabled(true);
    download.disabled = true;

    function loadChart(symbol, name) {
      selectedSymbol=symbol;const ownGroups=groupTokens(currentRows.find(row=>row.symbol===symbol)?.groups);activeGroup=ownGroups.includes(groupSelect.value)?groupSelect.value:ownGroups[0]||"original";currentStatistics=null;refreshReaderList(filterRows(currentRows,groupSelect.value,search.value));
      const token = ++chartRequest;
      chartController?.abort();
      chartController = new AbortController();
      clearOriginalChart();
      setChartControlsDisabled(true);
      windowObject.Numeric283Chart?.clear();
      chartPanel.hidden = false;
      chartTitle.textContent = `${name}  ${symbol}`;
      const dateLine=document.getElementById("dailyReaderDate");if(dateLine)dateLine.textContent=`数据至 ${displayDay(payloadMetadata.data_date)} · ${displayGroups(currentRows.find(row=>row.symbol===symbol)?.groups||"")}入选`;
      chartStatus.textContent = `正在读取 ${symbol} 的 D${payloadMetadata.data_date} 历史；旧图已清空。`;
      chartPanel.scrollIntoView?.({ behavior: "smooth", block: "start" });
      if (!payloadMetadata.rows?.some((row) => row.symbol === symbol)) {
        chartStatus.textContent = "代码不在已载入的当前日期名单中，未请求历史。";
        return;
      }
      const reports = document.getElementById("relatedReports");
      if (reports) { reports.hidden=false;reports.dataset.identityDate=payloadMetadata.data_date;reports.dataset.generation=payloadMetadata.source_generation;windowObject.RelatedReports?.prepareSelection(symbol,name,currentRows.find(row=>row.symbol===symbol)?.display_name_source||null); }
      const datedOriginal = payloadMetadata.schema_version !== EXPECTED.schema_version;
      originalMode(datedOriginal);
      if (datedOriginal) { loadOriginalChart(symbol, token);showStatistics(symbol, token);showCompanyMaterials(symbol,token);return; }
      showStatistics(symbol, token);
      if (!windowObject.Numeric283Chart) {
        chartStatus.textContent = "图表渲染器不可用；旧图已清空。";
        return;
      }
      const query = new URLSearchParams({
        ts_code: symbol,
        start_date: "20260101",
        end_date: payloadMetadata.data_date,
        formula_version: payloadMetadata === EXPECTED || payloadMetadata.schema_version === EXPECTED.schema_version ? CHART_PROFILE : CHART_NAMESPACE,
      });
      windowObject.fetch(`/api/v4/research/a-share/history?${query}`, {
        signal: chartController.signal,
        cache: "no-store",
      }).then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      }).then((answer) => {
        const validated = payloadMetadata.schema_version === EXPECTED.schema_version ? validateChart(answer, symbol) : validateDatedChart(answer, symbol, payloadMetadata);
        if (token !== chartRequest) return;
        if (validated.status !== "READY") {
          chartStatus.textContent = [validated.status, ...(validated.cannot_confirm || [])].filter(Boolean).join(" · ") || "历史未确认；旧图已清空。";
          return;
        }
        const chartRows = validated.rows.map((row) => ({
          date: row.trade_date,
          open: row.open,
          high: row.high,
          low: row.low,
          close: row.close,
          volume: row.volume,
          values: {
            "白线": row.zge_white_line,
            "黄线": row.zge_yellow_line,
            BBI: row.BBI,
            J: row.J,
          },
        }));
        windowObject.Numeric283Chart.setStock({ symbol, name, chartRows });
        setChartControlsDisabled(false);
        chartStatus.textContent = `${symbol} · 截至 D${payloadMetadata.data_date} · ${chartRows.length} 根已存日K。参考线命名空间：${CHART_NAMESPACE}。`;
      }).catch((error) => {
        if (token === chartRequest && error.name !== "AbortError") {
          setChartControlsDisabled(true);
          windowObject.Numeric283Chart.clear();
          chartStatus.textContent = `读取未确认，旧图已清空：${error.message}`;
        }
      });
    }

    function refresh(rows) {
      const filtered = filterRows(rows, groupSelect.value, search.value);
      renderRows(tbody, filtered, payloadMetadata, loadChart);
      refreshReaderList(filtered);
      count.textContent = `${filtered.length}只 / ${rows.length}只；组别可重叠。`;
      status.textContent = "当前日期产品已载入。研究用途；尚未进行本卡图形复核。";
    }

    function showStatistics(symbol, token) {
      const host=document.getElementById("dailyEventStatistics");if(!host)return;host.textContent="正在读取已算同条件胜率…";
      windowObject.fetch(`/api/v4/research/a-share/daily-product?date=${payloadMetadata.data_date}&symbol=${encodeURIComponent(symbol)}`,{cache:"no-store",signal:chartController.signal})
        .then(r=>r.json()).then(answer=>{if(token!==chartRequest)return;const row=answer.row;if(answer.status!=="READY"||row?.symbol!==symbol||answer.source_generation!==payloadMetadata.source_generation||answer.data_date!==payloadMetadata.data_date)throw new Error("同股统计身份不符");
          currentStatistics={row,presentation:statisticsPresentation(row,symbol,payloadMetadata),conditional:{}};renderStatistics(symbol);loadConditionalSummaries(symbol,activeGroup,token);
        }).catch(e=>{if(token===chartRequest)host.textContent=`统计未确认：${e.message}`;});
    }
    function commitPayload(payload) {
      const rows = payload.schema_version === EXPECTED.schema_version ? validateData(payload) : validateDatedData(payload);
      payload = keepCurrentProductBinding(payloadMetadata, payload);
      if (payloadMetadata?.source_generation !== payload.source_generation || payloadMetadata?.data_date !== payload.data_date
          || payloadMetadata?.artifact?.sha256 !== payload.artifact?.sha256) {
        clearOriginalChart();
        ++chartRequest; chartController?.abort(); windowObject.Numeric283Chart?.clear(); setChartControlsDisabled(true); windowObject.RelatedReports?.clear();
        selectedSymbol=null;const material=document.getElementById('dailyCompanyMaterials');if(material)material.textContent='新日期资料待选股读取。';const cases=document.getElementById('dailyEventCases');if(cases)cases.hidden=true;
        const stats = document.getElementById("dailyEventStatistics"); if(stats) stats.textContent = "新日期名单已更新；请选择当前名单股票读取统计。";
        chartStatus.textContent = "名单已更新；请主动选择当前名单股票。";
      }
      payloadMetadata = payload; currentRows = rows; download.disabled = false; setupReaderLayout();
      const title = document.getElementById("dailyNumeric283Title"); if(title) title.textContent = `数值候选名单 · D${payload.data_date} · ${rows.length}只`;
      for(const option of groupSelect.options) option.textContent = option.value === "all" ? `全部（${rows.length}）` : `${GROUP_LABELS[option.value]}（${payload.group_counts[option.value]}）`;
      refresh(rows);
      status.textContent = `D${payload.data_date} · ${payload.status || "日期产品"} · 已处理 ${payload.processed_count ?? rows.length}/${payload.source_universe_count ?? rows.length} · 未知股票 ${payload.unknown_count ?? "未知"}；组别可重叠。`;
      if(document.getElementById("dailyReaderMain")&&!selectedSymbol){const first=rows.find(r=>r.symbol==="002003.SZ")||rows[0];if(first)loadChart(first.symbol,first.display_name||"名称未提供");}
    }
    async function loadDated(expectedEvent) {
      const token = ++productRequest;
      const response = await windowObject.fetch("/api/v4/research/a-share/daily-product", {cache:"no-store"});
      if(!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if(token !== productRequest) return;
      if(expectedEvent && !completionMatchesProduct(expectedEvent, payload)) throw new Error("完成事件与当前日期产品、manifest或artifact身份不匹配");
      commitPayload(payload);
    }
    groupSelect.addEventListener("change", () => refresh(currentRows));
    search.addEventListener("input", () => refresh(currentRows));
    download.addEventListener("click", () => {
      const blob = new windowObject.Blob([toCsv(filterRows(currentRows, groupSelect.value, search.value), payloadMetadata)], {type:"text/csv;charset=utf-8"});
      const url = windowObject.URL.createObjectURL(blob), anchor = document.createElement("a"); anchor.href=url; anchor.download=`numeric-candidates-D${payloadMetadata.data_date}.csv`; anchor.click(); windowObject.setTimeout(()=>windowObject.URL.revokeObjectURL(url),0);
    });
    loadDated().catch(error => { status.textContent = `当前日期产品未确认：${error.message}；保留已验证名单。`; download.disabled = true; });
    if(typeof windowObject.EventSource === "function") {
      const events = new windowObject.EventSource("/api/v4/research/events");
      events.addEventListener("a_share_daily_completed", event => { try { const body=validateDailyCompletionEvent(JSON.parse(event.data)); if (event.lastEventId && event.lastEventId !== body.event_id) throw new Error("SSE id 与事件 ID 不匹配"); loadDated(body).catch(e=>{status.textContent=`新日期产品未确认，保留已核验名单：${e.message}`;}); } catch(e) { status.textContent=`完成事件身份未确认，保留已验证名单：${e.message}`; } });
      windowObject.addEventListener("pagehide",()=>events.close(),{once:true});
    }
    windowObject.addEventListener("pagehide", clearOriginalChart, {once:true});

  }

  const api = Object.freeze({
    EXPECTED,
    GROUP_LABELS,
    CSV_FIELDS,
    CHART_PROFILE,
    CHART_NAMESPACE,
    validateData,
    validateDatedData,
    validateDatedChart,
    validateDailyCompletionEvent,
    completionMatchesProduct,
    keepCurrentProductBinding,
    statisticsPresentation,
    D29_NUMERIC_FORMULA_SHA256,
    ORIGINAL_ENGINE_SHA256,
    validateOriginalChart,
    filterRows,
    displayGroups,
    displayPendingGroups,
    displayAnchor,
    renderRows,
    toCsv,
    validateChart,
    mount,
  });
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root && root.document && typeof root.fetch === "function") mount(root.document, root);
})(typeof globalThis !== "undefined" ? globalThis : this);
