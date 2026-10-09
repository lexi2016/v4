import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire, stripTypeScriptTypes } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// Compile the full supplied live App, its real setup functions, template and
// Stage panel. Other views and the review HTTP client are explicit boundaries.
// SSR never invokes browser mount hooks; event tests invoke real callbacks.
export const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const phase = process.env.STAGE_UI_PHASE ?? 'after';
assert.ok(['before', 'after'].includes(phase));
export const sourceRoot = process.env.STAGE_UI_SOURCE_ROOT
  ? resolve(process.env.STAGE_UI_SOURCE_ROOT) : resolve(root, phase, 'apps/web/src');
const beforeSourceRoot = process.env.STAGE_UI_BEFORE_SOURCE_ROOT
  ? resolve(process.env.STAGE_UI_BEFORE_SOURCE_ROOT) : resolve(root, 'before/apps/web/src');
assert.ok(process.env.STAGE_UI_RUNTIME, 'STAGE_UI_RUNTIME must name an installed Vue runtime');
const runtime = createRequire(resolve(process.env.STAGE_UI_RUNTIME, 'package.json'));
export const vue = runtime('vue');
const compiler = runtime('@vue/compiler-sfc');
const parser = runtime('@babel/parser');
const ssr = runtime('@vue/server-renderer');
export const versions = Object.fromEntries(['vue', '@vue/compiler-sfc', '@vue/server-renderer', '@babel/parser']
  .map(name => [name, runtime(name + '/package.json').version]));
export const appSource = readFileSync(resolve(sourceRoot, 'App.vue'), 'utf8');
export const beforeAppSource = readFileSync(resolve(beforeSourceRoot, 'App.vue'), 'utf8');
export const runtimeSource = readFileSync(resolve(sourceRoot, 'contracts/runtime.ts'), 'utf8');
export const beforeRuntimeSource = readFileSync(resolve(beforeSourceRoot, 'contracts/runtime.ts'), 'utf8');
export function parseScript(source) {
  return parser.parse(compiler.parse(source).descriptor.scriptSetup.content,
    { sourceType: 'module', plugins: ['typescript'] });
}

function moduleCode(code) {
  const js = stripTypeScriptTypes(code, { mode: 'strip' });
  const ast = parser.parse(js, { sourceType: 'module' });
  let result = js;
  for (const item of [...ast.program.body].reverse()) {
    if (item.type === 'ImportDeclaration') {
      const dependency = `dependencies[${JSON.stringify(item.source.value)}]`;
      const statements = item.specifiers.map(specifier => {
        const access = specifier.type === 'ImportSpecifier'
          ? `${dependency}[${JSON.stringify(specifier.imported.name ?? specifier.imported.value)}]` : dependency;
        return `const ${specifier.local.name} = ${access};`;
      }).join('\n');
      result = result.slice(0, item.start) + statements + result.slice(item.end);
    } else if (item.type === 'ExportNamedDeclaration' && item.declaration) {
      result = result.slice(0, item.start) + result.slice(item.declaration.start);
    }
  }
  assert.doesNotMatch(result, /^\s*(import|export)\s/m);
  return result;
}

const stubView = name => ({ name, setup: () => () => vue.h('section', { 'data-view': name }, name) });
const dependencies = { vue, 'vue/server-renderer': ssr,
  './api/review': { loadReview: async date => ({ trade_date: date }) } };
for (const [name, path] of [
  ['TaskStatusView', './views/TaskStatusView.vue'], ['ReviewView', './views/ReviewView.vue'],
  ['ResearchView', './views/ResearchView.vue'], ['GlobalIndustryMap', './components/research/GlobalIndustryMap.vue'],
  ['WechatMentionPool', './components/research/WechatMentionPool.vue'],
]) dependencies[path] = stubView(name);

function compile(relativePath) {
  const filename = resolve(sourceRoot, relativePath);
  const source = readFileSync(filename, 'utf8');
  const parsed = compiler.parse(source, { filename });
  assert.deepEqual(parsed.errors, []);
  const script = compiler.compileScript(parsed.descriptor, { id: 'r4-live-ui', genDefaultAs: '__sfc__' });
  const template = compiler.compileTemplate({ source: parsed.descriptor.template.content,
    filename, id: 'r4-live-ui', compilerOptions: { bindingMetadata: script.bindings } });
  assert.deepEqual(template.errors, []);
  const code = moduleCode(script.content) + '\n' + moduleCode(template.code)
    + '\n__sfc__.render = render; return __sfc__;';
  return new Function('dependencies', code)(dependencies);
}
dependencies['./components/review/StageExecutionEvidencePanel.vue'] = compile('components/review/StageExecutionEvidencePanel.vue');
const App = compile('App.vue');

export function browser(url = 'http://127.0.0.1:18873/?date=20261009&stage=STAGE_0930_0935') {
  const assignments = [], navigations = [];
  let current = new URL(url);
  const location = { get href() { return current.href; }, get search() { return current.search; },
    get pathname() { return current.pathname; }, get hash() { return current.hash; },
    assign(value) { assignments.push(value); } };
  globalThis.window = { location, history: { pushState(_state, _title, value) {
    navigations.push(value); current = new URL(value, current); } },
    setTimeout, clearTimeout, addEventListener() {}, removeEventListener() {} };
  return { assignments, navigations };
}

export async function renderApp(payload = workbench(), overrides = {}) {
  browser();
  let state, vnode;
  const component = { ...App, setup(props, context) {
    state = App.setup(props, context);
    state.selectedDate.value = '20261009';
    state.selectedStage.value = 'STAGE_0930_0935';
    state.dateData.value = { default_date: '20261009', navigation_date: '20261009',
      stage_dates: ['20260928', '20261009'], future_target_dates: [] };
    state.stageWorkbench.value = payload;
    for (const [key, value] of Object.entries(overrides)) {
      assert.ok(vue.isRef(state[key]), 'fixture requires a real ref: ' + key);
      state[key].value = value;
    }
    return state;
  }, render(...args) { vnode = App.render.apply(this, args); return vnode; } };
  const app = vue.createSSRApp(component);
  const warnings = [];
  app.config.warnHandler = message => warnings.push(message);
  const html = await ssr.renderToString(app);
  assert.deepEqual(warnings, [], 'compiled live App warnings');
  return { html, state, vnode };
}

export function workbench() {
  const results = Object.fromEntries(['A_SHARE', 'HK_CONNECT'].map((market, index) => [market, {
    status: 'RESULT_AVAILABLE', selected_rows: 10, requested_rows: index ? 695 : 216,
    source_rows: index ? 695 : 206, missing_quote_rows: index ? 0 : 10,
    quote_coverage_ratio: index ? 1 : 206 / 216, trade_date: '20261009', stage_id: 'STAGE_0930_0935', market,
    run_id: index ? 'run-cfbdc9b36a7308da178d193a' : 'run-2688466a1ae4464ba7237f0b',
    artifact_id: 'fixture-artifact-' + market, algorithm_sha256: 'a'.repeat(64),
    raw_artifact_sha256: (index ? 'b' : 'c').repeat(64), selection_mode: 'BACKFILL',
    ...(index ? { research_source_status: 'RECORDED_IN_VERIFIED_SELECTION', research_source: {
      schema_version: 'HK_CURRENT_DAY_RESEARCH_V1', mode: 'CURRENT_DAY_RESEARCH_ONLY',
      market: 'HK_CONNECT', trade_date: '20261009', universe_as_of: '20261008',
      captured_at: '2026-10-09T15:38:41+08:00', stale_universe: true,
      hk_connect_membership_status: 'CANNOT_CONFIRM', formal_d1_eligible: false, source_sha256: 'd'.repeat(64),
    } } : {}),
  }]));
  return { trade_date: '20261009', run_id: 'consumer-fixture-only',
    stage: { stage_id: 'STAGE_0930_0935', status: 'PARTIAL_WITH_ROWS', display_status: '原正式状态保留' },
    selected_a_rows: 10, selected_hk_rows: null, selected_total_rows: null, selection_mode: 'FIXTURE_ONLY',
    markets: { A: { ...results.A_SHARE }, HK: { ...results.HK_CONNECT,
      display_mode: 'OBSERVATION_UNVERIFIED', selected_rows: null, observation_count: 10,
      display_reasons: ['正式 D1/PIT 及资格待确认'] } },
    unified_rows: ['A', 'HK'].flatMap(market => Array.from({ length: 10 }, (_, index) => ({
      market, code: String(index + 1).padStart(market === 'A' ? 6 : 5, '0'), name: market + '原候选' + index,
      rank: index + 1, status: 'WATCH_ONLY', trade_status: 'WATCH_ONLY', formal_eligible: false,
    }))),
    execution_evidence: { trade_date: '20261009', stage_id: 'STAGE_0930_0935', status: 'EXECUTION_UNVERIFIED',
      execution_origin: 'CURRENT_DAY_RESEARCH_REPLAY', attempt_mode: 'RECOVERY', due_status: 'HISTORICAL_BACKFILL',
      execution_verified: false, natural_verified: false, markets: {}, cannot_confirm: [],
      receipt_history_binding: 'OWNER_HISTORY_SHA_BOUND', selection_results: results,
      selection_artifact_bindings: { A_SHARE: { status: 'BOUND_TO_VERIFIED_SELECTION_TRIO' },
        HK_CONNECT: { status: 'BOUND_TO_VERIFIED_SELECTION_TRIO' } },
      RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false },
    RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false };
}

export function primary(html) { return html.replace(/<details\b[^>]*>[\s\S]*?<\/details>/g, ''); }
export function text(html) { return html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim(); }
export function evidenceHtml(html) {
  return html.match(/<section\b[^>]*aria-label="阶段选股结果与运行记录"[^>]*>([\s\S]*?)<\/section>/)?.[0] ?? '';
}
export function market(html, key) {
  return text(html.match(new RegExp(`<article\\b[^>]*data-market="${key}"[^>]*>([\\s\\S]*?)<\\/article>`))?.[1] ?? '');
}
export function findVnode(node, predicate) {
  if (!node) return undefined;
  if (Array.isArray(node)) {
    for (const child of node) { const found = findVnode(child, predicate); if (found) return found; }
    return undefined;
  }
  if (typeof node !== 'object') return undefined;
  return predicate(node) ? node : findVnode(node.children, predicate);
}
export function vnodeText(node) {
  if (Array.isArray(node)) return node.map(vnodeText).join('');
  return node == null || typeof node === 'boolean' ? ''
    : typeof node === 'object' ? vnodeText(node.children) : String(node);
}
