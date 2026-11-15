const unsafeFlags = ['production_allowed', 'buy_gate_updated', 'orders_sent'];
const priceFields = ['open', 'high', 'low', 'close'];
const isoDate = date => `${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6)}`;

export function validateDailyChart(chart, day, symbol) {
  const rows = chart?.rows;
  const sourceDate = day.source_date.replaceAll('-', '');
  if (chart?.schema !== 'V4_WORKBENCH_DAILY_K_V1' || chart.symbol !== symbol || chart.source_date !== day.source_date ||
      chart.generation !== day.generation || chart.input_sha256 !== day.input_sha256 ||
      chart.numeric_manifest?.sha256 !== day.numeric_manifest?.sha256 || chart.numeric_manifest?.path !== day.numeric_manifest?.path ||
      chart.selector?.sha256 !== day.source_selector_sha256 || chart.selector?.path !== day.source_close_reference?.selector?.path ||
      chart.snapshot?.sha256 !== day.source_close_reference?.snapshot?.sha256 || chart.snapshot?.path !== day.source_close_reference?.snapshot?.path ||
      chart.formula_group_sha256 !== day.formula_groups.artifact.sha256 || chart.price_basis !== `QFQ_ASOF_${sourceDate}` ||
      chart.volume_basis !== 'QFQ_EVENT_VOLUME' || chart.historical_PIT !== false || chart.RESEARCH_ONLY !== true || unsafeFlags.some(key => chart[key] !== false) ||
      !Array.isArray(rows) || !rows.length || rows.length > 120 || rows.at(-1)?.trade_date !== sourceDate || rows.some((row, index) =>
        !/^\d{8}$/.test(row.trade_date) || (index && row.trade_date <= rows[index-1].trade_date) ||
        !priceFields.every(key => Number.isFinite(row[key])) || !Number.isFinite(row.volume) || row.volume < 0 ||
        row.low > Math.min(row.open, row.close) || row.high < Math.max(row.open, row.close))) {
    throw Error('日K来源身份或行情字段不一致');
  }
  return chart;
}

export function renderDailyChart(host, chart) {
  const make = (tag, label) => Object.assign(document.createElement(tag), {textContent: label});
  const toolbar = make('div', '');
  toolbar.className = 'chart-toolbar';
  const buttons = [60, 120].map(count => {
    const button = make('button', `近${count}根`);
    button.type = 'button';
    toolbar.append(button);
    return button;
  });
  const dateSelect = make('select', '');
  dateSelect.setAttribute('aria-label', '定位日K交易日');
  toolbar.append(dateSelect);
  for (const row of chart.rows) dateSelect.add(new Option(isoDate(row.trade_date), row.trade_date));
  const canvas = make('canvas', '前复权日K和成交量');
  canvas.style.cssText = 'display:block;width:100%;height:340px';
  canvas.setAttribute('aria-label', `${chart.symbol} 前复权日K和成交量，数据截至 ${chart.source_date}`);
  canvas.setAttribute('role', 'img');
  const readout = make('p', '');
  readout.className = 'readout';
  host.replaceChildren(toolbar, canvas, readout);
  Object.assign(host.dataset, {symbol: chart.symbol, sourceDate: chart.source_date, rowCount: String(chart.rows.length)});
  let windowSize = 120;
  let end = chart.rows.length;
  let selected = end - 1;
  let xOffset = 4;
  let step = 0;

  function draw() {
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    const ctx = canvas.getContext('2d');
    ctx.scale(ratio, ratio);
    ctx.font = '11px system-ui';
    const visible = chart.rows.slice(Math.max(0, end-windowSize), end);
    const low = Math.min(...visible.map(row => row.low));
    const high = Math.max(...visible.map(row => row.high));
    const delta = high !== low ? (high-low)*0.04 : Math.max(Math.abs(high)*0.04, 0.01);
    const volumeTop = height*0.74, bottom = height-24;
    const maxVolume = Math.max(1, ...visible.map(row => row.volume));
    const plotWidth = Math.max(1, width-61);
    step = plotWidth/visible.length;
    const y = price => 10 + (high+delta-price)/(high-low+delta*2)*(volumeTop-25);
    const line = (x1,y1,x2,y2) => { ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke(); };
    for (let tick=0; tick<=4; tick++) {
      const value = low+(high-low)*tick/4;
      ctx.fillStyle = '#9eb3cd'; ctx.strokeStyle = '#31485f';
      line(xOffset,y(value),plotWidth+xOffset,y(value));
      ctx.fillText(value.toFixed(2),plotWidth+xOffset+4,y(value)+4);
    }
    ctx.fillStyle = '#9eb3cd'; ctx.fillText('成交量',plotWidth+xOffset+4,volumeTop+12);
    visible.forEach((row,index) => {
      const x = xOffset+(index+0.5)*step;
      const colour = row.close >= row.open ? '#eb656b' : '#48af8b';
      const body = Math.max(1, step*0.65);
      ctx.strokeStyle = colour; ctx.fillStyle = colour;
      line(x,y(row.high),x,y(row.low));
      ctx.fillRect(x-body/2,y(Math.max(row.open,row.close)),body,Math.max(1,Math.abs(y(row.open)-y(row.close))));
      ctx.globalAlpha = 0.65;
      const volumeHeight = row.volume/maxVolume*(bottom-volumeTop);
      ctx.fillRect(x-body/2,bottom-volumeHeight,body,volumeHeight);
      ctx.globalAlpha = 1;
      if (row === chart.rows[selected]) { ctx.strokeStyle = '#bfd3e8'; line(x,9,x,bottom); }
      if (index === 0 || index === visible.length-1) {
        ctx.fillStyle = '#9eb3cd';
        ctx.textAlign = index === 0 ? 'left' : 'right';
        ctx.fillText(isoDate(row.trade_date),index === 0 ? xOffset : plotWidth+xOffset,height-7);
        ctx.textAlign = 'left';
      }
    });
    const bar = chart.rows[selected];
    dateSelect.value = bar.trade_date;
    readout.textContent = `${chart.symbol} · ${isoDate(bar.trade_date)} · 开 ${bar.open.toFixed(2)} / 高 ${bar.high.toFixed(2)} / 低 ${bar.low.toFixed(2)} / 收 ${bar.close.toFixed(2)} · 成交量 ${bar.volume.toLocaleString('zh-CN',{maximumFractionDigits:3})}`;
  }

  buttons.forEach((button,index) => {
    button.onclick = () => { windowSize = index === 0 ? 60 : 120; draw(); };
  });
  dateSelect.onchange = () => {
    selected = chart.rows.findIndex(row => row.trade_date === dateSelect.value);
    end = selected+1;
    draw();
  };
  canvas.onpointermove = event => {
    if (!step) return;
    const start = Math.max(0,end-windowSize);
    const index = Math.max(start, Math.min(end-1,start+Math.floor((event.offsetX-xOffset)/step)));
    if (index !== selected) { selected = index; draw(); }
  };
  const watch = new ResizeObserver(draw);
  watch.observe(canvas);
  draw();
  return () => { watch.disconnect(); host.replaceChildren(); delete host.dataset.symbol; };
}
