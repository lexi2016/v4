import { describe, expect, it } from 'vitest';
import { beijingTime, strategySummary } from './managerStrategySummary';
describe('strategy-specific summaries',()=>{
  it('keeps zero, partial and unknown within their own channel',()=>{
    const value={daily_channels:{channels:[{channel:'ANNOUNCEMENT',status:'READY_EMPTY',candidate_count:0},
      {channel:'OVERSOLD',status:'PARTIAL',candidate_count:null},{channel:'HK_CONNECT',status:'READY',candidate_count:77}]}};
    expect(strategySummary(value,'ANNOUNCEMENT')).toContain('候选 0 只');
    expect(strategySummary(value,'OVERSOLD')).toContain('部分结果');
    expect(strategySummary(value,'OVERSOLD')).toContain('候选 未知');
    expect(strategySummary(value,'OVERSOLD')).not.toContain('77');
    expect(strategySummary(undefined,'ANNOUNCEMENT')).toContain('候选 未知');
  });
  it('converts explicit instants to Beijing time and does not guess an absent timezone',()=>{
    expect(beijingTime('2026-10-09T23:05:00Z')).toContain('2026/10/10 07:05');
    expect(beijingTime('2026-10-10T07:05:00+08:00')).toBe(beijingTime('2026-10-09T23:05:00Z'));
    expect(beijingTime('2026-10-10T07:05:00')).toBe('未知');expect(beijingTime(null)).toBe('未知');
  });
});
