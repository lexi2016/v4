import { expect, it } from 'vitest';
import { readableReason } from '../display';
it('displays the saved old 80% gate and new 60% gate without changing either record', () => {
 const old={metrics:{previous_session:'20261012',close:'38.92',max_high_60:'48.98',price_threshold:'39.184',price_pass:true,volume_ratio:'6.53',volume_pass:true},decision:'SELECTED'};
 const fresh={metrics:{...old.metrics,price_threshold:'29.388',price_ratio:'0.6',price_pass:false,oversold_rules_version:'POSITIVE_OPERATING_RESEARCH_V1_OVERSOLD_PRICE40_V2'},decision:'CONDITIONAL_WATCH'};
 const before=JSON.stringify([old,fresh]);
 expect(readableReason(old)).toContain('80%门槛（较60日前高至少低20%） 39.184');
 expect(readableReason(fresh)).toContain('60%门槛（较60日前高至少低40%） 29.388（未满足）');
 expect(readableReason(fresh)).toContain('1.5倍门槛（满足）');
 expect(JSON.stringify([old,fresh])).toBe(before);
 expect(readableReason({metrics:{max_high_60:'48.98',price_threshold:null}})).toContain('比例未知');
});
