import { afterEach, describe, expect, it, vi } from 'vitest';
import raw from './fixtures/three_lane_daily_synthetic.json';
import { renderDailyChannels, validateDailyChannels, workspaceRequestDateBindings } from '../dailyChannels';
import { refreshManagerWorkspace, requestManagerWorkspace } from '../../api/managerWorkspace';

const cases = raw.cases as Record<string, any>;
function workspaceResponse(date: string): Record<string, unknown> {
  return {schema_version:'v4.manager_research.workspace.v1',semantic_version:'20260921.manager-semantic.r3.v1',
    target_trade_date:date,input_identity:'a'.repeat(64),stocks:[],focus_symbols:[],company_events:[],
    rejected_relations:[],briefing:{},themes:[],materials:[],gaps:[],
    lanes:['STAGE','CATALYST','CLOSE'].map(lane=>({lane,owner:'synthetic-source',state:'NOT_RUN',target_date:date,
      stock_count:null,last_attempt_at:null,last_success_at:null,run_id:null,execution_kind:'READ_ONLY',
      failure_reasons:[],next_plan:null,schedule_status:'UNBOUND',input_coverage:{}})),
    summary:{stock_count:0,relation_count:0,theme_count:0,reused_material_count:0,formal_recommendation_count:0},
    date_bindings:{plan_date:date,selection_date:date,announcement_date:'20261008'},
    plan_context:{plan_trade_date:date,research_cutoff:'2026-10-11T09:00:00+08:00'},
    read_context:{mode:'CURRENT_DYNAMIC_PREVIEW',status:'VERIFIED_WITH_GAPS',
      as_of:'2026-10-11T09:00:00+08:00',candidate_count_known:false,contract:'20260923.workspace-history-read.r1'},
    RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false};
}
afterEach(() => { vi.unstubAllGlobals(); document.body.replaceChildren(); });

describe('original three-lane readback contracts', () => {
  it.each(['partial', 'empty', 'missing', 'stage'])('admits the actual Python projection for %s synthetic inputs', (name) => {
    const value = structuredClone(cases[name]);
    expect(validateDailyChannels(value.daily_channels, value.date_bindings, value)).toBe(value.daily_channels);
  });
  it('retains all 61 native Stage rows and unknown availability after DOM reload', () => {
    const value=cases.stage;
    const host=document.createElement('div');document.body.append(host);
    for (let read=0;read<2;read++) {
      renderDailyChannels(host, value.daily_channels, value.date_bindings);
      const hk=host.querySelector('[data-daily-channel="HK_CONNECT"]')!;
      expect(hk.querySelectorAll('[data-daily-symbol]')).toHaveLength(61);
      expect(hk.textContent).toContain('原 Stage 已保存产物，执行与可用时间待核');
      expect(hk.textContent).toContain('run-original-fixture');
      expect(hk.textContent).not.toContain('产物时间');
    }
  });
  it.each(['selection_receipt_sha256','run_id','product_sha256'])('rejects a changed Stage %s binding', (field) => {
    const value=structuredClone(cases.stage);
    value.daily_channels.channels[1][field]=field==='run_id' ? 'another-run' : '9'.repeat(64);
    expect(() => validateDailyChannels(value.daily_channels,value.date_bindings,value)).toThrow();
  });
  it.each(['truncate', 'empty-zero', 'empty-unknown', 'reverse', 'name', 'reason', 'lane-evidence', 'source-ref', 'membership'])
    ('rejects a Stage projection changed by %s against its complete original source', (change) => {
      const value=structuredClone(cases.stage);
      const channel=value.daily_channels.channels[1];
      if (change==='truncate') { channel.rows=channel.rows.slice(0,50); channel.candidate_count=50; }
      if (change==='empty-zero') { channel.rows=[]; channel.candidate_count=0; }
      if (change==='empty-unknown') { channel.rows=[]; channel.candidate_count=null; }
      if (change==='reverse') channel.rows.reverse();
      if (change==='name') channel.rows[0].name='Changed name';
      if (change==='reason') channel.rows[0].reason='Changed reason';
      if (change==='lane-evidence') channel.rows[0].lane_evidence=['Changed evidence'];
      if (change==='source-ref') channel.rows[0].source_refs[0].receipt_sha256='9'.repeat(64);
      if (change==='membership') {
        channel.authority.codes=channel.authority.codes.slice(0,50);
        channel.rows=channel.rows.slice(0,50); channel.candidate_count=50;
      }
      expect(() => validateDailyChannels(value.daily_channels,value.date_bindings,value)).toThrow();
    });
  it('admits the full ordered member subset and preserves unknown when that subset is empty', () => {
    const value=structuredClone(cases.stage);
    const channel=value.daily_channels.channels[1];
    for (const members of [channel.authority.codes.slice(1), []]) {
      channel.authority.codes=members;
      value.selection_diagnostics.membership.codes=members;
      channel.rows=cases.stage.daily_channels.channels[1].rows.filter((row: any)=>members.includes(row.symbol));
      channel.candidate_count=channel.rows.length || null;
      channel.gaps=['HK_SELECTION_EXECUTION_AND_AVAILABILITY_NOT_VERIFIED',
        ...cases.stage.daily_channels.channels[1].rows.filter((row: any)=>!members.includes(row.symbol))
          .map((row: any)=>`NOT_IN_TARGET_HK_CONNECT_UNIVERSE:${row.symbol}`)];
      expect(validateDailyChannels(value.daily_channels,value.date_bindings,value)).toBe(value.daily_channels);
    }
    channel.candidate_count=0;
    expect(() => validateDailyChannels(value.daily_channels,value.date_bindings,value)).toThrow();
  });
  it.each(['historical', 'backfill-run', 'backfill-mode', 'selection_mode=BACKFILL',
    'recovery_mode=HISTORICAL_BACKFILL', 'HISTORICAL_BACKFILL', 'substitute_kind=HK_0930_0935_FOR_HK_0925'])
    ('rejects original Stage provenance with %s before admitting daily rows', (rejection) => {
      const value=structuredClone(cases.stage);
      if (rejection==='historical') value.read_context={mode:'HISTORICAL_AS_OF'};
      else for (const source of [value.daily_channels.channels[1].source_result,
        value.stage_selection_readback.markets.HK_CONNECT]) {
        if (rejection==='backfill-run') source.backfill_run_id='original-backfill-run';
        else if (rejection==='backfill-mode') source.selection_mode='BACKFILL';
        else source.source_evidence=[rejection];
      }
      expect(() => validateDailyChannels(value.daily_channels,value.date_bindings,value)).toThrow();
    });
  it('keeps a valid zero in its own lane while other lanes remain unknown', () => {
    const value=cases.empty;
    const host=document.createElement('div');
    renderDailyChannels(host,value.daily_channels,value.date_bindings);
    expect(host.querySelector('[data-daily-channel="OVERSOLD"]')?.textContent).toContain('候选 0 只');
    expect(host.querySelector('[data-daily-channel="HK_CONNECT"]')?.textContent).toContain('候选数量未知');
    expect(host.querySelector('[data-daily-channel="ANNOUNCEMENT"]')?.textContent).toContain('候选数量未知');
  });
  it('forwards only explicit publication/selection aliases, retaining backend calendar defaults', () => {
    expect(workspaceRequestDateBindings(new URLSearchParams('date=20261009&plan_date=20261009'))).toEqual({});
    expect(workspaceRequestDateBindings(new URLSearchParams('selection_date=2026-10-08&publication_date=2026-10-07')))
      .toEqual({selection_date:'20261008',announcement_date:'20261007'});
    expect(() => workspaceRequestDateBindings(new URLSearchParams('announcement_date=2026-02-30'))).toThrow();
  });
  it('validates POST response against the requested publication date', async () => {
    const date='20261009';
    const response=workspaceResponse(date);
    const fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify(response),{status:200}));vi.stubGlobal('fetch',fetch);
    await expect(refreshManagerWorkspace(date,new AbortController().signal,{announcement_date:'20261007'}))
      .rejects.toThrow('WORKSPACE_DAILY_DATE_BINDING_MISMATCH');
    expect(String(fetch.mock.calls[0][0])).toContain('announcement_date=20261007');
  });
  it.each(['GET','POST'])('rejects an unbound %s response when an explicit source date was requested', async (method) => {
    const date='20261009'; const response=workspaceResponse(date); delete response.date_bindings;
    vi.stubGlobal('fetch',vi.fn().mockImplementation(()=>Promise.resolve(new Response(JSON.stringify(response),{status:200}))));
    const signal=new AbortController().signal;
    const request = method==='GET'
      ? requestManagerWorkspace(date,signal,'auto',{announcement_date:'20261007'})
      : refreshManagerWorkspace(date,signal,{announcement_date:'20261007'});
    await expect(request).rejects.toThrow('WORKSPACE_DAILY_DATE_BINDING_MISSING');
    // Existing responses remain readable when no source date was explicitly chosen.
    await expect(requestManagerWorkspace(date,signal,'auto')).resolves.toMatchObject({target_trade_date:date});
  });
});
