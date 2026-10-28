// Compiles and tests the actual new TS client; only HTTP transport is mocked.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const cp = require('node:child_process');
const root = path.resolve(__dirname,'../..');
const source = path.join(root,'apps/web/src/api/wechat_research.ts');
let mod;
async function client() {
  if (mod) return mod;
  assert.ok(fs.existsSync(source), 'Stage A TypeScript client is not implemented');
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'wechat-ts-test-'));
  try {
    cp.execFileSync('tsc',[source,'--outDir',dir,'--target','ES2022','--module','ES2022','--strict','--lib','ES2022,DOM','--skipLibCheck']);
    const js=fs.readFileSync(path.join(dir,'wechat_research.js'),'utf8');
    fs.writeFileSync(path.join(dir,'client.mjs'),js);
    mod=await import(pathToFileURL(path.join(dir,'client.mjs')).href);
  } finally { fs.rmSync(dir,{recursive:true,force:true}); }
  return mod;
}
const safety={RESEARCH_ONLY:true,WATCH_ONLY:true,NO_BUY_GATE:true,production_allowed:false,buy_gate_updated:false,orders_sent:false};
const rid='a'.repeat(64);
function material() { return {...safety,record_id:rid,article:{article_id:null,title:'报告',account:null,biz:null,url:'https://mp.weixin.qq.com/s/test',article_date:'20260917',published_at:null,metadata_origin:'IMPORT_RECEIPT'},identity:{package_id:'old',source_run_id:'run',input_digest:null,return_id:null,receipt_sha256:'b'.repeat(64),package_sha256:null,manifest_sha256:null,package_sha256_status:'UNKNOWN'},received_at:'2026-09-20T16:20:03+08:00',indexed_at:'2026-09-20T10:00:00+00:00',available_at:null,states:{archive:'REPORT_ONLY_ARCHIVED',input_binding:'LEGACY_INPUT_UNVERIFIED',structure:'MISSING',research_review:'NOT_EVALUATED_STAGE_A'},receipt_claims:{archive:'REPORT_ONLY_ARCHIVED',structure:'MISSING',input_binding_valid:false,semantic_research_accepted:false,independent_review_scope:[]},missing_artifacts:['coverage.csv','mentions.csv','unmapped.csv','summary.json'],cannot_confirm:['AVAILABLE_AT_NOT_ESTABLISHED'],source_status:'NOT_REGISTERED',origin:'USER_PROVIDED_CHAT_RETURN',archive_owner:'WECHAT_LOCAL_ARCHIVE',write_policy:'READ_ONLY'}; }
function listing() {return {...safety,schema_version:'v4.wechat_materials.stage_a.v1',status:'READY',query:{date:'20260917',date_basis:'article',q:'',limit:20},timezone:'Asia/Shanghai',items:[material()],total:1,returned:1,next_cursor:null,index_revision:'c'.repeat(64)};}
function detail() {return {...safety,schema_version:'v4.wechat_materials.stage_a.v1',status:'READY',material:material(),report:{status:'READABLE',content:'# 报告\n<script>bad</script>'},artifacts:[{artifact_id:'report',filename:'report.md',sha256:'d'.repeat(64),bytes:38,kind:'CHAT_RETURN',status:'HASH_MATCH'}]};}
function respond(obj,status=200) {global.fetch=async()=>new Response(JSON.stringify(obj),{status,headers:{'content-type':'application/json'}});}
test('report-only list and detail keep null states without stock objects',async()=>{const m=await client();respond(listing());let r=await m.loadWechatMaterials({date:'20260917'});assert.equal(r.items[0].available_at,null);respond(detail());r=await m.loadWechatMaterial(rid);assert.equal(r.material.states.input_binding,'LEGACY_INPUT_UNVERIFIED');assert.match(r.report.content,/<script>/);});
test('wrong date, query, counts, safety and schema are rejected',async()=>{const m=await client();for(const mutate of [x=>x.query.date='20260918',x=>x.total=0,x=>x.returned=2,x=>x.orders_sent=true,x=>x.schema_version='other',x=>x.items.push(x.items[0])]){const x=listing();mutate(x);respond(x);await assert.rejects(m.loadWechatMaterials({date:'20260917'}));}});
test('wrong detail version is never displayed',async()=>{const m=await client();const x=detail();x.material.record_id='e'.repeat(64);respond(x);await assert.rejects(m.loadWechatMaterial(rid));});
test('unsafe URLs and arbitrary artifact IDs do not become executable links',async()=>{const m=await client();for(const value of ['javascript:alert(1)','data:text/html,hi','file:///etc/passwd','//evil.test','https://good.test@evil.test','https://ok\\@evil.test'])assert.equal(m.safeArticleUrl(value),'');assert.equal(m.safeArticleUrl('https://mp.weixin.qq.com/s/test'),'https://mp.weixin.qq.com/s/test');assert.throws(()=>m.wechatArtifactUrl('../x','report'));assert.throws(()=>m.wechatArtifactUrl(rid,'../../x'));assert.throws(()=>m.wechatArtifactUrl(rid,'javascript:'));assert.ok(m.wechatArtifactUrl(rid,'report').endsWith('/artifacts/report'));});
test('HTTP failure, HTML instead of JSON, and pre-abort fail explicitly',async()=>{const m=await client();respond({detail:{code:'HASH_MISMATCH'}},409);await assert.rejects(m.loadWechatMaterial(rid),/HASH_MISMATCH/);global.fetch=async()=>new Response('<html/>');await assert.rejects(m.loadWechatMaterial(rid));const abort=new AbortController();abort.abort();await assert.rejects(m.loadWechatMaterials({date:'20260917'},abort.signal));});
test('no-config and empty are distinct legitimate list results',async()=>{const m=await client();for(const status of ['NOT_CONFIGURED','NOT_INDEXED','READY']){const x=listing();Object.assign(x,{status,items:[],total:0,returned:0});respond(x);const r=await m.loadWechatMaterials({date:'20260917'});assert.equal(r.status,status);}});
