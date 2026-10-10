/** Real V5 owner code with explicitly synthetic empty inputs, never 392 replay. */
import {readFileSync} from 'node:fs';
import {afterEach,describe,expect,it,vi} from 'vitest';
import {validateManagerWorkspace,requestManagerWorkspace} from './managerWorkspace';
const envelope=()=>{
 const path=process.env.V5_SYNTHETIC_CURRENT_RECOVERY_RESPONSE;
 if(!path)throw new Error('SYNTHETIC_CURRENT_RECOVERY_TEST_RESPONSE_REQUIRED');
 const value=JSON.parse(readFileSync(path,'utf8'));
 expect(value.kind).toBe('SYNTHETIC_EMPTY_OWNER_NOT_BUSINESS_EVIDENCE');return value;
};
const fixture=()=>envelope().result.payload;
afterEach(()=>vi.unstubAllGlobals());
describe('cloud CURRENT_RECOVERY synthetic owner response',()=>{
 it('accepts the exact generated owner run and SHA without historical promotion',()=>{
  const value=envelope();const raw=value.result.payload;
  const before=JSON.stringify(raw);const result=validateManagerWorkspace(raw,'20261009');
  expect(result.plan_product).toMatchObject({status:'CURRENT_RECOVERY',run_id:value.expected_run,sha256:value.expected_sha,consumed:true,historical_eligible:false});
  expect(JSON.stringify(raw)).toBe(before);
 });
 it('rejects broken context, provenance, date and same-run identities',()=>{
  for(const [where,key,value] of [
   ['read_context','v5_contract','wrong'],['read_context','historical_eligible',true],
   ['read_context','requested_view','historical'],['read_context','owner_view','historical'],
   ['read_context','read_as_of',null],['read_context','read_as_of','2020-01-01T00:00:00Z'],
   ['plan_product','consumed',false],['plan_product','historical_eligible',true],
   ['plan_product','sha256','bad'],['plan_product','run_id',null],['plan_product','status','CURRENT'],
   ['plan_product','owner_status','UNVERIFIED'],
  ] as const){
   const raw=fixture();raw[where][key]=value;
   expect(()=>validateManagerWorkspace(raw,'20261009'),`${where}.${key}`).toThrow(/WORKSPACE_/);
  }
  expect(()=>validateManagerWorkspace(fixture(),'20261008')).toThrow();
 });
 it('admits ordinary auto but rejects historical and dynamic relabeling',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(fixture()),{status:200})));
  const signal=new AbortController().signal;
  await expect(requestManagerWorkspace('20261009',signal,'auto')).resolves.toBeTruthy();
  await expect(requestManagerWorkspace('20261009',signal,'historical')).rejects.toThrow('WORKSPACE_VIEW_MISMATCH');
  await expect(requestManagerWorkspace('20261009',signal,'dynamic')).rejects.toThrow('WORKSPACE_VIEW_MISMATCH');
 });
});
