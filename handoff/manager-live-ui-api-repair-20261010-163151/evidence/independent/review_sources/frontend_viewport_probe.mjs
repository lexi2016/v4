/** Independent read-only candidate render probe; every URL is fulfilled offline. */
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createRequire, stripTypeScriptTypes } from 'node:module';
import path from 'node:path';
import { workspaceFixture } from './frontend_fixtures.mjs';

const require = createRequire(import.meta.url);
const root = path.resolve(import.meta.dirname, '../..');
const { chromium: playwright } = require(path.join(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES, 'playwright'));
const { default: portable } = await import('../frontend/runtime-deps/node_modules/@sparticuz/chromium/build/index.js');
const binaryFolder = path.join(root, 'work/frontend/browser-bin');
const output = path.join(import.meta.dirname, 'frontend-viewport');
const fontRoot = path.join(root, 'work/frontend/runtime-deps/node_modules/@fontsource/noto-sans-sc');
const fontCss = (await Promise.all(['400.css', '700.css'].map(name => readFile(path.join(fontRoot, name), 'utf8')))).join('\n');
await mkdir(output, { recursive: true });
await mkdir(path.join(output, 'font-cache'), { recursive: true });
await mkdir(path.join(output, 'tmp'), { recursive: true });
await writeFile(path.join(output, 'fonts.conf'), `<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig><dir>${binaryFolder}/fonts</dir><dir>/usr/share/fonts</dir><cachedir>${output}/font-cache</cachedir><config></config></fontconfig>`);

const names = ['api/managerWorkspace.ts', 'api/managerAnnouncementAnalysis.ts',
  'manager-selection/catalystObservationPanel.ts', 'manager-selection/dailyChannels.ts',
  'manager-selection/businessStatus.ts', 'manager-selection/researchAttention.ts',
  'manager-selection/announcementObservation.ts', 'manager-selection/announcementAnalysis.ts',
  'manager-selection/adapters/workspaceDecision.ts'];
const modules = new Map();
for (const name of names) {
  let file = path.join(root, 'candidate/apps/web/src', name), source;
  try { source = await readFile(file, 'utf8'); }
  catch (error) {
    if (error.code !== 'ENOENT') throw error;
    file = path.join(root, 'work/frontend/support', name);
    source = await readFile(file, 'utf8');
  }
  const js = stripTypeScriptTypes(source, { mode: 'strip', sourceUrl: file });
  modules.set('/src/' + name.replace(/\.ts$/, '.js'), js);
  modules.set('/src/' + name.replace(/\.ts$/, ''), js);
}
const results = [];
for (const viewport of [{ width: 1600, height: 1200 }, { width: 1280, height: 800 }, { width: 670, height: 900 }, { width: 669, height: 848 }]) {
  const browser = await playwright.launch({ headless: true,
    executablePath: path.join(binaryFolder, 'chromium'), args: portable.args,
    env: { ...process.env, TMPDIR: path.join(output, 'tmp'), FONTCONFIG_PATH: output,
      LD_LIBRARY_PATH: [binaryFolder, process.env.LD_LIBRARY_PATH].filter(Boolean).join(':') } });
  try {
    const context = await browser.newContext({ viewport });
    const page = await context.newPage();
    const unexpected = [], errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const fixture = workspaceFixture();
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== 'https://fixture.invalid') { unexpected.push(url.href); return route.abort(); }
      if (url.pathname === '/manager-selection/') return route.fulfill({ contentType: 'text/html', body: '<!doctype html><html lang="zh"><meta charset="utf-8"><title>Independent synthetic viewport review</title><link rel="stylesheet" href="/fonts/panel.css"><style>body{font-family:"Noto Sans SC",sans-serif}</style><body><main id="host"></main></body></html>' });
      if (modules.has(url.pathname)) return route.fulfill({ contentType: 'text/javascript', body: modules.get(url.pathname) });
      if (url.pathname === '/fonts/panel.css') return route.fulfill({ contentType: 'text/css', body: fontCss });
      if (/^\/fonts\/files\/[a-z0-9-]+\.woff2?$/.test(url.pathname)) return route.fulfill({ contentType: url.pathname.endsWith('woff2') ? 'font/woff2' : 'font/woff', body: await readFile(path.join(fontRoot, url.pathname.slice('/fonts/'.length))) });
      if (url.pathname === '/api/v4/manager/research/workspace') return route.fulfill({ contentType: 'application/json', body: JSON.stringify(fixture) });
      if (url.pathname.startsWith('/api/v4/manager/research/announcements')) return route.fulfill({ status: 503, contentType: 'application/json', body: '{}' });
      unexpected.push(url.href); return route.abort();
    });
    await page.goto('https://fixture.invalid/manager-selection/?date=20261009');
    await page.evaluate(async () => (await import('/src/manager-selection/catalystObservationPanel.js')).mountCatalystObservations(document.querySelector('#host'), '20261009'));
    await page.waitForFunction(() => document.querySelector('.manager-catalyst-observations')?.dataset.readState === 'READY');
    await page.evaluate(() => document.fonts.ready);
    const geometry = await page.evaluate(() => {
      const daily = document.querySelector('[data-daily-channels]');
      const heading = daily.querySelector('h3').getBoundingClientRect();
      const cards = [...daily.querySelectorAll('[data-daily-channel]')].map(node => {
        const card = node.getBoundingClientRect(), status = node.querySelector(':scope > strong').getBoundingClientRect();
        return { id: node.dataset.dailyChannel, top: card.top, bottom: card.bottom,
          status_top: status.top, status_bottom: status.bottom,
          status_in_initial_viewport: status.top >= 0 && status.bottom <= innerHeight };
      });
      return { heading_top: heading.top, heading_bottom: heading.bottom,
        heading_in_initial_viewport: heading.top >= 0 && heading.bottom <= innerHeight,
        cards, business_status_height: document.querySelector('.business-status').getBoundingClientRect().height,
        scroll_width: document.documentElement.scrollWidth, viewport_width: innerWidth };
    });
    assert.deepEqual(unexpected, []);
    assert.deepEqual(errors, []);
    await page.screenshot({ path: path.join(output, `${viewport.width}x${viewport.height}.png`), fullPage: false });
    results.push({ viewport, ...geometry });
  } finally { await browser.close(); }
}
await writeFile(path.join(output, 'geometry.json'), JSON.stringify({ scope: 'SYNTHETIC_OFFLINE_PANEL_ONLY; LIVE_API_UI_NOT_RUN', results }, null, 2) + '\n');
console.log(JSON.stringify(results, null, 2));
process.exitCode = results.every(result => result.heading_in_initial_viewport && result.scroll_width === result.viewport_width && result.cards.every(card => card.status_in_initial_viewport)) ? 0 : 1;
