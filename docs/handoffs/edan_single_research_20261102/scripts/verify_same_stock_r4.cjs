const {chromium}=require('/Users/lexi/.codex/skills/playwright-skill/node_modules/playwright-core');
const fs=require('fs'),path=__dirname+'/SAME_STOCK_UI_VERIFY_R4.json';
if(fs.existsSync(path))throw Error('IMMUTABLE_OUTPUT_EXISTS');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(String(e)));
  const base='http://127.0.0.1:54012/research-panel/workbench.html?date=2026-10-30';
  const snapshot=()=>page.evaluate(()=>({url:location.href,status:document.querySelector('#kbSingleStatus').textContent,
   score:document.querySelector('#kbSingleScore').textContent,frameHidden:document.querySelector('#kbSingleChart').hidden,
   latestVisible:!document.querySelector('#kbSingleVersionLatest').hidden,symbol:document.querySelector('#kbSingleCode').textContent,
   selected:document.querySelector('#kbSingleSelected').textContent}));
  const expectMismatch=async()=>{
   await page.waitForFunction(()=>document.querySelector('#kbSingleStatus')?.textContent.includes('版本已变或不可用'),null,{timeout:30000});
   const state=await snapshot(),url=new URL(state.url);
   if(state.score||!state.frameHidden||!state.latestVisible||url.searchParams.get('candidate_generation')!=='f'.repeat(64)||url.searchParams.get('stock_date')!=='2025-12-12')throw Error('SAME_STOCK_VERSION_PIN_BYPASS:'+JSON.stringify(state));
   return state;
  };
  await page.goto(base+'&symbol=301048.SZ&candidate_generation='+('f'.repeat(64))+'&stock_date=2025-12-12',{waitUntil:'domcontentloaded'});
  const mismatch=await expectMismatch();await page.click('#kbSingleGold');const sameStockMismatch=await expectMismatch();
  await page.reload({waitUntil:'domcontentloaded'});const mismatchReload=await expectMismatch();
  await page.click('#kbSingleVersionLatest');
  await page.waitForFunction(()=>new URL(location.href).searchParams.get('candidate_generation')==='9bf8022c1206fea7d5dd07c086ed3a4af23d61be4d75ab1b39d7625500975f43'&&document.querySelector('#kbSingleSelected')?.textContent==='2025-12-12',null,{timeout:30000});
  const explicitLatest=await snapshot();
  await page.click('#kbSingleOpen');
  await page.waitForFunction(()=>document.querySelector('#kbSingleCode')?.textContent==='002865.SZ'&&document.querySelector('#kbSingleSelected')?.textContent==='2026-10-30',null,{timeout:30000});
  await page.fill('#kbSingleDate','2025-12-12');await page.dispatchEvent('#kbSingleDate','change');
  await page.waitForFunction(()=>document.querySelector('#kbSingleSelected')?.textContent==='2025-12-12',null,{timeout:30000});
  const historical=await snapshot();await page.click('#kbSingleOpen');
  await page.waitForFunction(()=>document.querySelector('#kbSingleSelected')?.textContent==='2025-12-12'&&!document.querySelector('#kbSingleChart').hidden,null,{timeout:30000});
  const sameHistorical=await snapshot();
  if(sameHistorical.url!==historical.url||sameHistorical.score!==historical.score)throw Error('SAME_STOCK_HISTORY_CHANGED');
  await page.click('#kbSingleEdan');
  await page.waitForFunction(()=>document.querySelector('#kbSingleCode')?.textContent==='300206.SZ'&&new URL(location.href).searchParams.get('candidate_generation')==='b843699e8d3371ea95f22d4734283948aa50443ff5e939d444ba566d5a40c362'&&document.querySelector('#kbSingleSelected')?.textContent==='2026-10-30',null,{timeout:30000});
  const switched=await snapshot();if(new URL(switched.url).searchParams.has('stock_date'))throw Error('DIFFERENT_STOCK_HISTORY_LEAKED');
  if(errors.length)throw Error('PAGE_ERRORS:'+JSON.stringify(errors));
  fs.writeFileSync(path,JSON.stringify({status:'PASS_SAME_STOCK_PIN_AND_HISTORICAL_DATE',mismatch,sameStockMismatch,mismatchReload,explicitLatest,historical,sameHistorical,switched,errors,RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false},null,2)+'\n',{flag:'wx'});
  console.log(JSON.stringify({status:'PASS_SAME_STOCK_PIN_AND_HISTORICAL_DATE',path}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
