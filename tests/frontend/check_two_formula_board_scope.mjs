import assert from 'node:assert/strict';

const origin = process.argv[2] ?? 'http://127.0.0.1:18974';
const {chromium} = await import(process.env.WORKBENCH_PLAYWRIGHT ?? 'playwright');
const browser = await chromium.launch({headless:true, executablePath:process.env.WORKBENCH_CHROME});
const endpoint = date => '/api/v4/research/workbench/days/' + date;
const pageUrl = date => origin + '/research-panel/workbench.html?source_date=' + date;
const sourceDate = '2026-11-16';
const ids = ['b23_entry', 'pb2_confirm'];
const pendingLabels = ['192选股 待物化', '回测选股 待物化'];
const allowControlledResponses = process.argv.includes('--controlled-startup');

async function watchLegacyTabs(page) {
  await page.addInitScript(ids => {
    window.unexpectedWorkbenchTabs = [];
    new MutationObserver(changes => {
      for (const change of changes) {
        if (change.target.id !== 'groupFilters') continue;
        for (const tab of change.addedNodes) {
          if (tab.nodeName === 'BUTTON' && !ids.includes(tab.dataset.group)) {
            window.unexpectedWorkbenchTabs.push(tab.textContent);
          }
        }
      }
    }).observe(document, {childList:true, subtree:true});
  }, ids);
}

async function readPending(page) {
  await page.waitForFunction(() => document.querySelector('#loadingState')?.textContent?.includes('两组选股待物化'));
  const filters = page.locator('#groupFilters button');
  assert.deepEqual(await filters.allTextContents(), pendingLabels);
  assert.equal(await page.locator('#groupFilters button:enabled').count(), 0);
  assert.equal(await page.locator('#stockList [data-symbol]').count(), 0);
  assert.deepEqual(await page.evaluate(() => window.unexpectedWorkbenchTabs), []);
}

async function checkStartupCatalogueRace() {
  const page = await browser.newPage();
  const initialWorkflow = Promise.withResolvers(), releaseWorkflow = Promise.withResolvers();
  const firstObservation = Promise.withResolvers(), releaseObservation = Promise.withResolvers();
  const previousDate = '2026-11-13';
  let historyRequests = 0;
  await page.route('**/api/v4/research/workbench/workflow-contract', async route => {
    initialWorkflow.resolve();
    await releaseWorkflow.promise;
    await route.continue();
  });
  await page.route('**/api/v4/research/workbench/history', async route => {
    if (++historyRequests !== 1) return route.continue();
    const response = await route.fetch();
    const history = await response.json();
    // Simulate a newly published date using two actual installed catalog entries.
    history.days = history.days.filter(entry => entry.source_date <= previousDate);
    await route.fulfill({response, json:history});
  });
  await page.route(url => url.pathname === endpoint(previousDate) + '/observations', async route => {
    firstObservation.resolve();
    await releaseObservation.promise;
    await route.continue();
  });
  await page.addInitScript(() => {
    window.startupCatalogueReads = 0;
    const read = window.fetch;
    window.fetch = (input, options) => {
      const path = new URL(input instanceof Request ? input.url : input, location.href).pathname;
      if (path === '/api/v4/research/workbench/history') {
        window.startupCatalogueReads++;
      }
      return read(input, options);
    };
  });
  try {
    await page.goto(origin + '/research-panel/workbench.html?mode=latest', {waitUntil:'domcontentloaded'});
    await initialWorkflow.promise;
    const earlyCatalogueReads = await page.evaluate(() => {
      // The supported foreground refresh uses the same catalogue callback as a replay.
      window.pendingStartupRefresh = window.StockPanelHost.refreshSavedSources();
      return window.startupCatalogueReads;
    });
    assert.equal(earlyCatalogueReads, 0, 'catalogue refresh started a competing startup load');
    releaseWorkflow.resolve();
    await firstObservation.promise;
    // The next real source date is selectable while D13 optional observations are still held.
    await page.waitForFunction(date => document.querySelector('#researchDateStatus')?.textContent?.includes('来源 ' + date), sourceDate);
    const active = page.locator('#groupFilters button[data-group="b23_entry"]:enabled');
    await active.filter({hasText:'192选股 105'}).waitFor();
    releaseObservation.resolve();
    await page.evaluate(() => window.pendingStartupRefresh);
  } finally {
    releaseWorkflow.resolve();
    releaseObservation.resolve();
    await page.unrouteAll({behavior:'ignoreErrors'});
    await page.close();
  }
}

async function checkUnexpectedLegacyResponse() {
  const cases = {
    missing: day => { delete day.formula_groups; },
    legacy_row: day => { day.rows[0].group_states = {nav_smallk:'TRUE', original:'FALSE', nav_pullback:'FALSE', nav_breakout:'FALSE'}; },
    pending_rows: day => {
      day.formula_groups.status = 'CANNOT_CONFIRM_NOT_MATERIALIZED';
      day.formula_groups.group_counts = {b23_entry:null, pb2_confirm:null};
    },
    status: day => { day.formula_groups.status = 'PARTIAL'; },
    count_total: day => { day.formula_groups.group_counts.b23_entry--; },
    verified_empty: day => {
      day.formula_groups.status = 'READY_EMPTY';
      day.formula_groups.group_counts = {b23_entry:0, pb2_confirm:0};
      day.rows = [];
      day.scope_count = 0;
    },
  };
  for (const [name, mutate] of Object.entries(cases)) {
    const page = await browser.newPage();
    await watchLegacyTabs(page);
    await page.route(url => url.pathname === endpoint(sourceDate), async route => {
      const response = await route.fetch();
      const day = await response.json();
      mutate(day);
      await route.fulfill({response, json:day});
    });
    try {
      await page.goto(pageUrl(sourceDate), {waitUntil:'domcontentloaded'});
      if (name === 'verified_empty') {
        const filters = page.locator('#groupFilters button:enabled');
        await filters.filter({hasText:'192选股 0'}).waitFor();
        assert.deepEqual(await filters.allTextContents(), ['192选股 0', '回测选股 0']);
        assert.equal(await page.locator('#stockList [data-symbol]').count(), 0);
        assert.deepEqual(await page.evaluate(() => window.unexpectedWorkbenchTabs), []);
      } else {
        await readPending(page);
      }
    } finally {
      await page.unrouteAll({behavior:'ignoreErrors'});
      await page.close();
    }
  }
  return Object.keys(cases);
}

try {
  let controlledCases = [];
  if (allowControlledResponses) {
    await checkStartupCatalogueRace();
    controlledCases = await checkUnexpectedLegacyResponse();
  }
  const day = await fetch(origin + endpoint(sourceDate)).then(response => {
    assert.equal(response.status, 200);
    return response.json();
  });
  assert.equal(day.observation_date, '2026-11-17');
  assert.deepEqual(day.formula_groups.labels, {b23_entry:'192选股',pb2_confirm:'回测选股'});
  assert.deepEqual(day.formula_groups.group_counts, {b23_entry:105,pb2_confirm:49});
  assert.equal(day.rows.length, 133);
  assert.equal(day.rows.filter(row => ids.every(id => row.group_states[id] === 'TRUE')).length, 21);

  const page = await browser.newPage();
  await watchLegacyTabs(page);
  const duplicateGroupRequests = [];
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (new URL(request.url()).pathname.endsWith('/v192')) duplicateGroupRequests.push(request.url());
  });
  await page.goto(pageUrl(sourceDate),{waitUntil:'domcontentloaded'});
  const filters = page.locator('#groupFilters button');
  await page.locator('#groupFilters button[data-group="b23_entry"]:enabled').waitFor({timeout:20000});
  assert.deepEqual(await filters.allTextContents(), ['192选股 105','回测选股 49']);

  const pagesRead = {};
  async function readAll(group, expected) {
    const seen = [];
    const pages = [];
    const next = page.locator('#nextList');
    const prev = page.locator('#prevList');
    const last = Math.ceil(expected.length / 40);
    const readPage = () => page.evaluate(() => ({
      number: Number(document.querySelector('#listPage').textContent.match(/^第 (\d+) 页/)?.[1]),
      group: document.querySelector('#groupFilters button[aria-pressed="true"]')?.dataset.group ?? 'all',
      symbols: [...document.querySelectorAll('#stockList [data-symbol]')].map(row => row.dataset.symbol),
    }));
    for (let number = 1; number <= last; number++) {
      const result = await readPage();
      assert.equal(result.group, group, 'active group during pagination');
      assert.equal(result.number, number, 'exact page transition');
      assert.equal(result.symbols.length, Math.min(40, expected.length - seen.length));
      assert.equal(await next.isEnabled(), number < last);
      assert.equal(await prev.isEnabled(), number > 1);
      pages.push(result.symbols);
      seen.push(...result.symbols);
      if (number < last) await next.click();
    }
    assert.equal(new Set(seen).size, expected.length, 'no duplicate code across pages');
    assert.deepEqual(seen.sort(), expected.sort());
    pagesRead[group] = pages;
    if (last > 1) {
      await prev.click();
      const expectedPrevious = {number:last-1, group, symbols:pages[last-2]};
      assert.deepEqual(await readPage(), expectedPrevious);
      if (allowControlledResponses && group === 'b23_entry') {
        await page.evaluate(() => window.StockPanelHost.refreshSavedSources());
        assert.deepEqual(await readPage(), expectedPrevious, 'same-day catalogue refresh must retain the active page');
      }
    }
  }

  await readAll('all', day.rows.map(row => row.symbol));
  for (const id of ids) {
    const button = page.locator(`#groupFilters button[data-group="${id}"]`);
    await button.click();
    assert.equal(await button.getAttribute('aria-pressed'), 'true');
    await readAll(id, day.rows.filter(row => row.group_states[id] === 'TRUE').map(row => row.symbol));
  }
  assert.deepEqual(await page.evaluate(() => window.unexpectedWorkbenchTabs), []);

  const previous = await fetch(origin + endpoint('2026-11-13')).then(response => response.json());
  await page.locator('#researchCalendar').fill(previous.observation_date);
  await page.waitForFunction(() => document.querySelector('#researchDateStatus')?.textContent?.includes('来源 2026-11-13'));
  await page.locator('#groupFilters button[data-group="b23_entry"]:enabled').waitFor();
  assert.deepEqual(await filters.allTextContents(), [
    '192选股 ' + previous.formula_groups.group_counts.b23_entry,
    '回测选股 ' + previous.formula_groups.group_counts.pb2_confirm,
  ]);
  assert.deepEqual(await page.evaluate(() => window.unexpectedWorkbenchTabs), []);

  const pendingDates = ['2026-11-12', '2026-10-28'];
  for (const date of pendingDates) {
    await page.goto(pageUrl(date),{waitUntil:'domcontentloaded'});
    await readPending(page);
  }
  assert.deepEqual(duplicateGroupRequests, []);
  assert.deepEqual(errors, []);

  console.log(JSON.stringify({
    status:'PASS_TWO_FORMULA_BOARD_SCOPE', origin, source_date:day.source_date,
    observation_date:day.observation_date, generation:day.generation,
    input_sha256:day.input_sha256, numeric_manifest:day.numeric_manifest,
    group_counts:day.formula_groups.group_counts, union:day.rows.length,
    browser_paginated_membership:'EXACT_ALL_ROWS', duplicate_v192_route_requests:duplicateGroupRequests.length,
    pages:pagesRead, next_selected_source_date:previous.source_date, missing_source_dates:pendingDates,
    startup_race:allowControlledResponses?'PASS':'NOT_RUN', controlled_group_payloads:controlledCases, browser_errors:errors,
  }));
} finally {
  await browser.close();
}
