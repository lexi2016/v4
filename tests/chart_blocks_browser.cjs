// Isolated candidate transport/render check. No real API or user profile.
const fs=require('fs'),{chromium}=require('/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{const input=JSON.parse(fs.readFileSync(0,'utf8'));let browser;try{
 browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',args:['--no-first-run','--no-default-browser-check','--disable-extensions','--disable-background-networking']});
 const context=await browser.newContext({viewport:{width:1600,height:1200},acceptDownloads:false});const calls=[],faults=[];
 await context.route('**/*',async route=>{const request=route.request(),u=new URL(request.url());calls.push(u.pathname);if(u.origin!=='https://v4-fixture.invalid'||request.method()!=='GET')return route.abort();
 if(u.pathname==='/shared.html')return route.fulfill({body:input.html,contentType:'text/html',headers:{'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"}});
 if(u.pathname==='/api/v4/research/a-share/original-chart')return route.fulfill({json:input.metadata});
 if(u.pathname==='/projection')return route.fulfill({body:Buffer.from(input.projection,'base64'),contentType:'application/octet-stream'});
 return route.abort();});
 const page=await context.newPage();page.on('pageerror',e=>faults.push(String(e)));
 await page.goto('https://v4-fixture.invalid/shared.html?'+new URLSearchParams({date:input.metadata.data_date,symbol:input.metadata.symbol,generation:input.metadata.source_generation,input_sha256:input.metadata.input_sha256}),{waitUntil:'load'});
 await page.waitForFunction(s=>document.documentElement.dataset.loaded===s,input.metadata.symbol,{timeout:15000});
 const state=await page.evaluate(()=>({symbol:window.RESEARCH_PANEL_STATE.symbol,rows:window.RESEARCH_PANEL_STATE.rows.length,values:document.querySelectorAll('#values tr').length,drawings:document.querySelectorAll('#drawings tr').length,checked:document.querySelector('#draw-text').checked,pixels:Array.from(document.querySelector('#chart').getContext('2d').getImageData(0,0,2,2).data).some(x=>x)}));
 if(state.rows!==input.metadata.rows||state.values!==51||state.drawings!==22||!state.checked||faults.length||calls.some(x=>x.endsWith('.png')))throw Error(JSON.stringify({state,faults,calls}));
 const download=page.waitForEvent('download');await page.getByRole('button',{name:'导出当前图 PNG'}).click();await download;
 process.stdout.write(JSON.stringify({status:'PASS',state,requests:calls,automatic_png_requests:0,explicit_export:true}));
 }finally{if(browser)await browser.close();}})().catch(e=>{process.stderr.write(String(e));process.exitCode=1;});
