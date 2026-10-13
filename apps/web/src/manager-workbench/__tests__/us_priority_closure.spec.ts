import { describe, expect, it } from 'vitest';
import { readableReason, researchSections } from '../display';
describe('new reviewed US classification display', () => {
  it('shows the saved classification basis, price and counter evidence without strict promotion', () => {
    const row = { reason: 'US_REVIEWED_RELATION_CONDITIONAL_ONLY', us_symbol: 'EQIX', quote: { change_pct: 0.63739 }, research_priority_reason: '2017年历史合作，不证明当前条款。', priority_assessment: { counter_evidence: ['无当前收入证明'] } };
    const reason = readableReason(row);
    expect(reason).toContain('条件观察'); expect(reason).toContain('不能据此严格入选');
    expect(reason).toContain('本轮研究分类依据'); expect(reason).toContain('2017年历史合作'); expect(reason).toContain('0.63739%');
    expect(researchSections(row).find(x => x.key === 'counter_evidence')?.items[0].claim).toBe('无当前收入证明');
  });
  it('keeps old saved US reason and no invented new classification', () => {
    expect(readableReason({ reason: 'US_RELATION_PRIORITY_NOT_REVIEWED' })).toBe('关系依据已有审核，研究优先级尚未审核，保留待核。');
  });
});
