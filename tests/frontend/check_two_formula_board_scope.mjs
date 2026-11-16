import assert from 'node:assert/strict';

const origin = process.argv[2] ?? 'http://127.0.0.1:18974';
const {chromium} = await import(process.env.WORKBENCH_PLAYWRIGHT ?? 'playwright');
const browser = await chromium.launch({headless:true, executablePath:process.env.WORKBENCH_CHROME});
const endpoint = date => '/api/v4/research/workbench/days/' + date;
const pageUrl = date => origin + '/research-panel/workbench.html?source_date=' + date;
const ids = ['b23_entry', 'pb2_confirm'];

try {
  const day = await fetch(origin + endpoint('2026-11-16')).then(response => {
    assert.equal(response.status, 200);
    return response.json();
  });
  assert.equal(day.observation_date, '2026-11-17');
  assert.deepEqual(day.formula_groups.labels, {b23_entry:'192选股',pb2_confirm:'回测选股'});
  assert.deepEqual(day.formula_groups.group_counts, {b23_entry:105,pb2_confirm:49});
  assert.equal(day.rows.length, 133);
  assert.equal(day.rows.filter(row => ids.every(id => row.group_states[id] === 'TRUE')).length, 21);

  const page = await browser.newPage();
  const duplicateGroupRequests = [];
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (new URL(request.url()).pathname.endsWith('/v192')) duplicateGroupRequests.push(request.url());
  });
  await page.goto(pageUrl('2026-11-16'),{waitUntil:'domcontentloaded'});
  const filters = page.locator('#groupFilters button');
  const rows = page.locator('#stockList [data-symbol]');
  await page.locator('#groupFilters button[data-group="b23_entry"]:enabled').waitFor({timeout:20000});
  assert.deepEqual(await filters.allTextContents(), ['192选股 105','回测选股 49']);

  async function readAll(expected) {
    const seen = [];
    const next = page.locator('#nextList');
    do {
      seen.push(...await rows.evaluateAll(items => items.map(item=>item.dataset.symbol)));
      if (!await next.isEnabled()) break;
      await next.click();
    } while (seen.length < expected.length);
    assert.deepEqual(seen.sort(), expected.sort());
  }

  await readAll(day.rows.map(row => row.symbol));
  for (const id of ids) {
    const button = page.locator(`#groupFilters button[data-group="${id}"]`);
    await button.click();
    assert.equal(await button.getAttribute('aria-pressed'), 'true');
    await readAll(day.rows.filter(row => row.group_states[id] === 'TRUE').map(row => row.symbol));
  }
  assert.deepEqual(duplicateGroupRequests, []);
  assert.deepEqual(errors, []);

  const pendingDates = ['2026-11-12', '2026-10-28'];
  for (const date of pendingDates) {
    await page.goto(pageUrl(date),{waitUntil:'domcontentloaded'});
    await page.waitForFunction(() => document.querySelector('#loadingState')?.textContent?.includes('两组选股待物化'));
    assert.deepEqual(await filters.allTextContents(), ['192选股 待物化','回测选股 待物化']);
    assert.equal(await filters.locator(':enabled').count(), 0);
    assert.equal(await rows.count(), 0);
  }

  console.log(JSON.stringify({
    status:'PASS_TWO_FORMULA_BOARD_SCOPE', origin, source_date:day.source_date,
    observation_date:day.observation_date, generation:day.generation,
    input_sha256:day.input_sha256, numeric_manifest:day.numeric_manifest,
    group_counts:day.formula_groups.group_counts, union:day.rows.length,
    browser_paginated_membership:'EXACT_ALL_ROWS', duplicate_v192_route_requests:duplicateGroupRequests.length,
    missing_source_dates:pendingDates, browser_errors:errors,
  }));
} finally {
  await browser.close();
}
