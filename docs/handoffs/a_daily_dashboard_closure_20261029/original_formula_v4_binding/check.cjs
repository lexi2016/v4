const fs=require('fs'),path=require('path'),crypto=require('crypto');
const {chromium}=require('/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{const base=process.argv[2],out=process.argv[3];let browser;const result={status:'RUNNING',samples:[],page_errors:[],browser_closed:false,user_GUI:false};
try{browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',args:['--no-first-run','--no-default-browser-check','--disable-extensions']});const context=await browser.newContext({viewport:{width:1440,height:1000}});
await context.route('**/*',r=>{const u=new URL(r.request().url());return u.origin===base&&['GET','HEAD'].includes(r.request().method())?r.continue():r.abort();});
const page=await context.newPage();page.on('pageerror',e=>result.page_errors.push(String(e)));
await page.goto(base+'/dashboard-demo',{waitUntil:'domcontentloaded'});await page.waitForFunction(()=>document.querySelector('#productState')?.textContent.includes('247'));
const daily=page.frames().find(f=>f.url().includes('/research-panel/daily.html'));if(!daily)throw Error('daily iframe missing');
await daily.locator('#dailyNumeric283Search').waitFor();
for(const symbol of ['600025.SH','000410.SZ','920454.BJ']){
 const meta=await context.request.get(base+'/api/v4/research/a-share/original-chart?'+new URLSearchParams({date:'20261029',symbol}));const answer=await meta.json();if(answer.status!=='READY')throw Error(JSON.stringify(answer));
 const assets={};for(const [kind,ref]of Object.entries(answer.assets)){const r=await context.request.get(base+ref.url),bytes=await r.body(),sha=crypto.createHash('sha256').update(bytes).digest('hex');if(r.status()!==200||sha!==ref.sha256)throw Error(kind+' SHA');assets[kind]={bytes:bytes.length,sha256:sha};}
 await daily.locator('#dailyNumeric283Search').fill(symbol);await daily.locator('#dailyNumeric283Rows button').filter({hasText:symbol}).first().click();
 await daily.waitForFunction(s=>document.querySelector('#dailyNumeric283ChartStatus')?.textContent.includes(s)&&document.querySelector('#dailyNumeric283ChartStatus')?.textContent.includes('原式 d35c'),symbol,{timeout:30000});
 const original=daily.childFrames().find(f=>f.url().includes('/original-chart/html?'));if(!original)throw Error('original frame missing');
 const observed=await original.evaluate(()=>({symbol:window.RESEARCH_PANEL_STATE.symbol,date:window.RESEARCH_PANEL_STATE.rows.at(-1).trade_date,rows:window.RESEARCH_PANEL_STATE.rows.length,values:document.querySelectorAll('#values tr').length,drawings:document.querySelectorAll('#drawings tr').length,loaded:document.documentElement.dataset.loaded}));
 if(observed.symbol!==symbol||observed.date!==20261029||observed.values!==51||observed.drawings!==22||observed.rows!==answer.rows)throw Error(JSON.stringify(observed));
 await original.locator('#chart').screenshot({path:path.join(out,symbol+'.actual-canvas.png')});
 await daily.locator('#dailyNumeric283ChartPanel').screenshot({path:path.join(out,symbol+'.bound.png')});result.samples.push({symbol,metadata:answer,assets,observed,status_text:await daily.locator('#dailyNumeric283ChartStatus').innerText()});
}
await context.route('**/original-chart?**',r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'CANNOT_CONFIRM',cannot_confirm:['negative-fixture-stale']})}));
await daily.locator('#dailyNumeric283Search').fill('600025.SH');await daily.locator('#dailyNumeric283Rows button').filter({hasText:'600025.SH'}).first().click();await daily.waitForFunction(()=>document.querySelector('#dailyNumeric283ChartStatus')?.textContent.includes('negative-fixture-stale'));
result.stale_previous_frame_cleared=await daily.locator('#dailyOriginalFormulaFrame').count()===0;if(!result.stale_previous_frame_cleared)throw Error('stale frame retained');result.status='PASS_ISOLATED_3_API_UI';
}catch(e){result.status='FAIL';result.error=String(e);process.exitCode=1;}finally{if(browser){await browser.close();result.browser_closed=true;}fs.writeFileSync(path.join(out,'ACTUAL_ISOLATED_RECEIPT.json'),JSON.stringify(result,null,2)+'\n');}console.log(JSON.stringify({status:result.status,samples:result.samples.length,error:result.error,browser_closed:result.browser_closed,page_errors:result.page_errors}));})();
