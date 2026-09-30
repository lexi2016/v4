import { describe, expect, it } from 'vitest';
import { renderResearchAttention } from '../researchAttention';
import type { ResearchAttention, UsMarketAttention } from '../../api/managerWorkspace';

const flags={RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false};

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
});
