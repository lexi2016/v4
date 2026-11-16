const safetyFlags = ['production_allowed', 'buy_gate_updated', 'orders_sent'];
const digest = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const boundRef = value => typeof value?.path === 'string' && value.path.length > 0 && digest(value.sha256);
const shanghai = new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai', year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hourCycle:'h23'});
const text = value => typeof value === 'string' && value.trim() ? value.trim() : null;
const iso = value => typeof value === 'string' && /^\d{8}$/.test(value) ? `${value.slice(0,4)}-${value.slice(4,6)}-${value.slice(6)}` : text(value);
const number = value => typeof value === 'number' && Number.isFinite(value) ? value : null;

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
  let slots, received, receivedBody, inFlight;
  let enabled = false;

  function cancel() {
    inFlight?.abort();
    inFlight = null;
    slots?.forEach(slot => {slot.replaceChildren(); slot.removeAttribute('data-company-symbol');});
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

  async function show(day, symbol, url) {
    cancel();
    const controller = new AbortController();
    inFlight = controller;
    paint(symbol, [`${symbol} · 正在读取 F10 公司资料…`], [`${symbol} · 正在读取 F10 财务与股东资料…`]);
    try {
      const value = await load(url, controller.signal);
      if (inFlight !== controller) return;
      const accepted = validateFormulaF10(value, day, symbol);
      if (accepted.status === 'OBSERVED') {
        const content = formulaF10CardContent(accepted.f10);
        paint(symbol, content.company, content.financial);
        return;
      }
      const gap = accepted.status === 'CANNOT_CONFIRM_SOURCE_GAP' ? '当日 F10 有采集回执，本股缺少可用快照' : '当日 F10 尚未物化';
      paint(symbol, [`${symbol} · ${gap} · 待核`], [`${symbol} · 本日 F10 财务与股东资料待核`]);
    } catch {
      if (inFlight === controller) {
        paint(symbol, [`${symbol} · F10 来源读取或校验失败 · 待核`], [`${symbol} · 本日 F10 财务与股东资料待核`]);
      }
    }
  }

  return {configure, cancel, show};
}
