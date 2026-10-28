// @vitest-environment jsdom
import {describe,it,expect} from 'vitest';
import {validateManagerWorkspace} from '../../api/managerWorkspace';
import {renderResearchAttention} from '../researchAttention';
import {fixture,date} from './fixtures/issue8R2.fixture';

const flags={RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false};
const refs=[
  {owner:'panel-owner',payload_path:'/owner/panel.json',payload_sha256:'a'.repeat(64),manifest_path:'/owner/panel.manifest.json',manifest_sha256:'b'.repeat(64)},
  {owner:'master-owner',payload_path:'/owner/master.json',payload_sha256:'c'.repeat(64),manifest_path:'/owner/master.manifest.json',manifest_sha256:'d'.repeat(64)},
];
function ledger(){
  const excluded=Array.from({length:35},(_,i)=>({
    symbol:`HK.${String(i+1).padStart(5,'0')}`,name:`排除${i+1}`,decision_status:'EXCLUDED',source_group:'excluded',
    source_row_count:1,source_row_indexes:[i+1],target_trade_date:date,source_date:'20260930',
    source_input_identity:'a'.repeat(64),source_rule_version:'TEST_REBOUND_SCREEN_V2',
    decision_reason_code:'BOTH_REBOUND_GATES_FAILED',decision_reason:'两项严格门均未通过，原筛选排除。',
    source_metrics:{history_status:'KNOWN',screen_decision:'EXCLUDED',oversold_flag:false,volume_flag_5d_ge_1_5:false},
    source_refs:structuredClone(refs),research_priority:null,
    target_connect_eligibility:'UNCHANGED_SEPARATE_FORMAL_SELECTION',as_of_claim:'NONE_RETROSPECTIVE_RESEARCH',...flags,
  }));
  const unresolved=Array.from({length:4},(_,i)=>({
    symbol:`HK.${String(i+101).padStart(5,'0')}`,name:`待核${i+1}`,decision_status:'UNRESOLVED',source_group:'screen_unresolved',
    source_row_count:1,source_row_indexes:[36+i],target_trade_date:date,source_date:'20260930',
    source_input_identity:'a'.repeat(64),source_rule_version:'TEST_REBOUND_SCREEN_V2',
    decision_reason_code:'ORIGINAL_SCREEN_ROW_UNRESOLVED',decision_reason:'历史字段不完整，保持未决。',
    source_metrics:{history_status:'PARTIAL_UNKNOWN'},source_refs:[],research_priority:null,
    target_connect_eligibility:'UNCHANGED_SEPARATE_FORMAL_SELECTION',as_of_claim:'NONE_RETROSPECTIVE_RESEARCH',...flags,
  }));
  return {
    schema_version:'v4.manager_research.selection_ledger.v1',status:'READY_WITH_GAPS',target_trade_date:date,
    source_date:'20260930',source_input_identity:'a'.repeat(64),source_rule_version:'TEST_REBOUND_SCREEN_V2',
    source_status:'READY_WITH_GAPS',decision_identity:'b'.repeat(64),decisions:[...excluded,...unresolved],
    coverage:{input_row_count:39,accounted_input_row_count:39,unique_decision_count:39,selected_count:0,
      near_watch_count:0,excluded_count:35,unresolved_count:4,
      source_group_counts:{strict:0,near:0,pending:0,excluded:35,screen_unresolved:4}},
    gaps:['SCREEN_HISTORY_OR_VOLUME_INCOMPLETE:fixture'],universe_exhaustive:false,formal_selection_input:false,
    target_connect_eligibility:'UNCHANGED_SEPARATE_FORMAL_SELECTION',as_of_claim:'NONE_RETROSPECTIVE_RESEARCH',...flags,
  };
}

describe('10/2 research selection ledger',()=>{
  it('uses the target date in the research selection heading and accessible label',()=>{
    const x=fixture();const attention=structuredClone(x.research_attention);attention.research_selection=ledger();
    attention.research_selection.target_trade_date='20261103';
    const host=document.createElement('section');
    (renderResearchAttention as any)(host,attention,x.us_market_attention,x.selection_diagnostics);
    const section=host.querySelector('[data-research-selection-ledger]') as HTMLElement;
    expect(section.querySelector('h4')?.textContent).toBe('11/3研究候选');
    expect(section.getAttribute('aria-label')).toBe('11/3研究候选与筛选理由');
    expect(section.textContent).not.toContain('10/2研究候选');
  });
  it('keeps unavailable screen coverage unknown rather than rendering an observed zero',()=>{
    const x=fixture();x.research_attention.research_selection={
      schema_version:'v4.manager_research.selection_ledger.v1',status:'CANNOT_CONFIRM',target_trade_date:date,
      source_date:null,source_input_identity:null,source_rule_version:null,decision_identity:'e'.repeat(64),decisions:[],
      coverage:{input_row_count:null,accounted_input_row_count:null,unique_decision_count:null,selected_count:null,
        near_watch_count:null,excluded_count:null,unresolved_count:null,
        source_group_counts:{strict:null,near:null,pending:null,excluded:null,screen_unresolved:null}},
      gaps:['REBOUND_SCREEN_INPUT_NOT_AVAILABLE'],universe_exhaustive:false,formal_selection_input:false,
      target_connect_eligibility:'UNCHANGED_SEPARATE_FORMAL_SELECTION',as_of_claim:'NONE_RETROSPECTIVE_RESEARCH',...flags,
    };
    const validated=validateManagerWorkspace(x,date);const host=document.createElement('section');
    (renderResearchAttention as any)(host,validated.research_attention,validated.us_market_attention,validated.selection_diagnostics);
    expect(host.textContent).toContain('唯一台账 未知 条／输入 未知 行');
    expect(host.textContent).toContain('筛选输入未提供；各项数量未知');
    expect(host.textContent).not.toContain('研究入选 0');
    expect(host.querySelectorAll('[data-selection-group]')).toHaveLength(0);

    const inconsistent=fixture();inconsistent.research_attention.research_selection=structuredClone(x.research_attention.research_selection);
    inconsistent.research_attention.research_selection.coverage.input_row_count=0;
    expect(()=>validateManagerWorkspace(inconsistent,date)).toThrow('RESEARCH_SELECTION_COVERAGE_UNKNOWN');
  });
  it('does not attach a fixed date when the selection ledger is absent',()=>{
    const x=fixture();delete x.research_attention.research_selection;const host=document.createElement('section');
    (renderResearchAttention as any)(host,x.research_attention,x.us_market_attention,x.selection_diagnostics);
    const section=host.querySelector('[data-research-selection-ledger]') as HTMLElement;
    expect(section.querySelector('h4')?.textContent).toBe('研究候选');
    expect(section.getAttribute('aria-label')).toBe('研究候选与筛选理由');
    expect(section.textContent).not.toContain('10/2');
  });
  it('validates and renders the complete ledger beyond the old 30-card cap',()=>{
    const x=fixture();x.research_attention.research_selection=ledger();x.research_attention.config.display_limit=1;
    const validated=validateManagerWorkspace(x,date);const host=document.createElement('section');
    (renderResearchAttention as any)(host,validated.research_attention,validated.us_market_attention,validated.selection_diagnostics);
    expect(host.textContent).toContain('10/2研究候选');
    expect(host.textContent).toContain('明确排除 35');
    expect(host.querySelectorAll('.research-selection-decision')).toHaveLength(39);
    expect(host.querySelectorAll('[data-selection-group="EXCLUDED"] .research-selection-decision')).toHaveLength(35);
    expect(host.querySelector('[data-formal-selection]')?.textContent).toContain('正式选股当日不适用');
  });

  it('rejects duplicate stock decisions and broken row accounting',()=>{
    const duplicate=fixture();duplicate.research_attention.research_selection=ledger();
    duplicate.research_attention.research_selection.decisions[1].symbol=duplicate.research_attention.research_selection.decisions[0].symbol;
    expect(()=>validateManagerWorkspace(duplicate,date)).toThrow('WORKSPACE_RESEARCH_SELECTION_SYMBOL_INVALID');
    const countMismatch=fixture();countMismatch.research_attention.research_selection=ledger();
    countMismatch.research_attention.research_selection.coverage.accounted_input_row_count=38;
    expect(()=>validateManagerWorkspace(countMismatch,date)).toThrow('WORKSPACE_RESEARCH_SELECTION_COVERAGE_INVALID');
  });

  it('binds a strict research selection to the existing attention card priority',()=>{
    const x=fixture();
    const card={symbol:'HK.00001',name:'严格样例',research_attention_score:10,research_attention_band:'BACKGROUND_RESEARCH',
      qualified_lane_count:1,qualified_lanes:['STRICT_NEAR_SCREEN'],why_now:['STRICT_NEAR_SCREEN:10'],missing:[],
      screen_classification:'STRICT_REBOUND',original_screen_rank:null,evidence:[],
      freshest_published_at:null,freshest_acquired_at:null,...flags,
      decision:{schema_version:'v4.manager_research.attention_decision.v1',version:'20260927.evidence-state-triage.proposal-v1',
        status:'PROPOSAL_ONLY',state:'MARKET_STRUCTURE_NEEDS_COMPANY_CAUSE',group_label:'市场结构先行，缺公司级原因',group_order:2,
        summary:'量价结构已经出现，但缺公司级新原因。',next_check:'补查公司公告或公司特异材料。',
        invalidation:'后续screen不再成立时撤销。',why_now_readable:['既有量价筛选'],
        company_evidence_strength:0,market_confirmation_strength:3,context_strength:0,
        research_priority_key:[2,-10,0,-3,0,-1],formal_rank_writeback:false,stage_writeback:false,buy_gate_writeback:false}};
    x.research_attention.cards=[card];
    const selected={
      symbol:'HK.00001',name:'严格样例',decision_status:'SELECTED',source_group:'strict',source_row_count:1,source_row_indexes:[1],
      target_trade_date:date,source_date:'20260930',source_input_identity:'a'.repeat(64),source_rule_version:'TEST_REBOUND_SCREEN_V2',
      decision_reason_code:'ORIGINAL_STRICT_TWO_GATE_PASSED',decision_reason:'原strict两门均通过。',
      source_metrics:{classification:'STRICT_REBOUND',history_status:'KNOWN',strict_two_gate_oversold_5dvolume:true,
        oversold_flag:true,volume_flag_5d_ge_1_5:true},source_refs:structuredClone(refs),
      research_priority:{priority_rank:1,research_attention_score:10,research_attention_band:'BACKGROUND_RESEARCH',
        decision:structuredClone(card.decision),ordering_basis:'EVIDENCE_STATE_THEN_EXISTING_PROPOSAL_SCORE_THEN_PIT_FRESHNESS',status:'PROPOSAL_ONLY'},
      target_connect_eligibility:'UNCHANGED_SEPARATE_FORMAL_SELECTION',as_of_claim:'NONE_RETROSPECTIVE_RESEARCH',...flags};
    x.research_attention.research_selection={
      schema_version:'v4.manager_research.selection_ledger.v1',status:'READY',target_trade_date:date,
      source_date:'20260930',source_input_identity:'a'.repeat(64),source_rule_version:'TEST_REBOUND_SCREEN_V2',
      decision_identity:'b'.repeat(64),decisions:[selected],
      coverage:{input_row_count:1,accounted_input_row_count:1,unique_decision_count:1,selected_count:1,near_watch_count:0,
        excluded_count:0,unresolved_count:0,source_group_counts:{strict:1,near:0,pending:0,excluded:0,screen_unresolved:0}},
      gaps:[],universe_exhaustive:false,formal_selection_input:false,
      target_connect_eligibility:'UNCHANGED_SEPARATE_FORMAL_SELECTION',as_of_claim:'NONE_RETROSPECTIVE_RESEARCH',...flags};
    expect(validateManagerWorkspace(x,date)).toBe(x);
  });
});
