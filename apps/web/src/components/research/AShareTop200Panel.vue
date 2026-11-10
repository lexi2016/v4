<script setup lang="ts">
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from "vue";

type Pool = { pool_id: string; display_name?: string; materialized?: boolean; partial?: boolean; selected_count?: number | null; hit_count?: number | null; top200_coverage_pct?: number | null; selection_hit_rate_pct?: number | null };
type Stage = { execution_status?: string; research_evidence_status?: string; errors?: string[]; error_counts?: Record<string, number>; status?: string; row_count?: number | null; unique_codes?: number | null; hit_count?: number | null };
type Stock = { rank: number; code: string; name?: string | null; change_pct?: number | null; pool_hit: boolean; pool_memberships: string[]; stage_memberships: string[] };
type ComparisonRow = { group_id: string; status?: string; signal_date?: string | null; target_date?: string; selected_count?: number | null; hit_count?: number | null; top200_coverage_pct?: number | null; selection_hit_rate_pct?: number | null };
type Entry = { formula_comparison?: { status?: string; signal_date?: string; target_date?: string; historical_PIT?: boolean | null; rows?: ComparisonRow[] }; date: string; status?: string; a_pool?: { selected_count?: number | null; hit_count?: number | null; top200_coverage_pct?: number | null; selection_hit_rate_pct?: number | null; materialized_pool_count?: number | null; pool_count?: number | null; missing_pool_ids?: string[]; partial_pool_ids?: string[]; pools?: Pool[] }; seven_stage?: { selected_count?: number | null; hit_count?: number | null; top200_coverage_pct?: number | null; selection_hit_rate_pct?: number | null; stages?: Record<string, Stage> }; stage_coverage?: { available?: number | null; total?: number | null; missing_stages?: string[] }; top200?: { top_count?: number | null; min_change_pct?: number | null }; stocks?: Stock[]; detail_status?: string; detail_gap?: string };
type Payload = { requested_date?: string; archive_source?: unknown; selected_source_status?: string; schema_version?: string; generated_at?: string; latest_available_date?: string; dates: Entry[]; detail_projection?: unknown; safety_flags?: unknown };
const props = defineProps<{ date: string }>();
const emit = defineEmits<{ close: []; selectDate: [date: string] }>();
const payload = ref<Payload | null>(null);
const loading = ref(true);
const error = ref("");
const heading = ref<HTMLElement | null>(null);
const filter = ref<"all" | "pool" | "stage">("all");
const page = ref(0);
const PAGE_SIZE = 50;
const stageNames: Record<string, string> = { STAGE_0925: "09:25 竞价", STAGE_0930_0935: "09:30–09:35", STAGE_0935_0940: "09:35–09:40", STAGE_0940_0945: "09:40–09:45", STAGE_0945_1030: "09:45–10:30", STAGE_1300_1315: "13:00–13:15", STAGE_1445_1500: "14:45–15:00 尾盘" };
const poolNames: Record<string, string> = { a_d1_premarket_pool: "主预选池", a_d1_fupan_watchlist_pool: "复盘观察池", a_d1_stage7_fenshi_review_pool: "分时复盘池", a_share_research_recommendation_pool: "研报推荐池", a_share_baimao_research_map: "白毛研究池", wechat_public_account_v3_preselect: "公众号池" };
const selectedEntry = computed(() => payload.value?.dates.find(row => row.date === props.date) ?? null);
const latest = computed(() => payload.value?.latest_available_date);
const stocks = computed(() => selectedEntry.value?.stocks ?? []);
const filtered = computed(() => stocks.value.filter(row => filter.value === "pool" ? row.pool_hit : filter.value === "stage" ? row.stage_memberships.length > 0 : true));
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)));
const visibleStocks = computed(() => filtered.value.slice(page.value * PAGE_SIZE, (page.value + 1) * PAGE_SIZE));
const stageRows = computed(() => Object.entries(stageNames).map(([id, label]) => ({ id, label, entry: selectedEntry.value?.seven_stage?.stages?.[id] })));
const poolLabels = (ids?: string[]) => (ids ?? []).map(id => poolNames[id] || "未识别来源（见证据）").join("、");
const stageLabels = (ids?: string[]) => (ids ?? []).map(id => stageNames[id] || "未识别阶段（见证据）").join("、");
const count = (value?: number | null) => typeof value === "number" ? String(value) : "不可确认";
const percent = (value?: number | null) => typeof value === "number" ? `${value.toFixed(2)}%` : "不可确认";
const changeText = (value?: number | null) => typeof value === "number" ? `${value >= 0 ? "+" : ""}${percent(value)}` : "不可确认";
const dateText = (value: string) => value.replace(/^(\d{4})(\d{2})(\d{2})$/, "$1-$2-$3");
const coverage = computed(() => `${count(selectedEntry.value?.stage_coverage?.available)} / ${count(selectedEntry.value?.stage_coverage?.total)}`);
const poolCoverage = computed(() => `${count(selectedEntry.value?.a_pool?.materialized_pool_count)}/${count(selectedEntry.value?.a_pool?.pool_count)}`);
const incompleteStages = computed(() => selectedEntry.value?.stage_coverage?.available !== 7);
const comparisonNames: Record<string, string> = { four_group_union: "原四组公式并集", original: "原公式", nav_smallk: "导航小K", nav_pullback: "导航回踩", nav_breakout: "导航突破", v192: "v1.9.2 主池" };
function stageStatus(stage?: Stage) {
  const labels: Record<string, string> = { NOT_RUN: "未运行（无自然回执）", EXECUTION_FAILED: "执行失败，未生成名单", CANNOT_CONFIRM: "名单或来源不可确认", VALID_EMPTY: "有效空名单", PARTIAL_ROWS: "已生成名单，证据不完整", MATERIALIZED_ROWS: "已生成名单" };
  return labels[stage?.execution_status || ""] || (stage?.status === "READY" ? "原快照已物化" : "原快照未物化");
}
function stageReason(stage?: Stage) {
  const errors = stage?.errors ?? [];
  if (errors.some(e => e.includes("HOURLY_COMPLETION_WITNESS_MISSING"))) return "行情已到，小时研究完成回执未通过，未生成名单。";
  if (stage?.research_evidence_status === "CANNOT_CONFIRM") {
    const counts = stage.error_counts ?? {};
    const quality = Object.entries(counts).filter(([key]) => /QUALITY_SCORE_MISSING|CONTEXT_FIELDS_MISSING|CONTEXT_CODE_MISSING/.test(key)).reduce((sum, [, value]) => sum + value, 0);
    return `名单行数已保留；研究证据或来源完整性待核${quality ? `，逐股质量字段缺口 ${quality} 项` : ""}。`;
  }
  if (stage?.execution_status === "EXECUTION_FAILED") return "自然执行回执报告错误，不能按正常空名单评价。";
  if (stage?.execution_status === "CANNOT_CONFIRM") return "回执或名单边界核对未通过，详见来源证据。";
  return "";
}
watch([() => props.date, filter], () => { page.value = 0; });
let requestSerial=0, disposed=false, events: EventSource | null=null, lastEvent="", foregroundQueued=false;
async function refresh() {
  const date=props.date, mine=++requestSerial;
  loading.value=true; error.value=""; payload.value=null;
  try {
    const response=await fetch(`/api/v4/research/a-share/top200-hit?date=${encodeURIComponent(date)}`,{cache:"no-store"});
    if(!response.ok)throw new Error(`收盘复盘来源待核（HTTP ${response.status}）`);
    const body:unknown=await response.json();
    if(disposed||mine!==requestSerial||props.date!==date)return;
    const value=body as Payload;
    if(!value||value.schema_version!=="v4.research.a_share_pool_top200.v1"||value.requested_date!==date||!Array.isArray(value.dates))throw new Error("收盘复盘日期或来源不可确认");
    payload.value=value;
  } catch(reason) {
    if(!disposed&&mine===requestSerial&&props.date===date)error.value=reason instanceof Error?reason.message:"收盘复盘读取失败";
  } finally {
    if(!disposed&&mine===requestSerial&&props.date===date){loading.value=false;await nextTick();heading.value?.scrollIntoView?.({block:"start",behavior:"instant"});}
  }
}
function bindEvents(date:string) {
  events?.close();events=null;lastEvent="";
  if(typeof EventSource==="undefined")return;
  const sourceDate=date.replace(/^(\d{4})(\d{2})(\d{2})$/,"$1-$2-$3"),stream=new EventSource(`/api/v4/research/workbench/days/${sourceDate}/events`);events=stream;
  stream.addEventListener("workbench_completed",event=>{
    if(disposed||events!==stream||props.date!==date)return;
    try{const value=JSON.parse((event as MessageEvent).data);if(value.source_date!==sourceDate||!value.event_id||value.event_id===lastEvent)return;lastEvent=value.event_id;void refresh();}catch{/* Ignore an unbound event; next entry/focus reads saved sources. */}
  });
}
function foreground() {
  if(disposed||document.visibilityState==="hidden"||foregroundQueued)return;
  foregroundQueued=true;void Promise.resolve().then(()=>{foregroundQueued=false;if(!disposed)void refresh();});
}
watch(()=>props.date,date=>{bindEvents(date);void refresh();},{immediate:true});
onMounted(()=>{window.addEventListener("focus",foreground);document.addEventListener("visibilitychange",foreground);});
onBeforeUnmount(()=>{disposed=true;++requestSerial;events?.close();window.removeEventListener("focus",foreground);document.removeEventListener("visibilitychange",foreground);});

</script>

<template>
  <section class="panel a-top200-panel" data-testid="a-top200-panel" aria-label="A股来源池与已物化阶段 Top200 收盘复盘">
    <header ref="heading" class="a-top200-heading">
      <div><span class="eyebrow">A股 · 收盘复盘</span><h2>9A. 来源池 / 已物化阶段 Top200</h2><p>{{ dateText(date) }} · 同日收盘回看</p></div>
      <button type="button" data-testid="a-top200-close" @click="emit('close')">返回阶段选股</button>
    </header>
    <p v-if="loading" class="a-message" role="status">正在读取收盘复盘。</p>
    <p v-else-if="error" class="a-message" role="alert">{{ error }}</p>
    <template v-else>
      <div v-if="!selectedEntry" class="a-message" data-testid="a-top200-empty">
        <p>{{ dateText(date) }} 尚无收盘复盘工件，未运行或来源不可确认；不显示其他日期的结果。</p>
        <button v-if="latest && latest !== date" type="button" @click="emit('selectDate', latest)">查看最近已存日期 {{ dateText(latest) }}</button>
      </div>
      <template v-else>
        <div class="a-metrics">
          <article data-testid="a-top200-card-pool"><span>已接入来源池汇总（{{ poolCoverage }}）</span><strong>{{ count(selectedEntry.a_pool?.hit_count) }} <small>/ {{ count(selectedEntry.top200?.top_count) }}</small></strong><p>候选去重 {{ count(selectedEntry.a_pool?.selected_count) }} 只</p><dl><dt>收盘榜单覆盖率</dt><dd>{{ percent(selectedEntry.a_pool?.top200_coverage_pct) }}</dd><dt>候选名单命中率</dt><dd>{{ percent(selectedEntry.a_pool?.selection_hit_rate_pct) }}</dd></dl></article>
          <article data-testid="a-top200-card-seven"><span>已物化阶段（{{ count(selectedEntry.stage_coverage?.available) }}/{{ count(selectedEntry.stage_coverage?.total) }}）</span><strong>{{ count(selectedEntry.seven_stage?.hit_count) }} <small>/ {{ count(selectedEntry.top200?.top_count) }}</small></strong><p>已物化阶段并集 {{ count(selectedEntry.seven_stage?.selected_count) }} 只 · 覆盖 {{ coverage }}</p><dl><dt>收盘榜单覆盖率</dt><dd>{{ percent(selectedEntry.seven_stage?.top200_coverage_pct) }}</dd><dt>候选名单命中率</dt><dd>{{ percent(selectedEntry.seven_stage?.selection_hit_rate_pct) }}</dd></dl></article>
          <article data-testid="a-top200-card-top200"><span>A股收盘涨幅榜</span><strong>{{ count(selectedEntry.top200?.top_count) }} <small>只</small></strong><p>榜单最低涨幅 {{ percent(selectedEntry.top200?.min_change_pct) }}</p><p>覆盖率 = 命中数 ÷ 榜单数<br>名单命中率 = 命中数 ÷ 候选数</p></article>
        </div>
        <aside class="a-gaps" aria-label="本日数据缺口">
          <p>已接入来源池汇总（{{ poolCoverage }}），仅含下列已物化来源；<template v-if="selectedEntry.a_pool?.partial_pool_ids?.length">部分数据：{{ poolLabels(selectedEntry.a_pool.partial_pool_ids) }}；</template><template v-if="selectedEntry.a_pool?.missing_pool_ids?.length">未物化：{{ poolLabels(selectedEntry.a_pool.missing_pool_ids) }}。</template></p>
          <p>已物化阶段（{{ count(selectedEntry.stage_coverage?.available) }}/{{ count(selectedEntry.stage_coverage?.total) }}）；<strong v-if="incompleteStages">完整七阶段效果不可评价。</strong><template v-if="selectedEntry.stage_coverage?.missing_stages?.length">缺少 {{ stageLabels(selectedEntry.stage_coverage.missing_stages) }} 的有效名单，未补零，后来的补跑未混入历史快照；自然回执原因见阶段统计。</template><template v-else>按原快照逐阶段对照。</template></p>
        </aside>
        <section class="a-comparison" data-testid="a-top200-formula-comparison" aria-label="原四组公式与v1.9.2对照">
          <h3>原四组公式与 v1.9.2 对照</h3>
          <p>使用前一A股交易日已保存标签与目标日榜单求交；此表不属于上方已接入来源池汇总，不改变阶段输入。分组存在重合，不相加。</p>
          <template v-if="selectedEntry.formula_comparison?.status === 'READY'">
            <p>信号日 {{ selectedEntry.formula_comparison.signal_date ? dateText(selectedEntry.formula_comparison.signal_date) : '不可确认' }} · 目标日 {{ dateText(date) }}。历史事前数据认证：{{ selectedEntry.formula_comparison.historical_PIT === false ? '未通过（historical_PIT=false）' : '不可确认' }}；仅为已有产物回看。</p>
            <div class="a-table-scroll"><table><thead><tr><th>范围</th><th>信号日</th><th>目标日</th><th>候选</th><th>命中</th><th>榜单覆盖率</th><th>名单命中率</th></tr></thead><tbody><tr v-for="row in selectedEntry.formula_comparison.rows ?? []" :key="row.group_id" data-testid="a-top200-formula-row"><td>{{ comparisonNames[row.group_id] || row.group_id }}</td><td>{{ row.signal_date ? dateText(row.signal_date) : '不可确认' }}</td><td>{{ row.target_date ? dateText(row.target_date) : '不可确认' }}</td><td>{{ count(row.selected_count) }}</td><td>{{ count(row.hit_count) }}</td><td>{{ percent(row.top200_coverage_pct) }}</td><td>{{ percent(row.selection_hit_rate_pct) }}</td></tr></tbody></table></div>
          </template>
          <p v-else>精确信号日标签或来源绑定不足，公式对照不可确认；不使用旧日或最新标签补齐。</p>
        </section>
        <div class="a-list-heading"><div><h3>Top200 股票与命中归因</h3><p>分池与阶段重合只记一次命中，归因可同时出现多项。</p></div><label>显示范围<select v-model="filter" aria-label="Top200 显示范围"><option value="all">全部榜单（{{ stocks.length }}）</option><option value="pool">来源池命中（{{ stocks.filter(r => r.pool_hit).length }}）</option><option value="stage">阶段命中（{{ stocks.filter(r => r.stage_memberships.length).length }}）</option></select></label></div>
        <p v-if="!stocks.length" class="a-message" data-testid="a-top200-detail-gap">{{ selectedEntry.detail_gap || '缺少同日同来源的股票明细；统计保留，明细不可确认。' }}</p>
        <template v-else>
          <div class="a-table-scroll" tabindex="0" aria-label="Top200 股票表，可横向滚动">
            <table class="a-stocks"><thead><tr><th>排名</th><th>股票</th><th>当日涨幅</th><th>来源池命中归因</th><th>已物化阶段归因</th></tr></thead><tbody>
              <tr v-for="row in visibleStocks" :key="row.code" data-testid="a-top200-stock-row"><td>{{ row.rank }}</td><td><strong>{{ row.name || '名称不可确认' }}</strong><small>{{ row.code }}</small></td><td class="a-gain">{{ changeText(row.change_pct) }}</td><td><span :class="{ 'a-hit': row.pool_hit }">{{ row.pool_hit ? poolLabels(row.pool_memberships) || '汇总命中；分池归因不可确认' : '未命中已物化来源池' }}</span></td><td><span :class="{ 'a-hit': row.stage_memberships.length }">{{ row.stage_memberships.length ? stageLabels(row.stage_memberships) : '未命中已物化阶段' }}</span></td></tr>
            </tbody></table>
          </div>
          <nav class="a-pagination" aria-label="Top200 分页"><span>共 {{ filtered.length }} 只 · 第 {{ page + 1 }} / {{ pageCount }} 页</span><button type="button" :disabled="page === 0" @click="page--">上一页</button><button type="button" :disabled="page + 1 >= pageCount" @click="page++">下一页</button></nav>
        </template>
        <details class="a-details"><summary>分池统计 · {{ count(selectedEntry.a_pool?.materialized_pool_count) }} 路已物化</summary><div class="a-table-scroll"><table><thead><tr><th>来源池</th><th>状态</th><th>候选数</th><th>命中数</th><th>榜单覆盖率</th><th>名单命中率</th></tr></thead><tbody><tr v-for="pool in selectedEntry.a_pool?.pools ?? []" :key="pool.pool_id" data-testid="a-top200-pool-row"><td>{{ poolNames[pool.pool_id] || pool.display_name }}</td><td>{{ !pool.materialized ? '未物化' : pool.partial ? '部分数据' : '已物化' }}</td><td>{{ pool.materialized ? count(pool.selected_count) : '不可确认' }}</td><td>{{ pool.materialized ? count(pool.hit_count) : '不可确认' }}</td><td>{{ percent(pool.top200_coverage_pct) }}</td><td>{{ percent(pool.selection_hit_rate_pct) }}</td></tr></tbody></table></div></details>
        <details class="a-details"><summary>七阶段统计 · 已物化 {{ coverage }}</summary><div class="a-table-scroll"><table><thead><tr><th>阶段</th><th>状态</th><th>行数</th><th>去重候选</th><th>命中数</th><th>说明</th></tr></thead><tbody><tr v-for="row in stageRows" :key="row.id" data-testid="a-top200-stage-row"><td>{{ row.label }}</td><td>{{ stageStatus(row.entry) }}</td><td>{{ count(row.entry?.row_count) }}</td><td>{{ count(row.entry?.unique_codes) }}</td><td>{{ count(row.entry?.hit_count) }}</td><td>{{ stageReason(row.entry) }}</td></tr></tbody></table></div></details>
      </template>
      <details class="a-details"><summary>其他已存日期</summary><div class="a-date-list"><button v-for="entry in payload?.dates ?? []" :key="entry.date" type="button" :aria-pressed="entry.date === date" @click="emit('selectDate', entry.date)">{{ dateText(entry.date) }} · {{ entry.top200 ? '有收盘统计' : '缺收盘榜单' }}</button></div></details>
      <p class="a-boundary">仅用于研究回看。池与盘中名单和同日收盘榜单的交集不代表未来收益或事前预测能力；不同市场、不同分母的命中率不能直接比较策略强弱。</p>
      <details class="a-details a-evidence"><summary>来源与核对证据</summary><p>来源读取于 {{ payload?.generated_at || '不可确认' }} · 同日已保存来源；历史静态快照仅按精确日期保留</p><pre>{{ JSON.stringify({ schema: payload?.schema_version, archive_source: payload?.archive_source, selected_source_status: payload?.selected_source_status, projection: payload?.detail_projection, selected: selectedEntry, safety_flags: payload?.safety_flags }, null, 2) }}</pre></details>
    </template>
  </section>
</template>

<style scoped>
.a-top200-panel { min-width: 0; overflow-wrap: anywhere; }
.a-top200-heading { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; padding: 20px; border-bottom: 1px solid #d7e0e8; scroll-margin-top: 12px; }
h2 { margin: 5px 0; color: #263f57; font-size: 22px; } h3 { margin: 0 0 6px; font-size: 17px; } p { margin: 5px 0; line-height: 1.6; }
.a-top200-heading p, .a-list-heading p { color: #65788b; font-size: 13px; }
button, select { padding: 8px 12px; border: 1px solid #a7bacb; border-radius: 6px; background: #f8fbfd; color: #254d71; }
.a-message { margin: 18px 20px; padding: 14px; background: #f3f7fa; }
.a-metrics { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 14px; padding: 20px; }
.a-metrics article { min-width: 0; padding: 18px; border: 1px solid #d7e3ec; border-radius: 8px; background: #f7fafc; }
.a-metrics article > span { color: #526a7f; font-size: 13px; } .a-metrics strong { display: block; margin: 12px 0; color: #215477; font-size: 36px; } .a-metrics strong small { font-size: 17px; font-weight: 500; }
.a-metrics p, .a-metrics dl { color: #63798b; font-size: 12px; } .a-metrics dl { display: grid; grid-template-columns: 1fr auto; gap: 7px; margin: 14px 0 0; } dd { margin: 0; color: #215477; font-weight: 600; }
.a-gaps { margin: 0 20px 20px; padding: 10px 14px; color: #77581c; border-left: 3px solid #d6b463; background: #fff9e9; font-size: 12px; }
.a-comparison { margin: 20px; } .a-comparison > p { color: #65788b; font-size: 12px; } .a-comparison .a-table-scroll { margin: 12px 0; }
.a-list-heading { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px; margin: 20px; align-items: end; } .a-list-heading label { display: grid; gap: 5px; font-size: 12px; color: #526a7f; }
.a-table-scroll { max-width: 100%; min-width: 0; overflow-x: auto; margin: 0 20px; border: 1px solid #e0e7ed; border-radius: 5px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; } .a-stocks { min-width: 690px; table-layout: fixed; } .a-stocks th:nth-child(1) { width: 8%; } .a-stocks th:nth-child(2) { width: 19%; } .a-stocks th:nth-child(3) { width: 13%; } .a-stocks th:nth-child(4) { width: 28%; }
th,td { text-align: left; padding: 12px; border-bottom: 1px solid #e5ebf0; vertical-align: top; line-height: 1.5; } th { color: #526a7f; background: #f3f7fa; font-weight: 600; } td small { display: block; color: #7b8c9d; font-size: 11px; margin-top: 3px; } tbody tr:nth-child(even) { background: #fafcfd; } .a-gain { color: #b84c45; font-variant-numeric: tabular-nums; } .a-hit { color: #235c83; font-weight: 600; }
.a-pagination { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; padding: 14px 20px; align-items: center; font-size: 12px; } .a-pagination span { margin-right: auto; color: #63798b; }
.a-details { margin: 12px 20px; border: 1px solid #d9e3eb; border-radius: 6px; } summary { padding: 13px 15px; color: #365973; cursor: pointer; font-size: 13px; font-weight: 600; } .a-details .a-table-scroll { margin: 0 12px 12px; } .a-details table { min-width: 580px; } .a-date-list { display: flex; flex-wrap: wrap; gap: 8px; padding: 0 14px 14px; } .a-boundary { margin: 18px 20px; color: #748596; font-size: 12px; }
.a-evidence p { padding: 0 14px; font-size: 12px; } pre { padding: 14px; max-height: 420px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 11px; }
@media(max-width: 900px) { .a-metrics { grid-template-columns: repeat(2,minmax(0,1fr)); } .a-metrics article:last-child { grid-column: 1 / -1; } }
@media(max-width: 640px) { .a-top200-heading { padding: 16px; } h2 { font-size: 20px; } .a-metrics { gap: 10px; padding: 16px; } .a-metrics article { padding: 12px; } .a-metrics strong { font-size: 30px; } .a-metrics dl { grid-template-columns: 1fr; gap: 3px; } dd { margin-bottom: 5px; } .a-gaps,.a-list-heading,.a-boundary,.a-details { margin-left: 16px; margin-right: 16px; } .a-table-scroll { margin-left: 16px; margin-right: 16px; } }
</style>
