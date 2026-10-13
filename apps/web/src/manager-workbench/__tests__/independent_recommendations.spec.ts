import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import captured from './fixtures/independent-recommendations-http.local.json';
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/vue';
import Workbench from '../Workbench.vue';
import {firstReason,conditionLabel} from '../display';
import type {StockDecision} from '../types';
const fixture=captured.responses;
const response=(value:unknown)=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});
function install(){
 const fetch=vi.fn(async(value:RequestInfo|URL)=>{
  const url=new URL(String(value),'http://localhost');
  if(url.pathname.includes('/stocks/'))return response(url.searchParams.get('lane')==='US_MAPPING'?fixture.us_detail:fixture.oversold_detail);
  if(url.pathname.endsWith('/recommendations/US_MAPPING'))return response(fixture.us);
  if(url.pathname.endsWith('/recommendations/OVERSOLD'))return response(url.searchParams.get('decision')==='NOT_SELECTED'?fixture.oversold_alibaba_not_selected:fixture.oversold);
  throw new Error('Unexpected request '+url.pathname);
 });vi.stubGlobal('fetch',fetch);return fetch;
}
const category=()=>screen.getAllByRole('combobox').find(s=>within(s).queryByRole('option',{name:'未入选'}))!;
beforeEach(()=>window.history.replaceState(null,'','?date=20261013'));
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks();});
describe('two independent saved recommendation lists',()=>{
 it('defaults to US-only Alibaba watch with separate counts and source-specific details',async()=>{
  const fetch=install();render(Workbench);await screen.findByText('Alibaba Group Holding Limited');
  const table=screen.getByRole('table');expect(within(table).getAllByRole('row')).toHaveLength(2);
  expect(within(table).getByText(/Equinix于2017年/)).toBeTruthy();expect(within(table).queryByText(/收盘108.2/)).toBeNull();
  expect(screen.getByRole('button',{name:/美股映射推荐 · 严格入选 0 \/ 条件观察 1/})).toBeTruthy();
  expect(screen.getByRole('button',{name:/超跌推荐 · 严格入选 20 \/ 条件观察 277/})).toBeTruthy();
  expect(within(table).getByText(/已有合作关系仅支持条件观察/)).toBeTruthy();
  await fireEvent.click(within(table).getByRole('button',{name:/查看 HK.09988/}));
  await screen.findByRole('heading',{name:/美股映射 · 个股研究详情/});
  await waitFor(()=>expect(fetch.mock.calls.some(([u])=>String(u).includes('lane=US_MAPPING')&&String(u).includes('row_id=US_MAPPING'))).toBe(true));
  await screen.findByText('本推荐路径的已保存研究依据');
 });
 it('restores independent filters and opens oversold NOT_SELECTED for the same stock',async()=>{
  const fetch=install();render(Workbench);await screen.findByText('Alibaba Group Holding Limited');
  await fireEvent.click(screen.getByRole('button',{name:/超跌推荐/}));await screen.findByText(/服务端筛选后共 297 行/);
  await fireEvent.update(category(),'NOT_SELECTED');await screen.findByRole('button',{name:/查看 HK.09988/});
  expect(within(screen.getByRole('table')).getByText(/收盘 108.2/)).toBeTruthy();
  await fireEvent.click(within(screen.getByRole('table')).getByRole('button',{name:/查看 HK.09988/}));
  await waitFor(()=>expect(fetch.mock.calls.some(([u])=>String(u).includes('lane=OVERSOLD')&&String(u).includes('row_id=OVERSOLD'))).toBe(true));
  await fireEvent.click(screen.getByRole('button',{name:'返回名单'}));
  await fireEvent.click(screen.getByRole('button',{name:/美股映射推荐/}));await waitFor(()=>expect((category() as HTMLSelectElement).value).toBe(''));
  await fireEvent.click(screen.getByRole('button',{name:/超跌推荐/}));await waitFor(()=>expect((category() as HTMLSelectElement).value).toBe('NOT_SELECTED'));
 });
 it('ignores a late US response after switching to oversold',async()=>{
  let release!:(r:Response)=>void;const pending=new Promise<Response>(r=>release=r);
  vi.stubGlobal('fetch',vi.fn(async(u:RequestInfo|URL)=>String(u).includes('/US_MAPPING')?pending:response(fixture.oversold)));
  render(Workbench);await fireEvent.click(screen.getByRole('button',{name:/超跌推荐/}));
  await screen.findByText(/服务端筛选后共 297 行/);release(response(fixture.us));
  await waitFor(()=>expect(screen.getByRole('heading',{name:/超跌 · 独立港股推荐/})).toBeTruthy());
  expect(screen.getByText(/服务端筛选后共 297 行/)).toBeTruthy();
 });
 it('does not let another lane explain an aggregate watch; unknown condition codes remain unchanged',()=>{
  const stock={...fixture.us.data.stocks[0],lane_decisions:{US_MAPPING:fixture.us.data.stocks[0].lane_decisions.US_MAPPING,OVERSOLD:fixture.oversold_alibaba_not_selected.data.stocks[0].lane_decisions.OVERSOLD}} as StockDecision;
  expect(firstReason(stock)).toContain('Equinix');expect(firstReason(stock)).not.toContain('收盘');
  expect(conditionLabel('UNKNOWN_CONDITION')).toBe('UNKNOWN_CONDITION');
 });
});
