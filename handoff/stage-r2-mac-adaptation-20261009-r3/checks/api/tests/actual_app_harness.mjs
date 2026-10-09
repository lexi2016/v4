import assert from 'node:assert/strict';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { createRequire, stripTypeScriptTypes } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// This harness compiles and executes the supplied App and panel SFCs. The
// unavailable app-shell/other-view dependencies are explicit test boundaries;
// their implementations, HTTP requests and browser integration are not tested.
export const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const phase = process.env.STAGE_UI_PHASE ?? 'after';
if (!['before', 'after'].includes(phase)) throw new Error('unknown UI phase');
export const sourceRoot = process.env.STAGE_UI_SOURCE_ROOT
  ? resolve(process.env.STAGE_UI_SOURCE_ROOT) : resolve(root, '../..', phase, 'ui/apps/web/src');
const runtimeRoot = process.env.STAGE_UI_RUNTIME;
if (!runtimeRoot) throw new Error('STAGE_UI_RUNTIME must name an installed explicit Vue runtime');
const requireRuntime = createRequire(resolve(runtimeRoot, 'package.json'));
export const vue = requireRuntime('vue');
const compiler = requireRuntime('@vue/compiler-sfc');
const parser = requireRuntime('@babel/parser');
const ssr = requireRuntime('@vue/server-renderer');
export const versions = Object.fromEntries(['vue', '@vue/compiler-sfc', '@vue/server-renderer', '@babel/parser']
  .map(name => [name, requireRuntime(name + '/package.json').version]));
export const appPath = resolve(sourceRoot, 'App.vue');
export const appSource = readFileSync(appPath, 'utf8');
export const runtimeSource = readFileSync(resolve(sourceRoot, 'contracts/runtime.ts'), 'utf8');
export const runtimeAst = parser.parse(runtimeSource, { sourceType: 'module', plugins: ['typescript'] });
const compiledFiles = [];

function compile(filename, useSsr) {
  const source = readFileSync(filename, 'utf8');
  const parsed = compiler.parse(source, { filename });
  assert.deepEqual(parsed.errors, [], filename + ': SFC parse errors');
  const script = compiler.compileScript(parsed.descriptor, {
    id: 'r3-current-app', genDefaultAs: '__sfc__', inlineTemplate: true,
    templateOptions: { ssr: useSsr },
  });
  const js = stripTypeScriptTypes(script.content, { mode: 'strip' });
  const ast = parser.parse(js, { sourceType: 'module' });
  const imports = ast.program.body.filter(node => node.type === 'ImportDeclaration');
  let executable = js;
  for (const item of [...imports].reverse()) {
    const dependency = `dependencies[${JSON.stringify(item.source.value)}]`;
    const declarations = item.specifiers.map(specifier => {
      const access = specifier.type === 'ImportSpecifier'
        ? `${dependency}[${JSON.stringify(specifier.imported.name ?? specifier.imported.value)}]` : dependency;
      return `const ${specifier.local.name} = ${access};`;
    }).join('\n');
    executable = executable.slice(0, item.start) + declarations + executable.slice(item.end);
  }
  if (/^\s*(import|export)\s/m.test(executable)) throw new Error('unhandled compiler module declaration');
  if (process.env.STAGE_UI_GENERATED_DIR) {
    mkdirSync(process.env.STAGE_UI_GENERATED_DIR, { recursive: true });
    const outputName = filename.endsWith('/App.vue') ? 'current-app' : 'evidence-panel';
    writeFileSync(resolve(process.env.STAGE_UI_GENERATED_DIR, `${outputName}.${useSsr ? 'ssr' : 'vnode'}.compiled.js`), script.content);
  }
  const result = { filename, imports: imports.map(item => item.source.value), source_bytes: Buffer.byteLength(source),
    compiled_bytes: Buffer.byteLength(script.content), useSsr,
    create: new Function('dependencies', executable + '\nreturn __sfc__;') };
  compiledFiles.push(result);
  return result;
}

const appSsr = compile(appPath, true);
const appVnode = compile(appPath, false);
const panelImport = './components/review/StageExecutionEvidencePanel.vue';
const panelSsr = appSsr.imports.includes(panelImport) ? compile(resolve(sourceRoot, panelImport), true) : null;
const panelVnode = appVnode.imports.includes(panelImport) ? compile(resolve(sourceRoot, panelImport), false) : null;
export const compileFacts = compiledFiles.map(({ create, ...facts }) => facts);
const stubView = name => ({ name, setup: () => () => vue.h('section', { 'data-view': name }, name) });

export function researchSource() {
  return { schema_version: 'HK_CURRENT_DAY_RESEARCH_V1', mode: 'CURRENT_DAY_RESEARCH_ONLY',
    market: 'HK_CONNECT', trade_date: '20261009', universe_as_of: '20261008',
    captured_at: '2026-10-09T15:38:41+08:00', stale_universe: true,
    hk_connect_membership_status: 'CANNOT_CONFIRM', formal_d1_eligible: false, source_sha256: 'c'.repeat(64) };
}

export function hkResult() {
  return { status: 'RESULT_AVAILABLE', selection_status: 'CANNOT_CONFIRM', selected_rows: 10,
    requested_rows: 216, source_rows: 206, missing_quote_rows: 10, quote_coverage_ratio: 206 / 216,
    trade_date: '20261009', stage_id: 'STAGE_0930_0935', market: 'HK_CONNECT',
    run_id: 'run-hk-readback', artifact_id: 'selection-hk-readback', algorithm_sha256: 'a'.repeat(64),
    raw_artifact_sha256: 'b'.repeat(64), research_source: researchSource(),
    research_source_status: 'RECORDED_IN_VERIFIED_SELECTION' };
}

export function workbench() {
  const result = hkResult();
  return { trade_date: '20261009', stage: { stage_id: 'STAGE_0930_0935', status: 'CANNOT_CONFIRM',
    window: '09:30–09:35', display_status: '现有阶段状态保留' }, selected_hk_rows: null, selected_a_rows: 0,
    markets: { A: { selected_rows: 0 }, HK: { display_mode: 'OBSERVATION_UNVERIFIED', selected_rows: null,
      observation_count: 10, run_id: result.run_id, artifact_id: result.artifact_id,
      algorithm_sha256: result.algorithm_sha256, raw_artifact_sha256: result.raw_artifact_sha256 } },
    unified_rows: Array.from({ length: 10 }, (_, i) => ({ market: 'HK', code: `HK.${String(i + 1).padStart(5, '0')}`,
      name: `现有港股${i + 1}`, rank: i + 1 })),
    execution_evidence: { trade_date: '20261009', stage_id: 'STAGE_0930_0935', status: 'CANNOT_CONFIRM',
      execution_origin: 'CURRENT_DAY_RESEARCH_REPLAY', attempt_mode: 'RECOVERY', due_status: 'HISTORICAL_BACKFILL',
      execution_verified: false, natural_verified: false, markets: {}, cannot_confirm: [],
      RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false,
      selection_results: { HK_CONNECT: result }, selection_artifact_bindings: {} },
    RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false };
}

export function makeShell(payload, overrides = {}) {
  const events = [];
  const state = {
    stageDefinitions: [{ id: 'STAGE_0925', label: '09:25', timeline: '09:25' },
      { id: 'STAGE_0930_0935', label: '09:30–09:35', timeline: '09:30–09:35' }],
    closingTimeline: ['16:10 港股通收盘复盘'],
    selectedDate: vue.ref('20261009'), selectedStage: vue.ref('STAGE_0930_0935'), stageWorkbench: vue.ref(payload),
    pool: vue.ref(null), loading: vue.ref(false), loadError: vue.ref(''), stageLoading: vue.ref(false),
    stageError: vue.ref(''), stageRunStatus: vue.ref(''), navigationStatus: vue.ref(''),
    taskStatusActive: vue.ref(false), researchActive: vue.ref(false), researchArchiveEntry: vue.ref(false),
    closeReviewActive: vue.ref(false), reviewFocus: vue.ref('HK'), reviewTitle: vue.ref('收盘复盘'),
    runtimeLabel: vue.ref('isolated-current-app-fixture'), closeReviewLoading: vue.ref(false),
    closeReviewError: vue.ref(''), closeReviewPayload: vue.ref(null), isHkObservationOnlyDate: vue.ref(false),
    nextFutureTargetDate: vue.ref(''), nextHkTargetDate: vue.ref(''), selectedDateContext: vue.ref('当前交易日'),
    dateInputMin: vue.ref('20260101'), dateInputMax: vue.ref('20261231'), dateInputTitle: vue.ref('交易日'),
    currentStageDefinition: vue.ref({ label: '09:30–09:35' }), isPreopenStage: vue.ref(false),
    canLoadWechatMentions: vue.ref(false), collapsedPools: vue.ref({}), preselectionGroups: vue.ref([]),
    referenceMode: vue.ref(false), v11OpeningFilter: vue.ref(null), stageSummary: vue.ref(null),
    showAStageEvidenceGap: vue.ref(false), closeReview: vue.ref({}), modelMetric: vue.ref({}),
    stageUnionMetric: vue.ref({}), closeReviewEvidenceLabel: vue.ref('未验证'), reviewEvidenceGaps: vue.ref([]),
    formatPercent: value => value == null ? '未知' : String(value), formatDateInput: value => String(value),
    evidenceValue: value => value ?? '未知', qualityScore: value => value ?? '未知',
    rowCode: row => row.code, rowName: row => row.name ?? '名称待核对', rowRank: row => row.rank,
    aShareChangePct: row => row.change_pct, rowSupport: row => row.support, rowPressure: row => row.pressure,
    rowInvalidation: row => row.invalidation, rowNextEvidence: row => row.next_validation_time,
    rowScore: row => row.score ?? '未知', hkChangeLabel: () => '涨幅', hkChangeValue: () => '未知',
    hkScoreLabel: () => '阶段分', rowMissingFields: () => [], hitTop20: () => '未知', reviewClassification: value => value,
    stageCountText: value => value == null ? '不可确认' : String(value),
    stageMarketCountText: (summary, value) => summary?.display_mode === 'OBSERVATION_UNVERIFIED'
      ? `${summary.observation_count ?? 0} 条观察行 · 未验证` : summary?.display_mode === 'CANNOT_CONFIRM'
        ? '待确认/缺少正式产物' : value == null ? '不可确认' : String(value),
    poolRows: group => group.rows ?? [], poolEvidenceReason: () => '', poolEvidenceDetails: () => [],
    poolRowCode: row => row.code, poolRowName: row => row.name, poolRowSource: () => '原池来源',
    poolRowSourceLane: () => '原来源lane', poolCountLabel: group => String(group.rows?.length ?? 0),
    poolRowSignalDate: row => row.signal_date, isWechatPool: () => false, isBaimaoPool: () => false,
    isCompactResearchPool: () => false, timelineStageStatus: () => '原时间线状态', timelineStageCounts: () => '原时间线计数',
  };
  for (const name of ['togglePool', 'showNavigationStatus', 'openTaskStatus', 'openResearch', 'openManagerSelection',
    'scrollToPool', 'openNextFutureTargetPool', 'openNextHkTargetPool', 'loadStage', 'loadCloseReview', 'ensureStage',
    'onDateInputChange']) state[name] = (...args) => events.push([name, ...args]);
  Object.assign(state, overrides);
  state.aRows = overrides.aRows ?? vue.computed(() => (state.stageWorkbench.value?.unified_rows ?? []).filter(row => row.market === 'A').slice(0, 12));
  state.hkRows = overrides.hkRows ?? vue.computed(() => (state.stageWorkbench.value?.unified_rows ?? []).filter(row => row.market === 'HK'));
  state.aSummary = overrides.aSummary ?? vue.computed(() => state.stageWorkbench.value?.markets?.A ?? {});
  return { state, events };
}

function instantiate(shell, useSsr) {
  const dependencies = {
    vue, 'vue/server-renderer': ssr, './app_shell/useAppShell': { useAppShell: () => shell.state },
    './views/TaskStatusView.vue': stubView('TaskStatusView'), './views/ReviewView.vue': stubView('ReviewView'),
    './views/ResearchView.vue': stubView('ResearchView'),
    './components/research/GlobalIndustryMap.vue': stubView('GlobalIndustryMap'),
    './components/research/WechatMentionPool.vue': stubView('WechatMentionPool'),
  };
  const compiled = useSsr ? appSsr : appVnode;
  const panel = useSsr ? panelSsr : panelVnode;
  if (panel) dependencies[panelImport] = panel.create({ vue, 'vue/server-renderer': ssr });
  for (const name of compiled.imports) assert.ok(name in dependencies, 'unavailable dependency: ' + name);
  return compiled.create(dependencies);
}

export async function renderShell(shell) {
  const app = vue.createSSRApp(instantiate(shell, true));
  const warnings = [];
  app.config.warnHandler = message => warnings.push(message);
  const html = await ssr.renderToString(app);
  assert.deepEqual(warnings, [], 'actual App SSR warnings');
  return html;
}

export async function renderApp(payload = workbench(), overrides = {}) {
  return await renderShell(makeShell(payload, overrides));
}

export function appVnodes(shell) {
  const component = instantiate(shell, false);
  let captured;
  const insert = (node, parent, anchor) => {
    if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1);
    node.parent = parent;
    const index = anchor ? parent.children.indexOf(anchor) : -1;
    if (index < 0) parent.children.push(node); else parent.children.splice(index, 0, node);
  };
  const renderer = vue.createRenderer({
    patchProp: (node, key, _previous, value) => { node.props[key] = value; if (key === 'value') node._value = value; }, insert,
    remove: node => { if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1); },
    createElement: tag => ({ tag, props: {}, children: [], parent: null, listeners: {},
      get options() { return this.children.filter(child => child?.tag === 'option'); },
      addEventListener(name, listener) { this.listeners[name] = listener; },
      removeEventListener(name) { delete this.listeners[name]; } }),
    createText: value => ({ value, parent: null }), createComment: value => ({ value, parent: null }),
    setText: (node, value) => { node.value = value; },
    setElementText: (node, value) => { node.children = [value]; },
    parentNode: node => node.parent,
    nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1] ?? null,
    insertStaticContent: (value, parent, anchor) => {
      const node = { value, parent: null }; insert(node, parent, anchor); return [node, node];
    },
  });
  const app = renderer.createApp({ ...component, setup(props, context) {
    const render = component.setup(props, context);
    return (...args) => { captured = render(...args); return captured; };
  } });
  const warnings = [];
  app.config.warnHandler = message => warnings.push(message);
  app.mount({ children: [] });
  assert.deepEqual(warnings, [], 'actual App vnode render warnings');
  app.unmount();
  return captured;
}

export function findVnode(node, predicate) {
  if (!node) return undefined;
  if (Array.isArray(node)) {
    for (const child of node) { const found = findVnode(child, predicate); if (found) return found; }
    return undefined;
  }
  if (typeof node !== 'object') return undefined;
  if (predicate(node)) return node;
  return findVnode(node.children, predicate);
}

export function vnodeText(node) {
  if (Array.isArray(node)) return node.map(vnodeText).join('');
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node !== 'object') return String(node);
  return vnodeText(node.children);
}

export function primary(html) { return html.replace(/<details\b[^>]*>[\s\S]*?<\/details>/g, ''); }
export function text(html) { return html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim(); }
export function evidenceHtml(html) { return html.match(/<section\b[^>]*aria-label="阶段选股结果与运行记录"[^>]*>([\s\S]*?)<\/section>/)?.[0] ?? ''; }
export function market(html, key) { return text(html.match(new RegExp(`<article\\b[^>]*data-market="${key}"[^>]*>([\\s\\S]*?)<\\/article>`))?.[1] ?? ''); }
export function hkColumnCount(html) { return text(html.match(/<div class="market-title"><h3>港股通[^<]*<\/h3><span>([\s\S]*?)<\/span>/)?.[1] ?? ''); }
