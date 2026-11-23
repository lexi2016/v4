"""Frozen ACT-013 full observed A-market daily breadth. No fitting or panel writes."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
APP_ROOT=Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:sys.path.insert(0,str(APP_ROOT))
import numpy as np
import pandas as pd
from ops import pft_s_full_ashare as old
from ops.pft_act008_b import verify_source,write_json
from ops.pft_act008_b_score import scheduled_calendar

START,ASOF='20220101','20261120'
FACTOR_NAME='MARKET_REGIME_DAILY_2022_2026.csv'


def fold_a(frame,crosswalk):
    """Observed metadata universe, never the present-day or training cohort."""
    f=frame.copy();counts=Counter(raw_rows=len(f))
    f['ts_code']=f.ts_code.astype(str).str.strip().str.upper()
    f['trade_date']=f.trade_date.map(old._day)
    keep=f.ts_code.str.fullmatch(r'\d{6}\.(SH|SZ|BJ)')
    f=f[keep].copy();counts['non_a_code_rows']=int((~keep).sum())
    # Same published A market/exchange semantics as the frozen producer consumer.
    keep=np.array([old._a_market_row(c,{'market_type':m,'exchange':e}) for c,m,e in
                   zip(f.ts_code,f.market_type.fillna(''),f.exchange.fillna(''))],dtype=bool)
    counts['non_a_metadata_rows']=int((~keep).sum());f=f[keep].copy()
    if f.duplicated(['ts_code','trade_date']).any():raise ValueError('DUPLICATE_RAW_CODE_D')
    f['canonical']=f.ts_code;f['alias_priority']=0
    for r in crosswalk:
        mask=f.ts_code.isin([r['old'],r['new']])
        f.loc[mask,'canonical']=r['new']
        desired=np.where(f.loc[mask,'trade_date'].lt(r['effective']),r['old'],r['new'])
        f.loc[mask,'alias_priority']=(f.loc[mask,'ts_code'].to_numpy()==desired).astype(int)
    dup=f.duplicated(['canonical','trade_date'],keep=False)
    if dup.any():
        d=f[dup]
        if d.groupby(['canonical','trade_date']).alias_priority.sum().ne(1).any():
            raise ValueError('AMBIGUOUS_ALIAS_DATE')
    f=f.sort_values('alias_priority',kind='stable').drop_duplicates(['canonical','trade_date'],keep='last')
    counts['alias_rows_folded']=int(dup.sum()-f.loc[dup.reindex(f.index,fill_value=False)].shape[0])
    if f.duplicated(['canonical','trade_date']).any():raise ValueError('DUPLICATE_CANONICAL_D')
    counts['canonical_rows']=len(f);counts['duplicate_canonical_D_after_fold']=0
    return f,counts


def daily_aggregate(frame):
    f=frame.copy()
    cols=['close','pre_close','zge_white_line','zge_yellow_line','vol','amount','tradeable_basic']
    for c in cols:f[c]=pd.to_numeric(f[c],errors='coerce').astype('float64')
    positive=lambda x:np.isfinite(x)&x.gt(0)
    observed=f.tradeable_basic.eq(1)&positive(f.vol)
    counts=pd.DataFrame({'D':f.trade_date,'observed':observed.astype(int)})
    for key,left,right in [('cw','close','zge_white_line'),('cy','close','zge_yellow_line'),('wy','zge_white_line','zge_yellow_line')]:
        known=observed&positive(f[left])&positive(f[right])
        counts[key+'_n']=known.astype(int);counts[key+'_above']=(known&f[left].gt(f[right])).astype(int)
    comparable=observed&positive(f.close)&positive(f.pre_close)
    delta=f.close-f.pre_close
    counts['ad_n']=comparable.astype(int)
    counts['adv']=(comparable&delta.gt(1e-12)).astype(int)
    counts['dec']=(comparable&delta.lt(-1e-12)).astype(int)
    counts['unch']=(comparable&delta.abs().le(1e-12)).astype(int)
    amount_known=observed&positive(f.amount)
    counts['amount_n']=amount_known.astype(int)
    counts['amount']=f.amount.where(amount_known,0.)
    counts['adv_amount']=f.amount.where(amount_known&comparable&delta.gt(1e-12),0.)
    counts['dec_amount']=f.amount.where(amount_known&comparable&delta.lt(-1e-12),0.)
    result=counts.groupby('D',sort=True).sum()
    # Dates absent from observed market remain absent, rather than inventing sessions.
    result=result[result.observed.gt(0)]
    for c in ['cw','cy','wy']:result[c+'_share']=result[c+'_above']/result[c+'_n'].where(result[c+'_n'].gt(0))
    result['ad_ratio']=result.adv/result.dec.where(result.dec.gt(0))
    result['amount_ad_ratio']=result.adv_amount/result.dec_amount.where(result.dec_amount.gt(0))
    result.loc[result.amount_n.eq(0),['amount','adv_amount','dec_amount']]=np.nan
    return result.reset_index()


def finish_daily(frame):
    f=frame.sort_values('D').reset_index(drop=True).copy()
    if f.D.duplicated().any():raise ValueError('DUPLICATE_AGGREGATE_D')
    for c in ['cw','cy','wy']:f[c+'_missing']=f.observed-f[c+'_n']
    f['ad_missing']=f.observed-f.ad_n;f['amount_missing']=f.observed-f.amount_n
    f['amount_MA5']=f.amount.rolling(5,min_periods=5).mean()
    f['amount_MA20']=f.amount.rolling(20,min_periods=20).mean()
    f['liquidity_trend']=f.amount_MA5/f.amount_MA20.where(f.amount_MA20.gt(0))
    known=f[['cw_share','cy_share','wy_share']].notna().all(axis=1)
    on=f[['cw_share','cy_share','wy_share']].gt(.5).all(axis=1)
    f['gate']=np.where(~known,'UNKNOWN',np.where(on,'RISK_ON','RISK_OFF'))
    return f


def market(*,act005_root,data_root,output_dir,start=START,end=ASOF):
    from ops.pft_s_first_baseline import bind_current_panels
    from ops import research_panel_logical as reader
    if not START<=start<=end<=ASOF:raise ValueError('RANGE_OUTSIDE_FROZEN_SCOPE')
    if output_dir.exists() or output_dir.with_name(output_dir.name+'.partial').exists():raise ValueError('OUTPUT_EXISTS')
    frozen=old._validate_inputs(act005_root) # Source only, NOT a universe restriction.
    cross=pd.read_csv(old.CROSSWALK_FILE).fillna('')
    crosswalk=[dict(old=r.old_ts_code,new=r.new_ts_code,effective=old._day(r.code_change_effective_date))
               for r in cross.itertuples() if r.old_ts_code and r.new_ts_code]
    chunks=[];counts=Counter()
    with bind_current_panels(data_root) as (path,source,recheck):
        verify_source(source,frozen)
        basis=source['identity']['a_market_basis']
        if basis.get('amount_basis')!='RAW_TURNOVER':raise ValueError('AMOUNT_BASIS_DRIFT')
        schema=reader.parquet.read_schema(path);actual=old._schema_names(schema)
        fields=['ts_code','trade_date','market_type','exchange','close','pre_close','zge_white_line','zge_yellow_line','tradeable_basic','amount']
        mapping={c:actual[c] for c in fields};mapping['vol']=actual.get('vol',actual.get('volume'))
        if mapping['vol'] is None:raise ValueError('VOLUME_COLUMN_MISSING')
        # Read preceding market sessions for inclusive rolling windows even for canaries.
        read_start=START if start==START else (pd.Timestamp(start)-pd.Timedelta(days=60)).strftime('%Y%m%d')
        read_start=max(START,read_start)
        for year in range(int(read_start[:4]),int(end[:4])+1):
            lo=max(read_start,f'{year}0101');hi=min(end,f'{year}1231')
            filters=[[(mapping['trade_date'],'>=',old._date_value(schema,mapping['trade_date'],lo)),
                      (mapping['trade_date'],'<=',old._date_value(schema,mapping['trade_date'],hi))]]
            t=reader.parquet.read_table(path,columns=list(mapping.values()),filters=filters,use_threads=True)
            f=t.to_pandas().rename(columns={v:k for k,v in mapping.items()});del t
            f,c=fold_a(f,crosswalk);counts.update(c);chunks.append(daily_aggregate(f));del f
            print(json.dumps({'year':year,'counts':dict(c)}),flush=True)
        recheck()
    daily=finish_daily(pd.concat(chunks,ignore_index=True))
    # Prefix recomputation is independent of all subsequent dates.
    cut=max(1,len(daily)//2)
    prefix=finish_daily(pd.concat(chunks,ignore_index=True).sort_values('D').iloc[:cut])
    pd.testing.assert_frame_equal(prefix,daily.iloc[:cut].reset_index(drop=True))
    sessions,calendar=scheduled_calendar()
    if calendar['year']!=2026:raise ValueError('CALENDAR_YEAR_MISMATCH')
    expected=[d for d in sessions if max(read_start,'20260101')<=d<=end]
    actual_days=list(daily.loc[daily.D.ge('20260101'),'D'])
    if expected!=actual_days:raise ValueError('OBSERVED_2026_CALENDAR_MISMATCH:'+str({'missing':sorted(set(expected)-set(actual_days)),'extra':sorted(set(actual_days)-set(expected))}))
    daily=daily[daily.D.ge(start)].reset_index(drop=True)
    stage=output_dir.with_name(output_dir.name+'.partial');stage.mkdir(parents=True)
    p=stage/FACTOR_NAME;daily.to_csv(p,index=False,float_format='%.12g',na_rep='')
    if p.stat().st_size>=1_000_000:raise ValueError('FACTOR_NOT_STRICTLY_UNDER_1MB')
    receipt={'batch':'ACT-013','mode':'FULL' if (start,end)==(START,ASOF) else 'CANARY',
        'flags':old.FLAGS,'source':source,'range':[start,end],'read_range':[read_start,end],'counts':dict(counts),
        'rows':len(daily),'bytes':p.stat().st_size,'factor_sha256':old._sha_file(p),
        'code_sha256':old._sha_file(Path(__file__)),'calendar':calendar,'prefix_parity':'PASS',
        'projected_columns':mapping,'crosswalk_sha256':old._sha_file(old.CROSSWALK_FILE),
        'gate':'After D close: all three positive-comparable shares strictly > .50; UNKNOWN blocks new entries only',
        'turnover_units':'producer raw amount units, unchanged; absolute currency multiplier CANNOT_CONFIRM',
        'turnover_basis':'RAW_TURNOVER','ties_absolute_tolerance':1e-12,'fits_this_round':{'B':0,'S':0}}
    write_json(stage/'market_manifest.json',receipt);stage.rename(output_dir)
    return receipt


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['act005-root','data-root','output-dir']:p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--start',default=START);p.add_argument('--end',default=ASOF)
    try:r=market(**vars(p.parse_args(argv)))
    except Exception as e:print(json.dumps({'status':'FAILED','error':str(e)}),file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
