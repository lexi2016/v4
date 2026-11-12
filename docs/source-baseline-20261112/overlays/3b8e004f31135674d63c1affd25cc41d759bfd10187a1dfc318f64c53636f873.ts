// @vitest-environment jsdom
import {describe,it,expect} from 'vitest';
import {validateManagerWorkspace} from '../../api/managerWorkspace';
import {renderResearchAttention} from '../researchAttention';
import {fixture,date,gap} from './fixtures/issue8R2.fixture';
const check=(x:any)=>validateManagerWorkspace(x,date);
const render=(x:any)=>{const v=check(x);const h=document.createElement('section');
  (renderResearchAttention as any)(h,v.research_attention,v.us_market_attention,v.selection_diagnostics);return h;};
const mutate=(fn:(x:any)=>void)=>{const x=fixture();fn(x);return x;};

describe('Issue8 R2 real-owner observation shape in a synthetic envelope',()=>{
  it('accepts exact owner observations without mutating the envelope',()=>{const x=fixture(),copy=structuredClone(x);expect(check(x)).toBe(x);expect(x).toEqual(copy);});
  it('renders all independent observations without creating scored cards or BUY controls',()=>{
    const x=fixture(),h=render(x);expect(h.querySelectorAll('.research-observation-card')).toHaveLength(x.research_attention.observation_only.card_count);
    expect(h.querySelectorAll('.research-attention-card')).toHaveLength(0);expect(h.querySelector('button')).toBeNull();
    expect(h.textContent).toContain('独立公告观察');expect(h.textContent).toContain('资格未确认');
    expect(h.textContent).toContain('不进入 scored cards／focus／BUY');
    for(const row of x.research_attention.observation_only.cards){expect(h.textContent).toContain(row.support.quote);expect(h.textContent).toContain(row.available_at);}
  });
  it('does not hardcode nine/five and retains records beyond the scored display limit',()=>{
    const x=fixture();const o=x.research_attention.observation_only;o.cards=o.cards.slice(0,2);o.card_count=2;o.symbol_count=new Set(o.cards.map((r:any)=>r.symbol)).size;
    x.research_attention.config.display_limit=1;const h=render(x);expect(h.querySelectorAll('.research-observation-card')).toHaveLength(2);expect(h.textContent).toContain('2 条');
  });
  it('renders the actual formal holiday as not applicable rather than a successful empty scan',()=>{const h=render(fixture());
    const t=h.querySelector('[data-formal-selection]')!.textContent;expect(t).toContain('正式选股当日不适用');expect(t).toContain('港股证券');
    expect(t).toContain('CANNOT_CONFIRM');expect(t).not.toContain('成功扫描');expect(t).not.toContain('有效 0');expect(t).toContain(gap);
  });
  it('shows unknown formal applicability even with known research observations',()=>{
    const x=fixture(),f=x.selection_diagnostics.formal_selection;Object.assign(f,{status:'CANNOT_CONFIRM',reason:'HK_CONNECT_CALENDAR_UNVERIFIED',candidate_count:null});
    Object.assign(f.calendar,{status:'CANNOT_CONFIRM',reason:'HK_CONNECT_CALENDAR_UNVERIFIED',hk_connect_state:'UNKNOWN',hk_securities_state:'UNKNOWN',calendar_sha256:null});
    x.research_attention.input_diagnostics.scope.announcements.formal_selection=structuredClone(f);
    const h=render(x);expect(h.querySelector('[data-formal-selection]')!.textContent).toContain('正式选股状态未确认');
  });
  it('distinguishes a verified trading-day empty result from a holiday',()=>{
    const x=fixture(),f=x.selection_diagnostics.formal_selection;Object.assign(f,{status:'READY_EMPTY',reason:'TARGET_DATE_MEMBERSHIP_VERIFIED_NOT_BUY_ADMISSION',membership_status:'OWNER_VERIFIED'});
    Object.assign(f.calendar,{status:'APPLICABLE',reason:'HK_CONNECT_TRADING_DAY',hk_connect_state:'FULL_TRADING_DAY'});
    Object.assign(x.selection_diagnostics.membership,{status:'OWNER_VERIFIED',identity:'c'.repeat(64)});
    Object.assign(x.research_attention.input_diagnostics.scope.announcements,{status:'OWNER_VERIFIED',membership_identity:'c'.repeat(64),formal_selection:structuredClone(f)});
    const h=render(x);expect(h.querySelector('[data-formal-selection]')!.textContent).toContain('已核目标日资格，候选 0 条');
  });
  it('separates HKEX, Eastmoney and US coverage and exposes rejection counts and reasons',()=>{const t=render(fixture()).textContent!;
    for(const s of ['HKEX 官方公告','东方财富 selection','美股关系','非穷尽','输入 2','准入 0','拒绝 2','SYNTHETIC_PARTIAL_COVERAGE','EASTMONEY_HK_DISPLAY_TIME_OUTSIDE_CONSUMER_WINDOW','ISSUER_ACQUISITION_TIME_MISSING_OR_INVALID','NO_SUBJECT_BOUND_BUSINESS_OR_US_RELATION'])expect(t).toContain(s);
    expect(t).not.toContain('全市场无利好');
  });
  it('accepts legacy payloads but shows absent new fields as unknown, never valid zero',()=>{
    const x=fixture();delete x.selection_diagnostics;delete x.research_attention.observation_only;delete x.research_attention.input_diagnostics;x.research_attention.status='READY';x.research_attention.gaps=[];
    const t=render(x).textContent!;expect(t).toContain('独立公告观察未提供');expect(t).toContain('正式选股状态未提供');expect(t).toContain('来源诊断未提供');
    expect(t).toContain('状态 CANNOT_CONFIRM');expect(t).not.toContain('独立公告观察 0');
  });
  it('renders an empty observation container as unconfirmed, not an exhaustive negative',()=>{
    const x=fixture();Object.assign(x.research_attention.observation_only,{cards:[],card_count:0,symbol_count:0,status:'CANNOT_CONFIRM'});
    expect(render(x).textContent).toContain('未保留可展示观察；不等于全市场无正向公告');
  });
  it('does not infer acquisition clocks from alternate owner fields',()=>{
    const x=fixture();x.research_attention.input_diagnostics.us_relations.collected_at='2026-09-29T21:03:02+08:00';
    x.research_attention.input_diagnostics.us_relations.first_seen_at='2026-09-29T21:03:02+08:00';
    const h=render(x);expect(h.textContent).not.toContain('2026-09-29T21:03:02+08:00');expect(h.textContent).toContain('不以 collected_at／first_seen_at 补造采集时间');
  });
  it('preserves missing research state and clears previous observation DOM on reread',()=>{
    const h=render(fixture());renderResearchAttention(h,undefined,undefined);
    expect(h.querySelectorAll('.research-observation-card')).toHaveLength(0);expect(h.textContent).toContain('优先级未知');expect(h.textContent).toContain('正式选股状态未提供');
  });
  it('escapes titles/quotes and permits only safe http(s) evidence anchors',()=>{
    const x=fixture(),r=x.research_attention.observation_only.cards[0];r.title='<img src=x onerror=alert(1)>';r.support.quote='<script>alert(1)</script>';
    const h=render(x);expect(h.querySelector('img,script')).toBeNull();expect(h.textContent).toContain(r.support.quote);
    for(const a of h.querySelectorAll('a')){expect(a.href).toMatch(/^https?:/);expect(a.rel).toContain('noopener');expect(a.rel).toContain('noreferrer');}
  });
});

describe('Issue8 R2 rejects invalid new observation contracts',()=>{
  it.each([
    ['container null',(x:any)=>x.research_attention.observation_only=null],
    ['container wrong shape',(x:any)=>x.research_attention.observation_only=[]],
    ['count mismatch',(x:any)=>x.research_attention.observation_only.card_count++],
    ['unique symbol count mismatch',(x:any)=>x.research_attention.observation_only.symbol_count++],
    ['invalid status',(x:any)=>x.research_attention.observation_only.status='READY'],
    ['scored promotion',(x:any)=>x.research_attention.observation_only.scored_attention_input=true],
    ['formal promotion',(x:any)=>x.research_attention.observation_only.formal_selection_input=true],
    ['exhaustiveness promotion',(x:any)=>x.research_attention.observation_only.universe_exhaustive=true],
    ['unsafe container',(x:any)=>x.research_attention.observation_only.orders_sent=true],
    ['duplicate owner identity',(x:any)=>{const o=x.research_attention.observation_only;o.cards.push(structuredClone(o.cards[0]));o.card_count++;}],
  ])('rejects %s',(_name,fn)=>expect(()=>check(mutate(fn as any))).toThrow());
  it.each([
    ['focus promotion',(r:any)=>r.focus_eligible=true],['BUY promotion',(r:any)=>r.buy_allowed=true],
    ['qualified promotion',(r:any)=>r.qualified=true],['production promotion',(r:any)=>r.production_allowed=true],
    ['missing safety',(r:any)=>delete r.RESEARCH_ONLY],['invalid symbol',(r:any)=>r.symbol='HK.00000'],
    ['cross issuer',(r:any)=>r.support.action_subject='HK.99999'],['negated assertion',(r:any)=>r.support.polarity='NEGATED'],
    ['unclassified row',(r:any)=>r.disposition='PENDING'],['blank quote',(r:any)=>r.support.quote=''],
    ['missing body binding',(r:any)=>r.evidence=[]],['wrong body SHA',(r:any)=>r.document_sha256='f'.repeat(64)],
    ['wrong role',(r:any)=>r.observation_role='FORMAL_CANDIDATE'],['cross-date membership',(r:any)=>r.target_connect_membership.target_trade_date='20261001'],
    ['invalid membership state',(r:any)=>r.target_connect_membership.status='READY'],
    ['unsafe URL',(r:any)=>r.evidence[0].source_url='javascript:alert(1)'],
    ['unsafe reference',(r:any)=>r.evidence[0].body_ref.retrieved_at='yesterday'],
    ['future reference',(r:any)=>r.evidence[0].directory_ref.retrieved_at='2027-01-01T00:00:00Z'],
  ])('rejects %s',(_name,fn)=>expect(()=>check(mutate(x=>(fn as any)(x.research_attention.observation_only.cards[0])))).toThrow());
  it.each(['published_at','available_at','retrieved_at'])('requires an explicit valid %s',key=>{
    for(const bad of [undefined,null,'','yesterday','2026-09-30T17:27:00','2026-02-31T10:00:00Z','2027-01-01T00:00:00Z']){
      const x=fixture();x.research_attention.observation_only.cards[0][key]=bad;expect(()=>check(x),String(bad)).toThrow();}
  });
  it('rejects reversed acquisition order and publication before the freshness window',()=>{
    expect(()=>check(mutate(x=>x.research_attention.observation_only.cards[0].available_at='2026-10-01T00:00:00Z'))).toThrow();
    expect(()=>check(mutate(x=>x.research_attention.observation_only.cards[0].published_at='2026-09-01T00:00:00Z'))).toThrow();
  });
});

describe('Issue8 R2 formal and input diagnostics contracts',()=>{
  it.each([
    ['null formal',(x:any)=>x.selection_diagnostics.formal_selection=null],
    ['cross-date formal',(x:any)=>x.selection_diagnostics.formal_selection.target_trade_date='20261001'],
    ['holiday positive count',(x:any)=>x.selection_diagnostics.formal_selection.candidate_count=1],
    ['holiday null count',(x:any)=>x.selection_diagnostics.formal_selection.candidate_count=null],
    ['holiday lacks calendar',(x:any)=>delete x.selection_diagnostics.formal_selection.calendar],
    ['holiday claims trading day',(x:any)=>x.selection_diagnostics.formal_selection.calendar.hk_connect_state='FULL_TRADING_DAY'],
    ['calendar wrong date',(x:any)=>x.selection_diagnostics.formal_selection.calendar.target_trade_date='20261001'],
    ['calendar wrong SHA',(x:any)=>x.selection_diagnostics.formal_selection.calendar.calendar_sha256='bad'],
    ['calendar wrong owner',(x:any)=>x.selection_diagnostics.formal_selection.calendar.calendar_owner='unverified'],
    ['unknown masquerading as known',(x:any)=>{const f=x.selection_diagnostics.formal_selection;f.status='CANNOT_CONFIRM';f.candidate_count=0;}],
    ['unsafe formal',(x:any)=>x.selection_diagnostics.formal_selection.buy_allowed=true],
    ['unsafe selection',(x:any)=>x.selection_diagnostics.orders_sent=true],
    ['membership disagreement',(x:any)=>x.selection_diagnostics.formal_selection.membership_status='OWNER_VERIFIED'],
    ['null diagnostics',(x:any)=>x.research_attention.input_diagnostics=null],
    ['missing lane',(x:any)=>delete x.research_attention.input_diagnostics.us_relations],
    ['bad gaps type',(x:any)=>x.research_attention.input_diagnostics.official_announcements.gaps='none'],
    ['false completeness type',(x:any)=>x.research_attention.input_diagnostics.us_relations.material_complete='false'],
    ['invalid US state',(x:any)=>x.research_attention.input_diagnostics.us_relations.assessment_state='READY'],
    ['negative document count',(x:any)=>x.research_attention.input_diagnostics.eastmoney_selection.document_count=-1],
    ['mirror exhaustiveness claim',(x:any)=>x.research_attention.input_diagnostics.eastmoney_selection.exhaustive=true],
    ['bad coverage count',(x:any)=>x.research_attention.input_diagnostics.official_announcements.coverage.observed_document_count='12'],
    ['bad scope sums',(x:any)=>x.research_attention.input_diagnostics.scope.announcements.counts.official_documents.admitted=1],
    ['unsafe nested formal',(x:any)=>x.research_attention.input_diagnostics.scope.announcements.formal_selection.qualified=true],
  ])('rejects %s',(_name,fn)=>expect(()=>check(mutate(fn as any))).toThrow());
});


describe('Issue8 R2 cross-field and partial payload review',()=>{
  it.each(['observation_only','input_diagnostics'])('keeps missing %s compatible but unconfirmed',key=>{
    const x=fixture();delete x.research_attention[key];x.research_attention.status='READY';
    expect(render(x).textContent).toContain('状态 CANNOT_CONFIRM');
  });
  it('requires the same calendar identity in formal selection and filtered research input',()=>{
    expect(()=>check(mutate(x=>x.research_attention.input_diagnostics.scope.announcements.formal_selection.calendar.calendar_sha256='d'.repeat(64)))).toThrow();
  });
  it('rejects unknown target membership promoted on an independent observation',()=>{
    expect(()=>check(mutate(x=>Object.assign(x.research_attention.observation_only.cards[0].target_connect_membership,
      {status:'VERIFIED_TARGET_UNIVERSE',authority_identity:'e'.repeat(64)})))).toThrow();
  });
  it('allows independently witnessed target membership but never turns observations into BUY',()=>{
    const x=fixture();x.selection_diagnostics.membership.status='OWNER_VERIFIED';x.selection_diagnostics.membership.identity='c'.repeat(64);
    x.selection_diagnostics.formal_selection.membership_status='OWNER_VERIFIED';
    const scope=x.research_attention.input_diagnostics.scope.announcements;
    scope.status='OWNER_VERIFIED';scope.membership_identity='c'.repeat(64);scope.formal_selection.membership_status='OWNER_VERIFIED';
    for(const r of x.research_attention.observation_only.cards)Object.assign(r.target_connect_membership,
      {status:'VERIFIED_TARGET_UNIVERSE',authority_identity:'c'.repeat(64),reason:'TARGET_DATE_MEMBERSHIP_VERIFIED'});
    const h=render(x);expect(h.textContent).toContain('目标日名单已核（仍仅研究观察）');expect(h.querySelectorAll('.research-attention-card')).toHaveLength(0);
    expect(h.querySelector('button')).toBeNull();expect(x.focus_symbols).toEqual([]);
  });
  it('rejects assessed-zero in the new US lane when material completeness is false',()=>{
    expect(()=>check(mutate(x=>x.research_attention.input_diagnostics.us_relations.assessment_state='ASSESSED_ZERO'))).toThrow();
  });
  it('retains exact extra coverage fields without recasting missing counts to zero',()=>{
    const x=fixture();const c=x.research_attention.input_diagnostics.official_announcements.coverage;
    c.directory_exhaustion='UNVERIFIED';c.failed_issuers=[{symbol:'HK.00300',reason:'synthetic owner timeout'}];delete c.observed_document_count;
    const h=render(x);expect(h.textContent).toContain('已观察文档 未知');expect(h.textContent).toContain('synthetic owner timeout');expect(h.textContent).toContain('directory_exhaustion');
  });
  it('places source coverage before the independent card list',()=>{
    const h=render(fixture()),sources=h.querySelector('[data-input-diagnostics]')!,observations=h.querySelector('[data-observation-only]')!;
    expect(sources.compareDocumentPosition(observations)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
  it('uses unknown when a diagnostic membership rejection differs from the raw owner status',()=>{
    const x=fixture();const scope=x.research_attention.input_diagnostics.scope.announcements;
    // R1 evidence_view can reject malformed OWNER_VERIFIED input while formal_selection retains its raw membership label.
    scope.formal_selection.membership_status='OWNER_VERIFIED';scope.membership_identity='c'.repeat(64);
    x.selection_diagnostics.membership.status='OWNER_VERIFIED';x.selection_diagnostics.membership.identity='c'.repeat(64);
    x.selection_diagnostics.formal_selection.membership_status='OWNER_VERIFIED';
    expect(render(x).textContent).toContain('研究输入范围 · CANNOT_CONFIRM');
  });
});
