"""Non-US event-method replica from Futu FAQ Q16; no provider or data defaults."""
from datetime import datetime
import math

FIELDS=('open','high','low','close')
def date8(x):
 s=str(x).replace('-','')[:8];datetime.strptime(s,'%Y%m%d');return int(s)
def event_coefficients(event):
 vals={k:event[k] for k in ('fenhong','peigujia','songzhuangu','peigu')}
 if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in vals.values()):raise ValueError('NONFINITE_OR_MISSING_EVENT_FIELDS')
 if any(vals[k]<0 for k in vals):raise ValueError('NEGATIVE_EVENT_FIELD_UNSUPPORTED')
 d=1+vals['songzhuangu']/10+vals['peigu']/10
 if d<=0:raise ValueError('NONPOSITIVE_EVENT_DENOMINATOR')
 return 1/d,(-vals['fenhong']/10+vals['peigujia']*vals['peigu']/10)/d
def forward_adjust(rows,events,anchor):
 anchor=date8(anchor);before=[dict(r) for r in rows if date8(r['trade_date'])<=anchor];dates=[date8(r['trade_date']) for r in before]
 if not dates or dates!=sorted(set(dates)) or dates[-1]!=anchor:raise ValueError('EMPTY_DUPLICATE_ORDERED_OR_STALE_PRICE_WINDOW')
 for r in before:
  if any(isinstance(r[k],bool) or not isinstance(r[k],(int,float)) or not math.isfinite(r[k]) or r[k]<=0 for k in FIELDS):raise ValueError('INVALID_RAW_PRICE')
  if not r['low']<=min(r['open'],r['close'])<=max(r['open'],r['close'])<=r['high']:raise ValueError('INVALID_OHLC_SHAPE')
 accepted=[]
 for e in events:
  d=date8('%04d%02d%02d'%(e['year'],e['month'],e['day']))
  if d>anchor:continue
  if e['category'] in (11,12):raise ValueError('UNSUPPORTED_SPLIT_OR_CONSOLIDATION_CATEGORY')
  if e['category']!=1:continue
  a,b=event_coefficients(e);accepted.append((d,a,b))
 accepted.sort()
 if len({x[0] for x in accepted})!=len(accepted):raise ValueError('DUPLICATE_EXRIGHT_EVENT_DATE')
 result=[]
 for row,d in zip(before,dates):
  r=dict(row);a_total,b_total=1.0,0.0
  for ed,a,b in accepted:
   if ed>d:a_total,b_total=a_total*a,b_total*a+b
  for k in FIELDS:r[k]=float(row[k])*a_total+b_total
  if any(not math.isfinite(r[k]) or r[k]<=0 for k in FIELDS):raise ValueError('INVALID_ADJUSTED_PRICE')
  r.update(qfq_factor_A=a_total,qfq_factor_B=b_total,qfq_anchor=str(anchor),qfq_method='FUTU_Q16_NON_US_EVENT_AFFINE_REPLICA_NOT_LIVE_PARITY')
  result.append(r)
 return result
