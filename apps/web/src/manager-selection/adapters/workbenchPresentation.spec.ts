// SIMULATED presentation tests; no production data and no qualifying positive.
import { describe, expect, it } from 'vitest';
import { conditionIndicators, readableStatus, candidateHeadline, conditionGaps } from './workbenchPresentation';
import type { ManagerWorkbenchCandidate } from '../../contracts/managerWorkbenchResearch';
const card = (values: Array<boolean | 'unknown'>): ManagerWorkbenchCandidate => ({
  candidate_id: 'HK.00001',
  symbol: 'HK.00001',
  name: '模拟候选',
  source_lanes: ['CLOSE_DISCOVERY'],
  first_seen_at: '2026-08-31T15:30:00+08:00',
  last_seen_at: '2026-08-31T15:30:00+08:00',
  observed_at: '2026-08-31T15:30:00+08:00',
  available_at: '2026-08-31T15:30:00+08:00',
  turnover_amount: null,
  volume_comparison: null,
  position: null,
  catalyst: null,
  research_priority: null,
  data_status: 'SIMULATED',
  attention_reason: null,
  predicates: ['turnover_gt_100m_hkd', 'verified_volume_expansion', 'verified_oversold_or_breakout', 'new_direct_pit_catalyst']
    .map((predicate_id, i) => ({
      predicate_id,
      value: values[i]!,
      rule_version: 'manager-close-rework-r2-v1',
      reason: 'SIMULATED',
      input_refs: [],
    })),
  sources: [],
  risks: [],
  observation_plan: null,
  qualified: null,
  trade_date: '20260831',
});
describe('R2 Chinese observation presentation',()=>{
  it('keeps all four conditions distinct and unknown is not satisfied',()=>{
    expect(conditionIndicators(card([true,'unknown','unknown',false])).map(x=>x.state)).toEqual(['已确认','待补资料','待补资料','未满足']);
    expect(conditionIndicators(null).map(x=>x.label)).toEqual(['成交额','放量依据','超跌或突破','新催化']);
  });
  it('does not call an observation a full candidate',()=>{
    expect(candidateHeadline(card([true,'unknown','unknown','unknown']))).toBe('成交额观察待核');
    expect(conditionGaps(card([true,'unknown','unknown','unknown']))).toBe('待补：放量依据、超跌或突破、新催化');
  });
  it('never labels legacy qualified=true or arbitrary rules as the new complete condition',()=>{
    expect(candidateHeadline({...card([]),qualified:true,predicates:[]})).toBe('成交额观察待核');
    const complete = card([true, true, true, true]);
    const forged: ManagerWorkbenchCandidate = {
      ...complete,
      qualified: true,
      predicates: complete.predicates.map(predicate => ({
        ...predicate,
        rule_version: 'ARBITRARY_LEGACY_VERSION',
      })),
    };
    expect(candidateHeadline(forged)).toBe('成交额观察待核');
  });
  it('distinguishes all non-data and complete-zero states',()=>{
    const labels=['NOT_RUN','PENDING_SLOT','INPUT_MISSING','PARTIAL','FAILED','READY_EMPTY'].map(readableStatus);
    expect(new Set(labels).size).toBe(6);
    expect(labels.join(' ')).not.toMatch(/CANNOT_CONFIRM|fallback|exact|HK_CONNECT/);
    expect(readableStatus('READY_EMPTY')).toContain('已完成');
  });
});
