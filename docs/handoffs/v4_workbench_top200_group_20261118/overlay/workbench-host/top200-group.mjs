const symbolPattern = /^\d{6}\.(SH|SZ|BJ)$/;
const finite = value => typeof value === 'number' && Number.isFinite(value);

export function isTop200ForSelection(result, selectedDate) {
  return typeof selectedDate === 'string' && result?.source_date === selectedDate;
}

export function validateTop200Payload(value, sourceDate) {
  const fail = reason => ({ status: 'CANNOT_CONFIRM', source_date: sourceDate, rows: [], count: 0, reason });
  if (!/^\d{4}-\d{2}-\d{2}$/.test(sourceDate ?? '')) return fail('请求日期格式无效');
  if (value?.source_date === sourceDate && value.status === 'CANNOT_CONFIRM_NOT_MATERIALIZED' &&
      Array.isArray(value.top200) && value.top200.length === 0 && value.RESEARCH_ONLY === true &&
      value.production_allowed === false && value.buy_gate_updated === false && value.orders_sent === false) {
    return { status: 'EMPTY', source_date: sourceDate, rows: [], count: 0, reason: '本日 Top200 尚未物化' };
  }
  if (!value || value.data_date !== sourceDate.replaceAll('-', '')) return fail('返回数据日期与当前日期不一致');
  if (value.RESEARCH_ONLY !== true || value.production_allowed !== false ||
      value.buy_gate_updated !== false || value.orders_sent !== false) {
    return fail('研究边界标记不完整');
  }
  if (!Array.isArray(value.top200) || !Number.isInteger(value.top200_count) ||
      value.top200_count !== value.top200.length || value.top200.length > 200) {
    return fail('Top200 行数或计数不一致');
  }
  if (value.top200.length === 0) return { status: 'EMPTY', source_date: sourceDate, rows: [], count: 0, reason: '本日 Top200 尚未物化' };
  const symbols = new Set();
  for (const [index, row] of value.top200.entries()) {
    if (!row || row.rank !== index + 1 || row.source_date !== sourceDate ||
        !symbolPattern.test(row.symbol ?? '') || symbols.has(row.symbol) ||
        typeof row.name !== 'string' || !row.name.trim() || !finite(row.close) || row.close <= 0 ||
        !finite(row.change_pct) || !finite(row.amount_cny) || row.amount_cny < 0) {
      return fail(`第 ${index + 1} 行身份、排名或行情字段待核`);
    }
    symbols.add(row.symbol);
  }
  return {
    status: value.top200.length === 200 ? 'READY' : 'PARTIAL',
    source_date: sourceDate,
    rows: value.top200,
    count: value.top200.length,
    reason: value.top200.length === 200 ? '' : `仅返回 ${value.top200.length}/200 行`,
  };
}
