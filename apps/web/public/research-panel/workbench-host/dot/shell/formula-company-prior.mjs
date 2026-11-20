const safetyFlags = ['production_allowed', 'buy_gate_updated', 'orders_sent'];
const digest = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const boundRef = value => typeof value?.path === 'string' && value.path.length > 0 && digest(value.sha256);
const compactDate = value => typeof value === 'string' && /^\d{4}-?\d{2}-?\d{2}$/.test(value) ? value.replaceAll('-', '') : null;
const displayValue = value => {
  if (value === null || value === undefined) return null;
  if (typeof value !== 'object') return String(value).trim() || null;
  const selected = value.value ?? value.status ?? value.count;
  return selected === null || selected === undefined ? null : String(selected).trim() || null;
};

export function validatePriorCompanySnapshot(value, day, symbol) {
  const selected = compactDate(day?.source_date);
  const origin = compactDate(value?.source_date);
  const current = value?.current_candidate_identity ?? {};
  const material = value?.material_identity ?? {};
  const priorScope = value?.prior_formula_scope;
  const sameRef = (left, right) => boundRef(left) && boundRef(right) &&
    left.path === right.path && left.sha256 === right.sha256;
  if (value?.schema !== 'V4_FORMULA_PRIOR_COMPANY_SNAPSHOT_V1' ||
      value.status !== 'PRIOR_AVAILABLE' || value.symbol !== symbol ||
      value.selected_source_date !== day?.source_date || !selected || !origin || origin >= selected ||
      value.observation_date !== day?.observation_date ||
      current.data_date !== selected || current.source_generation !== day?.generation ||
      current.input_sha256 !== day?.input_sha256 || !sameRef(current.numeric_manifest, day?.numeric_manifest) ||
      material.data_date !== origin || !digest(material.source_generation) || !digest(material.input_sha256) ||
      !boundRef(material.numeric_manifest) || !boundRef(value.material_ref) || !boundRef(value.materials_manifest) ||
      typeof value.received_at !== 'string' || !Number.isFinite(Date.parse(value.received_at)) ||
      value.material_lifecycle?.view_mode !== 'HISTORICAL_ASOF' ||
      value.material_lifecycle?.historical_PIT_safe !== false ||
      value.RESEARCH_ONLY !== true || safetyFlags.some(key => value[key] !== false) ||
      !value.business_reported || typeof value.business_reported !== 'object' ||
      !value.financials_reported || typeof value.financials_reported !== 'object' ||
      !value.shareholders_reported || typeof value.shareholders_reported !== 'object' ||
      !Array.isArray(value.report_catalog) ||
      (priorScope !== undefined && (compactDate(priorScope.source_date) !== origin ||
        !compactDate(priorScope.observation_date) || !digest(priorScope.roster_sha256) ||
        !boundRef(priorScope.formula_group_ref) || priorScope.formula_group_ref.sha256 !== priorScope.roster_sha256 ||
        !boundRef(priorScope.owner_row_ref))) ||
      ['received_materials', 'secondary_screen', 'formula_group_scope', 'market', 'event_cases'].some(key => key in value)) {
    throw Error('FORMULA_PRIOR_COMPANY_IDENTITY_CONFLICT');
  }
  return value;
}

export function priorCompanyCardContent(prior, f10Status) {
  const business = displayValue(prior.business_reported?.value);
  const finance = prior.financials_reported ?? {};
  const shareholders = prior.shareholders_reported ?? {};
  const f10 = f10Status === 'NOT_MATERIALIZED' ? '本日 F10 尚未物化' :
    f10Status === 'CANNOT_CONFIRM_SOURCE_GAP' ? '本日 F10 已回执，本股快照缺失' : '本日 F10 待核';
  const period = displayValue(finance.latest_report_period);
  const revenue = displayValue(finance.latest_revenue);
  const netProfit = displayValue(finance.latest_net_profit_parent);
  const holderCount = displayValue(shareholders.holder_count);
  return {
    company: [
      `历史公司资料 · 原来源日 ${prior.source_date} · 本地接收 ${prior.received_at}`,
      `主营业务：${business ?? '该历史快照未提供可展示描述'}`,
      `资料引用：${prior.material_ref.sha256} · ${f10}`,
      '只显示主营、财务与股东快照；旧日二筛、行情和观察结论未带入。历史 PIT 未认证。',
    ],
    financial: [
      `历史报告期 ${period ?? '待核'} · 营收 ${revenue ?? '待核'} · 归母净利润 ${netProfit ?? '待核'}`,
      `历史股东户数 ${holderCount ?? '待核'}`,
      `原来源日 ${prior.source_date} · 本地接收 ${prior.received_at} · ${f10}`,
      '这是已收到的旧日公司快照，不代表所选日采集或当前评分。',
    ],
  };
}

export function validatePriorF10Snapshot(value, day, symbol) {
  const selected = compactDate(day?.source_date);
  const origin = compactDate(value?.source_date);
  const current = value?.current_candidate_identity ?? {};
  const material = value?.material_identity ?? {};
  if (value?.schema !== 'V4_FORMULA_PRIOR_F10_SNAPSHOT_V1' || value.status !== 'PRIOR_AVAILABLE' ||
      value.symbol !== symbol || value.selected_source_date !== day?.source_date ||
      value.selected_observation_date !== day?.observation_date || !selected || !origin || origin >= selected ||
      current.data_date !== selected || current.source_generation !== day?.generation ||
      current.input_sha256 !== day?.input_sha256 || current.numeric_manifest?.path !== day?.numeric_manifest?.path ||
      current.numeric_manifest?.sha256 !== day?.numeric_manifest?.sha256 ||
      material.data_date !== origin || !digest(material.source_generation) || !digest(material.input_sha256) ||
      !boundRef(material.numeric_manifest) || !boundRef(value.receipt) || !boundRef(value.stock_ref) ||
      value.historical_PIT !== false || value.RESEARCH_ONLY !== true ||
      safetyFlags.some(key => value[key] !== false) || !value.f10 ||
      value.f10.symbol !== symbol || value.f10.status !== 'OBSERVED' ||
      value.f10.historical_PIT !== false || safetyFlags.some(key => value.f10[key] !== false) ||
      !digest(value.f10.source_text_sha256) || typeof value.f10.captured_at !== 'string' ||
      !Number.isFinite(Date.parse(value.f10.captured_at)) ||
      [value.f10.source_updated_date, value.f10.finance_updated_date].some(date => {
        const compact = compactDate(date);
        return compact !== null && compact > selected;
      })) {
    throw Error('FORMULA_PRIOR_F10_IDENTITY_CONFLICT');
  }
  return value;
}

export function priorF10CardContent(prior, currentF10Status) {
  const f10 = prior.f10;
  const concepts = (Array.isArray(f10.concepts) ? f10.concepts : [])
    .map(item => typeof item?.name === 'string' ? item.name.trim() : '').filter(Boolean);
  const finance = f10.financials ?? {};
  const gap = currentF10Status === 'NOT_MATERIALIZED' ? '本日 F10 尚未物化' :
    currentF10Status === 'CANNOT_CONFIRM_SOURCE_GAP' ? '本日 F10 有回执，本股缺少快照' : '本日 F10 待核';
  return {
    company: [
      `历史通达信 F10 · 来源日 ${prior.source_date} · 采集 ${f10.captured_at}`,
      `主营业务：${displayValue(f10.source_detail?.main_business) ?? '旧快照未提供可确认主营描述'}`,
      `F10 更新 ${f10.source_updated_date ?? '待核'} · ${concepts.length ? concepts.join('、') : '概念待核'}`,
      `${gap}；保留原 receipt ${prior.receipt.sha256}，不代表所选日更新。历史 PIT 未认证。`,
    ],
    financial: [
      `旧 F10 报告期 ${displayValue(finance.report_period) ?? '待核'} · 财务更新 ${f10.finance_updated_date ?? '待核'}`,
      `营业总收入：${displayValue(finance.revenue_text) ?? '待核'} · 净利润：${displayValue(finance.net_profit_text) ?? '待核'}`,
      `股东人数：${displayValue(finance.holder_count) ?? '待核'} · EPS：${displayValue(finance.eps) ?? '待核'}`,
      `来源日 ${prior.source_date} · ${gap} · 历史资料，不参与当前评分。`,
    ],
  };
}
