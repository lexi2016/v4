"""Approved V1 numeric research proxies. Pure, prefix-causal, no IO/network."""
from decimal import Decimal as N, localcontext
from collections import deque
from bisect import bisect_left,bisect_right
TRUE='TRUE'; FALSE='FALSE'; UNKNOWN='UNKNOWN'
def truth(x): return UNKNOWN if x is None else TRUE if x else FALSE
def strict_and(*xs): return None if any(x is None for x in xs) else all(xs)
def strict_or(*xs): return None if any(x is None for x in xs) else any(xs)
def risk_and(*xs):return False if any(x is False for x in xs) else None if any(x is None for x in xs) else all(xs)
def risk_or(*xs):return True if any(x is True for x in xs) else None if any(x is None for x in xs) else any(xs)
def cmp(a,op,b):
 if a is None or b is None:return None
 return {'>':lambda:a>b,'>=':lambda:a>=b,'<':lambda:a<b,'<=':lambda:a<=b,'=':lambda:a==b}[op]()
def ratio(a,b): return None if a is None or b is None or b<=0 else a/b

def normalize(rows):
 out=[];last=0
 for row in rows:
  r={'date':int(row.get('date',row.get('trade_date')))}
  assert r['date']>last,'NONINCREASING_DATE';last=r['date']
  for k,alt in [('o','open'),('h','high'),('l','low'),('c','close'),('v','vol')]:
   v=N(str(row.get(k,row.get(alt))));r[k]=v if v.is_finite() else None
  out.append(r)
 return out

def valid(r,volume=True):
 p=[r[k] for k in ('o','h','l','c')]
 return all(x is not None and x>0 for x in p) and r['l']<=min(r['o'],r['c'])<=max(r['o'],r['c'])<=r['h'] and (not volume or r['v'] is not None and r['v']>=0)

def ma(rows,i,n,key='v',include=True):
 end=i+1 if include else i;start=end-n
 if start<0:return None
 vals=[r[key] for r in rows[start:end]]
 if any(v is None or (v<=0 if key!='v' else v<0) for v in vals):return None
 return sum(vals)/N(n)

def fund_keys(rows,breakout):
 """MA includes K; PLRY1 strict NOT(REF), OR/AND unknown propagation."""
 out=[];plry=[]
 with localcontext() as ctx:
  ctx.prec=28
  for i,r in enumerate(rows):
   p=rows[i-1] if i else None
   pc=p['c'] if p else None;pv=p['v'] if p else None
   pct=ratio(r['c'],pc);volr=ratio(r['v'],pv);vm=ratio(r['v'],ma(rows,i,20))
   body=cmp(r['c'],'>',r['o']) if valid(r) else None
   pl=strict_and(cmp(r['v'],'>',ma(rows,i,40)),cmp(r['v'],'>',None if pv is None else pv*N('1.8')),body)
   pl1=strict_and(pl,None if i==0 or plry[-1] is None else not plry[-1]);plry.append(pl)
   cp=None if not valid(r) else N(0) if r['h']==r['l'] else (r['c']-r['l'])/(r['h']-r['l'])
   fk=strict_and(cmp(None if pct is None else (pct-1)*100,'>=',N(4)),cmp(r['c'],'>=',r['o']) if valid(r) else None,strict_or(cmp(volr,'>=',N('1.45')),cmp(vm,'>=',N('1.35')),pl1),cmp(cp,'>=',N('.45')))
   out.append({'date':r['date'],'original_breakout':truth(breakout[i]),'FUNDK':truth(fk),'PLRY':truth(pl),'PLRY1':truth(pl1),'candidate':truth(strict_or(breakout[i],fk))})
 return out

def consolidation(rows,k,calendar=None):
 candidates=[];unknown=[]
 for n in range(5,21):
  a=k-n
  if a<0:unknown.append({'n':n,'reason':'INSUFFICIENT_PREK_BARS'});continue
  seg=rows[a:k]
  if not all(valid(r) for r in seg):unknown.append({'n':n,'reason':'INVALID_PREK_OHLCV'});continue
  if calendar is not None and [r['date'] for r in seg]!=calendar[bisect_left(calendar,seg[0]['date']):bisect_right(calendar,seg[-1]['date'])]:
   unknown.append({'n':n,'reason':'MISSING_PREK_EXCHANGE_BAR'});continue
  spread=max(r['h'] for r in seg)/min(r['l'] for r in seg)-1;drift=abs(seg[-1]['c']/seg[0]['c']-1)
  if spread<=N('.15') and drift<=N('.05'):
   red=[r['v'] for r in seg if r['c']>r['o']];green=[r['v'] for r in seg if r['c']<r['o']];flat=[r['v'] for r in seg if r['c']==r['o']]
   rv=sum(red);gv=sum(green);ra=None if not red else rv/len(red);ga=None if not green else gv/len(green)
   status=truth(strict_and(cmp(rv,'>',gv),cmp(ra,'>',ga)))
   candidates.append({'n':n,'start':seg[0]['date'],'end':seg[-1]['date'],'spread':spread,'close_drift':drift,'red_count':len(red),'green_count':len(green),'flat_count':len(flat),'red_sum':rv,'green_sum':gv,'flat_sum':sum(flat),'red_mean':ra,'green_mean':ga,'redgreen':status,'green_bars':[{'date':r['date'],'volume':r['v']} for r in seg if r['c']<r['o']]})
 selected=candidates[-1] if candidates else None
 # An unobservable longer candidate could be the required longest; do not silently choose shorter.
 higher_unknown=bool(selected and any(x['n']>selected['n'] for x in unknown))
 status=UNKNOWN if higher_unknown or not selected and unknown else selected['redgreen'] if selected else FALSE
 return {'status':status,'reason':'LONGER_SEGMENT_UNKNOWN' if higher_unknown else 'NO_QUALIFYING_SEGMENT' if not selected and not unknown else 'SEGMENT_UNKNOWN' if not selected else 'LONGEST_QUALIFYING_SEGMENT','selected':selected,'candidates':candidates,'unknown_lengths':unknown}

def pivots(rows):
 """Contiguous equal extrema zones, 2 bars on each side, known by prefix end."""
 result=[]
 for kind,key,sgn in [('peak','h',1),('trough','l',-1)]:
  a=0
  while a<len(rows):
   b=a
   while b+1<len(rows) and rows[b+1][key]==rows[a][key]:b+=1
   if a>=2 and b+2<len(rows) and all(valid(r) for r in rows[a-2:b+3]):
    x=rows[a][key]
    if all((x-r[key])*sgn>0 for r in rows[a-2:a]+rows[b+1:b+3]):result.append({'kind':kind,'i':b,'start_i':a,'end_i':b,'date':rows[b]['date'],'zone_dates':[r['date'] for r in rows[a:b+1]],'price':x,'known_i':b+2,'known_date':rows[b+2]['date']})
   a=b+1
 return sorted(result,key=lambda p:(p['i'],p['kind']))

def risk_scan(rows,event_dates=None,calendar=None,coverage_calendar=None):
 """TRUE = proxy hit, FALSE = fully observed non-hit, UNKNOWN = incomplete."""
 n=len(rows);event_dates=set(event_dates or [r['date'] for r in rows[-60:]])
 positions={d:i for i,d in enumerate(calendar if calendar is not None else [r['date'] for r in rows])}
 coverage_calendar=coverage_calendar if coverage_calendar is not None else calendar
 coverage=set(coverage_calendar) if coverage_calendar is not None else set(positions)
 coverage_dates=sorted(coverage)
 def expected_dates(first,last):return coverage_dates[bisect_left(coverage_dates,first):bisect_right(coverage_dates,last)]
 indices=[i for i,r in enumerate(rows) if r['date'] in event_dates]
 checks={f'D{k}':[] for k in range(1,6)};events=[]
 missing_dates=event_dates-{r['date'] for r in rows}
 def prevmax(i,n,key):
  if i<n or not all(valid(r) for r in rows[i-n:i]):return None
  return max(r[key] for r in rows[i-n:i])
 def accel(i):return None if i<11 or not valid(rows[i-1]) or not valid(rows[i-11]) else rows[i-1]['c']/rows[i-11]['c']-1>=N('.20')
 def big(i):
  if i<1 or not valid(rows[i]) or not valid(rows[i-1]):return None
  r=rows[i];d=r['o']-r['c'];span=r['h']-r['l']
  return r['c']<r['o'] and d/rows[i-1]['c']>=N('.03') and span>0 and d/span>=N('.60')
 def volbig(i,mult):
  value=ma(rows,i,20,include=False)
  return cmp(rows[i]['v'],'>=',None if value is None or value<=0 else value*mult)
 def record(kind,i,state,details,peak_i=None,completion_i=None,peak_indices=None):
  checks[kind].append({'date':rows[i]['date'],'status':truth(state),**details})
  if state is True:
   pi=i if peak_i is None else peak_i;ci=i if completion_i is None else completion_i
   span=peak_indices if peak_indices is not None else [pi];peak_price=max(rows[j]['h'] for j in span);ties=[j for j in span if rows[j]['h']==peak_price];pi=ties[-1]
   events.append({'proxy':kind,'event_date':rows[i]['date'],'completion_date':rows[ci]['date'],'peak_date':rows[pi]['date'],'peak_dates':[rows[j]['date'] for j in ties],'peak_price':peak_price,'peak_binding_dates':[rows[j]['date'] for j in span],'details':details})
 for i in indices:
  r=rows[i];hh=prevmax(i,60,'h');mv=prevmax(i,60,'v');v20=ma(rows,i,20,include=False)
  d1=risk_and(accel(i),cmp(r['h'],'>=',None if hh is None else hh*N('.9')),big(i),volbig(i,N(3)),cmp(r['v'],'>=',mv))
  if i<60 or not all(valid(z) for z in rows[i-60:i+1]):d1=None
  record('D1',i,d1,{'V20_prior':v20,'HH60_prior':hh,'maxV60_prior':mv,'acceleration':truth(accel(i)),'big_bear':truth(big(i)),'acceleration_base_date':rows[i-11]['date'] if i>=11 else None,'acceleration_base_close':rows[i-11]['c'] if i>=11 else None},peak_indices=list(range(max(0,i-10),i+1)))
  if i<9: d5=None;detail={'reason':'LT10_BARS'}
  else:
   seg=rows[i-9:i+1];hi=None if i<59 or not all(valid(z) for z in rows[i-59:i+1]) else max(z['h'] for z in rows[i-59:i+1])
   red=[z['v'] for z in seg if z['c']>z['o']];green=[z['v'] for z in seg if z['c']<z['o']]
   ra=sum(red)/len(red) if red else None;ga=sum(green)/len(green) if green else None
   small=None if i<10 or not all(valid(z) for z in rows[i-10:i+1]) else all(abs(rows[j]['c']-rows[j]['o'])/rows[j-1]['c']<=N('.03') for j in range(i-9,i+1))
   d5=risk_and(cmp(min(z['c'] for z in seg),'>=',None if hi is None else hi*N('.9')),small,len(green)>=3,bool(red),cmp(ga,'>=',None if ra is None else ra*N('1.5')),None if not green or not red else sum(green)>=sum(red))
   detail={'HH60_including_t':hi,'min_close10':min(z['c'] for z in seg),'small_body10':truth(small),'red_count':len(red),'green_count':len(green),'red_sum':sum(red),'green_sum':sum(green),'red_mean':ra,'green_mean':ga}
  if i<60 or not all(valid(z) for z in rows[i-60:i+1]):d5=None
  peak_i=max(range(max(0,i-9),i+1),key=lambda j:(rows[j]['h'],j)) if all(valid(z) for z in rows[max(0,i-59):i+1]) else i
  record('D5',i,d5,detail,peak_i,peak_indices=list(range(max(0,i-9),i+1)))
 ps=pivots(rows);peaks=[p for p in ps if p['kind']=='peak']
 ambiguous={p['i'] for p in ps if sum(q['i']==p['i'] for q in ps)>1}
 # Structural proxies use market ordinals ONLY; per-exchange coverage is separate.
 # Bound pairs by frozen 5..30 sessions; no historical cross-product.
 peaks_known=[p for p in peaks if p['date'] in positions]
 peak_ord=[positions[p['date']] for p in peaks_known]
 unavailable=[p for p in peaks if p['date'] not in positions]
 event_start=bisect_left([r['date'] for r in rows],min(event_dates)) if event_dates else n
 # Suffix minimum up to the event-window start excludes already broken old necklines in O(1).
 pre_min=[None]*(event_start+1);pre_bad=[0]*(event_start+1)
 for j in range(event_start-1,-1,-1):
  good=valid(rows[j]);old=pre_min[j+1]
  pre_min[j]=min(rows[j]['c'],old) if good and old is not None else rows[j]['c'] if good else old
  pre_bad[j]=pre_bad[j+1]+int(not good)
 bear_cache={}
 def bear_window(p):
  idx=p['i']
  if idx not in bear_cache:
   window=list(range(idx,min(n,idx+3)))
   states=[risk_and(big(k),volbig(k,N(2))) for k in window]
   bear_cache[idx]=(None if len(window)<3 else risk_or(*states),[{'date':rows[k]['date'],'big':truth(big(k)),'V20_prior':ma(rows,k,20,include=False),'volume':rows[k]['v']} for k in window])
  return bear_cache[idx]
 for p2 in unavailable:
  ci=p2['known_i']
  if rows[ci]['date'] in event_dates:
   for kind in ('D2','D4'):record(kind,ci,None,{'reason':'PEAK_OUTSIDE_EXCHANGE_CALENDAR_COVERAGE','peak2':p2})
 for bpos,p2 in enumerate(peaks_known):
  b=p2['i'];complete=p2['known_i'];p2ordinal=peak_ord[bpos]
  lo=bisect_left(peak_ord,p2ordinal-30,0,bpos);hi=bisect_right(peak_ord,p2ordinal-5,0,bpos)
  for p1 in peaks_known[lo:hi]:
   a=p1['i'];gap=p2ordinal-positions[p1['date']]
   assert 5<=gap<=30
   span=rows[a:b+1]
   requested=expected_dates(rows[a]['date'],rows[b]['date'])
   coverage_unknown=p1['date'] not in coverage or p2['date'] not in coverage
   priceok=None if coverage_unknown or ({a,b}&ambiguous) or not requested or [z['date'] for z in span]!=requested else True
   down=min(z['l'] for z in rows[a+1:b]) if b>a+1 and all(valid(z) for z in span) else None
   any2,detail2=bear_window(p2)
   detail={'peak1':p1,'peak2':p2,'spacing_market_sessions':gap,'neckline':down,'first_peak_acceleration':truth(accel(a)),'second_bear_window':detail2}
   if rows[complete]['date'] in event_dates:
    d2=risk_and(priceok,N('.9')*p1['price']<=p2['price']<=p1['price'],None if down is None else down<=p1['price']*N('.95'),accel(a),any2)
    if coverage_unknown:d2=None
    record('D2',complete,d2,detail,a,complete,peak_indices=list(range(p1['start_i'],p1['end_i']+1)))
   # D4 old pairs remain eligible only if their FIRST neckline break is in this event window.
   if abs(p2['price']/p1['price']-1)>N('.05'):continue
   any1,detail1=bear_window(p1)
   d4base=risk_and(priceok,any1,any2)
   if d4base is False:continue
   if down is None:
    if rows[complete]['date'] in event_dates:record('D4',complete,None,{**detail,'reason':'UNKNOWN_INTERPEAK_NECKLINE'})
    continue
   prior_unknown=False
   if b+1<event_start and complete<event_start:
    prior_unknown=pre_bad[b+1]>0
    if pre_min[b+1] is not None and pre_min[b+1]<down:continue
   crossing=None
   scan_start=max(b+1,event_start) if complete<event_start else b+1
   for j in range(scan_start,n):
    if not valid(rows[j]):prior_unknown=True;continue
    if rows[j]['c']<down:crossing=j;break
   if crossing is not None:
    ci=max(complete,crossing)
    if rows[ci]['date'] in event_dates:
     state=None if prior_unknown else d4base
     record('D4',ci,state,{**detail,'break_date':rows[crossing]['date'],'first_bear_window':detail1,'prior_cross_input_unknown':prior_unknown},a,ci,peak_indices=list(range(p1['start_i'],p1['end_i']+1))+list(range(p2['start_i'],p2['end_i']+1)))
 # D3 needs prior upwave and two adjacent downwaves. Collapse consecutive same-kind pivots conservatively.
 alternating=[]
 for p in ps:
  if p['i'] in ambiguous:continue
  if alternating and alternating[-1]['kind']==p['kind']:
   q=alternating[-1]
   if (p['price']>=q['price'] if p['kind']=='peak' else p['price']<=q['price']):alternating[-1]=p
  else:alternating.append(p)
 for j in range(4,len(alternating)):
  seq=alternating[j-4:j+1]
  if [p['kind'] for p in seq]!=['trough','peak','trough','peak','trough']:continue
  z,p1,v1,p2,v2=seq;a,b,c,d,e=[p['i'] for p in seq]
  ci=v2['known_i']
  if rows[ci]['date'] not in event_dates:continue
  def avg(l,h):return None if h<=l or not all(valid(r) for r in rows[l+1:h+1]) else sum(r['v'] for r in rows[l+1:h+1])/N(h-l)
  u1=avg(a,b);dn1=avg(b,c);u2=avg(c,d);dn2=avg(d,e);hh=prevmax(b,60,'h')
  requested=expected_dates(rows[a]['date'],rows[e]['date'])
  wave_gap=None if not requested or [r['date'] for r in rows[a:e+1]]!=requested else True
  d3=risk_and(wave_gap,cmp(p1['price'],'>=',hh),p2['price']<p1['price'],v2['price']<v1['price'],cmp(dn1,'>=',None if u1 is None or u1<=0 else u1*N('1.5')),cmp(dn2,'>=',None if u2 is None or u2<=0 else u2*N('1.5')))
  if hh is None:d3=None
  record('D3',ci,d3,{'turns':seq,'up1_mean':u1,'down1_mean':dn1,'up2_mean':u2,'down2_mean':dn2,'start_HH60_prior':hh},b,ci,peak_indices=list(range(p1['start_i'],p1['end_i']+1)))
 statuses={}
 # Insufficient 60+60 warmup or incomplete event-date coverage makes untriggered structural absence UNKNOWN.
 complete_history=bool(indices) and min(indices)>=60 and not missing_dates and all(valid(r) for r in rows[max(0,min(indices)-60):])
 for key,values in checks.items():
  statuses[key]=TRUE if any(x['status']==TRUE for x in values) else UNKNOWN if not complete_history or any(x['status']==UNKNOWN for x in values) else FALSE
 return {'proxy_status':statuses,'events':events,'checks':checks,'confirmed_pivots':[p for p in ps if p['known_i']>=max(0,n-60)],'missing_event_dates':sorted(missing_dates),'input_complete':complete_history,'event_dates':sorted(event_dates),'last_two_bars_unconfirmed_pivots':True}

def risk_disposition(scan,rows,keys):
 if not rows or not valid(rows[-1]):return {'status':UNKNOWN,'reason':'INVALID_D_PRICE','events':[]}
 out=[];states=[]
 for event in scan['events']:
  peak=event['peak_price'];drawdown=1-rows[-1]['c']/peak if peak and peak>0 else None
  later=[k['date'] for k in keys if k['candidate']==TRUE and event['completion_date']<k['date']<rows[-1]['date']]
  state=UNKNOWN if drawdown is None or drawdown>=N('.5') or later else FALSE
  reason='REBUILD_PENDING_50PCT' if drawdown is not None and drawdown>=N('.5') else 'LATER_STRUCTURE_APPLICABILITY_PENDING' if later else 'NUMERIC_PROXY_TRIGGERED'
  out.append({**event,'D_close':rows[-1]['c'],'peak_to_D_close_drawdown':drawdown,'later_key_dates':later,'disposition':state,'reason':reason});states.append(state)
 status=FALSE if FALSE in states else UNKNOWN if states or UNKNOWN in scan['proxy_status'].values() else TRUE
 return {'status':status,'reason':'ACTIVE_NUMERIC_PROXY' if status==FALSE else 'RISK_APPLICABILITY_OR_INPUT_PENDING' if status==UNKNOWN else 'LAST60_NUMERIC_PROXIES_NOT_TRIGGERED','events':out,'proxy_status':scan['proxy_status']}

def prior_key_gate(keys,requested_dates,available_dates):
 recent=[k for k in keys if k['date'] in requested_dates]
 return TRUE if any(k['candidate']==TRUE for k in recent) else UNKNOWN if any(k['candidate']==UNKNOWN for k in recent) or set(requested_dates)-set(available_dates) else FALSE

def result_binding_compatible(result,freeze_sha,calendar_sha):
 return result.get('execution_freeze_sha256')==freeze_sha and result.get('calendar_sha256')==calendar_sha

def market_spacing(first,last,exchange_dates):
 positions={day:i for i,day in enumerate(exchange_dates)}
 return None if first not in positions or last not in positions else positions[last]-positions[first]


# Daily product adapter. The frozen numeric functions above intentionally remain
# byte-for-byte identical to EXECUTION_FREEZE_R5.json; this layer only binds a
# caller-supplied causal prefix and source metadata to those predicates.
from collections import Counter
from collections.abc import Mapping

_GROUPS = ('original', 'nav_smallk', 'nav_pullback', 'nav_breakout')
_QUALIFIED = 'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH'
_SAFE_FLAGS = {
    'RESEARCH_ONLY': True,
    'production_allowed': False,
    'buy_gate_updated': False,
    'orders_sent': False,
}


def _as_date(value):
    try:
        date = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return date if len(str(date)) == 8 else None


def _tri(value):
    if isinstance(value, Mapping):
        value = value.get('status', value.get('membership', value.get('state')))
    if type(value) is bool:
        return TRUE if value else FALSE
    if value in ('TRUE', 'YES'):
        return TRUE
    if value in ('FALSE', 'NO'):
        return FALSE
    return UNKNOWN


def _decimal_or_none(value):
    if value is None:
        return None
    try:
        number = N(str(value))
    except Exception:
        return None
    return number if number.is_finite() else None


def _raw_bar_value(row, key, alias):
    value = row.get(key)
    if value is None:
        value = row.get(alias)
    if value is None and isinstance(row.get('ohlcv'), Mapping):
        nested = row['ohlcv']
        value = nested.get(key)
        if value is None:
            value = nested.get(alias)
    return value


def _unknown_group(baseline, reasons, anchor_date=None):
    after_redgreen = _gate_and(baseline, UNKNOWN)
    final = _gate_and(after_redgreen, UNKNOWN)
    return {
        'baseline': baseline,
        'redgreen_gate': UNKNOWN,
        'anchor_applicability': UNKNOWN,
        'after_redgreen': after_redgreen,
        'risk_clear_gate': UNKNOWN,
        'status': final,
        'after_risk': final,
        'anchor_date': anchor_date,
        'event_dates': [anchor_date] if anchor_date is not None else [],
        'reasons': list(dict.fromkeys(reasons)),
    }


def _gate_and(*states):
    return FALSE if FALSE in states else UNKNOWN if UNKNOWN in states else TRUE


def _base_statuses(baseline_memberships):
    source = baseline_memberships if isinstance(baseline_memberships, Mapping) else {}
    return {group: _tri(source.get(group)) for group in ('original', 'nav_pullback', 'nav_breakout')}


def _raw_g4_smallk(raw_g4_reference, asof, rows):
    """Compute the approved raw-day and volume-shrink base; never use QFQ close."""
    raw = raw_g4_reference if isinstance(raw_g4_reference, Mapping) else {}
    nested = raw.get('raw') if isinstance(raw.get('raw'), Mapping) else raw
    date = _as_date(raw.get('date') or raw.get('trade_date') or nested.get('trade_date'))
    correspondence = raw.get('correspondence_status', raw.get('status'))
    if correspondence == 'AUXILIARY_D28_G4_REFERENCE_RESEARCH_ONLY':
        correspondence = TRUE
    correspondence = _tri(correspondence)
    current_close = _decimal_or_none(nested.get('close'))
    raw_prev_close = _decimal_or_none(nested.get('prev_close'))
    if date != asof or correspondence != TRUE or current_close is None or raw_prev_close is None or raw_prev_close <= 0:
        return UNKNOWN, {
            'status': UNKNOWN,
            'reason': 'RAW_G4_REFERENCE_OR_SAME_DATE_RAW_PARITY_UNKNOWN',
            'raw_reference_date': date,
            'raw_g4_prev_close_supplied': raw_prev_close is not None,
        }
    if len(rows) < 2 or rows[-1]['date'] != asof:
        return UNKNOWN, {
            'status': UNKNOWN,
            'reason': 'CURRENT_OR_PREVIOUS_VOLUME_BAR_MISSING',
            'raw_reference_date': date,
            'raw_g4_prev_close': raw_prev_close,
        }
    current_volume = rows[-1]['v']
    previous_volume = rows[-2]['v']
    volume_shrink = None if current_volume is None or previous_volume is None or current_volume < 0 or previous_volume <= 0 else current_volume < previous_volume
    raw_day_small = abs(current_close - raw_prev_close) * N(100) <= raw_prev_close * N(3)
    membership = FALSE if raw_day_small is False or volume_shrink is False else TRUE if raw_day_small is True and volume_shrink is True else UNKNOWN
    return membership, {
        'status': membership,
        'reason': 'RAW_G4_REFERENCE_AND_VOLUME_SHRINK_EVALUATED',
        'raw_reference_date': date,
        'raw_g4_close': current_close,
        'raw_g4_prev_close': raw_prev_close,
        'raw_day_small': truth(raw_day_small),
        'volume_shrink': truth(volume_shrink),
        'volume_basis': 'CALLER_SUPPLIED_PREFIX_VOLUME',
        'raw_reference_basis': 'CALLER_SUPPLIED_RAW_G4_PREV_CLOSE',
    }


def _r5_d3_terminal_check(rows, calendar):
    """R5 d3_terminal.check, with its frozen predicates bound locally."""
    n = len(rows)
    ps = pivots(rows)
    counts = Counter(p['i'] for p in ps)
    ambiguous = {i for i, count in counts.items() if count > 1}
    turns = []
    for pivot in ps:
        if pivot['i'] in ambiguous:
            continue
        if turns and turns[-1]['kind'] == pivot['kind']:
            old = turns[-1]
            if (pivot['price'] >= old['price'] if pivot['kind'] == 'peak' else pivot['price'] <= old['price']):
                turns[-1] = pivot
        else:
            turns.append(pivot)

    def expected(first, last):
        return calendar[bisect_left(calendar, first):bisect_right(calendar, last)]

    def average(start, end):
        segment = rows[start + 1:end + 1]
        if end <= start or not all(valid(row) for row in segment):
            return None
        requested = expected(rows[start + 1]['date'], rows[end]['date'])
        if not requested or [row['date'] for row in segment] != requested:
            return None
        return sum(row['v'] for row in segment) / N(end - start)

    candidates = []
    for end in range(max(0, n - 2), n):
        if end + 1 < n and rows[end + 1]['l'] == rows[end]['l']:
            continue
        start = end
        while start and rows[start - 1]['l'] == rows[end]['l']:
            start -= 1
        if start < 2:
            continue
        neighborhood = rows[start - 2:]
        if not all(valid(row) for row in neighborhood):
            continue
        low = rows[end]['l']
        right = rows[end + 1:]
        if not all(low < row['l'] for row in rows[start - 2:start] + right):
            continue
        before = [pivot for pivot in turns if pivot['i'] < start]
        if len(before) < 4:
            continue
        sequence = before[-4:]
        if [pivot['kind'] for pivot in sequence] != ['trough', 'peak', 'trough', 'peak']:
            continue
        t0, p1, t1, p2 = sequence
        a, b, c, d = [pivot['i'] for pivot in sequence]
        if not (p2['price'] < p1['price'] and low < t1['price']):
            continue
        hh = None if b < 60 or not all(valid(row) for row in rows[b - 60:b]) else max(row['h'] for row in rows[b - 60:b])
        if hh is not None and p1['price'] < hh:
            continue
        up1 = average(a, b)
        down1 = average(b, c)
        up2 = average(c, d)
        down2 = average(d, end)
        compare1 = None if up1 is None or up1 <= 0 or down1 is None else down1 >= up1 * N('1.5')
        compare2 = None if up2 is None or up2 <= 0 or down2 is None else down2 >= up2 * N('1.5')
        if compare1 is False or compare2 is False:
            continue
        candidates.append({
            'status': UNKNOWN,
            'reason': 'D3_PLAUSIBLE_SECOND_DOWNWAVE_TERMINAL_NOT_RIGHT2_CONFIRMED',
            'turns': sequence,
            'terminal_zone_dates': [row['date'] for row in rows[start:end + 1]],
            'terminal_low': low,
            'available_right_bars': n - end - 1,
            'required_right_bars': 2,
            'start_HH60_prior': hh,
            'up1_mean': up1,
            'down1_mean': down1,
            'up2_mean': up2,
            'down2_mean': down2,
            'first_down_volume_test': truth(compare1),
            'second_down_volume_test': truth(compare2),
            'asof': rows[-1]['date'],
        })
    return {
        'status': UNKNOWN if candidates else FALSE,
        'reason': 'PLAUSIBLE_INCOMPLETE_D3_TERMINAL' if candidates else 'NO_PLAUSIBLE_INCOMPLETE_D3_TERMINAL',
        'candidates': candidates,
    }


def _safe_risk_scan(rows, event_dates, calendar):
    """Keep missing D5 colour/volume fields UNKNOWN instead of crashing the oracle."""
    requested = set(event_dates)
    for index, row in enumerate(rows):
        if row['date'] not in requested or index < 9:
            continue
        if any(rows[j][key] is None for j in range(index - 9, index + 1) for key in ('o', 'c', 'v')):
            return {
                'proxy_status': {f'D{i}': UNKNOWN for i in range(1, 6)},
                'events': [],
                'checks': {f'D{i}': [] for i in range(1, 6)},
                'confirmed_pivots': [],
                'missing_event_dates': sorted(requested - {bar['date'] for bar in rows}),
                'input_complete': False,
                'event_dates': sorted(requested),
                'last_two_bars_unconfirmed_pivots': True,
                'reason': 'REQUIRED_RISK_WINDOW_FIELDS_MISSING',
            }
    return risk_scan(rows, event_dates, calendar, calendar)


def _unknown_product(symbol, asof, baseline, reasons, *, future_bars_excluded=0, prior10_dates=None, smallk=None):
    groups = {}
    for group in _GROUPS:
        group_baseline = baseline.get(group, UNKNOWN)
        group_reasons = list(reasons)
        if group == 'nav_smallk' and smallk is not None:
            group_baseline = _gate_and(smallk, UNKNOWN)
        groups[group] = _unknown_group(group_baseline, group_reasons)
    return {
        'symbol': symbol,
        'asof': asof,
        'status': 'UNKNOWN_INPUT_COVERAGE',
        'groups': groups,
        'layers': groups,
        'baseline': {group: groups[group]['baseline'] for group in _GROUPS},
        'new_prior10_key_gate': UNKNOWN,
        'latest_prior_new_key_date': None,
        'all_new_key_dates': [],
        'new_key_unknown_dates': [],
        'prior10_dates': prior10_dates or [],
        'future_bars_excluded': future_bars_excluded,
        'input_coverage': {'status': UNKNOWN, 'reasons': list(dict.fromkeys(reasons))},
        'risk': {'status': UNKNOWN, 'reason': 'UNKNOWN_INPUT_COVERAGE', 'events': [], 'proxy_status': {f'D{i}': UNKNOWN for i in range(1, 6)}},
        **_SAFE_FLAGS,
    }


def evaluate_daily_product(
    *,
    symbol,
    asof,
    fullprefix,
    exchange_calendar,
    original_breakout_by_date,
    baseline_memberships,
    old_main_anchor_date,
    qualification_status,
    raw_g4_reference,
):
    """Evaluate the frozen R5 four-group predicates for one explicit as-of date.

    Inputs are already bound by the caller. The function has no I/O and never
    obtains data. `original_breakout_by_date` contains the exact V192 assignment
    result for each source date as TRUE/FALSE/UNKNOWN; missing dates stay UNKNOWN.
    `fullprefix` may contain later bars, which are excluded before any predicate
    runs. `exchange_calendar` must be the same-exchange session calendar.
    `baseline_memberships` and `old_main_anchor_date` must be valid at this same
    as-of cutoff; a current-only descriptor cannot be reused for a historical D.
    `raw_g4_reference` must be the same-date raw close/prev_close reference with
    raw correspondence verified by the caller.
    """
    asof = _as_date(asof)
    base = _base_statuses(baseline_memberships)
    baseline = {**base, 'nav_smallk': UNKNOWN}
    reasons = []
    if asof is None:
        return _unknown_product(symbol, asof, baseline, ['INVALID_ASOF_DATE'])

    calendar_values = []
    for value in exchange_calendar if isinstance(exchange_calendar, (list, tuple)) else ():
        date = _as_date(value)
        if date is None:
            return _unknown_product(symbol, asof, baseline, ['INVALID_EXCHANGE_CALENDAR_DATE'])
        calendar_values.append(date)
    if not calendar_values or calendar_values != sorted(set(calendar_values)) or asof not in calendar_values:
        return _unknown_product(symbol, asof, baseline, ['ASOF_MISSING_OR_INVALID_EXCHANGE_CALENDAR'])
    calendar = [date for date in calendar_values if date <= asof]
    asof_position = calendar.index(asof)
    prior10_dates = calendar[max(0, asof_position - 10):asof_position]

    qualification = qualification_status
    if isinstance(qualification, Mapping):
        qualification = qualification.get('status')
    if qualification != _QUALIFIED:
        return _unknown_product(
            symbol,
            asof,
            baseline,
            ['UNKNOWN_SOURCE_ADMISSION'],
            prior10_dates=prior10_dates,
            future_bars_excluded=0,
        )

    if not isinstance(fullprefix, (list, tuple)):
        return _unknown_product(symbol, asof, baseline, ['FULLPREFIX_MISSING_OR_INVALID'], prior10_dates=prior10_dates)

    parsed = []
    undated = 0
    future_bars_excluded = 0
    for source_row in fullprefix:
        if not isinstance(source_row, Mapping):
            undated += 1
            continue
        source_date = _as_date(source_row.get('date') or source_row.get('trade_date'))
        if source_date is None:
            undated += 1
            continue
        if source_date > asof:
            future_bars_excluded += 1
            continue
        raw = {'date': source_date}
        for key, alias in (('o', 'open'), ('h', 'high'), ('l', 'low'), ('c', 'close'), ('v', 'vol')):
            value = _raw_bar_value(source_row, key, alias)
            if key == 'v' and value is None:
                value = source_row.get('volume')
                if value is None and isinstance(source_row.get('ohlcv'), Mapping):
                    value = source_row['ohlcv'].get('volume')
            number = _decimal_or_none(value)
            raw[key] = str(number) if number is not None else 'NaN'
        parsed.append(raw)

    if undated:
        return _unknown_product(symbol, asof, baseline, ['UNDATED_PREFIX_ROW'], future_bars_excluded=future_bars_excluded, prior10_dates=prior10_dates)
    if not parsed:
        return _unknown_product(symbol, asof, baseline, ['FULLPREFIX_EMPTY'], future_bars_excluded=future_bars_excluded, prior10_dates=prior10_dates)
    dates = [row['date'] for row in parsed]
    if dates != sorted(set(dates)):
        return _unknown_product(symbol, asof, baseline, ['DUPLICATE_OR_NONINCREASING_PREFIX_DATES'], future_bars_excluded=future_bars_excluded, prior10_dates=prior10_dates)
    if any(date not in calendar for date in dates):
        return _unknown_product(symbol, asof, baseline, ['PREFIX_DATE_OUTSIDE_EXCHANGE_CALENDAR'], future_bars_excluded=future_bars_excluded, prior10_dates=prior10_dates)
    if dates[-1] != asof:
        return _unknown_product(symbol, asof, baseline, ['ASOF_BAR_MISSING'], future_bars_excluded=future_bars_excluded, prior10_dates=prior10_dates)

    rows = normalize(parsed)
    source_statuses = original_breakout_by_date if isinstance(original_breakout_by_date, Mapping) else {}
    breakout = []
    original_signal_dates = []
    source_dates = []
    original_unknown_dates = []
    for source_row in rows:
        date = source_row['date']
        state = _tri(source_statuses.get(date, source_statuses.get(str(date))))
        breakout.append(None if state == UNKNOWN else state == TRUE)
        if state == TRUE:
            original_signal_dates.append(date)
        if state == UNKNOWN:
            original_unknown_dates.append(date)
        if date in source_statuses or str(date) in source_statuses:
            source_dates.append(date)
    keys = fund_keys(rows, breakout)
    available_dates = [row['date'] for row in rows]
    prior_key_states = keys[:-1]
    recent_gate = prior_key_gate(prior_key_states, prior10_dates, available_dates)
    if len(prior10_dates) != 10:
        recent_gate = UNKNOWN
    smallk, smallk_detail = _raw_g4_smallk(raw_g4_reference, asof, rows)
    baseline['nav_smallk'] = _gate_and(smallk, recent_gate)

    eligible = [i for i, key in enumerate(prior_key_states) if key['candidate'] == TRUE]
    uncertain = [key['date'] for key in prior_key_states if key['candidate'] == UNKNOWN]
    latest = eligible[-1] if eligible else None
    path_indices = sorted(set([i for i in eligible if rows[i]['date'] in prior10_dates] + ([latest] if latest is not None else [])))
    paths = []
    for index in path_indices:
        segment = consolidation(rows, index, calendar)
        paths.append({
            'anchor_date': rows[index]['date'],
            'role': 'LATEST_PRIOR_NEW_KEY' if index == latest else 'EARLIER_REFERENCE_RETAINED_NOT_SELECTED',
            'key': keys[index],
            'ohlcv': rows[index],
            'preK': segment,
            'same_anchor_support': {
                'D_close': rows[-1]['c'],
                'K_low': rows[index]['l'],
                'K_high': rows[index]['h'],
                'within_K_range': None if rows[index]['l'] is None or rows[-1]['c'] is None or rows[index]['h'] is None else rows[index]['l'] <= rows[-1]['c'] <= rows[index]['h'],
                'above_K_high': None if rows[index]['h'] is None or rows[-1]['c'] is None else rows[-1]['c'] > rows[index]['h'],
            },
        })
    current = next((path for path in paths if path['role'] == 'LATEST_PRIOR_NEW_KEY'), None)
    key_uncertain = latest is None or any(date > rows[latest]['date'] for date in uncertain)
    primary_redgreen = UNKNOWN if key_uncertain or current is None else current['preK']['status']
    unresolved_other = primary_redgreen == FALSE and any(path['role'] != 'LATEST_PRIOR_NEW_KEY' and path['preK']['status'] != FALSE for path in paths)
    redgreen = UNKNOWN if unresolved_other else primary_redgreen

    baseline['original'] = base['original']
    baseline['nav_pullback'] = base['nav_pullback']
    baseline['nav_breakout'] = base['nav_breakout']
    old_main_anchor_date = _as_date(old_main_anchor_date)
    risk_event_dates = calendar[max(0, len(calendar) - 60):]
    risk_scan_result = _safe_risk_scan(rows, risk_event_dates, calendar)
    d3_terminal = None
    if risk_scan_result['proxy_status']['D3'] == FALSE:
        d3_terminal = _r5_d3_terminal_check(rows, calendar)
        if d3_terminal['status'] == UNKNOWN:
            risk_scan_result['proxy_status']['D3'] = UNKNOWN
            risk_scan_result['checks']['D3'].append({'date': asof, 'status': UNKNOWN, 'terminal_pending': d3_terminal})
    disposition = risk_disposition(risk_scan_result, rows, keys)

    layers = {}
    for group in _GROUPS:
        applicability = TRUE
        group_reasons = []
        if key_uncertain:
            applicability = UNKNOWN
            group_reasons.append('LATEST_NEW_KEY_UNRESOLVED')
        if group in ('nav_pullback', 'nav_breakout') and baseline[group] == TRUE:
            new_anchor = rows[latest]['date'] if latest is not None else None
            if old_main_anchor_date != new_anchor:
                applicability = UNKNOWN
                group_reasons.append('OLD_DESCRIPTOR_AND_NEW_FILTER_ANCHOR_DIFFER')
        if group == 'nav_smallk' and current and current['anchor_date'] not in prior10_dates:
            applicability = UNKNOWN
            group_reasons.append('CURRENT_NEW_KEY_NOT_IN_PRIOR10')
        after_redgreen = _gate_and(baseline[group], redgreen, applicability)
        final = _gate_and(after_redgreen, disposition['status'])
        if redgreen != TRUE:
            group_reasons.append('REDGREEN_' + redgreen)
        if disposition['status'] != TRUE:
            group_reasons.append(disposition['reason'])
        if d3_terminal is not None and d3_terminal['status'] == UNKNOWN:
            group_reasons.append('D3_TERMINAL_UNCONFIRMED')
        anchor_date = rows[latest]['date'] if latest is not None else None
        layers[group] = {
            'baseline': baseline[group],
            'redgreen_gate': redgreen,
            'anchor_applicability': applicability,
            'after_redgreen': after_redgreen,
            'risk_clear_gate': disposition['status'],
            'status': final,
            'after_risk': final,
            'anchor_date': anchor_date,
            'event_dates': [anchor_date] if anchor_date is not None else [],
            'reasons': list(dict.fromkeys(group_reasons)),
        }

    field_missing = [
        {'date': row['date'], 'fields': [{'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'vol'}[key] for key in ('o', 'h', 'l', 'c', 'v') if row[key] == 'NaN']}
        for row in parsed
        if any(row[key] == 'NaN' for key in ('o', 'h', 'l', 'c', 'v'))
    ]
    coverage_reasons = []
    if field_missing:
        coverage_reasons.append('MISSING_REQUIRED_PREFIX_FIELDS')
    if original_unknown_dates:
        coverage_reasons.append('V192_BREAKOUT_STATUS_UNKNOWN_OR_MISSING')
    if smallk == UNKNOWN:
        coverage_reasons.append('RAW_G4_REFERENCE_OR_VOLUME_COVERAGE_UNKNOWN')
    if recent_gate == UNKNOWN:
        coverage_reasons.append('PRIOR10_KEY_COVERAGE_UNKNOWN')
    if not risk_scan_result.get('input_complete', False):
        coverage_reasons.append('RISK_PROXY_HISTORY_OR_EVENT_COVERAGE_UNKNOWN')
    result = {
        'symbol': symbol,
        'asof': asof,
        'status': 'NUMERIC_PROXIES_COMPUTED',
        'groups': layers,
        'layers': layers,
        'baseline': {group: layers[group]['baseline'] for group in _GROUPS},
        'old_raw_memberships': {group: baseline[group] for group in ('original', 'nav_pullback', 'nav_breakout')},
        'smallk_raw_base': smallk,
        'smallk_reference': smallk_detail,
        'new_prior10_key_gate': recent_gate,
        'prior10_dates': prior10_dates,
        'latest_prior_new_key_date': rows[latest]['date'] if latest is not None else None,
        'new_key_true_count': len(eligible),
        'new_key_unknown_dates': uncertain,
        'all_new_key_dates': [key['date'] for key in prior_key_states if key['candidate'] == TRUE],
        'unselected_older_key_applicability': 'UNKNOWN_NOT_PROMOTED_TO_CURRENT_REFERENCE',
        'primary_path_redgreen': primary_redgreen,
        'other_path_applicability_pending': unresolved_other,
        'filter_anchor_paths': paths,
        'event_dates': {
            'original_v192_true': original_signal_dates,
            'new_key_true': [key['date'] for key in prior_key_states if key['candidate'] == TRUE],
            'risk': [event['event_date'] for event in disposition['events']],
        },
        'risk': disposition,
        'risk_scan': risk_scan_result,
        'd3_terminal_r5': d3_terminal,
        'history_bars': len(rows),
        'future_bars_excluded': future_bars_excluded,
        'input_coverage': {
            'status': UNKNOWN if coverage_reasons else TRUE,
            'reason': coverage_reasons[0] if coverage_reasons else 'QUALIFIED_COMPLETE_INPUTS_SUPPLIED',
            'reasons': coverage_reasons,
            'missing_fields': field_missing,
            'v192_breakout_unknown_or_missing_dates': original_unknown_dates,
            'qualification_status': _QUALIFIED,
            'original_breakout_coverage_count': len(source_dates),
            'prefix_date_count': len(rows),
            'calendar_prefix_count': len(calendar),
        },
        'whole_original_formula_compute_calls': 0,
        'PIT': False,
        'native_tdx_certified': False,
        'human_list_confirmation_required_before_images': True,
        **_SAFE_FLAGS,
    }
    return result
