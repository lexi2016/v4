"""D12 full-universe return denominators and limited static industry diagnostics.
Prices end at D12 close. Later/static mapping is marked separately and never
used to create candidates or infer contemporaneous sector membership.
"""
import hashlib,json,pathlib,sys,os,datetime
import numpy as np,pandas as pd
N=pathlib.Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def save(p,x):pathlib.Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str)+'\n')
def summary(x):
 known=x[x.return_status.eq('EXACT_D_AND_D_MINUS1')]
 return dict(scope=len(x),observed_return=len(known),unknown=len(x)-len(known),advancing=int((known.return_pct>0).sum()),declining=int((known.return_pct<0).sum()),unchanged=int((known.return_pct==0).sum()),median_return_pct=float(known.return_pct.median())if len(known)else None,mean_return_pct=float(known.return_pct.mean())if len(known)else None)
def main():
 f=json.loads((N/'RUN_FREEZE.json').read_text());os.environ.update(f['env']);sys.path.insert(0,f['env']['V4_APP_ROOT']);from ops import research_panel_logical as logical,research_panel_daily_product as prod
 prod.checked(f['selector']);reader=logical.parquet.ParquetFile(f['selector']['path']);cols=['ts_code','trade_date','close','name','market_type','exchange'];table=reader.read(columns=cols,filters=[('trade_date','>=','20261111'),('trade_date','<=','20261112')]);df=table.to_pandas();df['trade_date']=df.trade_date.astype(str);df=df[df.ts_code.isin(f['scope'])];assert not df.duplicated(['ts_code','trade_date']).any()
 grouped={str(code):g for code,g in df.groupby('ts_code',sort=False)};rows=[]
 for code in f['scope']:
  g=grouped.get(code,pd.DataFrame());d=g[g.trade_date.eq('20261112')]if len(g)else g;prev=g[g.trade_date.eq('20261111')]if len(g)else g
  valid=len(d)==len(prev)==1 and np.isfinite(float(d.close.iloc[0])) and np.isfinite(float(prev.close.iloc[0])) and float(prev.close.iloc[0])>0
  rows.append(dict(security_code=code,trade_date='2026-11-12',display_name=d.name.iloc[0]if len(d)else None,D_close=float(d.close.iloc[0])if len(d)else None,prev_trade_date='2026-11-11'if len(prev)else None,prev_close=float(prev.close.iloc[0])if len(prev)else None,return_pct=(float(d.close.iloc[0])/float(prev.close.iloc[0])-1)*100 if valid else None,return_status='EXACT_D_AND_D_MINUS1'if valid else 'UNKNOWN_MISSING_D_OR_PREVIOUS_EXACT_ROW',basis='same D12 generation QFQ_ASOF',historical_PIT=False))
 out=pd.DataFrame(rows);out.to_csv(N/'data/FULL_UNIVERSE_D12_RETURNS.csv',index=False,float_format='%.17g');base=summary(out);base.update(status='D12_FULL_UNIVERSE_RETURN_DESCRIPTIVE',source=f['selector'],source_generation=f['source_identity']['generation'],return_definition='D12 close / exact D11 close - 1; missing exact row remains UNKNOWN; no stale-date substitution',by_market={m:summary(out[out.security_code.str.endswith('.'+m)])for m in ('SH','SZ','BJ')},cutoff='2026-11-12T15:00:00+08:00');save(N/'MARKET_BREADTH.json',base)
 source=pathlib.Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/event_relation_f10_fixed_r4_20261112/data/F10_RESEARCH_INDUSTRY_FIXED_5537_V4.csv');mapping=pd.read_csv(source,encoding='utf-8-sig',dtype=str).fillna('');assert not mapping.symbol.duplicated().any()
 keep=mapping[(mapping.research_primary_code!='')&(mapping.research_primary_name!='')].copy();keep=keep.rename(columns={'symbol':'security_code'});merged=out.merge(keep,how='left',on='security_code',validate='one_to_one')
 # Source capture before cutoff is necessary, not sufficient to claim PIT.
 cut=datetime.datetime.fromisoformat('2026-11-12T15:00:00+08:00')
 def timing(v):
  try:return 'CAPTURED_BY_D_CUTOFF_STATIC_NONPIT'if datetime.datetime.fromisoformat(str(v))<=cut else 'LATER_INFO_CAPTURE_AFTER_D_CUTOFF'
  except (ValueError,TypeError):return 'CAPTURE_TIME_UNKNOWN'
 merged['industry_info_timing']=merged.captured_at.map(timing);merged['industry_role']='LIMITED_RESEARCH_MAPPING_DIAGNOSTIC_ONLY_NOT_SELECTION_INPUT';merged.to_csv(N/'data/FULL_UNIVERSE_LIMITED_INDUSTRY_CONTEXT.csv',index=False,float_format='%.17g');groups=[]
 for (code,name),g in merged[merged.research_primary_code.notna()].groupby(['research_primary_code','research_primary_name'],sort=True):
  item=summary(g);item.update(research_industry_code=code,research_industry_name=name,mapping_observed_members=len(g),known_return_members=item['observed_return'],complete_economic_industry_denominator='UNKNOWN',official_named_industry_field='UNKNOWN_NO_NATIVE_NAMED_FIELD',historical_PIT=False,captured_before_cutoff=int(g.industry_info_timing.eq('CAPTURED_BY_D_CUTOFF_STATIC_NONPIT').sum()),later_or_unknown_capture=int((~g.industry_info_timing.eq('CAPTURED_BY_D_CUTOFF_STATIC_NONPIT')).sum()),use='POSTHOC_STATIC_MAPPING_CONTEXT; NOT_A_SHARED_MARKET_OR_SELECTION_GATE');groups.append(item)
 pd.DataFrame(groups).to_csv(N/'outputs/LIMITED_INDUSTRY_D12_STRENGTH.csv',index=False,float_format='%.17g');save(N/'INDUSTRY_CONTEXT_COVERAGE.json',dict(status='LIMITED_STATIC_NONPIT_DIAGNOSTIC',mapping_source=dict(path=str(source),sha256=sha(source)),mapping_denominator=len(mapping),mapping_direct_primary_total=len(keep),matched_to_engine_scope=int(merged.research_primary_code.notna().sum()),engine_scope=len(out),unknown_industry_engine_scope=int(merged.research_primary_code.isna().sum()),groups=len(groups),full_industry_coverage=False,contemporaneous_availability_certified=False,selection_input_used=False,later_information_not_used_for_selection=True));print(json.dumps(base),flush=True)
if __name__=='__main__':main()
