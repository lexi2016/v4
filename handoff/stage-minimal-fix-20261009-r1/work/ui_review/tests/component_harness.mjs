import { readFileSync } from 'node:fs';
import { createRequire, stripTypeScriptTypes } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

const here = dirname(fileURLToPath(import.meta.url));
const work = resolve(here, '../..');
const src = resolve(process.env.UI_REVIEW_SOURCE ?? resolve(work, 'ui_presentation/after/apps/web/src/components/review/StageExecutionEvidencePanel.vue'));
const runtime = createRequire(resolve(process.env.STAGE_UI_RUNTIME ?? resolve(work, 'ui_runtime'), 'package.json'));
const Vue = runtime('vue');
const Compiler = runtime('@vue/compiler-sfc');
const Renderer = runtime('@vue/server-renderer');
const raw = readFileSync(src, 'utf8');
export const sourceIdentity = { path: src, sha256: createHash('sha256').update(raw).digest('hex') };
export const versions = { node: process.version, vue: runtime('vue/package.json').version,
  compiler: runtime('@vue/compiler-sfc/package.json').version, ssr: runtime('@vue/server-renderer/package.json').version };
const parsed = Compiler.parse(raw, { filename: src });
if (parsed.errors.length) throw new Error(JSON.stringify(parsed.errors));
const compiled = Compiler.compileScript(parsed.descriptor, {
  id: 'independent-stage-execution-review', genDefaultAs: '__component', inlineTemplate: true,
  templateOptions: { ssr: true },
});
let executable = stripTypeScriptTypes(compiled.content, { mode: 'strip' });
executable = executable.replace(/import\s*\{([^}]+)\}\s*from\s*['"](vue|vue\/server-renderer)['"];?/g,
  (_whole, names, module) => `const { ${names.replace(/\bas\b/g, ':')} } = ${module === 'vue' ? 'Vue' : 'Renderer'};`);
if (/^\s*(?:import|export)\s/m.test(executable)) throw new Error('Compiler generated an unsupported import; no code stubbing allowed');
const Component = new Function('Vue', 'Renderer', executable + '\nreturn __component;')(Vue, Renderer);

export async function render(evidence) {
  return Renderer.renderToString(Vue.createSSRApp(Component, { evidence }));
}

export function visible(html) {
  return html.replace(/<details\b[^>]*>[\s\S]*?<\/details>/g, '');
}

export function text(html) { return html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim(); }
export function lane(html, market) {
  const match = html.match(new RegExp(`<article\\b[^>]*data-market="${market}"[^>]*>([\\s\\S]*?)<\\/article>`));
  return match ? text(match[1]) : '';
}

export function fixture() {
  return {
    status: 'SELECTION_REFERENCES_PARTIALLY_BOUND_EXECUTION_UNVERIFIED',
    trade_date: '20261009', stage_id: 'STAGE_0940_0945',
    execution_verified: false, natural_verified: false,
    attempt_mode: 'NATURAL', due_status: 'DUE', declared_status: 'PARTIAL_WITH_ROWS',
    receipt_history_binding: 'OWNER_HISTORY_NOT_RECORDED', recorded_at: null,
    cannot_confirm: ['NO_INDEPENDENT_RUN_RECEIPT_SHA_BINDING'],
    markets: {
      A_SHARE: { selection_binding: 'BOUND_TO_VERIFIED_SELECTION', selected_rows: 10,
        requested_rows: 216, source_rows: 206, observed_rows: 206, accepted_rows: null, reasons: [] },
      HK_CONNECT: { selection_binding: 'NO_VERIFIED_SELECTION_BINDING', selected_rows: 0,
        requested_rows: null, source_rows: null, observed_rows: null, accepted_rows: null,
        status: 'CANNOT_CONFIRM', failure_layer: 'PRESELECTION_INPUT',
        reasons: ['HK D1 status must be STRICT_0_2_READY'] },
    },
    selection_results: {
      A_SHARE: { status: 'RESULT_AVAILABLE', selected_rows: 10, requested_rows: 216,
        source_rows: 206, missing_quote_rows: 10, quote_coverage_ratio: 206 / 216 },
      HK_CONNECT: { status: 'NO_VERIFIED_RESULT', selected_rows: null, requested_rows: null,
        source_rows: null, missing_quote_rows: null, quote_coverage_ratio: null },
    },
    selection_artifact_bindings: {},
  };
}
