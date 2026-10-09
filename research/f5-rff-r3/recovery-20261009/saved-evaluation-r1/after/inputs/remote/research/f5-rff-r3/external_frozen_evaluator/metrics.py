"""Fixed-domain predictive metrics, not a P&L/backtest engine.
Unknown bounds are identification bounds, NOT confidence intervals.
AP is reported on known scored labels only; its denominator is explicit.
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score
from .settings import CONTRACT


def select_top3(frame):
    q=frame.loc[frame.scoreable.astype(bool)&np.isfinite(frame.probability)].copy()
    q=q.sort_values(['session_id','probability','code'],ascending=[True,False,True],kind='mergesort')
    q=q.groupby('session_id',sort=False,group_keys=False).head(3).copy()
    q['rank']=q.groupby('session_id',sort=False).cumcount()+1
    q['weight']='1/3';return q


def paired_precision(a,b,sessions):
    days=list(map(int,sessions));v=[]
    for day in days:
        ar=a.loc[a.session_id==day];br=b.loc[b.session_id==day]
        left=dict(zip(ar.code,ar.y));right=dict(zip(br.code,br.y));lo=hi=0.
        for code in set(left)|set(right):
            coeff=int(code in left)-int(code in right)
            if not coeff:continue # exactly the same one-seat weight; no approximation
            val=left.get(code,right.get(code,np.nan))
            if np.isfinite(val):lo+=coeff*val;hi+=coeff*val
            elif coeff>0:hi+=coeff
            else:lo+=coeff
        v.append({'session_id':day,'lower':lo/3,'upper':hi/3})
    return {'denominator':3*len(days),'lower':float(np.mean([r['lower'] for r in v])) if v else None,
            'upper':float(np.mean([r['upper'] for r in v])) if v else None,'daily':v}


def probability_metrics(frame):
    q=frame.loc[frame.scoreable.astype(bool)&np.isfinite(frame.probability)]
    p=q.probability.to_numpy(float);y=q.y.to_numpy(float);known=np.isfinite(y)
    pk=p[known];yk=y[known];n=len(y);u=n-int(known.sum())
    if np.any((p<0)|(p>1)):raise ValueError('probabilities outside [0,1]')
    eps=np.finfo(float).eps
    ll=-(yk*np.log(np.clip(pk,eps,1-eps))+(1-yk)*np.log(np.clip(1-pk,eps,1)))
    bs=(pk-yk)**2;pu=p[~known]
    bins=[];edges=CONTRACT['calibration_bins']
    for j,(a,b) in enumerate(zip(edges[:-1],edges[1:])):
        ix=(p>=a)&((p<=b) if j==len(edges)-2 else (p<b));kk=ix&known
        count=int(ix.sum());h=float(y[kk].sum());uk=int((ix&~known).sum())
        bins.append({'left':a,'right':b,'count':count,'known':int(kk.sum()),'unknown':uk,
            'mean_probability':float(p[ix].mean()) if count else None,
            'observed_rate_known':float(y[kk].mean()) if kk.any() else None,
            'event_rate_lower':h/count if count else None,'event_rate_upper':(h+uk)/count if count else None})
    return {'scored':n,'known':int(known.sum()),'unknown':u,'positive_known':int(yk.sum()),
        'average_precision_known':float(average_precision_score(yk,pk)) if len(np.unique(yk))==2 else None,
        'pr_auc_definition':'noninterpolated_average_precision_known_labels_only',
        'brier_known':float(bs.mean()) if len(bs) else None,
        'logloss_known':float(ll.mean()) if len(ll) else None,
        'logloss_all_lower':float((ll.sum()+np.minimum(-np.log(np.clip(pu,eps,1-eps)),-np.log(np.clip(1-pu,eps,1))).sum())/n) if n else None,
        'logloss_all_upper':float((ll.sum()+np.maximum(-np.log(np.clip(pu,eps,1-eps)),-np.log(np.clip(1-pu,eps,1))).sum())/n) if n else None,
        'brier_all_lower':float((bs.sum()+np.minimum(pu**2,(1-pu)**2).sum())/n) if n else None,
        'brier_all_upper':float((bs.sum()+np.maximum(pu**2,(1-pu)**2).sum())/n) if n else None,
        'calibration_bins':bins,'probabilities_calibrated_claim':False}


def arm_metrics(frame,selected,calendar):
    days=list(calendar.session_id.astype(int));daily=[]
    for day in days:
        f=frame.loc[frame.session_id==day];s=selected.loc[selected.session_id==day]
        eligible=f.loc[f.scoreable.astype(bool)];k=np.isfinite(s.y);hits=int(s.loc[k,'y'].sum());u=int((~k).sum())
        ek=np.isfinite(eligible.y);h=int(eligible.loc[ek,'y'].sum());eu=int((~ek).sum());m=len(eligible)
        daily.append({'session_id':day,'market_date':str(calendar.loc[calendar.session_id==day,'market_date'].iloc[0]),
          'candidate_rows':len(f),'scoreable':m,'selected':len(s),'empty_slots':3-len(s),'hits':hits,'unknown_selected':u,
          'precision_lower':hits/3,'precision_upper':(hits+u)/3,
          'random_lower':h/m if m else np.nan,'random_upper':(h+eu)/m if m else np.nan})
    d=pd.DataFrame(daily);den=3*len(d);h=int(d.hits.sum());u=int(d.unknown_selected.sum())
    random_complete=np.isfinite(d.random_lower).all()
    rl=float(d.random_lower.mean()) if random_complete else None
    ru=float(d.random_upper.mean()) if random_complete else None
    # Confirmed NEW events, and the subset with a potential scoreable alarm in the evaluation grid.
    lo=min(days);hi=max(days);events=frame.loc[(frame.episode_state=='NEW')&frame.session_id.between(lo,hi)]
    hit_events=set();leads={};alert_hits=0
    for r in selected.itertuples():
        if np.isfinite(r.y) and r.y==1 and r.first_exact>=0:
            key=(str(r.code),int(r.first_exact));hit_events.add(key);alert_hits+=1
            leads.setdefault(key,[]).append(int(r.first_exact-r.session_id))
    event_keys=set(zip(events.code.astype(str),events.session_id.astype(int)))
    hit_events &= event_keys
    coverable=set()
    for code,t in event_keys:
        if frame.loc[(frame.code==code)&frame.session_id.between(t-5,t-1),'scoreable'].astype(bool).any():coverable.add((code,t))
    # Year-boundary outcomes outside this cohort remain separately logged; no forced matching.
    valid_hits=sum(len(leads[k]) for k in hit_events)
    known_sel=selected.loc[np.isfinite(selected.y)]
    repeats=0;prev=set()
    for day in days:
        now=set(selected.loc[selected.session_id==day,'code']);repeats+=len(now&prev);prev=now
    return {'dates':len(d),'slots':den,'hits_known':h,'unknown_selected':u,'empty_slots':int(d.empty_slots.sum()),
      'precision_lower':h/den if den else None,'precision_upper':(h+u)/den if den else None,
      'random_precision_lower':rl,'random_precision_upper':ru,
      'random_lift_lower':(h/den)/ru if ru and den else None,
      'false_alerts_known':int((known_sel.y==0).sum()),
      'false_alert_fraction_lower':int((known_sel.y==0).sum())/len(selected) if len(selected) else None,
      'false_alert_fraction_upper':(int((known_sel.y==0).sum())+u)/len(selected) if len(selected) else None,
      'false_positive_rate_known_opportunities':int((known_sel.y==0).sum())/int(((frame.y==0)&frame.scoreable.astype(bool)).sum()) if ((frame.y==0)&frame.scoreable.astype(bool)).any() else None,
      'unknown_newness_trigger_events':int((frame.episode_state=='UNKNOWN_NEWNESS').sum()),
      'confirmed_new_events':len(event_keys),'coverable_new_events':len(coverable),'hit_unique_episodes':len(hit_events),
      'episode_coverage_confirmed':len(hit_events)/len(event_keys) if event_keys else None,
      'episode_coverage_coverable':len(hit_events&coverable)/len(coverable) if coverable else None,
      'repeated_alerts_same_episode':valid_hits-len(hit_events),
      'consecutive_daily_repeated_names':repeats,
      'first_alarm_lead_sessions':[max(leads[k]) for k in sorted(hit_events)],
      'positive_alerts_first_time_ambiguous':int(((selected.y==1)&(selected.first_exact<0)).sum()),
      'probability':probability_metrics(frame),'daily':daily,
      'not_a_strategy_return':True,'domain':'FIXED_RESEARCH_PROXY_AT_RISK'}


def block_interval(daily,calendar):
    # Resample full market-date blocks, never compact away unknown dates.
    # Every draw is applied to both identification endpoints.
    a=pd.DataFrame(daily).merge(calendar[['session_id','year']],on='session_id',validate='one_to_one')
    block=CONTRACT['bootstrap']['block_sessions'];reps=CONTRACT['bootstrap']['replicates']
    rng=np.random.default_rng(CONTRACT['bootstrap']['seed'])
    groups=[g for _,g in a.groupby('year',sort=True)]
    if any(len(g)<block or not np.all(np.diff(g.session_id)==1) for g in groups):
        return {'status':'INSUFFICIENT_CONTIGUOUS_YEAR_BLOCKS','replications':0}
    out=np.zeros((reps,2));count=sum(len(g) for g in groups)
    for g in groups:
        arr=g[['lower','upper']].to_numpy();n=len(g);chunks=math.ceil(n/block)
        starts=rng.integers(0,n-block+1,size=(reps,chunks))
        ix=(starts[:,:,None]+np.arange(block)).reshape(reps,-1)[:,:n]
        out+=arr[ix].sum(1)
    out/=count
    return {'status':'DESCRIPTIVE_EXPOSED_HISTORY','block_sessions':block,'replications':reps,
      'lower_endpoint_interval':np.quantile(out[:,0],[.025,.975]).tolist(),
      'upper_endpoint_interval':np.quantile(out[:,1],[.025,.975]).tolist(),
      'independent_stock_days_claim':False}
