import { describe,it,expect } from 'vitest';
import { validateAnnouncementObservation } from '../../api/managerWorkspace.js';
import { renderAnnouncementObservation } from '../announcementObservation.js';
const safety={RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false};
const empty=()=>({schema_version:'v4.manager_research.announcement_observation.v1',target_trade_date:'20260924',
  research_cutoff:'2026-09-24T08:00:00+08:00',prior_session:'20260923',status:'NOT_RUN',count_known:false,
  latest_attempt:null,observations:[],pending_observations:[],official_documents:[],capture_runs:[],coverage:{},gaps:[],
  independent_of_strict_near_focus:true,...safety});
describe('independent official observation (SIMULATED DTO; actual validator/renderer)',()=>{
  it('does not convert NOT_RUN to zero candidates',()=>{
    const host=document.createElement('section');renderAnnouncementObservation(host,validateAnnouncementObservation(empty(),'20260924'));
    expect(host.textContent).toContain('数量未知');expect(host.textContent).not.toContain('0只候选');
  });
  it('rejects cross-date and BUY elevation',()=>{
    expect(()=>validateAnnouncementObservation(empty(),'20260923')).toThrow();
    expect(()=>validateAnnouncementObservation({...empty(),orders_sent:true},'20260924')).toThrow();
  });
  it('clears old section when input disappears',()=>{
    const host=document.createElement('section');host.textContent='OLD STOCK';host.dataset.announcementDate='20260923';renderAnnouncementObservation(host,undefined);
    expect(host.dataset.announcementDate).toBeUndefined();expect(host.textContent).not.toContain('OLD STOCK');expect(host.textContent).toContain('状态未知');
  });
});
