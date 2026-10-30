"""Old entry migration and requested-date isolation; no market collection."""
import hashlib,json,os,subprocess
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from apps.api.v4_api.research_panel_mount import create_research_panel_router
from ops.build_mac_workbench import build


def client(tmp_path,with_workbench=True):
    files={'safe.mjs':b'export const safe=true;'}
    (tmp_path/'待删除').mkdir()
    files['待删除/legacy-daily.html' if with_workbench else 'daily.html']=b'OLD_SINGLE_STOCK_ARCHIVE'
    if with_workbench:files['workbench.html']=b'NEW_WORKBENCH'
    for name,raw in files.items():(tmp_path/name).write_bytes(raw)
    manifest=tmp_path/'assets.json';manifest.write_text(json.dumps(dict(schema_version='research_panel.assets.v1',files=[dict(path=name,sha256=hashlib.sha256(raw).hexdigest()) for name,raw in files.items()])))
    app=FastAPI();app.include_router(create_research_panel_router(tmp_path,manifest));return TestClient(app)


def test_daily_redirect_preserves_query_legacy_is_explicit_and_all_assets_stay_hash_bound(tmp_path):
    c=client(tmp_path)
    for query in ('date=2026-10-28','date=20261017&stage=STAGE_0925'):
        response=c.get('/research-panel/daily.html?'+query,follow_redirects=False)
        assert response.status_code==307 and response.headers['location']=='/research-panel/workbench.html?'+query
        assert c.get(response.headers['location']).text=='NEW_WORKBENCH'
    assert c.get('/research-panel/legacy-daily.html?date=2026-10-28').text=='OLD_SINGLE_STOCK_ARCHIVE'
    (tmp_path/'待删除/legacy-daily.html').write_bytes(b'changed')
    assert c.get('/research-panel/legacy-daily.html').status_code==409
    assert c.get('/research-panel/unknown.mjs').status_code==404
    assert c.get('/research-panel/%2E%2E/secret.txt').status_code==404
    (tmp_path/'safe.mjs').write_text('drift');assert c.get('/research-panel/safe.mjs').status_code==409
    assert c.post('/research-panel/daily.html').status_code==405


def test_old_role_without_exported_workbench_keeps_existing_daily(tmp_path):
    c=client(tmp_path,False)
    assert c.get('/research-panel/daily.html',follow_redirects=False).text=='OLD_SINGLE_STOCK_ARCHIVE'


def test_requested_date_normalization_and_invalid_dates():
    node='/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    script="""import assert from 'node:assert/strict';import {requestedSourceDate as read} from './research/stock_panel_collab_20261030/mac-host/entry-date.mjs';assert.equal(read('?date=2026-10-28'),'2026-10-28');assert.equal(read('?date=20261017&stage=STAGE_0925'),'2026-10-17');assert.equal(read(''),null);for(const d of ['20260230','2026-13-01','','00000101'])assert.throws(()=>read('?date='+d));"""
    subprocess.run([node,'--input-type=module','-e',script],cwd=Path(__file__).resolve().parents[1],check=True,capture_output=True)


def test_actual_browser_requested_missing_day_never_loads_catalog_other_day(tmp_path):
    root=Path(__file__).resolve().parents[1];dot=Path(os.environ['DOT_FRAMEWORK_SOURCE_ROOT']);build(dot,tmp_path,root/'research/stock_panel_collab_20261030/mac-host/DOT_SOURCE_LOCK.json')
    node='/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    script=r"""const {chromium}=require('/Users/lexi/.codex/skills/playwright-skill/node_modules/playwright');const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');const root=process.argv[1];(async()=>{const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});try{const page=await browser.newPage();let reads=[];await page.route('**/*',async route=>{const u=new URL(route.request().url());if(u.pathname.startsWith('/api/')){if(u.pathname==='/api/v4/research/events')return route.fulfill({status:204,body:''});if(u.pathname.endsWith('/history'))return route.fulfill({json:{days:[{source_date:'2026-10-29',observation_date:'2026-10-30',revision:'a'.repeat(64)}]}});if(u.pathname.endsWith('/workflow-contract'))return route.fulfill({json:{time_contract:{nodes:[]},visual_stages:[]}});reads.push(u.pathname);return route.fulfill({status:404,json:{detail:'NOT_MATERIALIZED'}})}const p=path.join(root,u.pathname.replace('/research-panel/',''));if(!p.startsWith(root)||!fs.existsSync(p))return route.fulfill({status:404,body:''});return route.fulfill({body:fs.readFileSync(p),contentType:p.endsWith('.mjs')?'text/javascript':p.endsWith('.css')?'text/css':'text/html'});});for(const [query,wanted]of [['20260230',null],['20261017','2026-10-17'],['2026-10-28','2026-10-28']]){reads=[];await page.goto('http://workbench.test/research-panel/workbench.html?date='+query);await page.waitForFunction(()=>document.getElementById('loadingState').textContent.includes('CANNOT_CONFIRM'));const text=await page.locator('#loadingState').innerText();if(wanted){assert(text.includes(wanted)&&text.includes('未物化'));assert.equal(await page.locator('#date').inputValue(),wanted);assert.deepEqual(reads,['/api/v4/research/workbench/days/'+wanted]);assert((await page.locator('#macLegacyStockPage').getAttribute('href')).includes(wanted));}else assert.equal(reads.length,0);assert.equal(await page.locator('#content').isHidden(),true);console.log(JSON.stringify({query,wanted,text,reads}));}await page.evaluate(()=>{window.eventCloseCount=0;const close=EventSource.prototype.close;EventSource.prototype.close=function(){window.eventCloseCount++;return close.call(this)};window.StockPanelHost.bindDay({source_date:'2026-10-29',observation_date:'2026-10-30',generation:'a'.repeat(64),input_sha256:'b'.repeat(64)});document.getElementById('marketCards').textContent='OLD_D29_CARDS';});await page.locator('#date').dispatchEvent('change');await page.waitForFunction(()=>window.eventCloseCount===1);assert(!(await page.locator('#marketCards').innerText()).includes('OLD_D29_CARDS'));assert.equal(await page.locator('#date').inputValue(),'2026-10-28');await page.close();}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});"""
    result=subprocess.run([node,'-e',script,str(tmp_path)],cwd=root,text=True,capture_output=True)
    assert result.returncode==0,result.stderr

def test_homepage_fixed_bundle_patch_follows_current_query_and_rejects_drift(tmp_path):
    from ops.build_mac_workbench import build_homepage_entry
    root=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/workbench-rectification-20261030-r1-api/app/apps/web/dist')
    index=root/'index.html';bundle=root/'assets/main-DoI_EeJQ.js'
    result=build_homepage_entry(bundle,index,hashlib.sha256(index.read_bytes()).hexdigest(),tmp_path/'built')
    new=tmp_path/'built'/result['files'][0]['path'];text=new.read_text()
    assert '/assets/'+new.name in (tmp_path/'built/index.html').read_text() and 'daily.html?date=2026-10-28' not in text
    helper=text.splitlines()[0]
    node='/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    script="const assert=require('node:assert/strict');const window={location:{search:'?date=20261017&stage=STAGE_0925'}};"+helper+";assert.equal(researchWorkbenchHref(),'/research-panel/workbench.html?date=20261017');window.location.search='';assert.equal(researchWorkbenchHref(),'/research-panel/workbench.html');window.location.search='?date=2026-10-28';assert.equal(researchWorkbenchHref(),'/research-panel/workbench.html?date=2026-10-28');"
    subprocess.run([node,'-e',script],check=True,capture_output=True)
    import pytest
    bad=tmp_path/'drift.js';bad.write_text('changed')
    with pytest.raises(ValueError,match='SHA_DRIFT'):build_homepage_entry(bad,index,hashlib.sha256(index.read_bytes()).hexdigest(),tmp_path/'bad')
