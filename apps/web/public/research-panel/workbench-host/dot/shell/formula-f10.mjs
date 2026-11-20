const safetyFlags = ['production_allowed', 'buy_gate_updated', 'orders_sent'];
const digest = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const boundRef = value => typeof value?.path === 'string' && value.path.length > 0 && digest(value.sha256);
const shanghai = new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai', year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hourCycle:'h23'});
const text = value => typeof value === 'string' && value.trim() ? value.trim() : null;
const iso = value => typeof value === 'string' && /^\d{8}$/.test(value) ? `${value.slice(0,4)}-${value.slice(4,6)}-${value.slice(6)}` : text(value);
const number = value => typeof value === 'number' && Number.isFinite(value) ? value : null;

export function isFormulaF10Completion(day, event) {
  return Boolean(day?.formula_groups && event?.schema === 'V4_WORKBENCH_VERSIONS_V1' &&
    event.source_date === day.source_date && event.observation_date === day.observation_date &&
    event.generation === day.generation && event.input_sha256 === day.input_sha256 &&
    boundRef(day.numeric_manifest) && event.numeric_manifest?.path === day.numeric_manifest.path &&
    event.numeric_manifest?.sha256 === day.numeric_manifest.sha256 && digest(event.modules?.f10) &&
    event.RESEARCH_ONLY === true && safetyFlags.every(key => event[key] === false));
}

export function validateFormulaF10(value, day, symbol) {
  if (!['OBSERVED', 'CANNOT_CONFIRM_SOURCE_GAP', 'NOT_MATERIALIZED'].includes(value?.status) ||
      value.symbol !== symbol || value.data_date !== day.source_date.replaceAll('-', '') ||
      value.source_generation !== day.generation || value.input_sha256 !== day.input_sha256 ||
      value.historical_PIT !== false || value.RESEARCH_ONLY !== true || safetyFlags.some(key => value[key] !== false) ||
      (value.status !== 'NOT_MATERIALIZED' && !boundRef(value.receipt)) ||
      (value.status === 'OBSERVED' && (!boundRef(value.stock_ref) || !digest(value.f10?.source_text_sha256)))) {
    throw Error('FORMULA_F10_IDENTITY_CONFLICT');
  }
  return value;
}

export function validateFormulaCompanyResearch(value, day, symbol) {
  const received = value?.received_materials;
  const scope = received?.formula_group_scope;
  const membership = received?.formula_group_membership;
  const sameRef = (left, right) => boundRef(left) && boundRef(right) &&
    left.path === right.path && left.sha256 === right.sha256;
  const sourceDate = day.source_date.replaceAll('-', '');
  const observationDate = day.observation_date.replaceAll('-', '');
  const rosterSha = day.formula_groups?.artifact?.sha256;
  const expectedCount = Array.isArray(day.rows) ? day.rows.length : day.scope_count;
  if (value?.schema !== 'V4_RECEIVED_COMPANY_VIEW_V1' || value.symbol !== symbol ||
      value.source_date !== day.source_date || value.observation_date !== day.observation_date ||
      value.generation !== day.generation || value.input_sha256 !== day.input_sha256 ||
      !sameRef(value.numeric_manifest, day.numeric_manifest) ||
      value.company_scope_status !== 'FORMULA_ROSTER_EXACT_MATCH' || !digest(rosterSha) ||
      value.formula_roster_sha256 !== rosterSha ||
      value.RESEARCH_ONLY !== true || safetyFlags.some(key => value[key] !== false) ||
      received?.symbol !== symbol || received.data_date !== sourceDate ||
      received.source_generation !== day.generation || received.input_sha256 !== day.input_sha256 ||
      !sameRef(received.numeric_manifest, day.numeric_manifest) ||
      received.RESEARCH_ONLY !== true || safetyFlags.some(key => received[key] !== false) ||
      scope?.schema !== 'V4_FORMULA_GROUP_SCOPED_IMPORT_V1' || scope.source_date !== sourceDate ||
      scope.observation_date !== observationDate || scope.source_generation !== day.generation ||
      scope.input_sha256 !== day.input_sha256 || !sameRef(scope.numeric_manifest, day.numeric_manifest) ||
      scope.roster_sha256 !== value.formula_roster_sha256 || !Number.isInteger(expectedCount) ||
      scope.candidate_count !== expectedCount ||
      membership?.symbol !== symbol || membership.source_date !== sourceDate ||
      membership.observation_date !== observationDate ||
      membership.roster_sha256 !== value.formula_roster_sha256 || !boundRef(membership.owner_row_ref)) {
    throw Error('FORMULA_COMPANY_RESEARCH_IDENTITY_CONFLICT');
  }
  return value;
}

export function formulaCompanyResearchCardContent(company, f10Status) {
  const received = company.received_materials;
  const fundamentals = received.received_fundamentals ?? {};
  const business = received.business_reported ?? {};
  const value = text(business.value);
  const packageId = text(received.received_batch_summary?.package_id) ?? '批次身份待核';
  const scopeLabel = company.company_scope_status;
  const f10Label = f10Status === 'NOT_MATERIALIZED' ? '本日 F10 尚未物化' :
    f10Status === 'CANNOT_CONFIRM_SOURCE_GAP' ? '本日 F10 已回执，本股快照缺失' :
      f10Status === 'ERROR' ? '本日 F10 读取待核' : '本日 F10 正在读取';
  const reportPeriod = text(fundamentals.latest_financial_period) ??
    text(received.financials_reported?.latest_report_period);
  const hasReportedValues = fields => Object.entries(fields ?? {}).some(([key, item]) =>
    key !== 'latest_report_period' && item !== null && item !== undefined &&
    typeof item !== 'object' && text(String(item)) !== null);
  const hasFinancialValues = hasReportedValues(received.financials_reported);
  const hasShareholderValues = hasReportedValues(received.shareholders_reported);
  return {
    company: [
      `研究回传主营：${value ?? '本股未提供可展示主营描述'}`,
      `研究资料状态：${text(fundamentals.status) ?? '待核'} · ${text(fundamentals.evidence_status) ?? '证据状态待核'}`,
      `来源批次：${packageId} · D ${company.source_date} · O ${company.observation_date}`,
      `名单绑定：${scopeLabel} · ${received.formula_group_scope.candidate_count} 只研究范围`,
      `${f10Label} · 历史 PIT 未认证。`,
    ],
    financial: [
      `研究回传财务状态：${text(fundamentals.status) ?? '待核'}${reportPeriod ? ` · 报告期 ${reportPeriod}` : ''}`,
      `财务字段：${hasFinancialValues ? '有回传值，逐字段状态见进一步研究回传' : '未提供可确认数值，待核'}`,
      `股东字段：${hasShareholderValues ? '有回传值，逐字段状态见进一步研究回传' : '未提供可确认数值，待核'}`,
      `${f10Label}。`,
      `资料来源 ${Object.keys(received.source_refs ?? {}).length} 类文件绑定；仅供研究。`,
    ],
  };
}

export function formulaF10CardContent(f10) {
  const captured = Date.parse(f10.captured_at);
  const updated = iso(f10.source_updated_date);
  const captureLabel = Number.isFinite(captured) ? `${shanghai.format(captured).replaceAll('/', '-')} 上海` : '待核';
  const concepts = (Array.isArray(f10.concepts) ? f10.concepts : []).map(item => text(item?.name)).filter(Boolean);
  const industryCode = number(f10.industry?.tdx_finance_industry_code);
  const industryName = text(f10.industry?.name);
  const industry = industryName ?? (industryCode !== null ? `通达信行业代码 ${industryCode} · 名称未映射` : '行业待核');
  const detail = f10.source_detail ?? {};
  const finance = f10.financials ?? {};
  const holders = number(finance.holder_count);
  const holderDate = iso(detail.shareholder_record_date);
  return {
    company: [
      `主营业务：${text(detail.main_business) ?? 'F10 快照未提供可确认描述'}`,
      `行业：${industry}`,
      `F10 概念：${f10.concept_status === 'OBSERVED' && concepts.length ? `${concepts.length} 项 · ${concepts.join('、')}` : '待核'}`,
      `通达信 F10 · 采集 ${captureLabel} · F10 更新 ${updated ?? '待核'}`,
      '历史 PIT 未认证。',
    ],
    financial: [
      `报告期 ${iso(finance.report_period) ?? '待核'} · 财务数据更新 ${iso(f10.finance_updated_date) ?? '待核'}`,
      `营业总收入：${text(finance.revenue_text) ?? '待核'}`,
      `净利润：${text(finance.net_profit_text) ?? '待核'}`,
      `股东人数：${holders !== null ? holders.toLocaleString('zh-CN') : '待核'} · 统计日 ${holderDate ?? '待核'}`,
      `每股收益（元）：${number(finance.eps) ?? '待核'} · 每股净资产（元）：${number(finance.bps) ?? '待核'} · 净资产收益率：${number(finance.roe_pct) !== null ? `${finance.roe_pct}%` : '待核'}`,
    ],
  };
}

export function createFormulaF10Cards(document, load) {
  const legacy = ['companySummary','companyMetrics'].map(id => document.getElementById(id));
  let slots, received, receivedBody, inFlight, verified, notice, currentDay, currentSymbol;
  let f10Value, researchValue, f10Status;
  let enabled = false;

  function cancel() {
    inFlight?.abort();
    inFlight = null;
    verified = null;
    notice = null;
    f10Value = null;
    researchValue = null;
    f10Status = null;
    slots?.forEach(slot => {slot.replaceChildren(); slot.removeAttribute('data-company-symbol');});
  }

  function render(symbol) {
    if (f10Value?.status === 'OBSERVED') {
      const content = formulaF10CardContent(f10Value.f10);
      paint(symbol, content.company, content.financial);
    } else if (researchValue) {
      const content = formulaCompanyResearchCardContent(researchValue, f10Status);
      paint(symbol, content.company, content.financial);
    } else if (f10Status) {
      const gap = f10Status === 'CANNOT_CONFIRM_SOURCE_GAP' ? '当日 F10 有采集回执，本股缺少可用快照' :
        f10Status === 'NOT_MATERIALIZED' ? '当日 F10 尚未物化' :
          f10Status === 'ERROR' ? 'F10 来源读取或校验失败' : '正在读取 F10';
      paint(symbol, [`${symbol} · ${gap} · 待核`], [`${symbol} · 本日 F10 财务与股东资料待核`]);
    }
  }

  function configure(nextEnabled) {
    if (nextEnabled === enabled) return;
    enabled = nextEnabled;
    if (!slots) {
      slots = legacy.map(old => {
        const card = document.createElement('div');
        card.id = old.id === 'companySummary' ? 'formulaCompanySummary' : 'formulaCompanyMetrics';
        card.setAttribute('aria-live', 'polite');
        old.after(card);
        return card;
      });
      received = document.createElement('details');
      received.className = 'evidence-panel';
      const summary = document.createElement('summary');
      summary.textContent = '进一步研究回传';
      receivedBody = document.createElement('div');
      receivedBody.className = 'summary-grid';
      received.append(summary, receivedBody);
      document.getElementById('companyEvidence').closest('details').before(received);
    }
    if (enabled) receivedBody.append(...legacy);
    else {
      cancel();
      slots.forEach((slot, index) => slot.before(legacy[index]));
    }
    received.hidden = !enabled;
    slots.forEach(slot => {slot.hidden = !enabled;});
  }

  function paint(symbol, company, financial) {
    slots.forEach((slot, index) => {
      slot.dataset.companySymbol = symbol;
      const lines = index === 0 ? company : financial;
      slot.replaceChildren(...lines.map(label => {
        const p = document.createElement('p');
        p.textContent = label;
        return p;
      }));
    });
  }

  async function show(day, symbol, url, refresh=false) {
    const identity = JSON.stringify([symbol, day.source_date, day.observation_date, day.generation,
      day.input_sha256, day.numeric_manifest?.path, day.numeric_manifest?.sha256]);
    const retain = refresh && verified === identity;
    if (retain) inFlight?.abort();
    else cancel();
    currentDay = day;
    currentSymbol = symbol;
    f10Status = 'LOADING';
    const controller = new AbortController();
    inFlight = controller;
    if (!retain) paint(symbol, [`${symbol} · 正在读取 F10 公司资料…`], [`${symbol} · 正在读取 F10 财务与股东资料…`]);
    try {
      const value = await load(url, controller.signal);
      if (inFlight !== controller) return;
      const accepted = validateFormulaF10(value, day, symbol);
      if (accepted.status === 'OBSERVED') {
        f10Value = accepted;
      } else {
        f10Value = accepted;
      }
      f10Status = accepted.status;
      render(symbol);
      verified = identity;
      notice = null;
    } catch {
      if (inFlight !== controller) return;
      if (retain) {
        if (!notice) {
          notice = document.createElement('p');
          notice.setAttribute('role', 'status');
          notice.textContent = 'F10 更新待核 · 保留本股上次已校验资料';
          slots[0].append(notice);
        }
      } else {
        f10Status = 'ERROR';
        render(symbol);
      }
    }
  }

  function showResearch(day, symbol, value) {
    if (currentSymbol !== symbol || !currentDay ||
        currentDay.source_date !== day.source_date || currentDay.observation_date !== day.observation_date ||
        currentDay.generation !== day.generation || currentDay.input_sha256 !== day.input_sha256) return;
    try {
      researchValue = validateFormulaCompanyResearch(value, day, symbol);
      render(symbol);
    } catch {
      researchValue = null;
      render(symbol);
    }
  }

  return {configure, cancel, show, showResearch, refresh:(day,symbol,url)=>show(day,symbol,url,true)};
}
