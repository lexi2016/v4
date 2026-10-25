// Executes the exact deployed loadStageSnapshot with saved-byte fetch, no network.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const esbuild = require('/Users/lexi/Desktop/学习/v4_app/apps/web/node_modules/esbuild/lib/main.js');
const deployed = '/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-share-stage-history-restore-20261025-r3/app/apps/web/src/api/pool_stage.ts';
const root = __dirname;
const sha = x => crypto.createHash('sha256').update(x).digest('hex');
const manifest = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const bundle = esbuild.buildSync({entryPoints:[deployed],bundle:true,platform:'node',format:'cjs',write:false,nodePaths:['/Users/lexi/Desktop/学习/v4_app/apps/web/node_modules']}).outputFiles[0].contents;
fs.writeFileSync(path.join(root,'deployed_validator.cjs'), bundle);
const {loadStageSnapshot} = require(path.join(root,'deployed_validator.cjs'));
(async()=>{
 const results=[];
 for (const cell of manifest.cells) {
  const raw = fs.readFileSync(cell.path);
  if (cell.sha256 && sha(raw)!==cell.sha256) throw new Error('SAVED_PAYLOAD_SHA_DRIFT:'+cell.path);
  const payload=JSON.parse(raw);
  global.fetch=async()=>({ok:true,json:async()=>structuredClone(payload)});
  try { const accepted=await loadStageSnapshot(cell.trade_date,cell.stage_id); results.push({...cell,accepted:true,A_rows:accepted.selected_a_rows}); }
  catch(error) {results.push({...cell,accepted:false,first_error:String(error.message)});}
 }
 const report={schema:'EXACT_DEPLOYED_LOAD_STAGE_SNAPSHOT_OFFLINE_V1',frontend_source:deployed,frontend_sha256:sha(fs.readFileSync(deployed)),compiled_bundle_sha256:sha(bundle),node:process.version,network_requests:0,results};
 fs.writeFileSync(process.argv[3],JSON.stringify(report,null,2)+'\n');
 process.stdout.write(JSON.stringify({checked:results.length,accepted:results.filter(x=>x.accepted).length,failures:results.filter(x=>!x.accepted).map(x=>({date:x.trade_date,stage:x.stage_id,error:x.first_error}))})+'\n');
})().catch(e=>{process.stderr.write(String(e.stack)+'\n');process.exitCode=1;});
