#!/usr/bin/env node
/** Offline integration of the actual panel and validators. No browser/live API. */
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve, relative, extname } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { registerHooks, stripTypeScriptTypes } from 'node:module';
import { parseHTML } from '../test_support/vendor/linkedom-worker.mjs';

const workRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const options = {};
for (let i = 2; i < process.argv.length; i += 2) {
  if (!['--source-root', '--tests', '--suite', '--support-root', '--report'].includes(process.argv[i]) || !process.argv[i + 1]) {
    throw new Error('Usage: node tools/run_ui_harness.mjs --source-root PATH [--tests PATH | --suite PATH] [--support-root PATH] [--report PATH]');
  }
  options[process.argv[i].slice(2)] = resolve(process.argv[i + 1]);
}
const sourceRoot = options['source-root'] || resolve(workRoot, 'candidate');
const tests = options.tests || options.suite || resolve(workRoot, 'candidate/apps/web/src/manager-selection/catalystObservationPanel.repair.spec.ts');
const reportPath = options.report || resolve(workRoot, 'reports/ui_harness.json');
const supportRoot = options['support-root'] || resolve(workRoot, 'test_support/upstream');
const suiteSourceDir = resolve(sourceRoot, 'apps/web/src/manager-selection');
const sha256 = value => createHash('sha256').update(value).digest('hex');
const modules = new Map();

function resolveSource(path) {
  const candidates = [path];
  if (extname(path) === '.js') candidates.push(path.slice(0, -3) + '.ts');
  if (!extname(path)) candidates.push(path + '.ts', path + '.js');
  return candidates.find(candidate => existsSync(candidate));
}

registerHooks({
  resolve(specifier, context, nextResolve) {
    if ((specifier.startsWith('.') || specifier.startsWith('file:')) && context.parentURL?.startsWith('file:')) {
      let requested = fileURLToPath(new URL(specifier, context.parentURL));
      // The exact same repair cases must run against either source tree.
      if (context.parentURL === pathToFileURL(tests).href && specifier.startsWith('.')) {
        // Resolve application imports by their original source directory even
        // when the delivered test file itself lives outside the source tree.
        requested = resolve(suiteSourceDir, specifier);
      }
      let found = resolveSource(requested);
      if (!found) {
        const sourceRelative = relative(sourceRoot, requested);
        if (!sourceRelative.startsWith('..')) found = resolveSource(resolve(supportRoot, sourceRelative));
      }
      if (found) return { url: pathToFileURL(found).href, shortCircuit: true };
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url.startsWith('file:') && url.endsWith('.ts')) {
      const path = fileURLToPath(url);
      const bytes = readFileSync(path);
      modules.set(path, { path, sha256: sha256(bytes), bytes: bytes.length,
        origin: path === tests ? 'TEST' : path.startsWith(supportRoot + '/') ? 'RECOVERED_TEST_SUPPORT' : 'SOURCE_UNDER_TEST' });
      return { format: 'module', source: stripTypeScriptTypes(bytes.toString('utf8'), { mode: 'transform' }), shortCircuit: true };
    }
    return nextLoad(url, context);
  },
});

const { window } = parseHTML('<!doctype html><html><head></head><body></body></html>');
// Explicit support for the two form properties absent from LinkeDOM's worker.
// These implement reflected values only, never production behavior or assertions.
Object.defineProperty(window.HTMLSelectElement.prototype, 'value', {
  configurable: true,
  get() { return (this.querySelector('option[selected]') || this.querySelector('option'))?.value || ''; },
  set(value) {
    for (const option of this.querySelectorAll('option')) option.removeAttribute('selected');
    const selected = [...this.querySelectorAll('option')].find(option => option.value === String(value));
    if (selected) selected.setAttribute('selected', '');
  },
});
Object.defineProperty(window.HTMLDetailsElement.prototype, 'open', {
  configurable: true, get() { return this.hasAttribute('open'); },
  set(value) { if (value) this.setAttribute('open', ''); else this.removeAttribute('open'); },
});
let currentUrl = new URL('http://offline.invalid/manager-selection?date=20261010&plan_date=20261012');
const location = {};
for (const key of ['href', 'search', 'pathname', 'hash', 'origin', 'protocol', 'host']) {
  Object.defineProperty(location, key, { get: () => currentUrl[key],
    set: value => { if (key === 'href') currentUrl = new URL(value, currentUrl); else currentUrl[key] = value; } });
}
const history = { state: null, replaceState(state, _title, url) {
  this.state = state;
  if (url != null) currentUrl = new URL(url, currentUrl);
}, pushState(state, title, url) { this.replaceState(state, title, url); } };
Object.assign(window, { location, history });
for (const name of ['window', 'document', 'Event', 'CustomEvent', 'HTMLElement', 'HTMLDetailsElement',
  'HTMLInputElement', 'HTMLButtonElement', 'Node', 'Element', 'MutationObserver']) {
  Object.defineProperty(globalThis, name, { value: name === 'window' ? window : window[name], configurable: true, writable: true });
}
Object.defineProperty(globalThis, 'location', { value: location, configurable: true });
Object.defineProperty(globalThis, 'history', { value: history, configurable: true });
// Cases replace this stub with explicit synthetic responses. Any unconfigured fetch fails closed.
globalThis.fetch = async () => { throw new Error('OFFLINE_HARNESS_FETCH_NOT_CONFIGURED'); };

const startedAt = new Date().toISOString();
const results = [];
let setupError;
try {
  const suite = await import(pathToFileURL(tests).href);
  if (!Array.isArray(suite.repairCases) || !suite.repairCases.length) throw new Error('repairCases export missing or empty');
  for (const test of suite.repairCases) {
    const started = performance.now();
    try {
      await test.run();
      results.push({ name: test.name, status: 'PASS', duration_ms: Math.round(performance.now() - started) });
    } catch (error) {
      results.push({ name: test.name, status: 'FAIL', duration_ms: Math.round(performance.now() - started),
        error: String(error?.stack || error) });
    }
  }
} catch (error) { setupError = String(error?.stack || error); }
const vendorPath = resolve(workRoot, 'test_support/vendor/linkedom-worker.mjs');
const report = {
  schema_version: 'offline-mounted-panel-integration.v1',
  mode: 'DOM_INTEGRATION', live_api_ui: 'LIVE_API_UI_NOT_RUN',
  command: [process.execPath, ...process.argv.slice(1)],
  resolved_options: { source_root: sourceRoot, tests, support_root: supportRoot,
    suite_source_directory: suiteSourceDir, report: reportPath },
  source_root: sourceRoot, tests, started_at: startedAt, finished_at: new Date().toISOString(),
  node_version: process.version,
  dom: { package: 'WebReflection/linkedom', version: '0.18.12', license: 'ISC',
    worker_git_blob_sha: '21ed3f9cf1d80eebb2d0448d95c0dd080a5fd9fe', sha256: sha256(readFileSync(vendorPath)),
    limitations: ['No browser layout, paint, screenshots, real navigation, or live server',
      'No native details default click/toggle synthesis; tests explicitly dispatch toggle when needed',
      'Test-support shims provide select.value and reflected details.open only',
      'All fetch responses are synthetic; unconfigured fetch fails closed'] },
  totals: { pass: results.filter(result => result.status === 'PASS').length,
    fail: results.filter(result => result.status === 'FAIL').length },
  setup_error: setupError || null, tests_results: results,
  source_modules: [...modules.values()].sort((a, b) => a.path.localeCompare(b.path)),
};
mkdirSync(dirname(reportPath), { recursive: true });
writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n');
const log = [JSON.stringify({ command: report.command, mode: report.mode, live_api_ui: report.live_api_ui,
  ...report.totals, setup_error: report.setup_error, report: reportPath }),
  ...results.map(result => `${result.status} ${result.name}${result.error ? '\n' + result.error : ''}`)].join('\n') + '\n';
writeFileSync(reportPath.replace(/\.json$/, '') + '.log', log);
console.log(log.trimEnd());
if (setupError || report.totals.fail) process.exitCode = 1;
