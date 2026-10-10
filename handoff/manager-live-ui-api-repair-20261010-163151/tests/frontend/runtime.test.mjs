/**
 * Real panel + real fetch/parser/validators in offline Chromium. No API/owner runs.
 * The pinned test dependency directory or supplied primary runtime provides Playwright.
 * FRONTEND_SOURCE_ROOT can point at the immutable baseline to prove regression failure.
 */
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { createHash } from 'node:crypto';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createRequire, stripTypeScriptTypes } from 'node:module';
import path from 'node:path';
import { portableBrowser } from './portable-browser.mjs';
import { workspaceFixture, readyWorkspaceFixture, sha } from './fixtures.mjs';

const require = createRequire(import.meta.url);
const depsRoot = path.resolve(process.env.FRONTEND_RUNTIME_DEPS || path.join(import.meta.dirname, 'runtime-deps'));
let playwrightRoot = path.join(depsRoot, 'node_modules/playwright');
let playwright;
try { playwright = require(playwrightRoot); }
catch (error) {
  if (error.code !== 'MODULE_NOT_FOUND' || !process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES) throw error;
  playwrightRoot = path.join(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES, 'playwright');
  playwright = require(playwrightRoot);
}
const playwrightVersion = require(path.join(playwrightRoot, 'package.json')).version;
const root = path.resolve(import.meta.dirname, '../..');
const sourceRoot = path.resolve(process.env.FRONTEND_SOURCE_ROOT || path.join(root, 'candidate/apps/web/src'));
const supportRoot = path.resolve(process.env.FRONTEND_SUPPORT_ROOT || path.join(import.meta.dirname, 'support'));
// Screenshots may opt in to locally installed CJK fonts; regression tests do not require them.
const fontRoot = process.env.FRONTEND_CJK_FONT_ROOT && path.resolve(process.env.FRONTEND_CJK_FONT_ROOT);
const sourceNames = [
  'api/managerWorkspace.ts', 'api/managerAnnouncementAnalysis.ts',
  'manager-selection/catalystObservationPanel.ts', 'manager-selection/dailyChannels.ts',
  'manager-selection/businessStatus.ts', 'manager-selection/researchAttention.ts',
  'manager-selection/announcementObservation.ts', 'manager-selection/announcementAnalysis.ts',
  'manager-selection/adapters/workspaceDecision.ts',
];
const modules = new Map();
let fontCss = '';
let launchOptions;
let runtimeProvenance;
const runningBrowsers = new Set();
before(async () => {
  if (fontRoot) {
    fontCss = (await Promise.all(['400.css', '700.css'].map((filename) => readFile(path.join(fontRoot, filename), 'utf8')))).join('\n');
  }
  const provenance = [];
  for (const name of sourceNames) {
    let filename = path.join(sourceRoot, name);
    let source;
    try { source = await readFile(filename, 'utf8'); }
    catch (error) {
      if (error.code !== 'ENOENT') throw error;
      filename = path.join(supportRoot, name);
      source = await readFile(filename, 'utf8');
    }
    const javascript = stripTypeScriptTypes(source, { mode: 'strip', sourceUrl: filename });
    modules.set(`/src/${name.replace(/\.ts$/, '.js')}`, javascript);
    modules.set(`/src/${name.replace(/\.ts$/, '')}`, javascript);
    provenance.push({ module: name, source: filename, sha256: createHash('sha256').update(source).digest('hex') });
  }
  runtimeProvenance = { synthetic_offline_test: true, sourceRoot, node: process.version,
    playwright: playwrightVersion, browser_mode: process.env.FRONTEND_PORTABLE_CHROMIUM === '1' ? 'portable-chromium' : 'playwright-installed-chromium',
    optional_cjk_font: Boolean(fontRoot), sources: provenance };
  if (process.env.FRONTEND_ARTIFACT_DIR) {
    await mkdir(process.env.FRONTEND_ARTIFACT_DIR, { recursive: true });
    await writeFile(path.join(process.env.FRONTEND_ARTIFACT_DIR, 'rendered_source_hashes.json'),
      JSON.stringify(runtimeProvenance, null, 2) + '\n');
  }
  const launch = { headless: true };
  if (process.env.FRONTEND_PORTABLE_CHROMIUM === '1') {
    Object.assign(launch, await portableBrowser());
  }
  launchOptions = launch;
});
after(async () => { await Promise.all([...runningBrowsers].map((browser) => browser.close())); });

async function mounted(t, fixture, viewport = { width: 1600, height: 1200 }) {
  // The portable headless shell runs a single process; each case gets its own browser.
  const browser = await playwright.chromium.launch(launchOptions);
  runningBrowsers.add(browser);
  t.after(async () => { await browser.close(); runningBrowsers.delete(browser); });
  if (!runtimeProvenance.browser_version) {
    runtimeProvenance.browser_version = browser.version();
    console.log(`Synthetic offline runtime: Node ${process.version}; Playwright ${playwrightVersion}; Chromium ${browser.version()}; optional CJK font ${Boolean(fontRoot)}`);
    if (process.env.FRONTEND_ARTIFACT_DIR) {
      await writeFile(path.join(process.env.FRONTEND_ARTIFACT_DIR, 'rendered_source_hashes.json'),
        JSON.stringify(runtimeProvenance, null, 2) + '\n');
    }
  }
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  page.setDefaultTimeout(5000);
  const requests = [], unexpected = [], errors = [];
  let response = fixture;
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/*', async (route) => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== 'https://fixture.invalid') {
      unexpected.push(request.url()); await route.abort(); return;
    }
    if (url.pathname === '/manager-selection/') {
      const optionalFont = fontRoot ? '<link rel="stylesheet" href="/fonts/panel.css"><style>body{font-family:"Noto Sans SC",sans-serif}</style>' : '';
      await route.fulfill({ contentType: 'text/html', body: `<!doctype html><html lang="zh"><meta charset="utf-8"><title>Synthetic offline manager panel regression</title>${optionalFont}<body><main id="host"></main></body></html>` });
    } else if (modules.has(url.pathname)) {
      await route.fulfill({ contentType: 'text/javascript', body: modules.get(url.pathname) });
    } else if (fontRoot && url.pathname === '/fonts/panel.css') {
      await route.fulfill({ contentType: 'text/css', body: fontCss });
    } else if (fontRoot && /^\/fonts\/files\/[a-z0-9-]+\.woff2?$/.test(url.pathname)) {
      await route.fulfill({ contentType: url.pathname.endsWith('woff2') ? 'font/woff2' : 'font/woff',
        body: await readFile(path.join(fontRoot, url.pathname.slice('/fonts/'.length))) });
    } else if (url.pathname === '/api/v4/manager/research/workspace' || url.pathname === '/api/v4/manager/research/workspace/refresh') {
      requests.push({ method: request.method(), url: request.url(), body: request.postData() });
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(response) });
    } else if (url.pathname === '/api/v4/manager/research/announcements' || url.pathname === '/api/v4/manager/research/announcements/analysis') {
      // Unrelated original read routes stay within the fixture boundary and have no data.
      await route.fulfill({ status: 503, contentType: 'application/json', body: '{"synthetic_fixture":"SIDE_READ_UNAVAILABLE"}' });
    } else {
      unexpected.push(request.url()); await route.abort();
    }
  });
  t.after(async () => {
    await context.close();
    assert.deepEqual(unexpected, [], 'No unhandled or external request may escape the fixture boundary');
    assert.deepEqual(errors, [], 'The real panel must not raise a browser runtime exception');
  });
  await page.goto(`https://fixture.invalid/manager-selection/?date=${fixture.target_trade_date}`);
  await page.evaluate(async (date) => {
    const { mountCatalystObservations } = await import('/src/manager-selection/catalystObservationPanel.js');
    window.disposePanel = mountCatalystObservations(document.querySelector('#host'), date);
  }, fixture.target_trade_date);
  await page.waitForFunction(() => ['READY', 'FAILED'].includes(document.querySelector('.manager-catalyst-observations')?.dataset.readState));
  await page.evaluate(() => document.fonts.ready);
  assert.equal(await page.locator('.manager-catalyst-observations').getAttribute('data-read-state'), 'READY',
    'Synthetic fixture must pass the preserved validator through the real fetch path before assertions');
  return { page, requests, replaceResponse: (next) => { response = next; } };
}

async function waitReady(page, previousRequestCount, requests) {
  await page.waitForFunction(() => document.querySelector('.manager-catalyst-observations')?.dataset.readState === 'READY');
  assert.equal(requests.length, previousRequestCount + 1);
}

test('real panel visibly renders all three response-bound channels while the saved plan remains stale', async (t) => {
  // Removing the renderDailyChannels call or placing its host in collapsed details must fail.
  const fixture = workspaceFixture();
  const { page, requests } = await mounted(t, fixture);
  const daily = page.locator('[data-daily-channels]');
  assert.equal(await daily.count(), 1, 'The existing panel must wire the daily-channel renderer');
  assert.equal(await daily.isVisible(), true);
  assert.deepEqual(await daily.locator('[data-daily-channel]').evaluateAll((nodes) => nodes.map((n) => n.dataset.dailyChannel)),
    ['ANNOUNCEMENT', 'HK_CONNECT', 'OVERSOLD']);
  assert.equal(await daily.locator('details[open]').count(), 0);
  const visible = await daily.innerText();
  assert.equal(await daily.evaluate((node) => node.querySelector('h3').getBoundingClientRect().bottom < window.innerHeight), true,
    'The daily summary heading should be in the initial desktop viewport after core plan status');
  assert.match(visible, /来源\/选股日 20261009 · 公告日 20261008 · 计划日 20261009/);
  for (const name of ['ANNOUNCEMENT', 'HK_CONNECT', 'OVERSOLD', 'CANNOT_CONFIRM', 'PARTIAL',
    'ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED', 'TARGET_DATE_MEMBERSHIP_CANNOT_CONFIRM', 'SCREEN_GAP_695',
    '待核 693', '候选数量未知', '待核数量未知', 'SYNTHETIC_ANNOUNCEMENT_OWNER', '产物 SHA256', sha('c')]) {
    assert.ok(visible.includes(name), `Visible daily summary is missing ${name}`);
  }
  assert.match(await page.locator('.business-status-row').first().innerText(), /STALE_INPUTS_CHANGED/);
  const identity = page.getByRole('region', { name: '计划输入身份核对' });
  assert.match(await identity.innerText(), /consumed=false/);
  assert.match(await identity.innerText(), /projection\.materials/);
  assert.equal(await identity.locator('details').getAttribute('open'), null);
  await identity.locator('summary').click();
  assert.deepEqual(JSON.parse(await identity.locator('pre').innerText()), fixture.plan_product.input_identity_diagnostics);
  assert.deepEqual(requests.map((request) => [request.method, new URL(request.url).searchParams.get('date')]), [['GET', '20261009']]);
  if (process.env.FRONTEND_ARTIFACT_DIR) {
    await identity.locator('summary').click();
    await page.screenshot({ path: path.join(process.env.FRONTEND_ARTIFACT_DIR, 'synthetic-panel.png'), fullPage: true });
  }
});

test('real panel distinguishes validated candidates and a validated empty set with visible run and product identities', async (t) => {
  // Removing visible run/product/source fields or converting empty/unknown to one status must fail.
  const fixture = readyWorkspaceFixture();
  const { page } = await mounted(t, fixture);
  const announcement = page.locator('[data-daily-channel="ANNOUNCEMENT"]');
  const hk = page.locator('[data-daily-channel="HK_CONNECT"]');
  const oversold = page.locator('[data-daily-channel="OVERSOLD"]');
  assert.equal(await announcement.count(), 1, 'Daily results must be mounted by the real panel');
  assert.match(await announcement.innerText(), /READY · 结果已核/);
  assert.match(await announcement.innerText(), /合成公告候选 · HK\.09999/);
  assert.match(await announcement.innerText(), /候选 1 只.*待核 0/);
  assert.ok((await announcement.innerText()).includes(sha('7')));
  assert.match(await announcement.innerText(), /synthetic-announcement-run/);
  assert.match(await hk.innerText(), /合成港股通候选 · HK\.09998/);
  assert.ok((await hk.innerText()).includes(fixture.plan_product.sha256));
  assert.match(await hk.innerText(), /synthetic-plan-run/);
  assert.match(await oversold.innerText(), /READY_EMPTY · 已核空集/);
  assert.match(await oversold.innerText(), /候选 0 只.*待核 0/);
  assert.match(await oversold.innerText(), /原 owner 已核空集/);
  assert.match(await oversold.innerText(), /自然时段运行验收：CANNOT_CONFIRM/);
  await announcement.locator('summary').click();
  assert.deepEqual(JSON.parse(await announcement.locator('pre').innerText()), fixture.daily_channels.channels[0]);
});

test('all three daily statuses are in the first 670-by-900 viewport after the plan consumption status', async (t) => {
  const { page } = await mounted(t, workspaceFixture(), { width: 670, height: 900 });
  const daily = page.locator('[data-daily-channels]');
  assert.equal(await daily.count(), 1);
  const visibleStatuses = await daily.locator('[data-daily-channel] > strong').evaluateAll((nodes) =>
    nodes.map((node) => { const box = node.getBoundingClientRect(); return box.top >= 0 && box.bottom <= window.innerHeight; }));
  assert.deepEqual(visibleStatuses, [true, true, true], 'Each channel status must be visible before the secondary status/detail sections');
  assert.equal(await page.locator('.business-status-row').first().evaluate((node) =>
    Boolean(node.compareDocumentPosition(document.querySelector('[data-daily-channels]')) & Node.DOCUMENT_POSITION_FOLLOWING)), true);
  if (process.env.FRONTEND_ARTIFACT_DIR) {
    await page.screenshot({ path: path.join(process.env.FRONTEND_ARTIFACT_DIR, 'synthetic-panel-670.png'), fullPage: false });
  }
});

for (const reviewedCount of [4, 7, null]) {
  test(`US assessment and the daily mapping are adjacent, distinct scopes with reviewed count ${reviewedCount}`, async (t) => {
    // Reintroducing hardcoded four/33, or using daily status as assessment, must fail.
    const { page } = await mounted(t, workspaceFixture({ reviewedCount }));
    const scope = reviewedCount === null ? '数量未知' : `${reviewedCount} 项`;
    const rows = await page.locator('.business-status-row').allInnerTexts();
    const assessmentIndex = rows.findIndex((row) => row.startsWith('美股评估/完整度：'));
    assert.ok(assessmentIndex >= 0, 'Upper status must name the assessment/completeness scope');
    assert.match(rows[assessmentIndex], /尚未评估/);
    assert.ok(rows[assessmentIndex + 1].startsWith(`每日 US-HK 已审映射（${scope}）：VALID_EMPTY`));
    assert.match(rows[assessmentIndex + 1], /不代表全市场/);
    assert.match(rows[assessmentIndex + 1], /不代表美股评估\/完整度已完成/);
    const dailyMapping = await page.locator('[data-us-mapping-research]').innerText();
    assert.ok(dailyMapping.includes(`每日 US-HK 已审映射（${scope}）`));
    assert.match(dailyMapping, /VALID_EMPTY/);
    assert.match(dailyMapping, /匹配为0/);
    assert.match(dailyMapping, /不代表全市场/);
    assert.doesNotMatch(dailyMapping, /当前4个|固定33只/);
    if (reviewedCount !== 4) assert.doesNotMatch(dailyMapping, /4 个|4 项|4只|4个/);
  });
}

test('core plan and research results precede a collapsed audit retaining all 100 raw rows on repeated renders', async (t) => {
  // Leaving stock rows before research, making the outer audit open, or slicing rows must fail.
  const fixture = workspaceFixture({ rawCount: 100 });
  const { page, requests } = await mounted(t, fixture);
  const audit = page.locator('details[data-raw-observations]');
  assert.equal(await audit.count(), 1, 'All existing raw stock observations need one outer expandable audit');
  assert.equal(await audit.getAttribute('open'), null);
  assert.match(await audit.locator(':scope > summary').innerText(), /100/);
  const ordering = await page.evaluate(() => {
    const audit = document.querySelector('[data-raw-observations]');
    return ['.business-status', '[data-daily-channels]', '[aria-label="证据优先研究"]'].every((selector) =>
      Boolean(document.querySelector(selector).compareDocumentPosition(audit) & Node.DOCUMENT_POSITION_FOLLOWING));
  });
  assert.equal(ordering, true);
  assert.equal(await audit.locator('.decision-stock').count(), 100);
  assert.equal(await audit.locator('.decision-stock').first().isVisible(), false);
  assert.deepEqual(await audit.locator('.decision-stock').evaluateAll((nodes) => nodes.map((n) => n.dataset.stockKey)),
    fixture.stocks.map((stock) => stock.stock_key));
  await audit.locator(':scope > summary').click();
  await audit.locator('details[data-background] > summary').click();
  const lastStock = audit.locator('.decision-stock').last();
  await lastStock.locator(':scope > summary').click();
  await lastStock.getByText('本股完整可追溯预案与来源分类', { exact: true }).click();
  assert.deepEqual(JSON.parse(await lastStock.locator('pre').last().innerText()), fixture.stocks[99]);
  const previousCount = requests.length;
  await page.getByRole('button', { name: '读取更新', exact: true }).click();
  await waitReady(page, previousCount, requests);
  assert.equal(await audit.getAttribute('open'), null, 'New response starts with the full audit collapsed');
  assert.equal(await audit.locator('.decision-stock').count(), 100);
  assert.deepEqual(await audit.locator('.decision-stock').evaluateAll((nodes) => nodes.map((n) => n.dataset.stockKey)),
    fixture.stocks.map((stock) => stock.stock_key));
});

test('a date change clears the prior daily display and renders the new response date bindings', async (t) => {
  // Passing URL publication state or initialDate instead of response.date_bindings must fail.
  const fixture = readyWorkspaceFixture();
  const { page, requests, replaceResponse } = await mounted(t, fixture);
  const next = readyWorkspaceFixture({ target: '20261012', publication: '20261009', selection: '20261009' });
  replaceResponse(next);
  const previousCount = requests.length;
  await page.getByLabel('计划目标日', { exact: true }).fill('2026-10-12');
  await waitReady(page, previousCount, requests);
  const daily = page.locator('[data-daily-channels]');
  assert.equal(await daily.count(), 1);
  assert.match(await daily.innerText(), /来源\/选股日 20261009 · 公告日 20261009 · 计划日 20261012/);
  assert.doesNotMatch(await daily.innerText(), /20261008/);
  assert.deepEqual(requests.map((r) => new URL(r.url).searchParams.get('date')), ['20261009', '20261012']);
});

const rejectionCases = [
  ['workspace target mismatch', (v) => { v.target_trade_date = '20261012'; }, 'WORKSPACE_IDENTITY_INVALID'],
  ['workspace plan binding mismatch', (v) => { v.date_bindings.plan_date = '20261012'; }, 'WORKSPACE_DAILY_DATE_BINDING_MISMATCH'],
  ['announcement date mismatch', (v) => { v.daily_channels.channels[0].announcement_date = '20261007'; }, 'WORKSPACE_DAILY_CHANNEL_INVALID'],
  ['HK selection date mismatch', (v) => { v.daily_channels.channels[1].selection_date = '20261008'; }, 'WORKSPACE_DAILY_CHANNEL_INVALID'],
  ['oversold target date mismatch', (v) => { v.daily_channels.channels[2].target_trade_date = '20261012'; }, 'WORKSPACE_DAILY_CHANNEL_INVALID'],
  ['plan run mismatch', (v) => { v.daily_channels.channels[1].run_id = 'wrong-run'; }, 'WORKSPACE_DAILY_RUN_REFERENCE_INVALID'],
  ['source SHA mismatch', (v) => { v.daily_channels.channels[0].rows[0].source_refs[0].payload_sha256 = 'bad-sha'; }, 'WORKSPACE_DAILY_SOURCE_REFERENCE_INVALID'],
  ['research-only flag disabled', (v) => { v.RESEARCH_ONLY = false; }, 'WORKSPACE_SAFETY_INVALID'],
  ['production enabled', (v) => { v.production_allowed = true; }, 'WORKSPACE_SAFETY_INVALID'],
  ['BUY gate changed', (v) => { v.daily_channels.channels[1].buy_gate_updated = true; }, 'WORKSPACE_DAILY_SAFETY_INVALID'],
  ['orders sent', (v) => { v.daily_channels.orders_sent = true; }, 'WORKSPACE_DAILY_SAFETY_INVALID'],
  ['stale plan presented as consumed channel run', (v) => { v.plan_product.status = 'STALE_INPUTS_CHANGED'; v.plan_product.consumed = false; }, 'WORKSPACE_DAILY_RUN_REFERENCE_INVALID'],
];
for (const [name, mutate, expectedCode] of rejectionCases) {
  test(`preserved validator rejects ${name} and the real panel clears prior candidates`, async (t) => {
    const fixture = readyWorkspaceFixture();
    const { page, requests, replaceResponse } = await mounted(t, fixture);
    const invalid = structuredClone(fixture);
    mutate(invalid);
    const rejection = await page.evaluate(async (raw) => {
      try { (await import('/src/api/managerWorkspace.js')).validateManagerWorkspace(raw, '20261009'); return null; }
      catch (error) { return error.message; }
    }, invalid);
    assert.equal(rejection, expectedCode);
    replaceResponse(invalid);
    const previousCount = requests.length;
    await page.getByRole('button', { name: '读取更新', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.manager-catalyst-observations')?.dataset.readState === 'FAILED');
    assert.equal(requests.length, previousCount + 1);
    const daily = page.locator('[data-daily-channels]');
    assert.equal(await daily.count(), 1, 'Failed contract should expose unknown channels without old results');
    assert.equal(await daily.locator('[data-daily-symbol]').count(), 0);
    assert.equal(await daily.locator('[data-daily-status="CANNOT_CONFIRM"]').count(), 3);
    assert.doesNotMatch(await daily.innerText(), /HK\.0999[89]|synthetic-plan-run|synthetic-announcement-run/);
    assert.match(await daily.innerText(), /CANNOT_CONFIRM/);
    assert.match(await page.locator('.manager-catalyst-observations > [role="status"]').innerText(), /合同校验失败/);
  });
}

test('legacy response without daily date bindings remains readable with explicit unknown channel dates', async (t) => {
  const fixture = workspaceFixture();
  delete fixture.daily_channels; delete fixture.date_bindings;
  const { page } = await mounted(t, fixture);
  const daily = page.locator('[data-daily-channels]');
  assert.equal(await daily.count(), 1);
  assert.match(await daily.innerText(), /日期绑定未提供 · CANNOT_CONFIRM/);
  assert.equal(await daily.locator('[data-daily-status="CANNOT_CONFIRM"]').count(), 3);
  assert.doesNotMatch(await daily.innerText(), /公告日 20261009/);
});

test('stale diagnostics without supported component evidence remain CANNOT_CONFIRM', async (t) => {
  const fixture = workspaceFixture();
  fixture.plan_product.input_identity_diagnostics = { status: 'CANNOT_CONFIRM', reason: 'SAVED_COMPONENT_BASELINE_MISSING' };
  const { page } = await mounted(t, fixture);
  const identity = page.getByRole('region', { name: '计划输入身份核对' });
  assert.equal(await identity.count(), 1);
  assert.match(await identity.innerText(), /consumed=false/);
  assert.match(await identity.innerText(), /CANNOT_CONFIRM/);
  assert.doesNotMatch(await identity.innerText(), /变化组件：projection\.materials/);
});

test('refresh uses one validated response for the plan and daily summary without another GET', async (t) => {
  const fixture = readyWorkspaceFixture();
  const { page, requests } = await mounted(t, fixture);
  await page.getByRole('button', { name: '用既有材料生成计划', exact: true }).click();
  await waitReady(page, 1, requests);
  assert.deepEqual(requests.map((r) => r.method), ['GET', 'POST']);
  assert.equal(await page.locator('[data-daily-channel="ANNOUNCEMENT"]').count(), 1);
  assert.match(await page.locator('[data-daily-channel="ANNOUNCEMENT"]').innerText(), /synthetic-announcement-run/);
});
