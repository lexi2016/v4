// @vitest-environment jsdom
import {describe,it,expect} from 'vitest';
import {validateManagerWorkspace} from '../../api/managerWorkspace';
import {renderResearchAttention} from '../researchAttention';
import {fixture,date} from './fixtures/issue8R2.fixture';

const symbols=['NVDA','AVGO','AMD','COHR','LITE','CIEN','SOXX','MU','WDC','STX','VRT','DLR','EQIX',
  'CLOU','ARKX','UFO','BOTZ','DRIV','NLR','GRID','ITA','ICLN','TAN','LIT','XLE','FCG','COPX','GLD',
  'KBE','XBI','XLY','XLP','REMX'];
const flags={RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false};

function workspaceWithUsAssessments():any{
  const payload=fixture(),payloadSha='a'.repeat(64);
  const relations=[
    ['HK.00992','Lenovo Group Limited','NVDA'],['HK.01211','BYD Company Limited','NVDA'],
    ['HK.09868','XPeng Inc.','NVDA'],['HK.02015','Li Auto Inc.','NVDA'],
    ['HK.01810','Xiaomi Corporation','NVDA'],['HK.00992','Lenovo Group Limited','AMD'],
    ['HK.06166','Cambridge Industries Group','LITE'],['HK.06166','Cambridge Industries Group','COHR'],
    ['HK.06088','FIT Hon Teng Limited','AVGO'],['HK.00763','ZTE Corporation','CIEN'],
    ['HK.06823','HKT Trust and HKT Limited','DLR'],['HK.09988','Alibaba Group Holding Limited','EQIX'],
    ['HK.00992','Lenovo Group Limited','STX'],['HK.00992','Lenovo Group Limited','VRT'],
  ].map(([hk_symbol,hk_name,us_symbol],index)=>({hk_symbol,hk_code:hk_symbol.slice(3),hk_name,us_symbol,
    relationship_type:index===0?'TEST_FIXTURE_DOCUMENTED_COMPONENT_OPTION':'NAMED_TECHNOLOGY_INTEGRATION_CUSTOMER',
    direction:index===0?'TEST_FIXTURE_HK_BUYER_CAN_SELECT_US_COMPONENT_OPTION':
      'HK_CUSTOMER_OR_INTEGRATOR_OF_US_TECHNOLOGY_PROVIDER',
    evidence_timing:'RETROSPECTIVE_AFTER_TARGET_DATE',
    evidence_review_status:'SOURCE_EVIDENCE_CAPTURED_REVIEW_PENDING',
    target_date_eligibility:'CANNOT_CONFIRM',
    sources:[{title:'Official primary source',url:'https://example.com/source',source_body_sha256:'b'.repeat(64)}],
    ...flags}));
  const gapAssessments:Record<string,any>={
    MU:{us_symbol:'MU',candidate_hk_code:'00992',candidate_hk_symbol:'HK.00992',status:'ASSESSED_WITH_GAPS',
      conclusion:'CANNOT_CONFIRM',reason:'Micron source was readable only through web extraction; HTTP response body hash is unavailable.',
      available_at:'2026-10-11T10:10:25.875Z',reviewed_at:'2026-10-11T10:20:00+08:00',
      limitations:['TEST_FIXTURE; body hash unavailable.'],assessment_sha256:'f'.repeat(64),
      review_receipt_sha256:'e'.repeat(64),target_date_eligibility:'CANNOT_CONFIRM',
      sources:[{title:'Micron official release',url:'https://investors.micron.com/example',published_at:'2024-05-07',
        source_capture_status:'HTTP_429_NO_RESPONSE_BODY',source_body_sha256:null,
        source_body_sha256_status:'CANNOT_CONFIRM',source_locator:'Direct GET 429; no response body.'}],...flags},
    WDC:{us_symbol:'WDC',candidate_hk_code:'00992',candidate_hk_symbol:'HK.00992',status:'ASSESSED_WITH_GAPS',
      conclusion:'CANNOT_CONFIRM',reason:'Current product table says WDC without expanding the issuer name.',
      available_at:'2026-10-11T10:10:28.372Z',reviewed_at:'2026-10-11T10:20:00+08:00',
      limitations:['TEST_FIXTURE; issuer expansion unresolved.'],assessment_sha256:'d'.repeat(64),
      review_receipt_sha256:'e'.repeat(64),target_date_eligibility:'CANNOT_CONFIRM',
      sources:[{title:'Current Lenovo guide',url:'https://lenovopress.lenovo.com/example',published_at:'2026-09-16',
        source_capture_status:'HTTP_RESPONSE_BODY_CAPTURED',source_body_sha256:'c'.repeat(64),
        source_body_sha256_status:'VERIFIED_SHA256_HTTP_RESPONSE_BODY_BYTES',source_locator:'D4390 table.'},
        {title:'Withdrawn Lenovo SS530 guide',url:'https://lenovopress.lenovo.com/historical',
          source_capture_status:'WEB_EXTRACTED_WITHDRAWN_SOURCE_BODY_NOT_CAPTURED',source_body_sha256:null,
          source_body_sha256_status:'CANNOT_CONFIRM',source_locator:'Historical guide only.'}],...flags},
  };
  const assessments=symbols.map(symbol=>{
    const linked=relations.filter(relation=>relation.us_symbol===symbol);
    const isEtf=['SOXX','CLOU','ARKX','UFO','BOTZ','DRIV','NLR','GRID','ITA','ICLN','TAN','LIT','XLE',
      'FCG','COPX','GLD','KBE','XBI','XLY','XLP','REMX'].includes(symbol);
    return {symbol,instrument_classification:isEtf?'ETF_PROXY':'EQUITY_PROXY',quote_status:'VERIFIED',
      direction:'UP',quote_evidence:{session_date:'20261001',session_time:'16:00:00',change_pct:1.2,
        provider:'external_finance',source_payload_sha256:payloadSha},
      relation_assessment_status:linked.length?'SOURCE_EVIDENCE_CAPTURED_REVIEW_PENDING':
        gapAssessments[symbol]?'ASSESSED_WITH_GAPS':isEtf?'ETF_THEME_PROXY_ONLY':'NOT_EVALUATED',
      ...(gapAssessments[symbol]?{relation_assessment_evidence:gapAssessments[symbol]}:{}),
      relation_count:linked.length?linked.length:null,relations:linked,
      relation_gaps:linked.length?[]:gapAssessments[symbol]?[gapAssessments[symbol].reason]:
        isEtf?['ETF_PROXY_IS_NOT_AN_ISSUER_RELATION']:['RELATION_SEARCH_NOT_COMPLETE_FOR_SYMBOL'],
      target_date_eligibility:'CANNOT_CONFIRM',...flags};
  });
  payload.us_market_attention={...flags,schema_version:'v4.manager_research.us_market_bridge.v1',
    target_trade_date:date,research_cutoff:'2026-10-11T09:30:00+08:00',status:'READY',
    expected_us_session:'20261001',
    coverage_scope:'FIXED_24_INDUSTRY_PROXY_ROWS_AND_33_CONFIGURED_US_SYMBOLS_NOT_FULL_US_MARKET',
    raw_industry_up:[],raw_individual_up:[],gaps:[],
    coverage:{requested_symbol_count:33,available_symbol_count:33,assessed_symbol_count:33,unassessed_symbol_count:0},
    source_identity:{status:'VERIFIED',payload_sha256:payloadSha,receipt_sha256:'c'.repeat(64),manifest_sha256:'d'.repeat(64)},
    symbol_assessments:assessments,
    relation_evidence:{status:'PARTIAL_SOURCE_EVIDENCE_COVERAGE',artifact_sha256:'e'.repeat(64),
      eligible_relation_count:6,post_cutoff_relation_count:0,withheld_candidate_count:0,withheld_candidates:[],
      mapped_us_symbol_count:2,configured_us_symbol_count:33,coverage_complete:false,
      configured_equity_symbol_count:12,explicitly_assessed_equity_symbol_count:12,
      equity_assessment_coverage_complete:true,
      retrospective_relations_present:true,target_date_eligibility:'CANNOT_CONFIRM',gaps:['RELATION_EVIDENCE_COVERAGE_NOT_COMPLETE'],...flags}};
  payload.us_mapping_research={...flags,schema_version:'v4.manager_research.us_mapping_research.v1',
    target_trade_date:date,reviewed_research:null,
    daily_run:{...flags,schema_version:'v4.manager_research.us_mapping_daily_run.v1',target_trade_date:date,
      status:'NOT_RUN',run_id:null,matches:[],gaps:['US_MAPPING_NOT_RUN'],
      coverage:{reviewed_us_symbol_count:4,matched_us_symbol_count:null,matched_hk_relation_count:null,
        configured_us_universe_count:33,available_us_universe_count:33,full_market_coverage:false},
      research_cutoff:'2026-10-11T09:30:00+08:00',source_identity:null,target_date_eligibility:'CANNOT_CONFIRM'}};
  return payload;
}

describe('US mapping completion projection',()=>{
  it('validates and renders all configured quotes, retrospective customer links, ETF proxies, and the date-bound daily mapping state',()=>{
    const raw=workspaceWithUsAssessments();
    const validated=validateManagerWorkspace(raw,date);
    const host=document.createElement('section');
    renderResearchAttention(host,validated.research_attention,validated.us_market_attention,validated.selection_diagnostics,
      validated.us_mapping_research);

    expect(validated.us_market_attention?.symbol_assessments).toHaveLength(33);
    expect(host.querySelectorAll('[data-us-symbol]')).toHaveLength(33);
    expect(host.textContent).toContain('33/33');
    expect(host.textContent).toContain('ETF 主题代理（不是发行人）');
    expect(host.textContent).toContain('港股客户／集成方 → 美股技术提供方');
    expect(host.textContent).toContain('TEST_FIXTURE_DOCUMENTED_COMPONENT_OPTION');
    expect(host.textContent).toContain('TEST_FIXTURE_HK_BUYER_CAN_SELECT_US_COMPONENT_OPTION');
    expect(host.textContent).toContain('RETROSPECTIVE_AFTER_TARGET_DATE');
    expect(host.textContent).toContain('来源证据已记录，待人工复核');
    expect(host.textContent).toContain('目标日资格仍 CANNOT_CONFIRM');
    expect(validated.us_mapping_research?.target_trade_date).toBe(date);
    expect(host.textContent).toContain('每日 US-HK 已审映射');
    expect(host.textContent).toContain('该目标日尚无日常映射产物');
    expect(host.textContent).toContain('BYD Company Limited');
    expect(host.textContent).toContain('Li Auto Inc.');
    expect(host.textContent).toContain('Xiaomi Corporation');
    expect(host.textContent).toContain('个股关系已链接或有独立缺口评估 12/12');
    expect(host.textContent).toContain('ASSESSED_WITH_GAPS · CANNOT_CONFIRM');
    expect(host.textContent).toContain('HTTP_429_NO_RESPONSE_BODY');
    expect(host.textContent).toContain('WEB_EXTRACTED_WITHDRAWN_SOURCE_BODY_NOT_CAPTURED');
    const equities=(validated.us_market_attention?.symbol_assessments??[])
      .filter(row=>row.instrument_classification==='EQUITY_PROXY');
    expect(equities).toHaveLength(12);
    expect(equities.every(row=>row.relations.length>0 || row.relation_assessment_status==='ASSESSED_WITH_GAPS')).toBe(true);
    expect(host.textContent).not.toContain('关系数量为 0');
    expect(host.querySelector('button')).toBeNull();
  });

  it('decodes stale current coverage as unknown while retaining the saved verified empty count',()=>{
    const raw=workspaceWithUsAssessments();
    const daily=raw.us_mapping_research.daily_run;
    Object.assign(daily,{status:'CANNOT_CONFIRM',run_id:'saved-empty-run',generated_at:'2026-10-10T09:00:00+08:00',
      artifact_sha256:'b'.repeat(64),us_session_date:'20261008',
      matches:[],gaps:['STALE_INPUTS_CHANGED'],current_context_compatibility:'STALE_INPUTS_CHANGED',
      current_context_us_session:'20261009',current_context_source_payload_sha256:'f'.repeat(64),
      saved_product_status:'VALID_EMPTY',saved_product_us_session_date:'20261008',
      saved_product_source_payload_sha256:'a'.repeat(64),saved_product_match_count:0,
      latest_attempt_affects_saved_plan:false,latest_attempt_after_plan_cutoff:false,
      run_readback:{status:'VERIFIED',target_trade_date:date,run_id:'saved-empty-run',
        artifact_sha256:'b'.repeat(64),owner:'ManagerResearchJobService',read_at:'2026-10-11T10:00:00+08:00'}});
    daily.coverage.matched_us_symbol_count=null;
    daily.coverage.matched_hk_relation_count=null;

    const validated=validateManagerWorkspace(raw,date);
    const host=document.createElement('section');
    renderResearchAttention(host,validated.research_attention,validated.us_market_attention,
      validated.selection_diagnostics,validated.us_mapping_research);

    expect(validated.us_mapping_research?.daily_run.saved_product_match_count).toBe(0);
    expect(validated.us_mapping_research?.daily_run.coverage.matched_hk_relation_count).toBeNull();
    expect(host.textContent).toContain('当前会话一致性 STALE_INPUTS_CHANGED');
    expect(host.textContent).toContain('匹配数量未知');
    expect(host.textContent).not.toContain('匹配为0');
  });
});
