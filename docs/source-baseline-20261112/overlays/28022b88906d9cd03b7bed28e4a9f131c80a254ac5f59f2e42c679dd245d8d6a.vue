<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { loadAShareHistory, ORIGINAL_FORMULA_VERSION, type AShareHistory, type HistoryRow } from "../../api/a_share_history";

const props = defineProps<{ tradeDate: string }>();
const code = ref("000156.SZ");
const end = ref(props.tradeDate);
const start = ref(props.tradeDate.slice(0, 4) + "0101");
const result = ref<AShareHistory | null>(null);
const error = ref("");
const loading = ref(false);
let controller: AbortController | undefined;
let sequence = 0;
function clear() { sequence += 1; controller?.abort(); result.value = null; error.value = ""; loading.value = false; }
watch([code, start, end], clear);
watch(() => props.tradeDate, (date) => { clear(); end.value = date; start.value = date.slice(0, 4) + "0101"; });
onBeforeUnmount(clear);
async function load() {
  clear();
  const request = { ts_code: code.value.trim().toUpperCase(), start_date: start.value, end_date: end.value };
  const ticket = sequence;
  controller = new AbortController(); loading.value = true;
  try {
    const value = await loadAShareHistory(request, controller.signal);
    if (ticket !== sequence) return;
    result.value = value;
  } catch (caught) {
    if (ticket === sequence) error.value = caught instanceof Error ? caught.message : "读取未确认";
  } finally { if (ticket === sequence) loading.value = false; }
}
const rows = computed(() => result.value?.status === "READY" ? result.value.rows : []);
const chartRows = computed(() => rows.value.slice(-180));
function number(row: HistoryRow, key: string) { const v = row[key]; return typeof v === "number" && Number.isFinite(v) ? v : null; }
function display(row: HistoryRow, key: string) { const v = row[key]; return v === null || v === undefined ? "未确认" : typeof v === "number" ? v.toFixed(key.startsWith("user_v1_") ? 0 : 3) : String(v); }
function active(row: HistoryRow, key: string) { return row[key] === true || row[key] === 1; }
const scale = computed(() => {
  const values = chartRows.value.flatMap((row) => ["low", "high", "BBI", "zge_white_line", "zge_yellow_line", "ma60"].map((key) => number(row, key))).filter((v): v is number => v !== null);
  return { low: Math.min(...values), high: Math.max(...values) };
});
function x(index: number) { return 36 + index * 884 / Math.max(chartRows.value.length - 1, 1); }
function y(value: number | null) { return value === null ? 240 : 240 - 210 * (value - scale.value.low) / Math.max(scale.value.high - scale.value.low, .001); }
function line(key: string) { return chartRows.value.map((row, i) => ({ value: number(row, key), i })).filter((p) => p.value !== null).map((p) => `${x(p.i)},${y(p.value)}`).join(" "); }
const visibleLabels = ["user_v1_B1", "user_v1_B2", "user_v1_B3", "user_v1_macd_above_zero_second_gold", "user_v1_level1_buy_signal"];
</script>

<template>
  <section class="a-history" aria-label="A股原公式历史" data-testid="a-share-history">
    <h3>个股历史 · 原公式</h3>
    <form @submit.prevent="load" class="controls">
      <label>证券代码 <input v-model="code" aria-label="证券代码" placeholder="000156.SZ" required pattern="[0-9]{6}\.(SH|SZ|BJ)" /></label>
      <label>起始日 <input v-model="start" aria-label="起始日" required pattern="[0-9]{8}" /></label>
      <label>结束日 <input v-model="end" aria-label="结束日" required pattern="[0-9]{8}" /></label>
      <label>公式 <select :value="ORIGINAL_FORMULA_VERSION" aria-label="公式版本"><option :value="ORIGINAL_FORMULA_VERSION">用户原公式 · {{ ORIGINAL_FORMULA_VERSION }}</option></select></label>
      <button type="submit" :disabled="loading">{{ loading ? "读取中…" : "读取共享面板" }}</button>
    </form>
    <p class="boundary">读取已存日线与标签。一级为 B3 或严格零上二次金叉；历史逐日信号与仅末日显示的标签分开。研究数据，历史 PIT 未认证。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="result?.status === 'CANNOT_CONFIRM'" role="status">未确认：{{ result.cannot_confirm.join("；") }}</p>
    <p v-if="result?.status === 'EMPTY_EXACT_RANGE'" role="status">该代码在指定范围没有已接受记录；未替换为最近日期。</p>
    <template v-if="rows.length">
      <p>{{ result?.ts_code }} · {{ rows[0]?.trade_date }}—{{ rows[rows.length - 1]?.trade_date }} · {{ rows.length }} 条；主图展示末 {{ chartRows.length }} 条</p>
      <p class="legend">K线（红涨绿跌） · <span class="white">白线</span> · <span class="yellow">黄线</span> · <span class="bbi">BBI</span> · <span class="ma">MA60</span></p>
      <svg viewBox="0 0 950 270" role="img" aria-label="已存日线与黄白线主图" data-testid="a-share-history-chart">
        <rect width="950" height="270" fill="#17212f" />
        <g v-for="(row, index) in chartRows" :key="row.trade_date" :stroke="Number(row.close) >= Number(row.open) ? '#ff6969' : '#61ce9b'">
          <line :x1="x(index)" :x2="x(index)" :y1="y(number(row, 'high'))" :y2="y(number(row, 'low'))" />
          <line :x1="x(index)" :x2="x(index)" :y1="y(number(row, 'open'))" :y2="y(number(row, 'close'))" :stroke-width="Math.max(1, Math.min(5, 600 / chartRows.length))" />
        </g>
        <polyline :points="line('zge_white_line')" fill="none" stroke="#fff" stroke-width="1.4" />
        <polyline :points="line('zge_yellow_line')" fill="none" stroke="#ffd84d" stroke-width="1.4" />
        <polyline :points="line('BBI')" fill="none" stroke="#d49bff" stroke-width="1.2" />
        <polyline :points="line('ma60')" fill="none" stroke="#6cb9ff" stroke-width="1.2" />
        <text x="36" y="262" fill="#fff">{{ chartRows[0]?.trade_date }}</text><text x="830" y="262" fill="#fff">{{ chartRows[chartRows.length - 1]?.trade_date }}</text>
      </svg>
      <div class="history-table"><table><thead><tr><th>日期</th><th>开</th><th>高</th><th>低</th><th>收</th><th>量</th><th>额</th><th>白线</th><th>黄线</th><th>BBI</th><th>J</th><th>B1</th><th>B2</th><th>B3</th><th>严格零上二金</th><th>原一级</th></tr></thead>
        <tbody><tr v-for="row in [...rows].reverse()" :key="row.trade_date"><td>{{ row.trade_date }}</td><td v-for="key in ['open', 'high', 'low', 'close', 'volume', 'amount', 'zge_white_line', 'zge_yellow_line', 'BBI', 'J']" :key="key">{{ display(row, key) }}</td><td v-for="key in visibleLabels" :key="key">{{ active(row, key) ? '●' : display(row, key) }}</td></tr></tbody>
      </table></div>
      <details><summary>来源与完整原公式标签</summary>
        <p>公式 {{ result?.formula_version }} · 截止 {{ result?.identity?.asof_date }} · generation {{ result?.identity?.generation_id }}</p>
        <p>输入 SHA {{ result?.identity?.input_sha256 }} · manifest SHA {{ result?.identity?.manifest_sha256 }} · 产物 SHA {{ result?.identity?.artifact_sha256 }}</p>
        <p>公式源码 SHA {{ result?.identity?.formula_source_sha256 }} · {{ result?.identity?.verification_basis }}</p>
        <div class="history-table"><table><thead><tr><th>日期</th><th>原公式已存标签</th></tr></thead><tbody><tr v-for="row in [...rows].reverse()" :key="row.trade_date"><td>{{ row.trade_date }}</td><td><span v-for="(value, key) in row" :key="key"><span v-if="String(key).startsWith('user_v1_')">{{ key }}={{ value }}； </span></span></td></tr></tbody></table></div>
      </details>
    </template>
  </section>
</template>

<style scoped>
.a-history { border: 1px solid #cbd5e1; padding: 14px; margin: 16px 0; border-radius: 8px; }
.controls { display: flex; flex-wrap: wrap; align-items: end; gap: 10px; }.controls label { display: grid; gap: 4px; font-size: 12px; }.controls input { max-width: 150px; padding: 6px; }.controls select { max-width: 300px; padding: 6px; }.controls button { padding: 8px; }
.boundary, details { font-size: 12px; color: #475569; overflow-wrap: anywhere; }.legend { background: #17212f; color: #fff; padding: 5px; font-size: 12px; }.white { color: #fff; }.yellow { color: #ffd84d; }.bbi { color: #d49bff; }.ma { color: #6cb9ff; } svg { width: 100%; min-height: 180px; }
.history-table { overflow: auto; max-height: 420px; } table { border-collapse: collapse; font-size: 12px; white-space: nowrap; }th, td { padding: 5px 8px; border-bottom: 1px solid #e2e8f0; text-align: right; }th { position: sticky; top: 0; background: #f1f5f9; }
</style>
