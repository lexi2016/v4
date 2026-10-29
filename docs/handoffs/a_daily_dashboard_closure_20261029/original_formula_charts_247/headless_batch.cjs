// This batch only: reuse the accepted headless canvas/DOM checks, one private Chrome.
const fs = require('fs'), os = require('os'), path = require('path');
const {pathToFileURL} = require('url');
const {chromium} = require('/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const output = path.resolve(process.argv[2]);
const plan = JSON.parse(fs.readFileSync(path.join(output, 'PLANNED_ORDER.json'))).order;
const priority = ['002003.SZ', '601088.SH', '603444.SH'];
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'd35c-current247-'));
const checkpoints = path.join(output, 'render_checkpoints'), pngs = path.join(output, 'pngs');
fs.mkdirSync(checkpoints, {recursive: true}); fs.mkdirSync(pngs, {recursive: true});
const result = {status: 'RUNNING', samples: {}, errors: {}, headless: true, own_temporary_profile: true,
  user_GUI_or_profile_access: false, network_writes_blocked: true, browser_closed: false, temporary_profile_removed: false,
  concurrency_initial: 2, concurrency_maximum: 4, concurrency_changes: []};
const active = new Map();
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const started = Date.now();
let context, browser;

async function render(symbol, item) {
  const page = await context.newPage(), errors = [], t = Date.now();
  page.on('pageerror', error => errors.push(String(error)));
  page.on('console', message => {if (message.type() === 'error') errors.push(message.text());});
  try {
    await page.goto(pathToFileURL(item.html.path).href, {waitUntil: 'load', timeout: 60000});
    await page.waitForFunction(symbol => document.documentElement.dataset.loaded === symbol, symbol, {timeout: 30000});
    const observed = await page.evaluate(() => {
      const state = window.RESEARCH_PANEL_STATE, canvas = document.querySelector('#chart');
      const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
      let nonempty = false; for (let i = 3; i < pixels.length; i += 4) if (pixels[i]) {nonempty = true; break;}
      return {symbol: state.symbol, last_date: state.rows.at(-1).trade_date, total_rows: state.rows.length,
        visible_rows: state.visible.length, markers: state.markers, variable_table_rows: document.querySelectorAll('#values tr').length,
        drawing_table_rows: document.querySelectorAll('#drawings tr').length, text_enabled: document.querySelector('#draw-text').checked,
        canvas_pixels: [canvas.width, canvas.height], canvas_nonempty: nonempty};
    });
    if (observed.symbol !== symbol || observed.last_date !== 20261029 || observed.total_rows !== item.rows ||
        observed.variable_table_rows !== 51 || observed.drawing_table_rows !== 22 || !observed.text_enabled || !observed.canvas_nonempty || errors.length)
      throw new Error('ACTUAL_RENDER_CONTRACT_FAILED:' + JSON.stringify({observed, errors}));
    const screenshot = path.join(pngs, symbol.replace('.', '_') + '.actual.png');
    await page.screenshot({path: screenshot, fullPage: true});
    const record = {...observed, screenshot, status: 'MECHANICAL_HEADLESS_RENDER_PASS_NOT_SEMANTIC_REVIEW', seconds: (Date.now() - t) / 1000, errors};
    fs.writeFileSync(path.join(checkpoints, symbol.replace('.', '_') + '.json'), JSON.stringify(record) + '\n');
    result.samples[symbol] = record;
    if (priority.includes(symbol)) console.log(JSON.stringify({event: 'PRIORITY_PNG_READY', symbol, screenshot}));
    else if (Object.keys(result.samples).length % 25 === 0) console.log(JSON.stringify({event: 'PNG_PROGRESS', completed: Object.keys(result.samples).length}));
  } catch (error) {
    result.errors[symbol] = {reason: String(error), errors};
    fs.writeFileSync(path.join(checkpoints, symbol.replace('.', '_') + '.json'), JSON.stringify({status: 'CANNOT_CONFIRM', reason: String(error)}) + '\n');
  } finally {await page.close();}
}

(async () => {
  try {
    context = await chromium.launchPersistentContext(profile, {headless: true,
      executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', viewport: {width: 1600, height: 1200},
      args: ['--no-first-run', '--no-default-browser-check', '--disable-extensions', '--disable-background-networking', '--disable-sync']});
    browser = context.browser();
    await context.route('**/*', route => route.request().url().startsWith('file://') && ['GET', 'HEAD'].includes(route.request().method()) ? route.continue() : route.abort());
    for (const symbol of plan) {
      const file = path.join(checkpoints, symbol.replace('.', '_') + '.json');
      if (fs.existsSync(file)) {
        const prior = JSON.parse(fs.readFileSync(file));
        if (prior.status === 'MECHANICAL_HEADLESS_RENDER_PASS_NOT_SEMANTIC_REVIEW' && fs.existsSync(prior.screenshot)) result.samples[symbol] = prior;
      }
    }
    let limit = 2;
    while (true) {
      const progress = JSON.parse(fs.readFileSync(path.join(output, 'BATCH_PROGRESS.json')));
      const nextLimit = progress.computing_done && progress.resources.job_RSS_conservative_bytes < 32 * 2**30 &&
        progress.resources.available_reclaimable_estimate_bytes > 32 * 2**30 ? 4 : 2;
      if (nextLimit !== limit) {limit = nextLimit; result.concurrency_changes.push({at_seconds: (Date.now() - started) / 1000, pages: limit, resources: progress.resources});}
      const unfinishedPriority = priority.filter(s => !result.samples[s] && !result.errors[s] && !progress.failed[s]);
      const ordered = unfinishedPriority.length ? unfinishedPriority : plan;
      for (const symbol of ordered) {
        if (active.size >= limit) break;
        if (!progress.ready[symbol] || active.has(symbol) || result.samples[symbol] || result.errors[symbol]) continue;
        const promise = render(symbol, progress.ready[symbol]).finally(() => active.delete(symbol));
        active.set(symbol, promise);
      }
      const outstanding = Object.keys(progress.ready).some(s => !result.samples[s] && !result.errors[s]);
      if (progress.computing_done && !active.size && !outstanding) break;
      await pause(200);
    }
    result.status = Object.keys(result.errors).length ? 'PARTIAL_WITH_RENDER_ERRORS' : 'MECHANICAL_HEADLESS_BATCH_COMPLETE';
  } catch (error) {result.status = 'CANNOT_CONFIRM_CONTROLLER'; result.error = String(error); process.exitCode = 1;}
  finally {
    if (context) await context.close();
    result.browser_closed = !browser || !browser.isConnected();
    fs.rmSync(profile, {recursive: true, force: true}); result.temporary_profile_removed = !fs.existsSync(profile);
    result.wall_seconds = (Date.now() - started) / 1000;
    fs.writeFileSync(path.join(output, 'BATCH_RENDER_READBACK.json'), JSON.stringify(result, null, 2) + '\n');
  }
  console.log(JSON.stringify({event: 'HEADLESS_BATCH_FINISHED', status: result.status, rendered: Object.keys(result.samples).length,
    errors: Object.keys(result.errors).length, seconds: result.wall_seconds, browser_closed: result.browser_closed,
    profile_removed: result.temporary_profile_removed}));
})().catch(error => {console.error(String(error)); process.exitCode = 1;});
