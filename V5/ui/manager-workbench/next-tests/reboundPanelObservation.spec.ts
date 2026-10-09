import { describe, expect, it } from 'vitest';
import { renderReboundPanelObservation } from './reboundPanelObservation';

const fixture={target_date:'20261009',signal_date:'20261008',observed_at:'2026-10-09T20:53:19+08:00',
  observation_read_as_of:'2026-10-09T21:06:00+08:00',plan_research_cutoff:'2026-10-09T18:15:54+08:00',
  eligible_screen:null,formal_status:'CANNOT_CONFIRM',reason_codes:['TARGET_ELIGIBILITY_NOT_BOUND'],
  row_summary:{observed_rows:695,numeric_input_incomplete:695,missing_history_dates:['20261005','20261006','20261007'],
    native_comparison_counts:{close_le_prior60_high_times_0_8:{true:0,false:0,unknown:695},current_to_previous5_ge_1_5:{true:0,false:0,unknown:695}}}};

describe('independent current panel observations',()=>{
  it('labels 695 as observations, dates and unknowns, with full-row evidence summary',()=>{
    const host=document.createElement('section');renderReboundPanelObservation(host,fixture);
    expect(host.textContent).toContain('观察记录 695 条；输入不完整 695 条');
    expect(host.textContent).toContain('不是候选数');
    expect(host.textContent).toContain('2026-10-08');expect(host.textContent).toContain(fixture.observed_at);
    expect(host.textContent).toContain('2026-10-05、2026-10-06、2026-10-07');
    expect(host.textContent).toContain('未正式评估');
    expect(host.textContent).toContain(fixture.observation_read_as_of);
    expect(host.textContent).toContain(fixture.plan_research_cutoff);
    expect(host.textContent).toContain('不代表原计划当时已知');
    expect(host.textContent).toContain('未写入保存计划');
    expect(host.textContent).toContain('未知 695 条');
    expect(host.textContent).toContain('全量记录汇总');
    expect(host.textContent).not.toContain('HKD');
  });
  it('missing or rejected result does not become a zero count or stale rows',()=>{
    const host=document.createElement('section');renderReboundPanelObservation(host,fixture);
    renderReboundPanelObservation(host,{...fixture,row_summary:null,reason_codes:['OBSERVATION_MANAGER_AFTER_CUTOFF']});
    expect(host.textContent).toContain('观察记录数未知');expect(host.textContent).not.toContain('695');
    expect(host.textContent).toContain('OBSERVATION_MANAGER_AFTER_CUTOFF');
    renderReboundPanelObservation(host,undefined);expect(host.hidden).toBe(true);expect(host.textContent).toBe('');
  });
  it('all true numerical comparisons still do not become formal selection',()=>{
    const host=document.createElement('section');renderReboundPanelObservation(host,{...fixture,row_summary:{...fixture.row_summary,
      native_comparison_counts:{close_le_prior60_high_times_0_8:{true:695,false:0,unknown:0},current_to_previous5_ge_1_5:{true:695,false:0,unknown:0}}}});
    expect(host.textContent).toContain('正式资格 CANNOT_CONFIRM');expect(host.textContent).toContain('不是正式候选');
    expect(host.textContent).toContain('数值比较为真 695 条');
  });
  it('renders labels as text and rejects promoted eligibility',()=>{
    const host=document.createElement('section');renderReboundPanelObservation(host,{...fixture,eligible_screen:{strict:[]}});
    expect(host.textContent).toContain('观察记录数未知');expect(host.querySelector('article')).toBeNull();
    renderReboundPanelObservation(host,{...fixture,reason_codes:['<img src=x onerror=alert(1)>']});expect(host.querySelector('img')).toBeNull();
  });
});
