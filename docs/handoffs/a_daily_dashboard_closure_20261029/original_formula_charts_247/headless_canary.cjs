const fs = require('fs');
const os = require('os');
const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require('/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const samples = ['600814.SH'];

(async () => {
  const output = path.resolve(process.argv[2]);
  const manifest = JSON.parse(fs.readFileSync(path.join(output, 'MANIFEST.json')));
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'd35c-three-sample-'));
  const result = {scope: 'ONE_NEW_BOUND_D29_CACHE_CANARY', samples: [], headless: true,
    own_temporary_profile: true, user_GUI_or_profile_access: false,
    network_writes_blocked: true, browser_closed: false, temporary_profile_removed: false};
  let context, browser;
  try {
    context = await chromium.launchPersistentContext(profile, {
      headless: true, executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
      viewport: {width: 1600, height: 1200},
      args: ['--no-first-run', '--no-default-browser-check', '--disable-extensions', '--disable-background-networking', '--disable-sync'],
    });
    browser = context.browser();
    await context.route('**/*', route => route.request().url().startsWith('file://') && ['GET', 'HEAD'].includes(route.request().method())
      ? route.continue() : route.abort());
    for (const symbol of samples) {
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(String(error)));
      page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
      await page.goto(pathToFileURL(manifest.samples[symbol].html.path).href, {waitUntil: 'load', timeout: 30000});
      await page.waitForFunction(symbol => document.documentElement.dataset.loaded === symbol, symbol, {timeout: 15000});
      const observed = await page.evaluate(() => {
        const state = window.RESEARCH_PANEL_STATE;
        const canvas = document.querySelector('#chart');
        const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
        let nonempty = false;
        for (let i = 3; i < pixels.length; i += 4) if (pixels[i]) { nonempty = true; break; }
        return {symbol: state.symbol, last_date: state.rows.at(-1).trade_date, total_rows: state.rows.length,
          visible_rows: state.visible.length, markers: state.markers,
          variable_table_rows: document.querySelectorAll('#values tr').length,
          drawing_table_rows: document.querySelectorAll('#drawings tr').length,
          text_enabled: document.querySelector('#draw-text').checked,
          canvas_pixels: [canvas.width, canvas.height], canvas_nonempty: nonempty,
          caption: document.querySelector('#chart-caption').textContent,
          status: document.querySelector('#status').textContent};
      });
      if (observed.symbol !== symbol || observed.last_date !== 20261029 ||
          observed.total_rows !== manifest.samples[symbol].rows || observed.variable_table_rows !== 51 ||
          observed.drawing_table_rows !== 22 || !observed.canvas_nonempty || !observed.text_enabled || errors.length) {
        throw new Error('ACTUAL_RENDER_CONTRACT_FAILED: ' + JSON.stringify({observed, errors}));
      }
      const screenshot = path.join(output, symbol.replace('.', '_') + '.actual.png');
      await page.screenshot({path: screenshot, fullPage: true});
      result.samples.push({...observed, screenshot, errors, status: 'ACTUAL_RENDER_READBACK_PASS'});
      await page.close();
    }
    result.status = 'PASS_ACTUAL_NEW_CACHE_CANARY_READBACK';
  } catch (error) {
    result.status = 'FAILED_ACTUAL_READBACK';
    result.error = String(error);
    process.exitCode = 1;
  } finally {
    if (context) await context.close();
    result.browser_closed = !browser || !browser.isConnected();
    fs.rmSync(profile, {recursive: true, force: true});
    result.temporary_profile_removed = !fs.existsSync(profile);
    fs.writeFileSync(path.join(output, 'ACTUAL_RENDER_READBACK.json'), JSON.stringify(result, null, 2) + '\n');
  }
  console.log(JSON.stringify(result));
})().catch(error => { console.error(String(error)); process.exitCode = 1; });
