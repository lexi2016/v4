const unsafeFlags = ['production_allowed', 'buy_gate_updated', 'orders_sent'];
const priceFields = ['open', 'high', 'low', 'close'];
const isoDate = date => `${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6)}`;
const originalFormula = 'd35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac';
const originalEngine = 'ae4243ec9582055fb6f2ee796978ad20e17f9dee7a56388063cbdbcb56ef0d1c';
const markColors = {COLORRED:'#ff7c82',COLORGREEN:'#6bd3a0',COLORYELLOW:'#fbcd2d',COLORFFFFFF:'#edf4fc',COLORFF00FF:'#e3a2ff'};
const originalLineColors = {'白线':'#FFFFFF','黄线':'#FBCD2D'};
const decimalString = value => {
  if (typeof value!=='string' || value.length>64 || !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value.trim())) return false;
  const number=Number(value);
  const mantissa=value.trim().split(/[eE]/,1)[0];
  return Number.isFinite(number) && !(number===0&&/[1-9]/.test(mantissa));
};

export function verifiedOriginalMarks(chart) {
  const marks = chart.original_marks;
  if (marks?.status !== 'READY' || marks.schema !== 'V4_WORKBENCH_ORIGINAL_D35C_MARKS_V1' ||
      marks.formula_sha256 !== originalFormula || marks.engine_sha256 !== originalEngine ||
      !/^[a-f0-9]{64}$/.test(marks.sidecar?.sha256 ?? '') ||
      ['symbol','source_date','generation','input_sha256','formula_group_sha256','price_basis','volume_basis'].some(key => marks[key] !== chart[key]) ||
      ['numeric_manifest','selector','snapshot'].some(key => marks[key]?.sha256 !== chart[key]?.sha256 || marks[key]?.path !== chart[key]?.path) ||
      !Number.isSafeInteger(marks.unresolved_conditions) || marks.unresolved_conditions < 0 || marks.unresolved_conditions > chart.rows.length*22 ||
      !Array.isArray(marks.marks) || marks.marks.length > chart.rows.length*22) return null;
  if (marks.lines !== undefined) {
    const names=Object.keys(originalLineColors);
    if (!marks.lines || typeof marks.lines!=='object' || Array.isArray(marks.lines) ||
        Object.keys(marks.lines).sort().join('/')!==names.slice().sort().join('/')) return null;
    for (const name of names) {
      const points=marks.lines[name];
      if (!Array.isArray(points) || points.length!==chart.rows.length) return null;
      for (let index=0;index<points.length;index++) {
        const point=points[index];
        if (!point || typeof point!=='object' || Array.isArray(point) ||
            Object.keys(point).sort().join('/')!=='trade_date/y' ||
            point.trade_date!==chart.rows[index].trade_date ||
            (point.y!==null&&!decimalString(point.y))) return null;
      }
    }
  }
  const dates = new Set(chart.rows.map(row=>row.trade_date));
  const seen = new Set();
  for (const mark of marks.marks) {
    if (!mark || !dates.has(mark.trade_date) || !Number.isSafeInteger(mark.id) || mark.id<1 || mark.id>22 ||
        typeof mark.y !== 'string' || !mark.y.trim() || !Number.isFinite(Number(mark.y)) ||
        typeof mark.payload !== 'string' || !Array.isArray(mark.styles)) return null;
    const icon = mark.kind==='DRAWICON' && (mark.payload==='1'||mark.payload==='2') && mark.styles.length===0;
    const text = mark.kind==='DRAWTEXT' && mark.payload.length>0 && mark.payload.length<=24 && mark.styles.length===1 && Object.hasOwn(markColors,mark.styles[0]);
    const key = `${mark.trade_date}/${mark.id}`;
    if ((!icon&&!text)||seen.has(key))return null;
    seen.add(key);
  }
  return marks;
}

const markLabel = mark => mark.kind==='DRAWICON' ? (mark.payload==='1'?'▲':'▼') : mark.payload;

function drawOriginalMarks(ctx, markers, left, right, top, bottom) {
  const occupied = [];
  const priority = entry => entry.selected ? 0 : ['守线','破线'].includes(entry.mark.payload) ? 2 : 1;
  ctx.save();
  ctx.beginPath(); ctx.rect(left,top,right-left,bottom-top); ctx.clip();
  ctx.font = '600 12px system-ui';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (const entry of [...markers].sort((a,b)=>priority(a)-priority(b))) {
    const {mark,x,y} = entry;
    const color = markColors[mark.styles[0]] ?? markColors.COLORRED;
    ctx.fillStyle = color;
    if (mark.kind==='DRAWICON') {
      const direction = mark.payload==='1' ? -1 : 1;
      ctx.beginPath(); ctx.moveTo(x,y+direction*5);
      ctx.lineTo(x-4,y-direction*3); ctx.lineTo(x+4,y-direction*3); ctx.closePath();
      ctx.strokeStyle = '#031726'; ctx.lineWidth = 2; ctx.stroke(); ctx.fill();
      occupied.push({x0:x-4,x1:x+4,y0:y-5,y1:y+5});
      continue;
    }
    const width = ctx.measureText(mark.payload).width+6;
    const center = Math.max(left+width/2,Math.min(right-width/2,x));
    const label = [0,14,-14,28,-28].map(offset=>y+offset).find(yy=>{
      if (yy-7<top||yy+7>bottom)return false;
      const box={x0:center-width/2,x1:center+width/2,y0:yy-7,y1:yy+7};
      if (occupied.some(other=>box.x0<other.x1&&box.x1>other.x0&&box.y0<other.y1&&box.y1>other.y0))return false;
      occupied.push(box);
      return true;
    });
    // Crowded candles keep their exact anchor. Selecting the date lists every original mark.
    if (label === undefined || Math.abs(label-y)>3 || Math.abs(center-x)>3) {
      ctx.beginPath();ctx.arc(x,y,2,0,Math.PI*2);ctx.fill();
    }
    if (label !== undefined) {
      ctx.strokeStyle='#031726';ctx.lineWidth=3;ctx.lineJoin='round';
      ctx.strokeText(mark.payload,center,label);ctx.fillText(mark.payload,center,label);
    }
  }
  ctx.restore();

}

function drawOriginalLines(ctx, lines, start, count, left, right, top, bottom, step, y) {
  if (!lines) return;
  ctx.save();
  ctx.beginPath(); ctx.rect(left,top,right-left,bottom-top); ctx.clip();
  ctx.lineWidth=2; ctx.lineJoin='round'; ctx.lineCap='round';
  for (const [name,color] of Object.entries(originalLineColors)) {
    ctx.strokeStyle=color;
    const points=lines[name].slice(start,start+count);
    let drawing=false;
    ctx.beginPath();
    points.forEach((point,index)=>{
      if (point.y===null) {
        if (drawing) ctx.stroke();
        ctx.beginPath();
        drawing=false;
        return;
      }
      const x=left+(index+0.5)*step;
      const value=y(Number(point.y));
      if (drawing) ctx.lineTo(x,value);
      else {ctx.moveTo(x,value);drawing=true;}
    });
    if (drawing) ctx.stroke();
  }
  ctx.restore();
}

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
  const original = verifiedOriginalMarks(chart);
  const markDates = new Map();
  for (const marker of original?.marks ?? []) {
    if (!markDates.has(marker.trade_date)) markDates.set(marker.trade_date, []);
    markDates.get(marker.trade_date).push(marker);
  }
  const markLegend = make('small', original ? '原 V4 主图 · D35C' : '原主图标记待核');
  const lineLegend = make('small', '');
  lineLegend.className = 'chart-line-legend';
  if (original?.lines) {
    lineLegend.style.cssText='display:inline-flex;gap:10px;margin-left:8px';
    for (const [name,color] of Object.entries(originalLineColors)) {
      const item=make('span','');
      item.style.cssText='display:inline-flex;align-items:center;gap:3px';
      const swatch=make('span','━━');
      swatch.style.cssText=`color:${color}`;
      const label=make('span',name);
      item.append(swatch,label);
      lineLegend.append(item);
    }
  }
  const dateSelect = make('select', '');
  dateSelect.setAttribute('aria-label', '定位日K交易日');
  toolbar.append(dateSelect, markLegend, lineLegend);
  for (const row of chart.rows) dateSelect.add(new Option(isoDate(row.trade_date), row.trade_date));
  const canvas = make('canvas', '前复权日K和成交量');
  canvas.style.cssText = 'display:block;width:100%;height:340px';
  canvas.setAttribute('aria-label', `${chart.symbol} 前复权日K和成交量，数据截至 ${chart.source_date}`);
  canvas.setAttribute('role', 'img');
  const readout = make('p', '');
  readout.className = 'readout';
  const marksReadout = make('p', '');
  marksReadout.className = 'readout';
  host.replaceChildren(toolbar, canvas, readout, marksReadout);
  host.dataset.originalMarkCount = String(original?.marks.length ?? 0);
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
    const start = Math.max(0, end-windowSize);
    const visible = chart.rows.slice(start, end);
    const anchors = visible.flatMap((row,index) => (markDates.get(row.trade_date) ?? []).map(mark => ({mark,index,selected:row===chart.rows[selected]})));
    const prices = anchors.map(entry=>Number(entry.mark.y));
    const linePrices = original?.lines ? Object.values(original.lines).flatMap(points => points.slice(start,end)
      .filter(point=>point.y!==null).map(point=>Number(point.y))) : [];
    const low = Math.min(...visible.map(row => row.low),...prices,...linePrices);
    const high = Math.max(...visible.map(row => row.high),...prices,...linePrices);
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
    drawOriginalLines(ctx, original?.lines, start, visible.length, xOffset, plotWidth+xOffset,
      3, volumeTop-9, step, y);
    drawOriginalMarks(ctx, anchors.map(entry=>({...entry,x:xOffset+(entry.index+0.5)*step,y:y(Number(entry.mark.y))})),
      xOffset, plotWidth+xOffset, 3, volumeTop-9);
    const bar = chart.rows[selected];
    const marked = markDates.get(bar.trade_date) ?? [];
    const unknown = original?.unresolved_conditions > 0 ? '；窗口有待核条件' : '';
    const markerText = original ? '本根原主图标记 · '+
      (marked.length ? marked.map(mark=>`${markLabel(mark)} @${mark.y}`).join(' / ') : '无已确认标记')+unknown : '';
    const lineText = original?.lines ? '原主图线 · '+Object.keys(originalLineColors).map(name=>
      `${name} ${original.lines[name][selected].y ?? '缺值'}`).join(' / ') : '';
    marksReadout.textContent = [markerText,lineText].filter(Boolean).join('；');
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
  return () => { watch.disconnect(); host.replaceChildren(); delete host.dataset.symbol; delete host.dataset.originalMarkCount; };
}
