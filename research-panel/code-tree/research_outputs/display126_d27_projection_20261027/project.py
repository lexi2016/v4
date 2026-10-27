from pathlib import Path
import json,gzip,hashlib,shutil,datetime
from decimal import Decimal
W=Path.cwd();P=W/'research_outputs/display126_d27_projection_20261027';(P/'stocks').mkdir(exist_ok=True)
A=W/'research_outputs/independent_d27_display126_20261027/DISPLAY_ADMISSION126.json';EXPECTED='17cbe4459fde3083c0f1d8aa0871b32bee434d21b3c0a8424941144a17139020'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert sha(A)==EXPECTED;ad=json.loads(A.read_text());allowed={r['symbol']:r for r in ad['display']};assert len(allowed)==123
special={'002086.SZ','002249.SZ','688306.SH'}
OLD85=W/'research_outputs/price_percentile85_20261027/PRICE_POSITION85.json';OLD41=W/'research_outputs/breakout41_price_position_20261027/PRICE_POSITION41.json';old85=json.loads(OLD85.read_text());old41=json.loads(OLD41.read_text());old={r['symbol']:r for r in old85['stocks']+old41['stocks']};rosters={'85':[r['symbol'] for r in old85['stocks']],'41':[r['symbol'] for r in old41['stocks']]};assert len(old)==126 and set(old)==set(allowed)|special
fields=['白线','黄线','BBI','MA60','守线','K','D','J','一级买点','二级买点','B1','B2','B3','突破','突破接十字星','零上二金','零下二金','卖点']
def write(p,x):
 assert shutil.disk_usage(W).free>3*1024**3
 p.write_text(json.dumps(x,ensure_ascii=False,separators=(',',':'),allow_nan=False))
def cmp(a,b):return None if a is None or b is None else (Decimal(str(a))>Decimal(str(b)))-(Decimal(str(a))<Decimal(str(b)))
def pos(rows,close):
 v=[Decimal(r['ohlcv']['close']) for r in rows];n=len(v);count=sum(x<=close for x in v);pct=Decimal(100)*count/n
 return {'start':rows[0]['trade_date'],'end':rows[-1]['trade_date'],'N':n,'n':n,'status':'COMPUTED_DESCRIPTIVE_NOT_VALUATION','count':count,'count_le':count,'pct':float(pct),'pct_decimal':str(pct),'min':str(min(v)),'max':str(max(v))}
records=[];positions={};lastbars=[];checks=0
for s in rosters['85']+rosters['41']:
 if s in allowed:
  ar=allowed[s];src=W/ar['formula_path'];assert sha(src)==ar['formula_sha256'];full=json.loads(gzip.decompress(src.read_bytes()));assert full['symbol']==s and full['field_count']==51 and full['drawing_count']==22;rs=full['rows'];assert len(rs)==ar['rows'] and rs[-1]['trade_date']==20261027;assert all(r['trade_date']<t['trade_date'] for r,t in zip(rs,rs[1:]));rr=rs[-180:];offset=len(rs)-len(rr);chart=[]
  for i,r in enumerate(rr):
   assert len(r['values'])==51 and len(r['drawings'])==22;o=r['ohlcv'];previous=rs[offset+i-1]['ohlcv'].get('close') if offset+i else None
   chart.append({'date':r['trade_date'],**{k:o.get(k) for k in ['open','high','low','close']},'volume':o.get('vol'),'previousClose':previous,'values':{k:r['values'].get(k) for k in fields},'priceFacts':{'closeVsOpen':cmp(o.get('close'),o.get('open')),'closeVsPreviousClose':cmp(o.get('close'),previous)}})
  source={'dailyCutoff':20261027,'indicatorDate':20261027,'basis':'D27_FIXED_VINTAGE_QFQ_NONPIT_LIMITED_RESEARCH_DISPLAY','volumeUnit':'source volume contract retained','projectionOnly':True,'originalValuesPerBar':51,'originalDrawingsPerBar':22,'projectedValueFields':fields,'retainedBars':len(chart),'inputCachedBars':len(rs),'noIndicatorRecalculation':True,'formulaPath':str(src.relative_to(W)),'formulaSHA256':sha(src),'admissionPath':str(A.relative_to(W)),'admissionSHA256':EXPECTED,'displayStatus':ar['display_status'],'nativeQfqCertified':False,'buyConfirmed':False,'productionAllowed':False,'amountPolicy':'No amount in chart projection; UI/gates use exact G4/qt, never pipeline float32'}
  c=Decimal(rs[-1]['ohlcv']['close']);near=pos(rs[-250:],c);total=pos(rs,c)
  positions[s]={'symbol':s,'name':old[s].get('name'),'status':'COMPUTED','asof':20261027,'close':str(c),'basis':'D27_FIXED_VINTAGE_QFQ_NONPIT','near250':near,'full':total,'recent250':near,'authorizedPrefix':total,'qualification':full['qualification'],'inputSHA':sha(src),'source':{'source_path':str(src.relative_to(W)),'source_sha256':sha(src),'admission_path':str(A.relative_to(W)),'admission_sha256':EXPECTED},'method':'100*count(close_i <= asof_close)/actual N; includes asof and ties; near250=min(250,N); full means admitted prefix, not listed lifetime','shortHistory':len(rs)<250,'PIT':False,'valuation':False,'prediction':False}
  status='D27_LIMITED_DISPLAY_FROM_INDEPENDENT_ADMISSION'
 else:
  src=(W/'research_outputs/live85_chart_projection_20261027/stocks'/f'{s}.json') if s in rosters['85'] else (W/'research_outputs/breakout41_panel_20261027/stocks'/f'{s}.json');d=json.loads(src.read_text());assert d['symbol']==s and d['chartRows'][-1]['date']==20261026;chart=d['chartRows'];source={**d['source'],'dailyCutoff':20261026,'indicatorDate':20261026,'displayStatus':'D26_RETAINED_D27_CONTINUATION_UNKNOWN','D27Continuation':'NOT_ADMITTED','originalD26ProjectionPath':str(src.relative_to(W)),'originalD26ProjectionSHA256':sha(src),'admissionPath':str(A.relative_to(W)),'admissionSHA256':EXPECTED,'amountPolicy':'No new amount or raw candle inserted'};positions[s]=old[s];status='D26_RETAINED_D27_CONTINUATION_UNKNOWN'
 fp=P/'stocks'/f'{s}.json';write(fp,{'symbol':s,'chartRows':chart,'source':source});last=chart[-1];lastbars.append({'symbol':s,'asof':last['date'],'status':status,'ohlcv':{k:last[k] for k in ['open','high','low','close','volume','previousClose']},'values':last['values'],'originalAnchorUnchanged':True,'chartDataPath':str(fp.relative_to(W)),'admissionSHA256':EXPECTED})
 records.append({'symbol':s,'pool':'85' if s in rosters['85'] else '41','path':str(fp.relative_to(W)),'sha256':sha(fp),'bytes':fp.stat().st_size,'first':chart[0]['date'],'last':last['date'],'bars':len(chart),'status':status,'source':source})
 # Read-back exact field values and types; this checks projection, not independent formula logic.
 d=json.loads(fp.read_text());assert d['chartRows']==chart;checks+=len(chart)*(7+len(fields));assert positions[s]['asof']==last['date']
for pool,syms in rosters.items():
 write(P/f'PRICE_POSITION{pool}.json',{'asof':'MIXED_PER_STOCK_123_D27_3_D26','scope':len(syms),'rosterSHA':old85['rosterSHA'] if pool=='85' else old41['rosterSHA'],'method':'per-stock asof fixed QFQ descriptive close rank, actual N; D26 special unchanged; no raw price insertion','stocks':[positions[s] for s in syms]})
write(P/'LASTBAR126.json',{'count':126,'admissionSHA256':EXPECTED,'stocks':lastbars})
write(P/'source_manifest.json',{'scope':126,'D27':123,'D26Retained':sorted(special),'admissionPath':str(A.relative_to(W)),'admissionSHA256':EXPECTED,'original85PositionSHA256':sha(OLD85),'original41PositionSHA256':sha(OLD41),'records':records,'bytes':sum(r['bytes'] for r in records),'createdUTC':datetime.datetime.now(datetime.timezone.utc).isoformat(),'originalAnchorsChanged':False,'newFormulaCalls':0,'newNetworkCalls':0})
write(P/'SELF_CHECK.json',{'status':'PASS_PROJECTION_READBACK_ONLY','checks':checks,'errors':[],'scope':126,'D27':123,'D26Retained':sorted(special),'shortCharts':[{'symbol':r['symbol'],'bars':r['bars'],'asof':r['last']} for r in records if r['bars']<180],'noSourceFormulaRecalculation':True})
print(json.dumps({'scope':126,'bytes':sum(r['bytes'] for r in records),'checks':checks,'shortCharts':[{'symbol':r['symbol'],'bars':r['bars']} for r in records if r['bars']<180],'free':shutil.disk_usage(W).free}))
