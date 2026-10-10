import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { validateManagerWorkspace, requestManagerWorkspace } from './managerWorkspace';
const fixture=()=>JSON.parse(readFileSync(resolve(process.env.V5_REAL_CURRENT_RECOVERY_RESPONSE || '../evidence/manager-read-publication.json'),'utf8')).result.payload;
afterEach(()=>vi.unstubAllGlobals());
describe('CURRENT_RECOVERY source-bound read',()=>{
 it('accepts the saved real recovery payload without changing its plan SHA',()=>{
  const raw=fixture();const result=validateManagerWorkspace(raw,'20261009');
  expect(result.plan_product).toMatchObject({status:'CURRENT_RECOVERY',run_id:'5b4feaf7ef7d4d13bec639e90b6d3db0',sha256:'56556a67ddc1a562e82b38e750be92fcfda070945397cc4eacffd1c79f42bcf0',consumed:true,historical_eligible:false});
 });
 it('rejects incomplete or falsely historical recovery identities',()=>{
  for(const [where,key,value] of [['read_context','v5_contract','wrong'],['read_context','historical_eligible',true],['read_context','requested_view','historical'],['read_context','owner_view','historical'],['read_context','read_as_of',null],['plan_product','consumed',false],['plan_product','historical_eligible',true],['plan_product','sha256','bad'],['plan_product','run_id',null],['plan_product','status','CURRENT']]){
   const raw=fixture();raw[where as string][key as string]=value;
   expect(()=>validateManagerWorkspace(raw,'20261009')).toThrow(/WORKSPACE_/);
  }
 });
 it('accepts ordinary auto and refuses explicit historical or dynamic relabeling',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(fixture()),{status:200})));
  const signal=new AbortController().signal;
  await expect(requestManagerWorkspace('20261009',signal,'auto')).resolves.toBeTruthy();
  await expect(requestManagerWorkspace('20261009',signal,'historical')).rejects.toThrow('WORKSPACE_VIEW_MISMATCH');
  await expect(requestManagerWorkspace('20261009',signal,'dynamic')).rejects.toThrow('WORKSPACE_VIEW_MISMATCH');
 });
});
