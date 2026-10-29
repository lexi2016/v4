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
    const coverage = row?.historical_coverage || {};
    const evaluatedDates = Array.isArray(coverage.evaluated_dates) ? coverage.evaluated_dates : [];
    const evaluatedCount = Number.isSafeInteger(coverage.evaluated_count) ? coverage.evaluated_count : evaluatedDates.length;
    const missing = Array.isArray(coverage.missing) ? coverage.missing.filter(value => typeof value === "string") : [];
    const historyState = coverage.known_full_history === true ? "全历史事件标签完整" : "全历史事件标签覆盖不完整";
    const dateSummary = evaluatedDates.length
      ? evaluatedDates.map(displayDay).join("、")
      : "日期未提供";
    const coverageSummary = coverage.evaluated_count === undefined && !evaluatedDates.length
      ? "同条件历史标签覆盖：未绑定；未启动全历史回算。"
      : `同条件事件标签已评估 ${evaluatedCount} 个日期（${dateSummary}）；${historyState}${missing.length ? `，缺项 ${missing.join("、")}` : ""}；未启动全历史回算。${coverage.historical_PIT === false ? "历史非PIT。" : ""}`;

    const stats = row?.statistics;
    const expectedAsOf = metadata?.data_date ? displayDay(metadata.data_date) : "";
    const statsBound = stats && stats.asof === expectedAsOf
      && ["DESCRIPTIVE_STATS_COMPUTED", "NO_EVENT_GROUPS"].includes(stats.status);
    const priceLines = [];
    if (!statsBound) {
      priceLines.push("价格分位：未绑定当前日期产品；没有触发历史重算。");
    } else {
      const prices = stats.price_distribution || {};
      for (const [label, key] of [["近250个有效收盘", "near_250"], ["全部有效历史", "all_history"]]) {
        const value = prices[key] || {};
        const percentile = Number.isFinite(value.percentile_le) ? `${(value.percentile_le * 100).toFixed(2)}%` : "未知";
        const count = Number.isSafeInteger(value.n) ? value.n : "未知";
        priceLines.push(`${label}价格分位：${percentile}；n=${count}；范围 ${displayDay(value.start_date)}—${displayDay(value.end_date)}。`);
      }
    }

    const groups = [];
    if (statsBound && Array.isArray(stats.groups)) {
      for (const group of stats.groups) {
        const identity = group?.source_identity;
        const bound = group?.identity_status === "BOUND"
          && identity?.generation === metadata?.source_generation
          && identity?.input === metadata?.source_identity?.input_sha256
          && identity?.formula === D29_NUMERIC_FORMULA_SHA256
          && identity?.asof === expectedAsOf
          && identity?.market === String(symbol || "").slice(-2)
          && identity?.basis === "QFQ_ASOF"
          && identity?.pit_status === "NONPIT"
          && identity?.rule_sha256 === group?.rule_sha256;
        const label = GROUP_LABELS[group?.group_id] || String(group?.group_id || "未知组");
        if (!bound) {
          groups.push({ label, bound: false, summary: `${label}：同条件收益身份未绑定当前名单代次，保留未知。`, horizons: [] });
          continue;
        }
        const eligible = Number.isSafeInteger(group.eligible_event_count) ? group.eligible_event_count : "未知";
        const unknown = coverage.unknown_by_group?.[group.group_id] ?? "未知";
        const horizons = Object.entries(group.horizons || {}).map(([key, value]) => {
          const total = Number.isSafeInteger(value?.total) ? value.total : "未知";
          const valid = Number.isSafeInteger(value?.valid) ? value.valid : "未知";
          const mean = Number.isFinite(value?.mean_return_pct) ? `${value.mean_return_pct.toFixed(2)}%` : "未知";
          const median = Number.isFinite(value?.median_return_pct) ? `${value.median_return_pct.toFixed(2)}%` : "未知";
          return {
            label: String(key).toUpperCase(),
            summary: `${String(key).toUpperCase()}：有效 ${valid}/${total}，正/负/平 ${value?.positive ?? "未知"}/${value?.negative ?? "未知"}/${value?.flat ?? "未知"}，未成熟 ${value?.not_matured ?? "未知"}，缺价 ${value?.missing_price ?? "未知"}；均值 ${mean}，中位 ${median}。`,
            cases: Array.isArray(value?.cases) ? value.cases.slice(0, 20) : [],
          };
        });
        groups.push({ label, bound: true, summary: `${label}：同条件历史事件 ${eligible}；未评估/未知条件日 ${unknown}。`, horizons });
      }
    } else if (statsBound) {
      groups.push({ label: "事件覆盖", bound: false, summary: "同条件历史收益组未提供；保留未知。", horizons: [] });
    } else {
      groups.push({ label: "事件覆盖", bound: false, summary: "同条件历史收益：未绑定当前日期产品；未触发历史重算。", horizons: [] });
    }
    return { coverageSummary, priceLines, groups };
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
      const token = ++chartRequest;
      chartController?.abort();
      chartController = new AbortController();
      setChartControlsDisabled(true);
      windowObject.Numeric283Chart?.clear();
      chartPanel.hidden = false;
      chartTitle.textContent = `${symbol} · ${name}`;
      chartStatus.textContent = `正在读取 ${symbol} 的 D${payloadMetadata.data_date} 历史；旧图已清空。`;
      chartPanel.scrollIntoView?.({ behavior: "smooth", block: "start" });
      if (!payloadMetadata.rows?.some((row) => row.symbol === symbol)) {
        chartStatus.textContent = "代码不在已载入的当前日期名单中，未请求历史。";
        return;
      }
      const reports = document.getElementById("relatedReports");
      if (reports) { chartPanel.appendChild(reports); reports.hidden = false; reports.dataset.identityDate = payloadMetadata.data_date; reports.dataset.generation = payloadMetadata.source_generation; windowObject.RelatedReports?.select(symbol,name); }
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
      count.textContent = `${filtered.length}只 / ${rows.length}只；组别可重叠。`;
      status.textContent = "当前日期产品已载入。研究用途；尚未进行本卡图形复核。";
    }

    function showStatistics(symbol, token) {
      const host = document.getElementById("dailyEventStatistics");
      if (!host) return;
      host.textContent = "正在读取同股同代统计…";
      windowObject.fetch(`/api/v4/research/a-share/daily-product?date=${payloadMetadata.data_date}&symbol=${encodeURIComponent(symbol)}`, {cache:"no-store"})
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }).then(answer => {
        const row = answer.row && {...answer.row, source_generation:answer.source_generation, data_date:answer.data_date};
        if (!row) throw new Error("同股统计未产出");
        if (token !== chartRequest) return;
        if (row.symbol !== symbol || row.source_generation !== payloadMetadata.source_generation || row.data_date !== payloadMetadata.data_date) throw new Error("统计身份不符");
        host.replaceChildren();
        const presentation = statisticsPresentation(row, symbol, payloadMetadata);
        appendTextLine(host, document, `${symbol} · D${displayDay(row.data_date)} · ${presentation.coverageSummary}`);
        for (const line of presentation.priceLines) appendTextLine(host, document, line);
        for (const group of presentation.groups) {
          appendTextLine(host, document, group.summary);
          for (const horizon of group.horizons) {
            const details = document.createElement("details"), summary = document.createElement("summary");
            summary.textContent = `${horizon.label} 历史事件覆盖（展开最近20项）`;
            details.appendChild(summary);
            appendTextLine(details, document, horizon.summary);
            for (const item of horizon.cases) {
              const result = Number.isFinite(item.return_pct) ? `${item.return_pct.toFixed(2)}%` : (item.status === "not_matured" ? "未成熟" : "未知");
              appendTextLine(details, document, `${displayDay(item.event_date)} → ${displayDay(item.target_date)}：${result}${item.detail_status ? `（${item.detail_status}）` : ""}`);
            }
            host.appendChild(details);
          }
        }
      }).catch(e => { if (token === chartRequest) host.textContent = `统计未确认：${e.message}`; });
    }
    function commitPayload(payload) {
      const rows = payload.schema_version === EXPECTED.schema_version ? validateData(payload) : validateDatedData(payload);
      if (payloadMetadata?.source_generation !== payload.source_generation) {
        ++chartRequest; chartController?.abort(); windowObject.Numeric283Chart?.clear(); setChartControlsDisabled(true); windowObject.RelatedReports?.clear();
        const stats = document.getElementById("dailyEventStatistics"); if(stats) stats.textContent = "新日期名单已更新；请选择当前名单股票读取统计。";
        chartStatus.textContent = "名单已更新；请主动选择当前名单股票。";
      }
      payloadMetadata = payload; currentRows = rows; download.disabled = false;
      const title = document.getElementById("dailyNumeric283Title"); if(title) title.textContent = `数值候选名单 · D${payload.data_date} · ${rows.length}只`;
      for(const option of groupSelect.options) option.textContent = option.value === "all" ? `全部（${rows.length}）` : `${GROUP_LABELS[option.value]}（${payload.group_counts[option.value]}）`;
      refresh(rows);
      status.textContent = `D${payload.data_date} · ${payload.status || "日期产品"} · 已处理 ${payload.processed_count ?? rows.length}/${payload.source_universe_count ?? rows.length} · 未知股票 ${payload.unknown_count ?? "未知"}；组别可重叠。`;
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
    statisticsPresentation,
    D29_NUMERIC_FORMULA_SHA256,
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
