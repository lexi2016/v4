const {chromium}=require('/Users/lexi/.codex/skills/playwright-skill/node_modules/playwright-core');
const fs=require('fs'),path=__dirname+'/VERSION_UI_VERIFY_R3.json';
if(fs.existsSync(path))throw Error('IMMUTABLE_OUTPUT_EXISTS');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(String(e)));
  await page.goto('http://127.0.0.1:52906/research-panel/workbench.html?date=2026-10-30&symbol=300206.SZ',{waitUntil:'domcontentloaded'});
  async function read(symbol,expectedDate){
   await page.waitForFunction(({symbol,date})=>{const f=document.querySelector('#kbSingleChart')?.contentWindow?.RESEARCH_PANEL_STATE;
    return document.querySelector('#kbSingleCode')?.textContent===symbol&&document.querySelector('#kbSingleDate')?.value===date&&
           f?.symbol===symbol&&String(f.rows[f.selected]?.trade_date)===date.replaceAll('-','')},{symbol,date:expectedDate},{timeout:30000});
   return await page.evaluate(()=>({url:location.href,symbol:document.querySelector('#kbSingleCode').textContent,
    date:document.querySelector('#kbSingleDate').value,score:document.querySelector('#kbSingleScore').textContent,
    selected:document.querySelector('#kbSingleSelected').textContent,chips:document.querySelector('#kbSingleChips').textContent,
    chartDate:document.querySelector('#kbSingleChart').contentWindow.RESEARCH_PANEL_STATE.rows[document.querySelector('#kbSingleChart').contentWindow.RESEARCH_PANEL_STATE.selected].trade_date}));
  }
  const first=await read('300206.SZ','2026-10-30');
  if(new URL(first.url).searchParams.get('candidate_generation')!=='1cf5bf8c85418b3126886026c3f0a5f7e24ce7f4e8289f41b0f983cb86fafd42')throw Error('INITIAL_CANDIDATE_NOT_PINNED');
  await page.click('#kbSingleGold');const gold=await read('301048.SZ','2026-10-30');
  if(new URL(gold.url).searchParams.get('symbol')!=='301048.SZ')throw Error('SWITCH_NOT_IN_URL');
  await page.reload({waitUntil:'domcontentloaded'});const goldReload=await read('301048.SZ','2026-10-30');
  if(new URL(goldReload.url).searchParams.get('candidate_generation')!=='9bf8022c1206fea7d5dd07c086ed3a4af23d61be4d75ab1b39d7625500975f43')throw Error('GOLD_CANDIDATE_NOT_RETAINED');
  await page.click('#kbSingleOpen');await read('002865.SZ','2026-10-30');
  await page.fill('#kbSingleDate','2025-12-12');await page.dispatchEvent('#kbSingleDate','change');
  const history=await read('002865.SZ','2025-12-12');
  if(!history.chips.includes('暴力K')||!history.chips.includes('反包'))throw Error('HISTORY_EVENTS_MISSING');
  if(new URL(history.url).searchParams.get('stock_date')!=='2025-12-12'||new URL(history.url).searchParams.get('date')!=='2026-10-30')throw Error('HISTORY_SOURCE_DATE_CONFLICT');
  await page.reload({waitUntil:'domcontentloaded'});const historyReload=await read('002865.SZ','2025-12-12');
  if(historyReload.score!==history.score||historyReload.chips!==history.chips)throw Error('HISTORY_RELOAD_VALUE_CONFLICT');
  if(new URL(historyReload.url).searchParams.get('candidate_generation')!==new URL(history.url).searchParams.get('candidate_generation'))throw Error('HISTORY_VERSION_NOT_RETAINED');
  await page.fill('#kbSingleDate','2025-12-13');await page.dispatchEvent('#kbSingleDate','change');
  const unavailable=await page.evaluate(()=>({url:location.href,status:document.querySelector('#kbSingleDateStatus').textContent,
      score:document.querySelector('#kbSingleScore').textContent,chartHidden:document.querySelector('#kbSingleChart').hidden}));
  if(!unavailable.status.includes('无已绑定交易数据')||unavailable.score||!unavailable.chartHidden)throw Error('MISSING_DATE_SHOWED_STALE_VALUE');
  await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.querySelector('#kbSingleDateStatus')?.textContent.includes('无已绑定交易数据'),null,{timeout:30000});
  const missingReload=await page.evaluate(()=>({date:new URL(location.href).searchParams.get('stock_date'),
      score:document.querySelector('#kbSingleScore').textContent,chartHidden:document.querySelector('#kbSingleChart').hidden}));
  if(missingReload.date!=='2025-12-13'||missingReload.score||!missingReload.chartHidden)throw Error('MISSING_DATE_RELOAD_CONFLICT');
  await page.click('#kbSingleLatest');const latest=await read('002865.SZ','2026-10-30');
  if(new URL(latest.url).searchParams.has('stock_date'))throw Error('LATEST_DID_NOT_CLEAR_PIN');
  await page.route('**/single-research/300206.SZ?*',async route=>{await new Promise(r=>setTimeout(r,1200));await route.continue().catch(()=>{});});
  await page.click('#kbSingleEdan');const pending=await page.evaluate(()=>({symbol:document.querySelector('#kbSingleCode').textContent,
      score:document.querySelector('#kbSingleScore').textContent}));
  if(pending.symbol!=='300206.SZ'||pending.score)throw Error('ASYNC_SWITCH_SHOWED_STALE_SCORE');
  await page.click('#kbSingleGold');const final=await read('301048.SZ','2026-10-30');
  await page.waitForTimeout(1500);const after=await read('301048.SZ','2026-10-30');
  if(new URL(after.url).searchParams.get('symbol')!=='301048.SZ'||after.score!==final.score)throw Error('ASYNC_SWITCH_OVERWROTE_STOCK');
  if(new URL(after.url).searchParams.get('candidate_generation')!=='9bf8022c1206fea7d5dd07c086ed3a4af23d61be4d75ab1b39d7625500975f43')throw Error('ASYNC_SWITCH_OVERWROTE_VERSION');
  const stale=new URL(after.url);stale.searchParams.set('candidate_generation','f'.repeat(64));
  await page.goto(stale.href,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.querySelector('#kbSingleStatus')?.textContent.includes('版本已变或不可用'),null,{timeout:30000});
  const mismatch=await page.evaluate(()=>({url:location.href,score:document.querySelector('#kbSingleScore').textContent,
      frameHidden:document.querySelector('#kbSingleChart').hidden,latestVisible:!document.querySelector('#kbSingleVersionLatest').hidden}));
  if(mismatch.score||!mismatch.frameHidden||!mismatch.latestVisible||new URL(mismatch.url).searchParams.get('candidate_generation')!=='f'.repeat(64))throw Error('STALE_CANDIDATE_SILENTLY_REPLACED');
  await page.click('#kbSingleVersionLatest');const acceptedLatest=await read('301048.SZ','2026-10-30');
  if(new URL(acceptedLatest.url).searchParams.get('candidate_generation')!=='9bf8022c1206fea7d5dd07c086ed3a4af23d61be4d75ab1b39d7625500975f43')throw Error('LATEST_CANDIDATE_NOT_BOUND');
  await page.goto('http://127.0.0.1:52906/research-panel/workbench.html?date=2026-10-30&symbol=000410.SZ',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.querySelector('#kbSingleCode')?.textContent==='000410.SZ'&&/^[a-f0-9]{64}$/.test(new URL(location.href).searchParams.get('panel_generation')||'')&&document.querySelector('#kbSingleStatus')?.textContent.includes('研究面板'),null,{timeout:30000});
  const scoped=await page.evaluate(()=>({url:location.href,symbol:document.querySelector('#kbSingleCode').textContent,score:document.querySelector('#kbSingleScore').textContent}));
  if(new URL(scoped.url).searchParams.has('candidate_generation'))throw Error('SCOPED_VERSION_TYPE_MIXED');
  await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(value=>document.querySelector('#kbSingleCode')?.textContent==='000410.SZ'&&new URL(location.href).searchParams.get('panel_generation')===value&&document.querySelector('#kbSingleStatus')?.textContent.includes('研究面板'),new URL(scoped.url).searchParams.get('panel_generation'),{timeout:30000});
  if(errors.length)throw Error('PAGE_ERRORS:'+JSON.stringify(errors));
  fs.writeFileSync(path,JSON.stringify({status:'PASS_PRIVATE_VERSION_PIN_SYMBOL_DATE_AND_SCOPED',first,gold,goldReload,history,
   historyReload,unavailable,missingReload,latest,pending,final,after,mismatch,acceptedLatest,scoped,errors,RESEARCH_ONLY:true,production_allowed:false,
   buy_gate_updated:false,orders_sent:false},null,2)+'\n',{flag:'wx'});
  console.log(JSON.stringify({status:'PASS_PRIVATE_VERSION_PIN_SYMBOL_DATE_AND_SCOPED',path}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
