import { describe, expect, it } from 'vitest';
import { businessStatusRows } from '../businessStatus';

// Pure DTO projection tests. Mac must also run original decoder/Vue suites.
const us={status:'READY',expected_us_session:'20260925',raw_industry_up:[{},{}],raw_individual_up:[{}]};
const row=(v:unknown,label:string)=>businessStatusRows(v as any).find(r=>r.label===label)!;
describe('business chain R2 zero/unknown/due distinctions',()=>{
  it('does not close zero mappings as a normal result',()=>{
    const x=row({us_market_attention:us,research_attention:{us_mapping_diagnostics:{status:'COMPUTED_BY_RELATION_LAYER',accepted_hk_mapping_count:0}}},'美股');
    expect(x.state).toBe('证据不足');expect(x.detail).toContain('行业上涨 2');expect(x.next).toContain('证据不足时不报告零关系');
  });
  it('keeps uncomputed bridge count distinct from computed zero',()=>{
    expect(row({us_market_attention:{...us,mapping_diagnostics:{status:'NOT_COMPUTED_BY_BRIDGE',accepted_hk_mapping_count:null}}},'美股').state).toBe('尚未评估');
  });
  it('calls positive relationships research rather than buy',()=>{
    const x=row({us_market_attention:us,research_attention:{us_mapping_diagnostics:{status:'COMPUTED_BY_RELATION_LAYER',accepted_hk_mapping_count:2}}},'美股');
    expect(x.state).toBe('已有合格关系');expect(x.next).toContain('不改变Stage、正式选股或BUY');
  });
  it('shows NOT_DUE without hiding missing artifact evidence',()=>{
    const x=row({lanes:[{lane:'STAGE',state:'UNVERIFIED',execution_timing:{execution_state:'NOT_DUE',artifact_status:'CANNOT_CONFIRM',schedule_state:'NOT_DUE'}}]},'Stage');
    expect(x.state).toBe('未到执行时点');expect(x.detail).toContain('CANNOT_CONFIRM');expect(x.next).toContain('不要提前');
  });
  it('retains confirmed failed attempt',()=>{
    expect(row({lanes:[{lane:'STAGE',state:'FAILED',execution_timing:{execution_state:'FAILED',artifact_status:'CANNOT_CONFIRM'}}]},'Stage').state).toBe('失败');
  });
  it('no announcement attempt is not no announcements',()=>{
    const x=row({},'公告');expect(x.detail).toContain('不是0公告');expect(x.next).toContain('受限手动');
  });
});

describe('US reason detail regression (Issue #22)',()=>{
  it('explains VERIFIED_RELATIONS_PASSED_TWO_SOURCE_PIT without a false evidence gap',()=>{
    const x=row({us_market_attention:us,research_attention:{us_mapping_diagnostics:{
      status:'COMPUTED_BY_RELATION_LAYER',assessment_state:'ASSESSED_WITH_RELATIONS',
      accepted_hk_mapping_count:1,material_input:{complete:true},
      assessment_reasons:['VERIFIED_RELATIONS_PASSED_TWO_SOURCE_PIT'],
    }}},'美股');
    expect(x.state).toBe('已有合格关系');
    expect(x.detail).toContain('合格关系 1 条');
    expect(x.detail).toContain('已核关系通过双来源与时点核验');
    expect(x.detail).not.toContain('缺口');
    expect(x.next).toContain('不改变Stage、正式选股或BUY');
  });
  it.each([
    ['ASSESSED_WITH_RELATIONS',1,'VERIFIED_RELATIONS_PASSED_TWO_SOURCE_PIT_UNKNOWN','已有合格关系','来源、主体或时点证据仍有缺口'],
    ['INSUFFICIENT',null,'TWO_SOURCE_PIT_VERIFIED_REQUIRED','证据不足','双来源与可用时间证据尚未同时满足'],
    ['INSUFFICIENT',null,'MATERIAL_INPUT_COMPLETENESS_UNVERIFIED','证据不足','关系材料完整性尚未确认'],
    ['NOT_EVALUATED',null,'US_MARKET_SNAPSHOT_NOT_READY','尚未评估','美股对应时段快照未就绪'],
    ['ASSESSED_ZERO',0,'NO_QUALIFIED_RELATION_AFTER_COMPLETE_TWO_SOURCE_PIT_EVALUATION','已评估，暂无合格关系','完整核验后暂无合格关系'],
  ])('preserves %s / count=%s / reason=%s',(assessment_state,accepted_hk_mapping_count,reason,state,detail)=>{
    const x=row({us_market_attention:{...us,status:assessment_state==='NOT_EVALUATED'?'CANNOT_CONFIRM':'READY'},research_attention:{us_mapping_diagnostics:{
      assessment_state,accepted_hk_mapping_count,assessment_reasons:[reason],
    }}},'美股');
    expect(x.state).toBe(state);expect(x.detail).toContain(detail);
    expect(x.detail).not.toContain('已核关系通过双来源与时点核验');
    if(assessment_state==='INSUFFICIENT')expect(x.detail).toContain('合格关系数量暂不能确认');
    if(assessment_state==='NOT_EVALUATED')expect(x.detail).toContain('合格关系尚未计算');
    if(assessment_state==='ASSESSED_ZERO')expect(x.detail).toContain('合格关系 0 条（已完成评估）');
  });
});
