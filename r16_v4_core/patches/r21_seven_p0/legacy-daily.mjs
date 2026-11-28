const el = id => document.getElementById(id);
const query = new URLSearchParams(location.search);
const requestedDates = query.getAll('date');
const sourceDate = requestedDates.length === 1 ? requestedDates[0] : '';
const symbolPattern = /^[0-9]{6}\.(SH|SZ|BJ)$/;
const shaPattern = /^[0-9a-f]{64}$/;
const safe = value => value?.RESEARCH_ONLY === true && value.production_allowed === false
  && value.buy_gate_updated === false && value.orders_sent === false;
const endpoint = '/api/v4/research/workbench/days/' + sourceDate;
let archive;
let controller;

function workbenchUrl(symbol) {
  const params = new URLSearchParams({ source_date: sourceDate, revision: archive.generation });
  if (symbol) params.set('symbol', symbol);
  return './workbench.html?' + params;
}

async function read(url, signal) {
  const response = await fetch(url, { cache: 'no-store', signal });
  if (!response.ok) throw new Error('HTTP ' + response.status);
  return response.json();
}

function sameIdentity(value, symbol) {
  return safe(value) && value.source_date === sourceDate && value.symbol === symbol
    && value.generation === archive.generation && value.input_sha256 === archive.input_sha256;
}

async function showStock() {
  controller?.abort();
  controller = new AbortController();
  const { signal } = controller;
  const symbol = el('archiveSymbol').value;
  const label = el('archiveSymbol').selectedOptions[0]?.textContent ?? symbol;
  el('archiveRecord').hidden = false;
  el('archiveName').textContent = label;
  el('archiveStockStatus').textContent = '正在读取同日单股归档。';
  el('archiveQuote').textContent = '';
  el('archiveIdentity').textContent = '数值归档清单 SHA-256 ' + archive.numeric_manifest.sha256;
  el('archiveChart').href = workbenchUrl(symbol);
  try {
    const stock = await read(endpoint + '/single-research/' + symbol + '?'
      + new URLSearchParams({ revision: archive.generation }), signal);
    if (signal.aborted) return;
    if (!sameIdentity(stock, symbol)) throw new Error('单股日期或归档身份待核');
    el('archiveStockStatus').textContent = stock.status === 'MATERIALIZED'
      ? '单股研究记录已物化 · ' + sourceDate
      : 'CANNOT_CONFIRM · 同日单股研究记录未绑定';
    const reference = archive.source_close_reference;
    const close = reference?.rows?.[symbol];
    if (reference?.source_date === sourceDate && reference.generation === archive.generation
      && reference.input_sha256 === archive.input_sha256 && reference.quote_role === 'SOURCE_DATE_CLOSE_REFERENCE'
      && safe(reference) && Number.isFinite(close?.price)) {
      el('archiveQuote').textContent = '同日收盘参考 ' + close.price + ' 元';
    }
  } catch (error) {
    if (!signal.aborted) el('archiveStockStatus').textContent = 'CANNOT_CONFIRM · ' + error.message;
  }
}

async function openArchive() {
  el('archiveDate').textContent = '收盘源日 ' + (sourceDate || '待指定');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(sourceDate)) throw new Error('需要一个明确的收盘源日');
  archive = await read(endpoint);
  if (!safe(archive) || archive.source_date !== sourceDate
    || !shaPattern.test(archive.generation ?? '') || !shaPattern.test(archive.input_sha256 ?? '')
    || !shaPattern.test(archive.numeric_manifest?.sha256 ?? '') || !Array.isArray(archive.rows)) {
    throw new Error('同日归档身份待核');
  }
  const stocks = archive.rows.filter(row => row.eligible_candidate === true && symbolPattern.test(row.symbol));
  if (!stocks.length) throw new Error('该日没有可显示的单股归档行');
  const choose = el('archiveSymbol');
  for (const row of stocks) {
    const option = document.createElement('option');
    option.value = row.symbol;
    option.textContent = row.symbol + ' · ' + (row.enriched_display_name || row.display_name || row.symbol);
    choose.append(option);
  }
  const requestedSymbol = query.get('symbol');
  if (requestedSymbol && !stocks.some(row => row.symbol === requestedSymbol)) {
    throw new Error('所选证券没有此日可核验的归档行');
  }
  if (requestedSymbol) choose.value = requestedSymbol;
  el('archiveSelection').hidden = false;
  el('archiveReturn').href = workbenchUrl('');
  el('archiveStatus').textContent = '同日公式研究归档已绑定 · ' + stocks.length + ' 只';
  choose.addEventListener('change', showStock);
  await showStock();
}

openArchive().catch(error => {
  el('archiveStatus').textContent = 'CANNOT_CONFIRM · ' + error.message + '。仅显示明确选定日期的归档。';
});
