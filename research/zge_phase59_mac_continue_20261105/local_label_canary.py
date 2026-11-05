"""Three source-price/date parity checks before local label overlay."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import runtime as r

ROOT=r.OUT
R4=Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/pullback_model_design_20261104/training_v1')
CONTRACT=R4/'EXPERIMENT_CONTRACT_R4.json'; cfg=json.loads(CONTRACT.read_text())
PANEL=Path(cfg['input']['selector_path']);SESSION=R4/'full/observed_a_sessions.parquet';PARTS=R4/'full/parts'
MIX=R4.parent/'mixed_cache/MIXED_INPUT_REPORT.json'
CLOUD=ROOT/'inputs/P5_9_ALL_A_UNIFIED_PANEL_303161.parquet'
SAMPLES=[('600028.SH',20260921),('000017.SZ',20260921),('920006.BJ',20260921)]

def stats_map():
    out={};allparts=[]
    for p in sorted(PARTS.glob('stats_*.json')):
        st=json.loads(p.read_text());allparts.append(st)
        for s in st['symbols']:
            tc=s['symbol']
            if tc in out:raise ValueError('CROSS_PART_STOCK_DUPLICATION:'+tc)
            out[tc]=st
    return out,allparts

def extract(codes,dates):
    by,_=stats_map();missing=sorted(codes-set(by))
    if missing:raise ValueError('TARGETS_ABSENT_IN_R4_CACHE:'+str(missing))
    ps={int(by[c]['part']):by[c] for c in codes};allprice=[];groups=set()
    mixed_report=json.loads(MIX.read_text()) if MIX.exists() else {'row_groups':[]}
    for i,st in ps.items():
        path=PARTS/f'prices_{i:05d}.parquet'
        if r.sha(path)!=st['price_sha256']:raise ValueError('PRICE_CACHE_HASH_DRIFT:'+str(path))
        z=pd.read_parquet(path);allprice.append(z.loc[z.ts_code.isin(codes)&z.trade_date.isin(dates)].copy())
        groups.update(st['source_groups'])
        if set(st['mixed_symbols'])&codes:groups.update(mixed_report['row_groups'])
    price=pd.concat(allprice,ignore_index=True) if allprice else pd.DataFrame()
    if price.duplicated(['ts_code','trade_date']).any():raise ValueError('CACHE_KEY_CONFLICT')
    pf=pq.ParquetFile(PANEL);raw=pf.read_row_groups(sorted(groups),columns=['ts_code','trade_date','market_type','open','volume'],use_threads=True).to_pandas()
    raw['trade_date']=pd.to_numeric(raw.trade_date,errors='coerce');raw=raw.loc[raw.ts_code.isin(codes)&raw.trade_date.isin(dates)].copy()
    validmarket=((raw.market_type.eq('A_SHARE')&raw.ts_code.str.fullmatch(r'\d{6}\.(SH|SZ)'))|(raw.market_type.eq('BJ')&raw.ts_code.str.fullmatch(r'\d{6}\.BJ')))
    if not validmarket.all():raise ValueError('SOURCE_MARKET_CONFLICT')
    if raw.duplicated(['ts_code','trade_date']).any():raise ValueError('PANEL_KEY_CONFLICT')
    raw=raw.rename(columns={'open':'panel_open'});j=price.merge(raw,on=['ts_code','trade_date'],how='outer',validate='one_to_one',indicator=True)
    if not j['_merge'].eq('both').all() or not np.isclose(j.open,j.panel_open,atol=1e-9,rtol=1e-9).all():raise ValueError('PRICE_CACHE_PANEL_MISMATCH')
    return j,{'cache_parts':sorted(ps),'row_groups':sorted(groups),'raw_physical_rows_read':len(raw),'matched_price_rows':len(j)}

def main():
    ss=pd.read_parquet(SESSION).trade_date.to_numpy(dtype='int64');assert len(ss)==len(set(ss)) and (np.diff(ss)>0).all()
    sample=pd.read_parquet(CLOUD,columns=['ts_code','signal_date','entry_date','entry_open_px','exit_date_t5','status_t5','ret_t5_pct'])
    dates=set();pairs=[]
    for tc,D in SAMPLES:
        x=sample[(sample.ts_code==tc)&(sample.signal_date==D)]
        if len(x)!=1 or x.status_t5.iloc[0]!='MATURED':raise ValueError('CLOUD_CANARY_KEY_MISSING')
        idx=np.searchsorted(ss,D)
        if idx>=len(ss) or ss[idx]!=D or idx+6>=len(ss):raise ValueError('SESSION_MAPPING_MISSING')
        en,ex=int(ss[idx+1]),int(ss[idx+6]);dates.update([en,ex]);pairs.append((tc,D,en,ex,x.iloc[0]))
    px,audit=extract({x[0] for x in SAMPLES},dates);px=px.set_index(['ts_code','trade_date']);rows=[]
    for tc,D,en,ex,src in pairs:
        entry=px.loc[(tc,en)];exit=px.loc[(tc,ex)]
        if not(bool(entry.price_valid) and bool(exit.price_valid) and np.isfinite(entry.volume) and np.isfinite(exit.volume) and entry.volume>0 and exit.volume>0):raise ValueError('CANARY_INVALID_PRICE_OR_VOLUME')
        localret=(exit.open/entry.open-1)*100.;inferred=float(src.entry_open_px)*(1+float(src.ret_t5_pct)/100.)
        checks={'entry_date':int(src.entry_date)==en,'exit_date':int(src.exit_date_t5)==ex,
          'entry_price':bool(np.isclose(float(src.entry_open_px),entry.open,rtol=1e-6,atol=1e-6)),
          'exit_price_inferred_from_cloud_return':bool(np.isclose(inferred,exit.open,rtol=1e-6,atol=1e-6)),
          'return_pct':bool(np.isclose(float(src.ret_t5_pct),localret,rtol=1e-6,atol=1e-6))}
        rows.append({'ts_code':tc,'signal_date':D,'entry_date':en,'exit_date':ex,'cloud_entry':float(src.entry_open_px),
          'local_entry':float(entry.open),'cloud_exit_inferred':inferred,'local_exit':float(exit.open),'entry_volume':float(entry.volume),
          'exit_volume':float(exit.volume),'cloud_ret_pct':float(src.ret_t5_pct),'local_ret_pct':localret,'checks':checks})
    passed=all(all(x['checks'].values()) for x in rows)
    report={'status':'THREE_LOCAL_LABEL_CANARY_PASS' if passed else 'THREE_LOCAL_LABEL_CANARY_FAIL',
      'sample_rule':'20260921 existing matured events; first SH, SZ, BJ representatives', 'samples':rows,'source_audit':audit,
      'source_basis':'V4 generation e3ff25234adf18d8f29805a1107b36d61416b7bba3af8f3da9e63f17ee42fe09, QFQ_ASOF_20261104; producer SHA not rehashed',
      'selector_declared_sha256':cfg['input']['selector_declared_sha256'],'r4_contract_sha256':r.sha(CONTRACT),'session_sha256':r.sha(SESSION),
      'calendar':'OBSERVED_PANEL_SESSION_PROXY_UNCERTIFIED','cloud_input_sha256':'ec10ffc05beec1ffee27cd3afe1c7e44a54cbeba1f705c6f6e633082a78c0a12'}
    path=ROOT/'LOCAL_LABEL_CANARY.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n');print(json.dumps(report,ensure_ascii=False))
    if not passed:raise ValueError('CLOUD_LOCAL_CANARY_MISMATCH_STOP')
if __name__=='__main__':main()
