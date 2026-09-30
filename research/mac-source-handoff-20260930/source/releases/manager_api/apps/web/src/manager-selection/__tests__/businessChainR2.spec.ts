import { describe, expect, it } from 'vitest';
import { businessStatusRows } from '../businessStatus';

// Pure DTO projection tests. Mac must also run original decoder/Vue suites.
const us={status:'READY',expected_us_session:'20260925',raw_industry_up:[{},{}],raw_individual_up:[{}]};
const row=(v:unknown,label:string)=>businessStatusRows(v as any).find(r=>r.label===label)!;
describe('business chain R2 zero/unknown/due distinctions',()=>{
  it('does not close zero mappings as a normal result',()=>{
    const x=row({us_market_attention:us,research_attention:{us_mapping_diagnostics:{status:'COMPUTED_BY_RELATION_LAYER',accepted_hk_mapping_count:0}}},'美股');
    expect(x.state).toBe('映射未形成');expect(x.detail).toContain('行业上涨 2');expect(x.next).toContain('逐信号');
  });
  it('keeps uncomputed bridge count distinct from computed zero',()=>{
    expect(row({us_market_attention:{...us,mapping_diagnostics:{status:'NOT_COMPUTED_BY_BRIDGE',accepted_hk_mapping_count:null}}},'美股').state).toBe('关系尚未计算');
  });
  it('calls positive relationships research rather than buy',()=>{
    const x=row({us_market_attention:us,research_attention:{us_mapping_diagnostics:{status:'COMPUTED_BY_RELATION_LAYER',accepted_hk_mapping_count:2}}},'美股');
    expect(x.state).toBe('映射已生成');expect(x.next).toContain('不升格为买入');
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
