import { describe, expect, it } from 'vitest';
import { renderResearchAttention } from '../researchAttention';
import type { ResearchAttention, UsMarketAttention } from '../../api/managerWorkspace';

const flags={RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false};
const historicalUs={
  schema_version:'v4.manager_research.us_market_bridge.v1',target_trade_date:'20260930',
  research_cutoff:'2026-09-30T09:27:08.283634+08:00',status:'READY',expected_us_session:'20260929',
  coverage_scope:'FIXED_24_INDUSTRY_PROXY_ROWS_AND_33_CONFIGURED_US_SYMBOLS_NOT_FULL_US_MARKET',
  selection_semantics:'POSITIVE_CHANGE_GT_ZERO_NOT_LARGE_GAIN_SCREEN',
  raw_industry_up:[
    {label:'CPO',pct_change:4.074828,status:'READY'},{label:'黄金',pct_change:1.32042,status:'READY'},
    {label:'新能源',pct_change:1.189768,status:'READY'},{label:'半导体',pct_change:1.185827,status:'READY'},
    {label:'光伏',pct_change:1.069767,status:'READY'},{label:'数据中心',pct_change:0.621453,status:'READY'},
    {label:'稀土',pct_change:0.527377,status:'READY'},{label:'电网',pct_change:0.416831,status:'READY'},
    {label:'机器人',pct_change:0.313123,status:'READY'},{label:'锂电池',pct_change:0.292912,status:'READY'},
    {label:'AI算力',pct_change:0.270542,status:'READY'},{label:'铜/有色',pct_change:0.269763,status:'READY'},
    {label:'生物医药',pct_change:0.146862,status:'READY'},{label:'存储',pct_change:0.077887,status:'READY'},
  ],
  raw_individual_up:[
    {symbol:'LITE',change_pct:5.662528,session_date:'20260929'},{symbol:'COHR',change_pct:3.459019,session_date:'20260929'},
    {symbol:'CIEN',change_pct:3.102937,session_date:'20260929'},{symbol:'VRT',change_pct:1.798885,session_date:'20260929'},
    {symbol:'AVGO',change_pct:1.581944,session_date:'20260929'},{symbol:'GLD',change_pct:1.32042,session_date:'20260929'},
    {symbol:'ICLN',change_pct:1.189768,session_date:'20260929'},{symbol:'SOXX',change_pct:1.185827,session_date:'20260929'},
    {symbol:'TAN',change_pct:1.069767,session_date:'20260929'},{symbol:'MU',change_pct:1.053151,session_date:'20260929'},
    {symbol:'REMX',change_pct:0.527377,session_date:'20260929'},{symbol:'GRID',change_pct:0.416831,session_date:'20260929'},
    {symbol:'EQIX',change_pct:0.415402,session_date:'20260929'},{symbol:'BOTZ',change_pct:0.313123,session_date:'20260929'},
    {symbol:'LIT',change_pct:0.292912,session_date:'20260929'},{symbol:'COPX',change_pct:0.269763,session_date:'20260929'},
    {symbol:'XBI',change_pct:0.146862,session_date:'20260929'},{symbol:'XLY',change_pct:0.12844,session_date:'20260929'},
    {symbol:'WDC',change_pct:0.05516,session_date:'20260929'},
  ],
  coverage:{industry_proxy_count:24,requested_symbol_count:33,available_symbol_count:19},
  source_identity:{payload_sha256:'7eb0094a0546f62f5346dddd795977e8bbda3520e34eed03f2556b2fdfd81566',
    receipt_sha256:'9ee7e53afdd8ce42f11a6ede4f0569a92553bea308eec5f97d253b3d895e5879',
    manifest_sha256:'65cb30a8599b05d38b9aa70d1ecc655d6f6d9d1076b04567b140f9581147a58b'},
  gaps:[],historical_source_recheck:{state:'COMPLETED_READ_ONLY_RECHECK',source_status:'READY',
    saved_plan_run_id:'ba13fba330464300b760fe940ba579a1',saved_plan_sha256:'3ac5534e6310fd63b6f01f17c5d85ae015460513a967d97f7b142a44717d8ce2',
    research_cutoff:'2026-09-30T09:27:08.283634+08:00',checked_at:'2026-10-01T00:00:00+08:00',
    saved_plan_modified:false,selected_stock_verdict_modified:false},...flags,
} as unknown as UsMarketAttention;

describe('research attention renderer',()=>{
  it('keeps evidence priority separate from original screen rank and preserves raw US movers',()=>{
    const host=document.createElement('div');
    const attention={schema_version:'v4.manager_research.research_attention.v1',target_trade_date:'20260924',
      research_cutoff:'2026-09-24T09:27:35+08:00',status:'READY_WITH_GAPS',priority_name:'RESEARCH_ATTENTION_NOT_EXISTING_FOCUS_OR_BUY_RANK',
      config:{version:'20260925.research-attention.proposal-v1',status:'PROPOSAL_ONLY'},coverage:{},gaps:[],input_identity:'a'.repeat(64),
      strict_near_unchanged:true,existing_focus_rank_unchanged:true,stage_unchanged:true,cards:[{symbol:'HK.09690',name:'Fixture',
        research_attention_score:58,research_attention_band:'IMMEDIATE_RESEARCH',qualified_lane_count:2,qualified_lanes:['OFFICIAL_ANNOUNCEMENT','STRICT_NEAR_SCREEN'],
        why_now:['OFFICIAL_ANNOUNCEMENT:42','STRICT_NEAR_SCREEN:6'],missing:[],screen_classification:'NEAR_CONDITION',original_screen_rank:185,
        evidence:[{evidence_lane:'OFFICIAL_ANNOUNCEMENT',evidence_class:'OFFICIAL_PARSED_DOCUMENT',published_at:'2026-09-24T08:14:00+08:00',source_url:'https://www.hkexnews.hk/fixture.pdf'}],...flags}],...flags} as unknown as ResearchAttention;
    const us={schema_version:'v4.manager_research.us_market_bridge.v1',target_trade_date:'20260924',research_cutoff:'2026-09-24T09:27:35+08:00',
      status:'PARTIAL',expected_us_session:'20260923',coverage_scope:'FIXED_24_INDUSTRY_PROXY_ROWS_AND_33_CONFIGURED_US_SYMBOLS_NOT_FULL_US_MARKET',
      raw_industry_up:[{label:'AI算力',pct_change:2.3,status:'READY'}],raw_individual_up:[{symbol:'NVDA',change_pct:1.7,session_date:'20260923'}],coverage:{},source_identity:null,gaps:[],...flags} as unknown as UsMarketAttention;
    renderResearchAttention(host,attention,us);
    expect(host.textContent).toContain('不是原筛选／focus／BUY 排名');
    expect(host.textContent).toContain('原near/strict内部rank：185');
    expect(host.textContent).toContain('美股原始上涨发现');
    expect(host.textContent).toContain('NVDA');
    expect(host.textContent).toContain('NOT_FULL_US_MARKET');
  });

  it('renders the exact historical US raw rows when research attention is missing',()=>{
    const host=document.createElement('div');
    renderResearchAttention(host,undefined,historicalUs);
    expect(host.textContent).toContain('研究优先级未读取');
    expect(host.textContent).toContain('优先级未知且不等于0只');
    expect(host.textContent).toContain('原计划未消费本次回查');
    expect(host.textContent).toContain('计划/选股判定未改');
    expect(host.textContent).toContain('历史来源已重新核验');
    expect(host.textContent).toContain('保存 cutoff 2026-09-30T09:27:08.283634+08:00');
    expect(host.textContent).toContain('US session 20260929');
    expect(host.textContent).toContain('行业代理上涨 14 条');
    expect(host.textContent).toContain('配置内个股上涨 19 条');
    for(const row of historicalUs.raw_industry_up)expect(host.textContent).toContain(row.label);
    for(const row of historicalUs.raw_individual_up)expect(host.textContent).toContain(row.symbol);
    expect(host.querySelectorAll('.research-attention-card')).toHaveLength(0);
  });

  it('does not fabricate raw US rows when the owner input is missing',()=>{
    const host=document.createElement('div');
    renderResearchAttention(host,undefined,undefined);
    expect(host.textContent).toContain('研究优先级未读取');
    expect(host.textContent).toContain('US owner 未绑定/未读取，覆盖未知。');
    expect(host.textContent).not.toContain('行业代理上涨');
    expect(host.textContent).not.toContain('配置内个股上涨');
  });
});
