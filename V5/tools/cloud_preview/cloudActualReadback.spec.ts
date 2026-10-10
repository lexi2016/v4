import {readFileSync} from 'node:fs';
import {afterEach,expect,it,vi} from 'vitest';
import {waitFor} from '@testing-library/vue';
import {mountCatalystObservations} from './catalystObservationPanel';
let dispose:(()=>void)|undefined;
afterEach(()=>{dispose?.();vi.unstubAllGlobals();document.body.replaceChildren();window.history.replaceState({},'', '/');});
it('renders the saved cloud auto response with the same run and honest missing-source state',async()=>{
 const path=process.env.V5_CLOUD_WORKSPACE_RESPONSE;
 if(!path) throw new Error('V5_CLOUD_WORKSPACE_RESPONSE_REQUIRED');
 const payload=JSON.parse(readFileSync(path,'utf8'));
 expect(payload.plan_product.consumed).toBe(true);
 expect(payload.workspace_plan_attempt.run_id).toBe(payload.plan_product.run_id);
 const calls:URL[]=[];
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{
  const u=new URL(String(input),'http://localhost');calls.push(u);
  if(u.pathname.endsWith('/workspace'))return {ok:true,status:200,json:async()=>payload} as Response;
  return {ok:false,status:503,json:async()=>({status:'CANNOT_CONFIRM',reason_codes:['MODULE_RESULT_NOT_AVAILABLE']})} as Response;
 }));
 window.history.replaceState({},'', '/manager-selection/?date=20261012');
 const host=document.createElement('div');document.body.append(host);
 dispose=mountCatalystObservations(host,'20261012');
 await waitFor(()=>expect(host.querySelector('[data-read-state]')?.getAttribute('data-read-state')).toBe('READY'));
 expect(calls.filter(u=>u.pathname.endsWith('/workspace')).map(u=>Object.fromEntries(u.searchParams))).toEqual([{date:'20261012',view:'auto'}]);
 expect(host.textContent).toContain(payload.plan_product.run_id);
 expect(host.textContent).toContain('20261012');
 expect(host.querySelector('[data-daily-symbol]')).toBeNull();
 expect(host.textContent).toMatch(/未知|待核|未提供/);
});
