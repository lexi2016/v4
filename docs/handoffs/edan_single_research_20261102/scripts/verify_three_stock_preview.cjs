const {chromium}=require('/Users/lexi/.codex/skills/playwright-skill/node_modules/playwright-core');
const fs=require('fs');
const out=__dirname+'/THREE_STOCK_UI_VERIFY_R1.json';
if(fs.existsSync(out))throw Error('IMMUTABLE_OUTPUT_EXISTS');
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',args:['--no-sandbox']});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[];page.on('pageerror',e=>errors.push(String(e)));
    await page.goto('http://127.0.0.1:65444/research-panel/workbench.html?date=2026-10-30&symbol=300206.SZ',{waitUntil:'domcontentloaded'});
    const snapshot=async(symbol,name,score)=>{
      await page.waitForFunction(({symbol,name})=>document.querySelector('#kbSingleCode')?.textContent===symbol&&
        document.querySelector('#kbSingleStatus')?.textContent.includes(name+'单股研究'),{symbol,name},{timeout:30000});
      const value=await page.evaluate(()=>({symbol:document.querySelector('#kbSingleCode')?.textContent,
        score:document.querySelector('#kbSingleScore')?.textContent,status:document.querySelector('#kbSingleStatus')?.textContent,
        selected:document.querySelector('#kbSingleDate')?.value,
        frameSymbol:document.querySelector('#kbSingleChart')?.contentWindow?.RESEARCH_PANEL_STATE?.symbol,
        frameRows:document.querySelector('#kbSingleChart')?.contentWindow?.RESEARCH_PANEL_STATE?.rows?.length,
        pool:document.querySelector('#kbSingleResearch')!==null}));
      if(value.symbol!==symbol||value.frameSymbol!==symbol||!value.score.includes(score)||value.selected!=='2026-10-30')throw Error('UI_STOCK_MISMATCH:'+JSON.stringify(value));
      return value;
    };
    const a=await snapshot('300206.SZ','理邦仪器','4/5');
    await page.click('#kbSingleOpen');const b=await snapshot('002865.SZ','钧达股份','4/5');
    await page.fill('#kbSingleDate','2025-12-12');await page.dispatchEvent('#kbSingleDate','change');
    await page.waitForFunction(()=>document.querySelector('#kbSingleSelected')?.textContent==='2025-12-12',{timeout:15000});
    const historical=await page.evaluate(()=>({date:document.querySelector('#kbSingleDate')?.value,chips:document.querySelector('#kbSingleChips')?.textContent}));
    if(!historical.chips.includes('暴力K')||!historical.chips.includes('反包'))throw Error('HISTORICAL_KB_EVENTS_MISSING');
    await page.click('#kbSingleGold');const c=await snapshot('301048.SZ','金鹰重工','1～2');
    await page.click('#kbSingleEdan');const d=await snapshot('300206.SZ','理邦仪器','4/5');
    await page.reload({waitUntil:'domcontentloaded'});const e=await snapshot('300206.SZ','理邦仪器','4/5');
    if(errors.length)throw Error('PAGE_ERRORS:'+JSON.stringify(errors));
    fs.writeFileSync(out,JSON.stringify({status:'PASS_PRIVATE_THREE_STOCK_SWITCH_HISTORY_RELOAD',stocks:[a,b,c,d,e],
      junda_historical:historical,errors,RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false},null,2)+'\n',{flag:'wx'});
    console.log(JSON.stringify({status:'PASS_PRIVATE_THREE_STOCK_SWITCH_HISTORY_RELOAD',path:out}));
  }finally{await browser.close()}
})().catch(err=>{console.error(err);process.exitCode=1});
