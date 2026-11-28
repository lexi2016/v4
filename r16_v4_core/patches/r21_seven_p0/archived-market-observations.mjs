const numberFormat = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 });
const datePattern = /^\d{4}-\d{2}-\d{2}$/;
const shaPattern = /^[0-9a-f]{64}$/;
const marketSeries = {
  US: [['US Nasdaq COMP', '纳斯达克综合指数'], ['US SP500', '标普 500'], ['US DJIA', '道琼斯指数']],
  JP: [['JP Nikkei 225', '日经 225']],
  KR: [['KR NAVER KOSPI', 'KOSPI'], ['KR NAVER KOSDAQ', 'KOSDAQ']],
};
const marketNames = { US: '美国', JP: '日本', KR: '韩国' };
let request = 0;
let panel;
let archiveRead;

function measuredNumber(value) {
  const number = typeof value === 'number' ? value
    : typeof value === 'string' && /^[-+]?\d+(?:,\d{3})*(?:\.\d+)?$/.test(value)
      ? Number(value.replaceAll(',', '')) : NaN;
  return Number.isFinite(number) ? number : null;
}

function httpsUrl(text) {
  try {
    const value = new URL(text);
    if (value.protocol === 'https:' && !value.username && !value.password) return value.href;
  } catch {}
  return null;
}

export function samplesForObservation(snapshot, observationDate) {
  if (!datePattern.test(observationDate) || !shaPattern.test(snapshot?.receipt_sha256 ?? '')
    || snapshot.production_allowed !== false || snapshot.buy_gate_updated !== false
    || snapshot.orders_sent !== false || !Array.isArray(snapshot.samples)) return [];
  return snapshot.samples.filter(row => row.source_status === 'DATED_CLOSE_SAMPLE'
    && row.session_date_local === observationDate && measuredNumber(row.close) > 0
    && shaPattern.test(row.source_response_sha256 ?? '') && httpsUrl(row.source_url));
}

function make(tag, content) {
  const element = document.createElement(tag);
  if (content) element.textContent = content;
  return element;
}

export async function showArchivedMarketObservations(currentCards, observationDate) {
  const version = ++request;
  panel?.remove();
  panel = null;
  if (!currentCards || !datePattern.test(observationDate ?? '')) return;
  const livePanel = panel = make('details');
  livePanel.className = 'evidence-panel';
  livePanel.id = 'archivedMarketObservations';
  livePanel.open = true;
  livePanel.dataset.observationDate = observationDate;
  livePanel.append(make('summary', '海外已核验收盘样本 · 观察日 ' + observationDate));
  currentCards.after(livePanel);
  const note = make('p', '正在核对所选观察日的同日收盘来源。');
  livePanel.append(note);
  let snapshot;
  try {
    archiveRead ??= fetch(new URL('./archived-market-observations.json', import.meta.url), { cache: 'no-cache' })
      .then(response => {
        if (!response.ok) throw new Error('ARCHIVED_OBSERVATION_SOURCE_MISSING');
        return response.json();
      }).catch(error => {
        archiveRead = null;
        throw error;
      });
    snapshot = await archiveRead;
  } catch {
    if (version === request) note.textContent = 'CANNOT_CONFIRM · 所选观察日收盘来源读取失败。';
    return;
  }
  if (version !== request) return;
  note.textContent = '只列交易日与所选观察日相同的留档收盘值。采集时间单列，历史 PIT 待核。';
  const samples = new Map(samplesForObservation(snapshot, observationDate).map(row => [row.key, row]));
  for (const [market, series] of Object.entries(marketSeries)) {
    const section = make('section');
    section.append(make('h3', marketNames[market]));
    const list = make('ul');
    for (const [key, label] of series) {
      const row = samples.get(key);
      if (!row) {
        list.append(make('li', label + ' · CANNOT_CONFIRM · 所选观察日无已核验收盘来源'));
        continue;
      }
      const change = measuredNumber(row.change_pct);
      const item = make('li', label + ' · 交易日 ' + observationDate
        + ' · 收盘 ' + numberFormat.format(measuredNumber(row.close))
        + (change === null ? ' · 涨跌幅待核' : ' · 涨跌幅 ' + numberFormat.format(change) + '%')
        + (row.observed_at_cst ? ' · 采集 ' + row.observed_at_cst : '') + ' · ');
      const source = make('a', '原始来源');
      source.href = httpsUrl(row.source_url);
      source.rel = 'noopener noreferrer';
      source.target = '_blank';
      item.append(source);
      list.append(item);
    }
    section.append(list);
    livePanel.append(section);
  }
}
