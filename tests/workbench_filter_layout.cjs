// Real saved-data UI regression. No collection, calculation or account actions.
// WORKBENCH_PLAYWRIGHT_MODULE points at an existing Playwright installation.
// WORKBENCH_CANDIDATE_ROOT optionally overlays only the three changed assets.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.WORKBENCH_PLAYWRIGHT_MODULE || 'playwright');
const overlay = process.env.WORKBENCH_CANDIDATE_ROOT;
const output = process.env.WORKBENCH_TEST_OUTPUT;
const origin = process.env.WORKBENCH_TEST_ORIGIN || 'http://127.0.0.1:8873';
const assets = new Set(['workbench.html', 'workbench-host/bootstrap.mjs', 'workbench-host/dot/shell/workbench.local.mjs']);

(async () => {
  const browser = await chromium.launch({headless: true, channel: 'chrome'});
  const results = [];
  try {
    for (const width of [694, 1440, 390]) {
      const page = await browser.newPage({viewport: {width, height: 869}});
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      if (overlay) await page.route('**/research-panel/**', async route => {
        const relative = decodeURIComponent(new URL(route.request().url()).pathname.slice('/research-panel/'.length));
        if (!assets.has(relative)) return route.continue();
        await route.fulfill({path: path.join(overlay, relative), contentType: relative.endsWith('.mjs') ? 'text/javascript' : 'text/html'});
      });
      const dayResponse = page.waitForResponse(r => /\/workbench\/days\/2026-10-29\?/.test(r.url()));
      await page.goto(origin + '/research-panel/workbench.html?date=2026-10-29');
      const day = await (await dayResponse).json();
      await page.waitForFunction(() => document.querySelectorAll('#stockList button').length > 0);
      const count = () => page.locator('#listCount').innerText();
      const rows = () => page.locator('#stockList button');
      const inspect = () => page.evaluate(() => ({
        counts: document.querySelector('#listCount').textContent,
        pager: document.querySelector('#listPage').textContent,
        rows: document.querySelectorAll('#stockList button').length,
        selected: document.querySelector('#stockCode').textContent,
        scope: document.querySelector('#scope').value,
        activeGroup: document.querySelector('#groupFilters [aria-pressed=true]')?.textContent,
        listRect: document.querySelector('#stockGridViewport').getBoundingClientRect().toJSON(),
        filtersBeforeList: !!(document.querySelector('#scope').compareDocumentPosition(document.querySelector('#stockList')) & Node.DOCUMENT_POSITION_FOLLOWING),
        sourcesBelowList: !!(document.querySelector('#stockList').compareDocumentPosition(document.querySelector('.source-note')) & Node.DOCUMENT_POSITION_FOLLOWING),
      }));
      const initial = await inspect();
      const total = day.rows.filter(r => r.eligible_candidate).length;
      assert.equal(total, 247, 'Keep the existing frozen 247 candidate union');
      assert.equal(initial.rows, 40);
      assert.equal(initial.scope, 'candidates');
      assert.equal(initial.activeGroup, '全部候选');
      assert(initial.filtersBeforeList && initial.sourcesBelowList);
      assert(initial.listRect.height >= 240);
      assert(initial.pager.includes('共 7 页'));
      assert((await count()).includes('总候选 247只'));
      await page.locator('#nextList').click();
      assert((await count()).includes('（41–80）'));
      assert((await page.locator('#listPage').innerText()).includes('第 2 页'));
      await rows().first().click();
      assert.equal(await page.locator('#stockCode').innerText(), await rows().first().getAttribute('data-symbol'));
      const groupResults = [];
      for (const [index, group] of ['nav_smallk', 'original', 'nav_pullback', 'nav_breakout', 'pending', 'fifth'].entries()) {
        await page.locator('#groupFilters button').nth(index + 1).click();
        const expected = day.rows.filter(r => r.eligible_candidate && (group === 'pending' ? Object.values(r.group_states).includes('UNKNOWN') : group === 'fifth' ? r.in_fifth : r.group_states[group] === 'TRUE'));
        assert((await count()).includes(`筛选后 ${expected.length}只`));
        assert.equal(await rows().count(), Math.min(expected.length, 40));
        if (expected.length) {
          const selected = await page.locator('#stockCode').innerText();
          assert(expected.some(r => r.symbol === selected), 'Selected stock stays in filtered result');
          assert((await page.locator('#listPage').innerText()).includes('第 1 页'));
        } else assert(await page.locator('#content').isHidden());
        groupResults.push({group, count: expected.length});
      }
      await page.locator('#groupFilters button').first().click();
      await page.locator('#scope').selectOption('all');
      assert((await count()).includes(`当前范围 ${day.rows.length}只`));
      await page.locator('#query').fill('联化科技');
      assert.equal(await rows().count(), 1);
      assert((await rows().first().innerText()).includes('联化科技'));
      await page.locator('#query').fill('__no_stock_matches_this_query__');
      assert.equal(await rows().count(), 0);
      assert((await count()).includes('筛选后 0只 · 本页 0只'));
      assert((await page.locator('#listPage').innerText()).includes('第 0 页 / 共 0 页'));
      assert(await page.locator('#content').isHidden());
      assert(await page.locator('#prevList').isDisabled());
      assert(await page.locator('#nextList').isDisabled());
      await page.locator('#query').fill('');
      await page.locator('#nextList').click();
      await page.locator('[data-stock-sort=name]').click();
      assert((await page.locator('#listPage').innerText()).includes('第 1 页'));
      assert.equal(await page.locator('#stockSort').inputValue(), 'name_asc');
      await page.locator('[data-stock-sort=name]').click();
      assert.equal(await page.locator('#stockSort').inputValue(), 'name_desc');
      await page.locator('#showStockRates').click();
      await page.locator('[data-stock-sort=d2]').click();
      assert.equal(await page.locator('#stockSort').inputValue(), 'd2_desc');
      await page.locator('[data-stock-sort=d2]').click();
      assert.equal(await page.locator('#stockSort').inputValue(), 'd2_asc');
      await page.locator('[data-stock-sort=d5]').click();
      assert.equal(await page.locator('#stockSort').inputValue(), 'd5_desc');
      await page.locator('#showStockNames').click();
      const classification = page.locator('.classification-filter');
      await classification.locator('summary').click();
      await page.locator('#classificationQuery').fill('__no_classification_matches__');
      assert.equal(await rows().count(), 0);
      await page.locator('#classificationQuery').fill('');
      await classification.locator('summary').click();
      await page.locator('#scope').selectOption('candidates');
      await page.locator('#groupFilters button').first().click();
      assert.equal(await rows().count(), 40);
      assert.equal(new URL(page.url()).searchParams.get('date'), '2026-10-29');
      assert((await page.locator('#date').inputValue()).startsWith('2026-10-29|'));
      await page.locator('#showStockNames').click();
      await page.waitForTimeout(350);
      if (output) await page.screenshot({path: path.join(output, `AFTER_${width}.png`), fullPage: true});
      assert.deepEqual(errors, []);
      results.push({width, initial, groups: groupResults, final: await inspect(), checks: 'scope/group/search/classification/counts/page/switch/sort/empty/date PASS', errors});
      await page.close();
    }
    if (output) fs.writeFileSync(path.join(output, 'BROWSER_RESULT.json'), JSON.stringify({status: 'PASS', mode: overlay ? 'CANDIDATE_THREE_ASSET_OVERLAY_WITH_REAL_API' : 'ACTUAL_DEPLOYED_GET', results}, null, 2));
    console.log(JSON.stringify({status: 'PASS', widths: results.map(r => r.width), mode: overlay ? 'candidate overlay; real API' : 'actual deployed page'}));
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
