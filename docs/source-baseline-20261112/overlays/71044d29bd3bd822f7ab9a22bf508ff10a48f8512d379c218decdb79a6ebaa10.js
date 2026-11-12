'use strict';
// Read-only adapter consumer. No collection, timer, ranking, or trade actions.
(() => {
  const section = document.getElementById('openingObservation');
  if (!section) return;
  const stageIds = ['STAGE_0925', 'STAGE_0930_0935', 'STAGE_0935_0940'];
  let sequence = 0, controller = null, current = null;
  const shown = value => value === null || value === undefined || value === '' ? 'UNKNOWN' : String(value);
  const add = (parent, tag, text) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; parent.appendChild(node); return node; };
  const validDay = value => { if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false; const date = new Date(value + 'T00:00:00Z'); return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value; };
  const validSymbol = value => /^(\d{6}\.(SH|SZ|BJ)|\d{5}\.HK)$/.test(String(value));
  function abort() { ++sequence; if (controller) controller.abort(); controller = null; }
  function header(context, state) {
    section.hidden = false; section.replaceChildren();
    add(section, 'h2', '当日开盘观察 · 只读研究');
    if (context) {
      add(section, 'p', `${context.name || ''} ${context.symbol} · 观察日：${context.tradeDate} · 候选源日：${shown(context.candidateSourceDate)} · 图源日：${shown(context.chartSourceDate)} · 修订：${shown(context.revision)}`);
      if (!context.candidateSourceDate) add(section, 'p', '候选源日未唯一提供：' + shown(context.candidateSourceDateReason) + '；不从图源日或上一自然日推定。');
      if (context.candidateSourceClaims?.length) evidence(section, '候选源日各来源声明（保留冲突）', context.candidateSourceClaims);
      add(section, 'p', `所选日清单：${shown(context.candidateCount)} 个身份；本股原归属：${context.sources.map(source => `${source.title || source.id} (${source.id})`).join(' / ') || 'UNKNOWN'}。页面候选身份与阶段输入池尚未核实为同一池。`);
      const refresh = add(section, 'button', '重新读取已生成结果'); refresh.type = 'button'; refresh.onclick = () => { if (current) select(current); };
    }
    const status = add(section, 'p', state); status.setAttribute('aria-live', 'polite');
    add(section, 'p', '行情时刻、采集/可得时间和覆盖范围以各阶段来源为准。迟补、UNKNOWN、失败与事后复盘不能视为实时认证。当前研报查询是当前知识补充，不能冒充历史阶段截止前已知信息。');
    return status;
  }
  function clear(message = '等待选择股票。') { abort(); current = null; header(null, message); }
  function validate(data, context) {
    if (!data || data.schema_version !== 'research.opening_observation.v1' || data.trade_date !== context.tradeDate || data.symbol !== context.symbol || data.market !== (context.symbol.endsWith('.HK') ? 'HK_CONNECT' : 'A_SHARE') || data.candidate_context?.source_date !== context.candidateSourceDate || data.candidate_context?.authority !== 'CLIENT_CONTEXT_ONLY' || data.candidate_context?.stage_input_identity_verified !== false || data.write_performed !== false || data.RESEARCH_ONLY !== true || data.research_only !== true || data.production_allowed !== false || data.buy_gate_updated !== false || data.orders_sent !== false || !['AVAILABLE', 'PARTIAL', 'UNAVAILABLE'].includes(data.status) || !Array.isArray(data.stages) || data.stages.length !== stageIds.length) throw Error('开盘接口身份、日期或只读合同不一致；未显示行情。');
    data.stages.forEach((stage, index) => {
      if (!stage || stage.stage_id !== stageIds[index] || !['AVAILABLE', 'MISSING', 'FAILED', 'UNCONFIGURED', 'NOT_DUE'].includes(stage.availability) || !Array.isArray(stage.rows) || !Array.isArray(stage.missing_reasons) || !stage.metrics || stage.rows.some(row => row.symbol !== context.symbol)) throw Error('阶段或行证券身份合同不一致；未显示行情。');
      for (const key of ['price', 'previous_close', 'change_pct', 'volume', 'turnover']) if (stage.metrics[key] !== null && (typeof stage.metrics[key] !== 'number' || !Number.isFinite(stage.metrics[key]))) throw Error('阶段数值合同不一致；未显示行情。');
      if (!['REALTIME_OBSERVATION', 'RETROSPECTIVE', 'UNCONFIRMED', 'UNAVAILABLE'].includes(stage.observation_mode) || !['TIMELY', 'LATE', 'UNSAFE', 'UNKNOWN', 'UNAVAILABLE'].includes(stage.temporal_state)) throw Error('阶段时点合同不一致；未显示行情。');
    });
  }
  function evidence(parent, title, value) { const box = add(parent, 'details'); add(box, 'summary', title); add(box, 'pre', JSON.stringify(value, null, 2)); }
  function poolSummary(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return 'UNKNOWN';
    const fields = [], evidenceCounts = [];
    function visit(object, prefix = '', depth = 0) {
      if (!object || typeof object !== 'object' || Array.isArray(object) || depth > 2) return;
      for (const key of Object.keys(object).slice(0, 32)) {
        const item = object[key], path = prefix ? `${prefix}.${key}` : key;
        if ((key === 'source_evidence' || key === 'cannot_confirm') && Array.isArray(item)) {
          if (evidenceCounts.length < 4) evidenceCounts.push(`${path}=${item.length}项`);
        } else if (/(pool|revision|signal_date|source_date)/i.test(key) &&
          ['string', 'number', 'boolean'].includes(typeof item)) {
          if (fields.length < 6) {
            const text = String(item), label = path.length > 64 ? `${path.slice(0, 61)}…` : path;
            fields.push(`${label}=${text.length > 96 ? `${text.slice(0, 93)}…` : text}`);
          }
        } else if (item && typeof item === 'object' && !Array.isArray(item) && depth < 2) {
          visit(item, path, depth + 1);
        }
      }
    }
    visit(value);
    const summary = [...fields, ...evidenceCounts];
    return `${summary.length ? summary.join(' · ') : '元数据已提供'}；完整来源证据见下方展开`;
  }
  function render(data, context) {
    header(context, `接口状态：${data.status} · 本次只读生成时间：${shown(data.generated_at)}（不是行情可得时间）`);
    for (const stage of data.stages) {
      const card = add(section, 'article'); card.className = 'opening-stage';
      add(card, 'h3', `${stage.stage_id} · ${shown(stage.window)} · 截止 ${shown(stage.cutoff_at)}`);
      if (stage.scheduled_cutoff_at && stage.scheduled_cutoff_at !== stage.cutoff_at) add(card, 'p', `本市场观察截止 ${stage.cutoff_at}；V4 调度截止 ${stage.scheduled_cutoff_at}，调度时间不延长可用行情窗口。`);
      add(card, 'p', `可用性：${stage.availability} · 来源状态：${shown(stage.source_status)} · 观察模式：${stage.observation_mode} · 时点状态：${stage.temporal_state}`);
      if (stage.missing_reasons.length) add(card, 'p', '异常 / 缺失原因：' + stage.missing_reasons.join('；'));
      if (stage.availability === 'NOT_DUE') { add(card, 'p', '尚未到阶段截止时点；未展示未来阶段快照。'); continue; }
      const raw = stage.raw, metrics = stage.metrics;
      if (stage.availability === 'AVAILABLE' && raw && stage.rows.length) {
        add(card, 'p', `价格：${shown(metrics.price)} · 昨收：${shown(metrics.previous_close)}（价格单位/币种以来源为准，未提供则待核） · 相对昨收涨跌：${shown(metrics.change_pct)}${metrics.change_pct === null ? '' : '%'} · 成交量：${shown(metrics.volume)}（来源单位，未核实） · 成交额：${shown(metrics.turnover)}（来源单位/币种，未核实）`);
        add(card, 'p', `本股行情时刻：${shown(metrics.quote_time)} · 采集时间：${shown(raw.captured_at)} · 可得时间：${shown(raw.available_at)} · 本股原始行数：${stage.rows.length}`);
      } else add(card, 'p', '本阶段无可展示的本股已核验原始行情；覆盖状态以来源证据为准，不表示筛除。');
      if (raw) {
        if (raw.identity_missing_reasons?.length) add(card, 'p', `来源证券身份待核：${raw.identity_missing_reasons.join('；')}。不能确认本股覆盖，不能解释为筛除。未解析原始证券：${Array.isArray(raw.unresolved_source_symbols) ? raw.unresolved_source_symbols.join(' / ') : 'UNKNOWN'}。`);
        if (raw.timestamp_missing_reasons?.length) add(card, 'p', '采集/可得时间证据待核：' + raw.timestamp_missing_reasons.join('；') + '；全部声明保留在下方来源证据中，不升级为实时认证。');
        if (raw.coverage_missing_reasons?.length) add(card, 'p', '覆盖字段缺失原因：' + raw.coverage_missing_reasons.join('；'));
        add(card, 'p', `原始输入覆盖：${shown(raw.source_rows)} / ${shown(raw.requested_rows)}（来源行 / 请求行）；产物行数 ${shown(raw.row_count)}；覆盖比 ${shown(raw.coverage_ratio)}。仅 VERIFIED_RAW_INPUT_ONLY；数量相同不能证明与页面候选池相同。`);
        add(card, 'p', `来源 ${shown(raw.source_id)} · run_id ${shown(raw.run_id)} · 池/修订摘要：${poolSummary(raw.pool_identity)}`);
      }
      const selection = stage.selection;
      if (selection) add(card, 'p', `阶段推荐 Top10：${selection.selected_symbol_present === true ? '包含本股' : selection.selected_symbol_present === false ? '未包含本股（不表示筛除，也不表示原始行情未覆盖）' : 'UNKNOWN'}；与原始输入绑定：${shown(selection.raw_binding_matches)}。${(selection.missing_reasons || []).join('；')}`);
      else add(card, 'p', '阶段推荐 Top10：未提供可核验结果；不表示筛除。');
      add(card, 'p', `价格口径：${shown(metrics.price_basis)}；历史支撑比较：${shown(metrics.historical_support_comparison)}。同历史时段量比：UNKNOWN（${shown(metrics.historical_volume_ratio_reason)}）。不依据分钟或五档推断撤单、主力身份或真实净流入。`);
      if (metrics.missing_reasons?.length) add(card, 'p', '指标缺失原因：' + metrics.missing_reasons.join('；'));
      evidence(card, `全部本股原始行、分钟标签与来源证据（${stage.rows.length} 行；未截断）`, {raw: stage.raw, rows: stage.rows, selection: stage.selection});
    }
  }
  async function select(input) {
    abort();
    const context = {...input, candidateSourceDate: input.candidateSourceDate ?? null, sources: Array.isArray(input.sources) ? input.sources.map(source => ({...source})) : []};
    current = context; const mine = sequence;
    if (!validDay(context.tradeDate) || !validSymbol(context.symbol) || (context.candidateSourceDate !== null && (!validDay(context.candidateSourceDate) || context.candidateSourceDate >= context.tradeDate))) { current = null; header(null, '页面日期或证券身份合同不一致；未请求开盘数据。'); return; }
    header(context, '正在只读请求已生成结果；未保留上次选择的行情。');
    const query = new URLSearchParams({date: context.tradeDate, symbol: context.symbol});
    if (context.candidateSourceDate !== null) query.set('candidate_source_date', context.candidateSourceDate);
    const active = new AbortController(); controller = active;
    try {
      const result = await fetch('/api/v3/research/opening-observation?' + query.toString(), {cache: 'no-store', credentials: 'same-origin', mode: 'same-origin', redirect: 'error', signal: active.signal});
      if (mine !== sequence) return;
      if (!result.ok) throw Error(`HTTP ${result.status}；开盘只读接口未提供可用响应。`);
      const data = await result.json();
      if (mine !== sequence) return;
      validate(data, context); render(data, context);
    } catch (error) {
      if (mine !== sequence) return;
      header(context, `开盘观察读取失败：${error.message} 未显示旧行情；可手动重试。`);
    } finally { if (mine === sequence) controller = null; }
  }
  window.OpeningObservation = {select, clear};
  clear();
})();
