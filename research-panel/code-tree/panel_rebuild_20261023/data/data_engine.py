"""Isolated raw parser and explicitly UNVERIFIED fixed-vintage adjustment candidate."""
import struct, math, datetime
from pathlib import PurePosixPath

def parse_day(data):
 if len(data)%32:raise ValueError('TRUNCATED_DAY')
 rows=[];last=0
 for d,o,h,l,c,a,v,res in struct.iter_unpack('<5If2I',data):
  if len(str(d))!=8:raise ValueError('INVALID_DATE_WIDTH')
  datetime.datetime.strptime(str(d),'%Y%m%d')
  if d<=last or not math.isfinite(a) or a<0 or v<0 or min(o,h,l,c)<0 or h<max(o,l,c) or l>min(o,h,c):raise ValueError('INVALID_DAY_RECORD')
  last=d;rows.append(dict(trade_date=d,open=o/100,high=h/100,low=l/100,close=c/100,amount=a,vol=v,reserved=res))
 return rows

def classify(name):
 n=PurePosixPath(name.replace('\\','/')).name
 if len(n)!=12 or not n.endswith('.day') or not n[2:8].isdigit():return 'UNKNOWN_IDENTITY'
 m,c=n[:2],n[2:8]
 if m=='sh' and c[:3] in ('600','601','603','605','688','689'):return 'SH_A_CODE_CANDIDATE'
 if m=='sz' and c[:3] in ('000','001','002','003','300','301'):return 'SZ_A_CODE_CANDIDATE'
 if m=='bj' and c[:2] in ('43','83','87','88','92'):return 'BJ_MAPPING_UNVERIFIED'
 return 'NON_A_SHARE'

def decode_gbbq(data,constants):
 if len(data)<4:raise ValueError('TRUNCATED_GBBQ')
 count=struct.unpack_from('<I',data)[0]
 if len(data)!=4+29*count:raise ValueError('GBBQ_COUNT_LENGTH_MISMATCH')
 if len(constants)<4168:raise ValueError('FORMAT_CONSTANTS_TRUNCATED')
 k=struct.unpack('<'+str(len(constants)//4)+'I',constants);mask=0xffffffff
 result=[]
 def block(off):
  x,y=struct.unpack_from('<II',data,off);x^=k[17]
  for j in range(16,0,-1):
   f=((k[18+(x>>24)]+k[274+((x>>16)&255)])&mask)^k[530+((x>>8)&255)]
   f=(f+k[786+(x&255)])&mask
   x,y=(y^f^k[j])&mask,x
  return struct.pack('<II',(y^k[0])&mask,x)
 for index in range(count):
  off=4+index*29
  clear=block(off)+block(off+8)+block(off+16)+data[off+24:off+29]
  market,code,date,category,*v=struct.unpack('<B7sIBffff',clear)
  code=code.rstrip(b'\0').decode('ascii')
  if not code.isdigit() or len(code)!=6 or not all(math.isfinite(x) for x in v):raise ValueError('INVALID_DECODED_EVENT')
  if len(str(date))!=8:raise ValueError('INVALID_DATE_WIDTH')
  datetime.datetime.strptime(str(date),'%Y%m%d')
  result.append(dict(record_index=index,market=market,code=code,date=date,category=category,**dict(zip(['c1','c2','c3','c4'],v))))
 return result

def qfq_candidate(bars,events,asof):
 if not bars:return None,['NO_BARS']
 if any(r['trade_date']>asof for r in bars):return None,['BAR_AFTER_ASOF']
 relevant=[e for e in events if bars[0]['trade_date']<e['date']<=asof]
 reasons=[]
 for e in relevant:
  if e['category'] in (11,15):reasons.append('SPECIAL_EVENT_'+str(e['category']))
  if e['category']==1 and e['c4']!=0:reasons.append('RIGHTS_RATIO_UNVERIFIED')
  if e['category']==1 and (e['c1']<0 or e['c3']<0):reasons.append('NEGATIVE_CORPORATE_ACTION')
 if reasons:return None,sorted(set(reasons))
 ordinary=sorted([e for e in relevant if e['category']==1],key=lambda e:e['date'])
 if len({e['date'] for e in ordinary})!=len(ordinary):return None,['DUPLICATE_EVENT_DATE']
 out=[]
 for row in bars:
  q=dict(row)
  for e in ordinary:
   if row['trade_date']<e['date']:
    den=1+e['c3']/10
    for field in ('open','high','low','close'):q[field]=(q[field]-e['c1']/10)/den
  out.append(q)
 return out,['FIXED_VINTAGE_AFFINE_CANDIDATE_NOT_INDEPENDENTLY_CERTIFIED']
