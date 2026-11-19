#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import readline from "node:readline";
import { chromium } from "/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";

const [sourceRoot, workbenchRoot, previewHtml, clientModule, adapterZip, bindingOutput, uiRoot] = process.argv.slice(2);
if ([sourceRoot, workbenchRoot, previewHtml, clientModule, adapterZip, bindingOutput, uiRoot].some((value) => !value)) {
  throw new Error("usage: verify_browser.mjs SOURCE_ROOT WORKBENCH_ROOT PREVIEW_HTML CLIENT_MODULE ADAPTER_ZIP BINDING_OUTPUT UI_ROOT");
}
const current = path.dirname(new URL(import.meta.url).pathname);
const panelPython = process.env.PANEL_PYTHON || "/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python";
const serveScript = path.join(current, "serve_archive_preview.py");
const receiptPath = path.join(uiRoot, "BROWSER_RECEIPT.json");
const downloadRoot = path.join(uiRoot, "native_exports");
const screenshotRoot = path.join(uiRoot, "screenshots");
await Promise.all([fs.mkdir(downloadRoot, { recursive: true }), fs.mkdir(screenshotRoot, { recursive: true })]);

let serverProcess;
let browser;
let origin;
let serverStderr = "";
const requestLog = [];
const consoleErrors = [];
const blockedExternal = [];
let page;
const receipt = {
  task: "P515_D18_DISPLAY_SCOPE_SOURCE_AND_FIX_V1",
  role: "CODEX_MAC / MASTER_FOLLOWUP_20261119_V3_NATIVE_PROVENANCE_AND_ARCHIVE_PREVIEW writer",
  scope: "isolated loopback preview from original V4 workbench HTML/CSS plus D17 archived originals",
  status: "RUNNING",
  started_at: new Date().toISOString(),
  browser: null,
  origin: null,
  entry_route: null,
  browser_entry_click: "NOT_RUN",
  python_interpreter: panelPython,
  v3_display_binding: null,
  interactions: [],
  screenshots: [],
  downloads: [],
  request_log: requestLog,
  console_errors: consoleErrors,
  external_requests_blocked: blockedExternal,
  model_fit: 0,
  preprocessing_fit: 0,
  model_api_calls: 0,
  new_probabilities: 0,
  static_new_scores: 0,
  model_deserialization: 0,
  production_published: false,
};

async function waitForServer(child) {
  const lines = readline.createInterface({ input: child.stdout });
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error("archive server startup timed out")), 10000);
    lines.on("line", (line) => {
      const parsed = JSON.parse(line);
      if (parsed.ready) { clearTimeout(timeout); resolve(parsed); }
    });
    child.once("exit", (code) => { clearTimeout(timeout); reject(new Error(`archive server exited before readiness: ${code}`)); });
  });
}

async function text(selector) { return (await page.locator(selector).textContent())?.trim() ?? ""; }
async function screenshot(name) {
  const file = path.join(screenshotRoot, name);
  await page.screenshot({ path: file, fullPage: true });
  receipt.screenshots.push({ file, bytes: (await fs.stat(file)).size });
}
async function click(selector) { await page.locator(selector).click({ timeout: 5000 }); }
async function expectCount(expected, reason, unit = "只") {
  const actual = await text("#archiveListCount");
  if (!actual.includes(`${expected.toLocaleString("zh-CN")}${unit}`)) throw new Error(`${reason}: expected ${expected}${unit}, got ${actual}`);
  receipt.interactions.push({ check: reason, expected_count: expected, rendered_count_text: actual });
}

try {
  serverProcess = spawn(panelPython, [
    serveScript,
    "--source-root", sourceRoot,
    "--workbench-root", workbenchRoot,
    "--preview-html", previewHtml,
    "--client-module", clientModule,
    "--adapter-zip", adapterZip,
    "--binding-output", bindingOutput,
    "--port", "0",
  ], { stdio: ["ignore", "pipe", "pipe"] });
  serverProcess.stderr.setEncoding("utf8");
  serverProcess.stderr.on("data", (chunk) => { serverStderr += chunk; });
  const ready = await waitForServer(serverProcess);
  origin = ready.origin;
  receipt.origin = origin;
  receipt.server_host = ready.host;
  receipt.adapter_gate_output = bindingOutput;

  browser = await chromium.launch({
    executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    headless: true,
    args: ["--disable-background-networking", "--disable-sync", "--no-first-run", "--no-default-browser-check"],
  });
  receipt.browser = { name: "Google Chrome", version: browser.version(), executable: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true };
  const context = await browser.newContext({ viewport: { width: 1600, height: 1100 }, acceptDownloads: true, serviceWorkers: "block" });
  await context.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) {
      blockedExternal.push(url.href);
      await route.abort("blockedbyclient");
      return;
    }
    await route.continue();
  });
  page = await context.newPage();
  globalThis.page = page;
  page.on("request", (request) => requestLog.push({ method: request.method(), url: request.url(), resource_type: request.resourceType() }));
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  const entryUrl = `${origin}/research-panel/workbench.html?mode=p515-d17-archive-preview`;
  receipt.entry_route = entryUrl;
  await page.goto(entryUrl, { waitUntil: "networkidle" });
  if (!(await page.locator("header.mast .brand").isVisible())) throw new Error("original V4 workbench masthead not visible");
  if (await page.locator("#p515ArchiveView").isVisible()) throw new Error("archive appeared before clicking the original V4 workbench entry");
  if ((await page.locator("#p515ArchiveEntry").count()) !== 1) throw new Error("original workbench entry button missing");
  receipt.interactions.push({ check: "original workbench route loaded before archive tab", status: "PASS", original_header_visible: true, archive_hidden_until_click: true });
  await screenshot("01_original_workbench_entry.png");

  await click("#p515ArchiveEntry");
  receipt.browser_entry_click = "PASS: clicked button in retained original workbench masthead";
  await page.locator("#pageStatus").waitFor({ state: "visible" });
  await page.waitForFunction(() => document.getElementById("archiveListCount")?.textContent?.includes("822只"));
  const v3 = await page.evaluate(() => window.P515_ARCHIVE_PREVIEW.state.identity.v3_display_binding);
  receipt.v3_display_binding = v3;
  if (v3.status !== "PASS" || v3.output_rows.full_disposition_ledger !== 5572 || v3.output_rows.main_candidates_pass !== 822 || v3.output_rows.attached_scores !== 0) {
    throw new Error("actual V3 display binding result failed the 5572/822/0 oracle");
  }
  if (v3.model_score_records_provided !== 0) throw new Error("V3 display call unexpectedly received score records");
  if (!(await page.locator("#p515ArchiveView .archive-intro h1").textContent()).includes("模型未接入")) throw new Error("D17 archive/model status label missing");
  if (!(await page.locator(".archive-banner").textContent()).includes("789 只源无分")) throw new Error("789 source-unscored count not shown separately");
  if (!(await page.locator(".archive-banner").textContent()).includes("822 只主名单")) throw new Error("822 main list score-attachment boundary not shown separately");
  const sourceIdentityText = await text("#sourceIdentity");
  if (sourceIdentityText.includes("undefined")) throw new Error(`archive provenance contains undefined: ${sourceIdentityText}`);
  const pagerBox = await page.locator("#archivePrev").boundingBox();
  if (!pagerBox || pagerBox.y + pagerBox.height > 1100) throw new Error("archive pagination controls are below the first viewport");
  receipt.interactions.push({ check: "source date is present and archive pager remains visible in initial viewport", status: "PASS", source_identity: sourceIdentityText, pager_y: pagerBox.y });
  receipt.interactions.push({ check: "actual V3 pure display adapter bound before archive source served", status: "PASS", adapter_version: v3.adapter_version, entry_point: v3.entry_point, rows: v3.output_rows, score_records_provided: 0 });
  await screenshot("02_archive_default_822.png");

  await click('[data-dataset="disposition"]');
  await page.locator("#dispositionFilter").selectOption("ANCHOR_BROKEN");
  await expectCount(1699, "5572 disposition filter ANCHOR_BROKEN");
  await screenshot("03_disposition_filtered.png");

  await click('[data-dataset="shortlist"]');
  await page.locator("#stageFilter").selectOption("异动");
  await page.locator("#dayFilter").selectOption("2");
  await expectCount(23, "822 stage=异动 plus pullback_day=2 filter");
  await screenshot("04_stage_and_pullback_day_filtered.png");

  await page.locator("#archiveQuery").fill("NO_SUCH_SECURITY_CODE_000000");
  await expectCount(0, "zero-match security search");
  if ((await text("#detailName")) !== "无匹配记录" || (await page.locator("#detailFields tr").count()) !== 0) {
    throw new Error("zero search results display a fallback stock detail");
  }
  receipt.interactions.push({ check: "zero-result search clears detail panel instead of showing another security", status: "PASS" });
  await page.locator("#stageFilter").selectOption("");
  await page.locator("#dayFilter").selectOption("");
  await page.locator("#archiveQuery").fill("688757.SH");
  await expectCount(1, "positive security search 688757.SH");
  const wintech = await page.locator("#detailFields tr").evaluateAll((rows) => Object.fromEntries(rows.map((row) => [
    row.querySelector("th")?.textContent ?? "",
    row.querySelector("td")?.textContent ?? "",
  ])));
  if (wintech["代码"] !== "688757.SH" || wintech["简称"] !== "胜科纳米" || wintech["信号类型"] !== "建仓波" || wintech["结构回调日数"] !== "3" || wintech["D收盘"] !== "23.2") {
    throw new Error(`688757.SH original fields do not match the frozen row: ${JSON.stringify(wintech)}`);
  }
  receipt.interactions.push({ check: "positive 688757.SH search renders exact source fields", status: "PASS", fields: { code: wintech["代码"], name: wintech["简称"], signal: wintech["信号类型"], pullback_day: wintech["结构回调日数"], d_close: wintech["D收盘"] } });
  await screenshot("04b_search_688757_original_fields.png");
  await page.locator("#archiveQuery").fill("");

  await page.locator("#stageFilter").selectOption("");
  await page.locator("#dayFilter").selectOption("");
  await page.locator("#archiveSort").selectOption("代码:asc");
  const sortedVisible = await page.locator("#archiveList .stock-code").allTextContents();
  const expectedSorted = sortedVisible.slice().sort((a, b) => a.localeCompare(b, "zh-CN", { numeric: true, sensitivity: "base" }));
  if (JSON.stringify(sortedVisible) !== JSON.stringify(expectedSorted)) throw new Error("stable ascending security-code sort is not ordered");
  receipt.interactions.push({ check: "ascending stable sort by security code", status: "PASS", visible_first_5: sortedVisible.slice(0, 5) });

  await page.locator("#archiveSort").selectOption("结构回调日数:desc");
  const descRows = await page.locator("#archiveList .stock-item").evaluateAll((items) => items.map((item) => ({
    originalIndex: Number(item.dataset.originalIndex),
    dayText: item.querySelector(".archive-row-meta span:nth-child(2)")?.textContent ?? "",
  })));
  for (let i = 1; i < descRows.length; i += 1) {
    if (Number(descRows[i - 1].dayText) < Number(descRows[i].dayText)) throw new Error("descending pullback-day sort is out of order");
    if (Number(descRows[i - 1].dayText) === Number(descRows[i].dayText) && descRows[i - 1].originalIndex > descRows[i].originalIndex) {
      throw new Error("descending sort reversed source order for tied values");
    }
  }
  receipt.interactions.push({ check: "descending stage sort preserves original row order for ties", status: "PASS", inspected_rows: descRows.length });

  await page.locator("#archiveSort").selectOption("original");
  const firstPageCodes = await page.locator("#archiveList .stock-code").allTextContents();
  if (firstPageCodes.length !== 40) throw new Error(`original first page row count mismatch: ${firstPageCodes.length}`);
  await click("#archiveNext");
  const page2Text = await text("#archiveListPage");
  if (!page2Text.includes("第 2 页 / 共 21 页")) throw new Error(`pagination did not cross onto page 2: ${page2Text}`);
  receipt.interactions.push({ check: "pagination crosses from page 1 to page 2", status: "PASS", rendered: page2Text });
  for (let i = 0; i < 19; i += 1) await click("#archiveNext");
  const lastPageText = await text("#archiveListPage");
  const lastPageCodes = await page.locator("#archiveList .stock-code").allTextContents();
  if (!lastPageText.includes("第 21 页 / 共 21 页") || lastPageCodes.length !== 22) throw new Error(`unexpected last page state: ${lastPageText}, rows=${lastPageCodes.length}`);
  receipt.interactions.push({ check: "pagination reaches original last page", status: "PASS", rendered: lastPageText, visible_rows: lastPageCodes.length, first_last_page_code: lastPageCodes[0] });
  await screenshot("05_archive_last_page_822.png");

  await click('[data-dataset="scores"]');
  await expectCount(33, "independent original 33-row score ledger", "行");
  const scoreSummary = await page.locator("#archiveList .stock-item").first().locator(".archive-row-meta span:nth-child(2)");
  const summaryFacts = await scoreSummary.evaluate((element) => ({
    text: element.textContent,
    height: element.getBoundingClientRect().height,
    textOverflow: getComputedStyle(element).textOverflow,
    whiteSpace: getComputedStyle(element).whiteSpace,
    maxWidth: getComputedStyle(element).maxWidth,
  }));
  const scoreDetail = await page.locator("#detailFields tr").evaluateAll((rows) => Object.fromEntries(rows.map((row) => [
    row.querySelector("th")?.textContent ?? "", row.querySelector("td")?.textContent ?? "",
  ])));
  if (summaryFacts.height > 16 || summaryFacts.textOverflow !== "ellipsis" || summaryFacts.whiteSpace !== "nowrap" || summaryFacts.maxWidth !== "96px") {
    throw new Error(`score-card PB summary does not stay on one clipped line: ${JSON.stringify(summaryFacts)}`);
  }
  if (scoreDetail.R2_PB !== summaryFacts.text) throw new Error("full score-card PB identity differs from the original source value");
  receipt.interactions.push({ check: "score sidebar PB summary ellipsizes without wrapping while detail retains the full source key", status: "PASS", summary_height: summaryFacts.height, full_pb_id_chars: scoreDetail.R2_PB.length });
  await screenshot("06_original_33_score_ledger.png");

  const exports = [
    ["disposition", "导出 5,572 行全范围处置原表"],
    ["shortlist", "导出 822 行量价初筛原表"],
    ["scores", "导出 33 行原评分独立账本"],
  ];
  for (const [id, name] of exports) {
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: 15000 }),
      page.getByRole("button", { name }).click(),
    ]);
    const target = path.join(downloadRoot, download.suggestedFilename());
    await download.saveAs(target);
    receipt.downloads.push({ id, suggested_filename: download.suggestedFilename(), file: target, bytes: (await fs.stat(target)).size });
  }

  if (blockedExternal.length) throw new Error(`external browser requests attempted: ${blockedExternal.join(", ")}`);
  const nonLocal = requestLog.filter((item) => new URL(item.url).origin !== origin);
  if (nonLocal.length) throw new Error(`non-loopback requests observed: ${JSON.stringify(nonLocal)}`);
  if (requestLog.some((item) => /\/api\/|market|quotes?|projections|top200/i.test(new URL(item.url).pathname))) {
    throw new Error("the archive page requested an API/market route");
  }
  if (consoleErrors.length) throw new Error(`browser console errors: ${consoleErrors.join(" | ")}`);
  receipt.request_log = requestLog;
  receipt.status = "PASS_BROWSER_UI_AND_NATIVE_DOWNLOADS";
  receipt.finished_at = new Date().toISOString();
  receipt.research_only = { RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false };
  receipt.source_files = await page.evaluate(() => window.P515_ARCHIVE_PREVIEW.state.identity.files);
  receipt.http_requests = requestLog.map((item) => new URL(item.url).pathname);
  receipt.server_stderr = serverStderr;
} catch (error) {
  receipt.status = "FAIL_OR_INCOMPLETE";
  receipt.error = error?.stack ?? String(error);
  receipt.finished_at = new Date().toISOString();
  receipt.server_stderr = serverStderr;
} finally {
  try { await fs.writeFile(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8"); } catch {}
  if (browser) await browser.close().catch(() => {});
  if (serverProcess && serverProcess.exitCode === null) {
    serverProcess.kill("SIGTERM");
    await new Promise((resolve) => serverProcess.once("exit", resolve));
  }
}

console.log(JSON.stringify({ status: receipt.status, receipt: receiptPath, browser: receipt.browser, entry_click: receipt.browser_entry_click, v3: receipt.v3_display_binding?.output_rows, interactions: receipt.interactions, downloads: receipt.downloads, blocked_external: blockedExternal.length, console_errors: consoleErrors }, null, 2));
if (receipt.status !== "PASS_BROWSER_UI_AND_NATIVE_DOWNLOADS") process.exitCode = 1;
