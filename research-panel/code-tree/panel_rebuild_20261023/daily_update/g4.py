"""G4 daily snapshot candidate, inferred offsets validated against same-date official .day.
Not a vendor-published format contract. Date is obtained from verified linked package, not embedded.
"""
import struct,math,datetime

def parse(cod,md1,market,date):
 if len(cod)%150 or len(md1)%512 or len(cod)//150!=len(md1)//512:raise ValueError('RECORD_ALIGNMENT')
 if market not in ('SH','SZ','BJ') or len(str(date))!=8:raise ValueError('IDENTITY_OR_DATE')
 datetime.datetime.strptime(str(date),'%Y%m%d');out={}
 for i in range(len(cod)//150):
  code=cod[i*150:i*150+6].decode('ascii',errors='replace')
  if not code.isdigit():continue
  symbol=code+'.'+market
  if symbol in out:raise ValueError('DUPLICATE_SYMBOL')
  b=md1[i*512:(i+1)*512];prev,o,h,l,c=struct.unpack_from('<5d',b,4);vol=struct.unpack_from('<Q',b,56)[0];amount=struct.unpack_from('<d',b,72)[0]
  if not all(math.isfinite(x) for x in (prev,o,h,l,c,amount)) or min(o,h,l,c,amount)<0 or h<max(o,l,c) or l>min(o,h,c):raise ValueError('INVALID_OHLCV:'+symbol)
  out[symbol]={'trade_date':date,'open':o,'high':h,'low':l,'close':c,'amount':amount,'vol':vol,'prev_close':prev}
 return out
