"""One pre-registered evaluation after immutable score and Top10 lock."""
import json,math
import numpy as np
import pandas as pd
from scipy.stats import pearsonr,spearmanr
import pyarrow.dataset as ds
import common as c
import train_score as t

ENTRY={20261027:20261028,20261028:20261029};EXIT={20261027:20261104,20261028:20261105}
DATES=[20261028,20261029,20261030,20261102,20261103,20261104,20261105]

def scalar(x):return None if x is None or not np.isfinite(x) else float(x)
def strictmean(x):return scalar(np.mean(x)) if len(x)>0 and np.isfinite(np.asarray(x,dtype=float)).all() else None

def prices(codes):
    filt=ds.field('ts_code').isin(sorted(codes))&(ds.field('trade_date')>=str(DATES[0]))&(ds.field('trade_date')<=str(DATES[-1]))
    d=ds.dataset(c.PANEL,format='parquet').to_table(columns=['ts_code','trade_date','market_type','open','high','low','close','volume'],filter=filt,use_threads=True).to_pandas()
    d['trade_date']=d.trade_date.astype(int);code=d.ts_code.astype(str);m=d.market_type.astype(str);a=code.str.fullmatch(r'\d{6}\.(SH|SZ)');bj=code.str.fullmatch(r'\d{6}\.BJ');keep=(a&m.eq('A_SHARE'))|(bj&m.eq('BJ'))
    if (~keep).any():raise ValueError('EVAL_MARKET_OR_CODE_CONFLICT')
    if d.duplicated(['ts_code','trade_date']).any():raise ValueError('EVAL_DUPLICATE_KEY')
    d['valid']=t.valid_price(d);return d

def overlay(scores,p):
    labels=scores[['ts_code','signal_date']].copy()
    for side,mapping in [('entry',ENTRY),('exit',EXIT)]:
        labels[side+'_date']=labels.signal_date.map(mapping)
        z=p[['ts_code','trade_date','open','volume','valid']].rename(columns={'trade_date':side+'_date','open':side+'_open','volume':side+'_volume','valid':side+'_valid'})
        labels=labels.merge(z,on=['ts_code',side+'_date'],how='left',validate='many_to_one')
    known=labels.entry_valid.fillna(False).to_numpy(dtype=np.bool_)&labels.exit_valid.fillna(False).to_numpy(dtype=np.bool_)
    labels['label_status']=np.where(known,'KNOWN','UNKNOWN_PRICE_OR_VOLUME');labels['ret_t5_pct']=np.nan
    labels.loc[known,'ret_t5_pct']=(labels.loc[known,'exit_open']/labels.loc[known,'entry_open']-1)*100
    return labels

def excursions(slot,p):
    lookup={(str(x.ts_code),int(x.trade_date)):x for x in p.itertuples()};r=[]
    for x in slot.itertuples():
        entry=ENTRY[int(x.signal_date)];exit=EXIT[int(x.signal_date)];dates=[d for d in DATES if entry<=d<exit];rows=[lookup.get((str(x.ts_code),d)) for d in dates];final=lookup.get((str(x.ts_code),exit))
        if any(q is None or not q.valid for q in rows) or final is None or not final.valid:
            r.append((np.nan,np.nan));continue
        start=float(rows[0].open);low=min([float(q.low) for q in rows]+[float(final.open)]);high=max([float(q.high) for q in rows]+[float(final.open)])
        r.append(((low/start-1)*100,(high/start-1)*100))
    return r

def portfolio(g,p,fee_bp):
    lookup={(str(x.ts_code),int(x.trade_date)):x for x in p.itertuples()};fee=fee_bp/10000/2;cash=1.;positions=[];marks=[{'date':'INITIAL','mark':'initial','nav':1.}]
    for day in DATES:
        # Exit first, with real open proceeds and exit fees.
        for q in list(positions):
            if q['exit']==day:
                row=lookup.get((q['code'],day))
                if row is None or not row.valid:return None,'MISSING_EXIT_OPEN'
                cash+=q['shares']*float(row.open)*(1-fee);positions.remove(q)
        new=g[g.signal_date.map(ENTRY).eq(day)]
        for date,batch in new.groupby('signal_date'):
            budget=.5/len(batch)/(1+fee)
            for row in batch.itertuples():
                q=lookup.get((str(row.ts_code),day))
                if q is None or not q.valid:return None,'MISSING_ENTRY_OPEN'
                cash-=budget*(1+fee);positions.append({'code':str(row.ts_code),'exit':EXIT[int(date)],'shares':budget/float(q.open)})
        if cash < -1e-9:return None,'CASH_NEGATIVE'
        openvalue=cash
        for q in positions:
            row=lookup.get((q['code'],day))
            if row is None or not row.valid:return None,'MISSING_HELD_OPEN'
            openvalue+=q['shares']*float(row.open)
        marks.append({'date':day,'mark':'open','nav':openvalue})
        closevalue=cash
        for q in positions:
            row=lookup.get((q['code'],day))
            if row is None or not row.valid:return None,'MISSING_HELD_CLOSE'
            closevalue+=q['shares']*float(row.close)
        marks.append({'date':day,'mark':'close','nav':closevalue})
    nav=np.asarray([q['nav'] for q in marks]);dd=nav/np.maximum.accumulate(nav)-1
    return {'fee_roundtrip_bp':fee_bp,'final_nav':float(nav[-1]),'max_drawdown_pct':float(dd.min()*100),'wealth_path':marks},None

def main():
    lock=json.loads((t.OUT/'SCORES_LOCK.json').read_text());verify=json.loads((t.OUT/'FRESH_PROCESS_PARITY.json').read_text())
    if verify['status']!='PASS':raise ValueError('FRESH_PROCESS_PASS_REQUIRED')
    for file,key in [('oos_scores_before_y.parquet','scores_sha256'),('selected_slots_before_y.parquet','selected_slots_sha256')]:
        if c.sha(t.OUT/file)!=lock[key]:raise ValueError('LOCK_CHANGED')
    # This is the first time test outcome prices are read in this experiment.
    x=pd.read_parquet(t.OUT/'oos_scores_before_y.parquet');s=pd.read_parquet(t.OUT/'selected_slots_before_y.parquet');p=prices(set(x.ts_code));lab=overlay(x,p)
    lab.to_parquet(t.OUT/'test_label_overlay.parquet',index=False,compression='zstd');merged=x.merge(lab,on=['ts_code','signal_date'],validate='one_to_one');sm=s.merge(lab,on=['ts_code','signal_date'],validate='many_to_one')
    ex=excursions(sm,p);sm['mae_pct']=[q[0] for q in ex];sm['mfe_pct']=[q[1] for q in ex];sm.to_parquet(t.OUT/'selected_with_outcomes.parquet',index=False,compression='zstd')
    days={};arms=['parent_original','uniform','personal']
    for date,g in merged.groupby('signal_date',sort=True):
        known=g.label_status.eq('KNOWN');ret=g.ret_t5_pct.to_numpy(float);pool_complete=bool(known.all());pool_mean=strictmean(ret)
        rec={'pool_total':len(g),'pool_known':int(known.sum()),'pool_unknown':int((~known).sum()),'pool_gross_mean_pct':pool_mean,'pool_known_only_mean_pct':scalar(g.loc[known,'ret_t5_pct'].mean()),'arms':{}}
        for arm in arms:
            z=sm[(sm.signal_date==date)&(sm.arm==arm)];k=z.label_status.eq('KNOWN');ys=z.ret_t5_pct.to_numpy(float);total=len(z);gross=strictmean(ys)
            score=g['score_'+arm].to_numpy(float);good=np.isfinite(score)&np.isfinite(ret);n=int(good.sum())
            ic=scalar(pearsonr(score[good],ret[good]).statistic) if n>=3 and np.std(score[good])>0 and np.std(ret[good])>0 else None
            ric=scalar(spearmanr(score[good],ret[good]).statistic) if n>=3 and np.std(score[good])>0 and np.std(ret[good])>0 else None
            positives=int((g.loc[known,'ret_t5_pct']>=5).sum());selectedpositive=int((z.loc[k,'ret_t5_pct']>=5).sum())
            rec['arms'][arm]={'selected':total,'selected_known':int(k.sum()),'selected_unknown':int((~k).sum()),'gross_top_pct':gross,'gross_known_only_diagnostic_pct':scalar(z.loc[k,'ret_t5_pct'].mean()),'net50_pct':None if gross is None else gross-.5,'net100_pct':None if gross is None else gross-1.,'top_minus_full_pool_pct':None if gross is None or pool_mean is None else gross-pool_mean,'hit_rate_full':None if gross is None else float((ys>0).mean()),'known_only_hit_rate':None if not k.any() else float((z.loc[k,'ret_t5_pct']>0).mean()),'recall_ge5_full':None if not pool_complete or not k.all() or positives==0 else selectedpositive/positives,'recall_ge5_known_diagnostic':None if positives==0 else selectedpositive/positives,'pool_ge5_known':positives,'selected_ge5_known':selectedpositive,'IC_known_diagnostic':ic,'RankIC_known_diagnostic':ric,'ic_known_count':n,'mae_known_count':int(z.mae_pct.notna().sum()),'mfe_known_count':int(z.mfe_pct.notna().sum()),'mae_mean_complete_pct':strictmean(z.mae_pct.to_numpy(float)),'mfe_mean_complete_pct':strictmean(z.mfe_pct.to_numpy(float))}
        u=rec['arms']['uniform']['gross_top_pct'];v=rec['arms']['personal']['gross_top_pct'];rec['personal_minus_uniform_top_pct']=None if u is None or v is None else v-u;days[str(date)]=rec
    portfolios={}
    for arm in arms:
        sub=sm[sm.arm.eq(arm)]
        portfolios[arm]={}
        for cost in [0,50,100]:
            result,err=portfolio(sub,p,cost);portfolios[arm][str(cost)]=result if result is not None else {'status':'UNAVAILABLE','reason':err}
    result={'status':'ONE_PASS_OOS_EVALUATED','robust_verdict':'INCONCLUSIVE_BY_DESIGN_TWO_TEST_SESSIONS','test_days':days,'portfolio_mark_to_market':portfolios,'limits':['Temporal holdout on current-asof QFQ panel; PIT=false','2 overlapping dates cannot establish robust efficacy, CI, or Sharpe','score uncalibrated; cost scenarios approximate transaction effects; no tradability certification','UNKNOWN selected slots never replaced','Recall/IC known-only diagnostics do not certify missing outcomes'],'selected_slots_sha256':lock['selected_slots_sha256'],'scores_sha256':lock['scores_sha256'],'label_overlay_sha256':c.sha(t.OUT/'test_label_overlay.parquet'),'selected_outcomes_sha256':c.sha(t.OUT/'selected_with_outcomes.parquet'),'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    t.writej(t.OUT/'OOS_EVALUATION.json',result);print(json.dumps({'stage':'OOS_COMPLETE','days':days,'verdict':result['robust_verdict']},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
