'use strict';
// Scope registration is injected by the bounded candidate builder, not discovered from market data.
window.R19Results = (() => {
  const PROFILE = 'R19_FROZEN_151_20261027', DATE = '20261027';
  const $ = id => document.getElementById('r19' + id);
  const SCOPE = [{"symbol":"000661.SZ","registered_result":true},{"symbol":"002028.SZ","registered_result":true},{"symbol":"002230.SZ","registered_result":true},{"symbol":"002241.SZ","registered_result":true},{"symbol":"002249.SZ","registered_result":true},{"symbol":"002315.SZ","registered_result":true},{"symbol":"002326.SZ","registered_result":true},{"symbol":"002327.SZ","registered_result":true},{"symbol":"002850.SZ","registered_result":true},{"symbol":"300005.SZ","registered_result":true},{"symbol":"300009.SZ","registered_result":true},{"symbol":"300395.SZ","registered_result":true},{"symbol":"300748.SZ","registered_result":true},{"symbol":"300782.SZ","registered_result":true},{"symbol":"300976.SZ","registered_result":true},{"symbol":"301360.SZ","registered_result":true},{"symbol":"301489.SZ","registered_result":true},{"symbol":"603175.SH","registered_result":true},{"symbol":"603296.SH","registered_result":true},{"symbol":"603667.SH","registered_result":true},{"symbol":"603836.SH","registered_result":true},{"symbol":"605169.SH","registered_result":true},{"symbol":"688306.SH","registered_result":true},{"symbol":"688368.SH","registered_result":true},{"symbol":"688808.SH","registered_result":true},{"symbol":"000049.SZ","registered_result":true},{"symbol":"000065.SZ","registered_result":true},{"symbol":"000430.SZ","registered_result":true},{"symbol":"000523.SZ","registered_result":true},{"symbol":"000528.SZ","registered_result":true},{"symbol":"000620.SZ","registered_result":true},{"symbol":"000630.SZ","registered_result":true},{"symbol":"000656.SZ","registered_result":true},{"symbol":"000691.SZ","registered_result":true},{"symbol":"000697.SZ","registered_result":true},{"symbol":"000711.SZ","registered_result":true},{"symbol":"000725.SZ","registered_result":true},{"symbol":"000793.SZ","registered_result":true},{"symbol":"000796.SZ","registered_result":true},{"symbol":"000908.SZ","registered_result":true},{"symbol":"000937.SZ","registered_result":true},{"symbol":"000970.SZ","registered_result":true},{"symbol":"000980.SZ","registered_result":true},{"symbol":"001270.SZ","registered_result":true},{"symbol":"001288.SZ","registered_result":true},{"symbol":"001399.SZ","registered_result":true},{"symbol":"002072.SZ","registered_result":true},{"symbol":"002076.SZ","registered_result":true},{"symbol":"002086.SZ","registered_result":true},{"symbol":"002122.SZ","registered_result":true},{"symbol":"002142.SZ","registered_result":true},{"symbol":"002157.SZ","registered_result":true},{"symbol":"002175.SZ","registered_result":true},{"symbol":"002200.SZ","registered_result":true},{"symbol":"002217.SZ","registered_result":true},{"symbol":"002219.SZ","registered_result":true},{"symbol":"002245.SZ","registered_result":true},{"symbol":"002251.SZ","registered_result":true},{"symbol":"002309.SZ","registered_result":true},{"symbol":"002310.SZ","registered_result":true},{"symbol":"002321.SZ","registered_result":true},{"symbol":"002356.SZ","registered_result":true},{"symbol":"002366.SZ","registered_result":true},{"symbol":"002427.SZ","registered_result":true},{"symbol":"002482.SZ","registered_result":true},{"symbol":"002647.SZ","registered_result":true},{"symbol":"002713.SZ","registered_result":true},{"symbol":"002717.SZ","registered_result":false},{"symbol":"002721.SZ","registered_result":true},{"symbol":"002742.SZ","registered_result":true},{"symbol":"002766.SZ","registered_result":true},{"symbol":"002822.SZ","registered_result":true},{"symbol":"002825.SZ","registered_result":true},{"symbol":"002827.SZ","registered_result":false},{"symbol":"002948.SZ","registered_result":true},{"symbol":"300010.SZ","registered_result":true},{"symbol":"300071.SZ","registered_result":true},{"symbol":"300091.SZ","registered_result":true},{"symbol":"300093.SZ","registered_result":true},{"symbol":"300125.SZ","registered_result":true},{"symbol":"300159.SZ","registered_result":true},{"symbol":"300176.SZ","registered_result":true},{"symbol":"300209.SZ","registered_result":true},{"symbol":"300256.SZ","registered_result":true},{"symbol":"300278.SZ","registered_result":true},{"symbol":"300370.SZ","registered_result":true},{"symbol":"300475.SZ","registered_result":true},{"symbol":"300506.SZ","registered_result":true},{"symbol":"300772.SZ","registered_result":true},{"symbol":"300848.SZ","registered_result":true},{"symbol":"301217.SZ","registered_result":true},{"symbol":"301314.SZ","registered_result":true},{"symbol":"301383.SZ","registered_result":true},{"symbol":"301468.SZ","registered_result":false},{"symbol":"600009.SH","registered_result":true},{"symbol":"600010.SH","registered_result":true},{"symbol":"600017.SH","registered_result":true},{"symbol":"600030.SH","registered_result":true},{"symbol":"600057.SH","registered_result":true},{"symbol":"600066.SH","registered_result":true},{"symbol":"600081.SH","registered_result":true},{"symbol":"600117.SH","registered_result":true},{"symbol":"600136.SH","registered_result":true},{"symbol":"600157.SH","registered_result":true},{"symbol":"600165.SH","registered_result":true},{"symbol":"600188.SH","registered_result":true},{"symbol":"600221.SH","registered_result":true},{"symbol":"600246.SH","registered_result":true},{"symbol":"600360.SH","registered_result":true},{"symbol":"600375.SH","registered_result":true},{"symbol":"600459.SH","registered_result":true},{"symbol":"600479.SH","registered_result":true},{"symbol":"600521.SH","registered_result":true},{"symbol":"600589.SH","registered_result":true},{"symbol":"600595.SH","registered_result":true},{"symbol":"600601.SH","registered_result":true},{"symbol":"600621.SH","registered_result":false},{"symbol":"600654.SH","registered_result":true},{"symbol":"600666.SH","registered_result":true},{"symbol":"600715.SH","registered_result":true},{"symbol":"600734.SH","registered_result":true},{"symbol":"600759.SH","registered_result":true},{"symbol":"600909.SH","registered_result":true},{"symbol":"600958.SH","registered_result":true},{"symbol":"601015.SH","registered_result":true},{"symbol":"601016.SH","registered_result":true},{"symbol":"601088.SH","registered_result":true},{"symbol":"601108.SH","registered_result":true},{"symbol":"601187.SH","registered_result":true},{"symbol":"601229.SH","registered_result":true},{"symbol":"601236.SH","registered_result":true},{"symbol":"601326.SH","registered_result":false},{"symbol":"601377.SH","registered_result":true},{"symbol":"601555.SH","registered_result":true},{"symbol":"601865.SH","registered_result":true},{"symbol":"601866.SH","registered_result":true},{"symbol":"601868.SH","registered_result":true},{"symbol":"601916.SH","registered_result":true},{"symbol":"601990.SH","registered_result":true},{"symbol":"603007.SH","registered_result":true},{"symbol":"603030.SH","registered_result":true},{"symbol":"603162.SH","registered_result":true},{"symbol":"603363.SH","registered_result":true},{"symbol":"603559.SH","registered_result":true},{"symbol":"605056.SH","registered_result":true},{"symbol":"605117.SH","registered_result":true},{"symbol":"605258.SH","registered_result":false},{"symbol":"688293.SH","registered_result":true},{"symbol":"688379.SH","registered_result":true},{"symbol":"688450.SH","registered_result":true},{"symbol":"688496.SH","registered_result":false}];
  const labels = {BOTH_SELECTED:'本地选中且捕获分组列入',TDX_ONLY:'捕获分组列入；本地未选',PYTHON_ONLY:'本地选中；捕获分组未列入',BOTH_REJECTED:'本地未选且捕获分组未列入',CANNOT_CONFIRM:'不可确认'};
  let request = 0, controller, bound = false;
  const text = value => value === null || value === undefined ? 'UNKNOWN' : typeof value === 'object' ? JSON.stringify(value) : String(value);
  function clear(message = '') {
    $('Status').textContent = message;
    $('Result').hidden = true;
    $('Identity').textContent = '';
    $('Comparison').textContent = '';
    $('Values').replaceChildren(); $('Drawings').replaceChildren();
    window.R19Chart.clear();
  }
  function table(host, headers, rows) {
    const t = document.createElement('table'), head = document.createElement('thead'), tr = document.createElement('tr');
    for (const label of headers) { const th = document.createElement('th'); th.textContent = label; tr.append(th); }
    head.append(tr); t.append(head);
    const body = document.createElement('tbody');
    for (const row of rows) { const line = document.createElement('tr'); for (const value of row) { const td = document.createElement('td'); td.textContent = text(value); line.append(td); } body.append(line); }
    t.append(body); host.append(t);
  }
  function validate(answer, symbol, date) {
    if (answer.ts_code !== symbol || answer.end_date !== date || answer.formula_version !== PROFILE || answer.profile_id !== PROFILE) throw Error('响应代码、日期或profile不匹配');
    if (answer.research_only !== true || answer.production_allowed !== false || answer.buy_gate_updated !== false || answer.orders_sent !== false) throw Error('研究资格标志不匹配');
    if (answer.status !== 'READY') return answer;
    const last = answer.r19_research?.last_row;
    if (date !== DATE || answer.r19_research?.target_date !== DATE || !last || String(last.trade_date) !== DATE || Object.keys(last.values || {}).length !== 51 || !Array.isArray(last.drawings) || last.drawings.length !== 22 || !Array.isArray(answer.rows) || !answer.rows.length || answer.rows.at(-1).trade_date !== DATE) throw Error('冻结日期或51变量/22绘图合同不匹配');
    if (answer.rows.some(row => row.ts_code !== symbol || row.trade_date > DATE || Object.keys(row).some(key => key.startsWith('user_v1_')))) throw Error('响应含错误身份或非本profile字段');
    return answer;
  }
  function show(answer) {
    const research = answer.r19_research || {}, identity = answer.identity || {};
    if (answer.status !== 'READY') {
      clear([answer.status, research.reason_zh, ...(answer.cannot_confirm || [])].filter(Boolean).join(' · '));
      if (research.official_cause_overlay) $('Status').textContent += ' · 官方状态：' + text(research.official_cause_overlay);
      return;
    }
    $('Result').hidden = false;
    $('Status').textContent = answer.ts_code + ' · 截至2026-10-27 · ' + answer.rows.length + '行实际已存历史';
    $('Identity').textContent = ['来源：'+text(identity.source_vendor)+' / '+text(identity.source_kind), '价格口径：'+text(identity.price_coordinate_type), text(identity.qualification_zh), text(research.coverage_note), 'PIT：'+text(identity.historical_PIT)+'；原生TDX等价：'+text(identity.native_tdx_equivalence_certified)+'；成交量单位已认证：'+text(identity.volume_unit_certified), '成交额：'+text(research.amount_status), '历史限制：'+text(identity.historical_source_limitations), '输入SHA：'+text(identity.input_sha256), '登记SHA：'+text(identity.r19_registry_sha256)].join('\n');
    const comparison = research.comparison || {};
    $('Comparison').textContent = [labels[comparison.diff_type] || '不可确认', '本地历史公式选中：'+text(comparison.python_selected)+'；捕获分组列入：'+text(comparison.tdx_captured_member), '本地日期：'+text(comparison.panel_date)+'；分组文件mtime：'+text(comparison.captured_group_mtime_local), '分组信号日：'+text(comparison.group_signal_date)+'；正式同日一致性：'+text(comparison.formal_same_day_parity), text(research.comparison_note)].join('\n');
    table($('Values'), ['变量','原始值'], Object.entries(research.last_row.values));
    table($('Drawings'), ['编号','类型','触发条件','内容','坐标','样式'], research.last_row.drawings.map(d => [d.id,d.kind,d.condition,d.payload,d.y,d.styles]));
    const chartRows = answer.rows.map(r => ({date:r.trade_date,open:r.open,high:r.high,low:r.low,close:r.close,volume:r.volume,values:{'白线':r.zge_white_line,'黄线':r.zge_yellow_line,BBI:r.BBI,J:r.J}}));
    window.R19Chart.setStock({chartRows});
  }
  async function load() {
    const token = ++request; controller?.abort(); controller = new AbortController();
    const symbol = $('Symbol').value, date = $('Date').value.replaceAll('-', '');
    clear('正在读取精确登记结果…');
    if (!SCOPE.some(item => item.symbol === symbol)) { clear('代码不在冻结151项内，未请求'); return; }
    try {
      const query = new URLSearchParams({ts_code:symbol,start_date:'20260101',end_date:date,formula_version:PROFILE});
      const response = await fetch('/api/v4/research/a-share/history?' + query, {signal:controller.signal,cache:'no-store'});
      if (!response.ok) throw Error('HTTP '+response.status);
      const answer = validate(await response.json(), symbol, date);
      if (token !== request) return;
      show(answer);
    } catch (error) { if (token === request && error.name !== 'AbortError') clear('读取未确认，旧图已清空：' + error.message); }
  }
  function bind() {
    if (bound) return; bound = true;
    for (const item of SCOPE) { const option = document.createElement('option'); option.value = item.symbol; option.textContent = item.symbol + ' · ' + (item.registered_result ? '已登记结果' : '目标日无行情'); $('Symbol').append(option); }
    $('Symbol').value = '600715.SH';
    window.R19Chart.bind();
    $('Load').addEventListener('click', load);
    for (const id of ['Symbol','Date']) $(id).addEventListener('change', () => { ++request; controller?.abort(); clear('选择已改变，请读取；仅支持截至2026-10-27的冻结结果。'); });
    clear('请选择股票并读取；不会自动请求原日更股票池。');
  }
  return {bind,load,validate};
})();
window.R19Results.bind();
