// Saved-data company lifecycle regression, using an owned headless context only.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.WORKBENCH_PLAYWRIGHT_MODULE||'playwright');
const root=process.env.WORKBENCH_CANDIDATE_ROOT,out=process.env.WORKBENCH_TEST_OUTPUT;
const assets=new Set(['workbench-host/bootstrap.mjs','workbench-host/company-local.mjs','workbench-host/dot/shell/workbench.local.mjs']);
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});let release;
 try{
  const page=await browser.newPage({viewport:{width:1440,height:869}}),errors=[],records=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{let host;Object.defineProperty(window,'StockPanelHost',{configurable:true,get:()=>host,set:value=>{host=value;const install=value.installCompletion;value.installCompletion=function(callback){window.__companyTestCompletion=callback;return install.call(this,callback)}}})});
  if(root)await page.route('**/research-panel/**',route=>{const rel=decodeURIComponent(new URL(route.request().url()).pathname.slice('/research-panel/'.length));return assets.has(rel)?route.fulfill({path:path.join(root,rel),contentType:'text/javascript'}):route.continue()});
  const inspect=()=>page.evaluate(()=>({selected:document.querySelector('#stockCode').textContent,panels:['companySummary','companyMetrics'].map(id=>{const e=document.getElementById(id);return {id,state:e.dataset.companyState,symbol:e.dataset.companySymbol,text:e.textContent}})}));
  const ready=async symbol=>{await page.waitForFunction(s=>['companySummary','companyMetrics'].every(id=>{const e=document.getElementById(id);return e.dataset.companyState==='READY'&&e.dataset.companySymbol===s&&e.textContent.trim()}),symbol);const s=await inspect();assert.equal(s.selected,symbol);records.push({check:'READY',...s});};
  const select=async symbol=>page.locator(`#stockList [data-symbol="${symbol}"]`).click();
  await page.goto('http://127.0.0.1:8873/research-panel/workbench.html?date=2026-10-29');
  await ready('688816.SH');
  await page.evaluate(()=>window.__companyTestCompletion.modules(['statistics']));
  await ready('688816.SH');
  await page.waitForTimeout(1200);assert((await inspect()).panels.every(x=>x.state==='READY'&&x.text));
  for(const symbol of ['688816.SH','920706.BJ','688057.SH']){await select(symbol);await ready(symbol);}
  let delayed=false;const blocked=new Promise(resolve=>release=resolve);
  await page.route('**/workbench/days/**/company/688816.SH?*',async route=>{const response=await route.fetch();delayed=true;await blocked;await route.fulfill({response})});
  await select('688816.SH');await page.waitForFunction(()=>document.querySelector('#companySummary').dataset.companyState==='LOADING');
  assert((await inspect()).panels.every(x=>x.state==='LOADING'&&x.symbol==='688816.SH'&&x.text.includes('读取')));
  // A same-stock chart/statistics completion must not cancel the company request.
  await page.evaluate(()=>window.__companyTestCompletion.modules(['statistics']));
  assert((await inspect()).panels.every(x=>x.state==='LOADING'&&x.symbol==='688816.SH'));
  await select('920706.BJ');await ready('920706.BJ');
  assert(delayed);release();await page.waitForTimeout(400);await ready('920706.BJ');
  records.push({check:'LATE_OLD_STOCK_IGNORED',...await inspect()});
  await page.unroute('**/workbench/days/**/company/688816.SH?*');
  await page.route('**/workbench/days/**/company/688057.SH?*',route=>route.fulfill({status:200,contentType:'application/json',body:'null'}));
  await select('688057.SH');await page.waitForFunction(()=>document.querySelector('#companySummary').dataset.companyState==='MISSING');
  assert((await inspect()).panels.every(x=>x.state==='MISSING'&&x.symbol==='688057.SH'&&x.text.includes('CANNOT_CONFIRM')));
  records.push({check:'MISSING_EXPLICIT_BOTH',...await inspect()});
  await page.unroute('**/workbench/days/**/company/688057.SH?*');
  await page.route('**/workbench/days/**/company/688057.SH?*',route=>route.fulfill({status:503,contentType:'application/json',body:'{"detail":"TEST_READ_UNAVAILABLE"}'}));
  await select('688057.SH');await page.waitForFunction(()=>document.querySelector('#companySummary').dataset.companyState==='ERROR');
  assert((await inspect()).panels.every(x=>x.state==='ERROR'&&x.symbol==='688057.SH'&&x.text.includes('CANNOT_CONFIRM')));
  records.push({check:'ERROR_EXPLICIT_BOTH',...await inspect()});
  await page.unroute('**/workbench/days/**/company/688057.SH?*');
  await select('688057.SH');await ready('688057.SH');
  const sourceReset=await page.evaluate(()=>{window.__companyTestCompletion.sourceChanged();return ['companySummary','companyMetrics'].map(id=>document.getElementById(id).dataset.companyState)});
  assert.deepEqual(sourceReset,['IDLE','IDLE']);await ready('688816.SH');
  records.push({check:'SOURCE_REBIND_CLEARS_COMPANY',...await inspect()});
  // Exercise the real date-reset entry: old company content clears immediately.
  const originalDate=await page.locator('#date').inputValue();
  const alternate=await page.locator('#date option').evaluateAll(options=>options.map(x=>x.value).find(x=>!x.startsWith('2026-10-29')));
  assert(alternate);await page.locator('#date').selectOption(alternate);
  const reset=await inspect();assert(reset.panels.every(x=>x.state==='IDLE'&&x.text.includes('未选择')));
  await page.locator('#date').selectOption(originalDate);await ready('688816.SH');
  await page.evaluate(()=>window.__companyTestCompletion.modules(['statistics']));await ready('688816.SH');
  assert.equal(new URL(page.url()).searchParams.get('date'),'2026-10-29');
  if(out)await page.screenshot({path:path.join(out,'AFTER_1440.png'),fullPage:true});
  await page.setViewportSize({width:694,height:869});await select('688057.SH');await ready('688057.SH');
  if(out)await page.screenshot({path:path.join(out,'AFTER_694.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  const result={status:'PASS',mode:root?'THREE_ASSET_CANDIDATE_WITH_REAL_GET_API':'ACTUAL_DEPLOYED_PAGE',checks:records,errors,scope:'initial; repeated same-stock selection; saved statistics refresh; 3-stock switch; both loading/missing/error states; late old response; date reset; 1440/694 visuals',cleanup:'Owned headless browser closed in finally; no user window/input taken'};
  if(out)fs.writeFileSync(path.join(out,'BROWSER_RESULT.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({status:'PASS',checks:records.length,mode:result.mode}));
 }finally{release?.();await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
