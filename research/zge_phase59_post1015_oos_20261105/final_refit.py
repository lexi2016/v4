"""Post-evaluation final refit and late-date features. Not independently OOS."""
import argparse,concurrent.futures,json,os,sys,time
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
from threadpoolctl import threadpool_limits
import common as c
import project
import train_score as t
from feature_logic import create_stock

RUN=t.OUT;DEST=c.ROOT/'final_refit';DEST.mkdir(exist_ok=True)
SESSIONS=[20261016,20261019,20261020,20261021,20261022,20261023,20261026,20261027,20261028,20261029,20261030,20261102,20261103,20261104,20261105]
LATE_CHECKPOINT_SHA='4134e712032a31c31dbdebe554df3b3728186d6a9781a37c83e98d7a82728d42'

def dump(name,obj):t.writej(DEST/name,obj)
def late_rows():
    filt=(ds.field('trade_date')>'20261028')&(ds.field('trade_date')<='20261105')
    d=ds.dataset(c.PANEL,format='parquet').to_table(columns=c.COLUMNS,filter=filt,use_threads=True).to_pandas();d['trade_date']=d.trade_date.astype(int)
    code=d.ts_code.fillna('').astype(str);m=d.market_type.fillna('').astype(str);a=code.str.fullmatch(r'\d{6}\.(SH|SZ)');bj=code.str.fullmatch(r'\d{6}\.BJ')
    bad=(m.eq('A_SHARE')&~a)|(m.eq('BJ')&~bj)
    if bad.any():raise ValueError('MARKET_CODE_CONFLICT')
    keep=((a&m.eq('A_SHARE'))|(bj&m.eq('BJ')))&~code.isin(c.EXCLUDED)
    out=d[keep].copy()
    if out.duplicated(['ts_code','trade_date']).any():raise ValueError('LATE_DUPLICATE_KEY')
    return out,{'late_physical_rows':len(d),'late_valid_rows_after_basis_exclusion':len(out),'late_excluded_basis_rows':int((code.isin(c.EXCLUDED)).sum())}

def worker(arg):
    tc,g,profile,complete=arg
    return create_stock(g,profile,complete)

def trailing():
    """Use only the last 350 bars of persisted same-generation prefix per stock."""
    p=pd.read_parquet(RUN/'raw_prefix_20240101_20261028.parquet');p=p.sort_values(['ts_code','trade_date']);p=p.groupby('ts_code',sort=False).tail(350)
    return p

def canary():
    c.bindings();codes=['600028.SH','000001.SZ','920006.BJ'];p=trailing();old=pd.read_parquet(RUN/'features_pre_oos.parquet');profiles=project.profilemap();complete=project.complete_history_codes();checks=[]
    for tc in codes:
        x=worker((tc,p[p.ts_code.eq(tc)],profiles.get(tc),tc in complete));a=x[x.signal_date.eq(20261028)].reset_index(drop=True);b=old[(old.ts_code.eq(tc))&(old.signal_date.eq(20261028))].reset_index(drop=True)
        cols=['ts_code','signal_date','pool_status','p52_type','risk','event_group','anchor_date','anchor_key','anchor_wave','bars_since_anchor','q35_count']+c.FEATURES
        if len(a)!=1 or len(b)!=1:raise ValueError('TAIL_CANARY_KEY_MISSING:'+tc)
        # All scalar Arrow and in-memory null representations are equivalent;
        # observed numeric values still have an absolute 1e-12 equality check.
        for col in cols:
            av,bv=a[col].iloc[0],b[col].iloc[0]
            if pd.isna(av) and pd.isna(bv):continue
            if pd.isna(av) or pd.isna(bv):raise ValueError('TAIL_CANARY_NULL_MISMATCH:'+tc+':'+col)
            if isinstance(av,(int,float,np.integer,np.floating)) and isinstance(bv,(int,float,np.integer,np.floating)):
                if not np.isclose(av,bv,rtol=0,atol=1e-12):raise ValueError('TAIL_CANARY_NUMERIC_MISMATCH:'+tc+':'+col)
            elif av!=bv:raise ValueError('TAIL_CANARY_VALUE_MISMATCH:'+tc+':'+col)
        checks.append({'stock':tc,'prefix_window_rows':len(p[p.ts_code.eq(tc)]),'event_and_87_fields_match':'PASS'})
    report={'status':'PASS','cases':checks,'method':'same persisted prefix, 350 prior rows per stock; P52 250-reference warmup and 15-bar anchor dependency preserved','tail_outcomes_opened':False}
    dump('TAIL_CANARY.json',report);print(json.dumps(report,ensure_ascii=False),flush=True)

def full():
    start=time.time();assert json.loads((DEST/'TAIL_CANARY.json').read_text())['status']=='PASS';c.bindings()
    cached=DEST/'new_dates_ohlcv_features_source.parquet'
    if c.sha(cached)!=LATE_CHECKPOINT_SHA:raise ValueError('LATE_SOURCE_CHECKPOINT_CHANGED')
    late=pd.read_parquet(cached);coverage={'late_source_checkpoint_rows':len(late),'late_physical_rows':'NOT_RECORDED_ON_PRIOR_READ','retained_basis_excluded_before_checkpoint':True}
    pre=trailing();joined=pd.concat([pre,late],ignore_index=True);del pre
    if joined.duplicated(['ts_code','trade_date']).any():raise ValueError('PREFIX_TAIL_DUPLICATE')
    profiles=project.profilemap();complete=project.complete_history_codes();groups=list(joined.groupby('ts_code',sort=True));del joined
    ck=DEST/'feature_checkpoints';ck.mkdir(exist_ok=True);finished=set()
    for receipt in sorted(ck.glob('batch_*.json')):
        meta=json.loads(receipt.read_text());data=ck/meta['data']
        if c.sha(data)!=meta['sha256'] or meta['late_source_sha256']!=LATE_CHECKPOINT_SHA:raise ValueError('FEATURE_CHECKPOINT_CHANGED')
        if finished.intersection(meta['codes']):raise ValueError('CHECKPOINT_DUPLICATE_STOCK')
        finished.update(meta['codes'])
    pending_groups=[(tc,g) for tc,g in groups if tc not in finished];batch_no=len(list(ck.glob('batch_*.json')));batch=[];batch_codes=[]
    def checkpoint():
        nonlocal batch_no,batch,batch_codes
        if not batch_codes:return
        batch_no+=1;name=f'batch_{batch_no:04d}.parquet';path=ck/name
        frame=pd.concat(batch,ignore_index=True) if batch else pd.DataFrame({'ts_code':pd.Series(dtype='str'),'signal_date':pd.Series(dtype='int64')})
        frame.to_parquet(path,index=False,compression='zstd')
        meta={'data':name,'sha256':c.sha(path),'late_source_sha256':LATE_CHECKPOINT_SHA,'codes':batch_codes}
        t.writej(ck/f'batch_{batch_no:04d}.json',meta);batch=[];batch_codes=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=12) as pool:
        pending={};it=iter(pending_groups)
        def submit():
            try:tc,g=next(it)
            except StopIteration:return False
            pending[pool.submit(worker,(tc,g,profiles.get(tc),tc in complete))]=tc;return True
        for _ in range(28):
            if not submit():break
        done_count=len(finished)
        while pending:
            done,_=concurrent.futures.wait(pending,return_when=concurrent.futures.FIRST_COMPLETED)
            for f in done:
                tc=pending.pop(f);x=f.result()
                if not x.empty:
                    y=x[x.signal_date.gt(20261028)]
                    if not y.empty:batch.append(y)
                batch_codes.append(tc);done_count+=1
                if len(batch_codes)>=250:checkpoint()
                submit()
            if done_count and done_count%1000==0:print(json.dumps({'stage':'LATE_FEATURES','stocks':done_count,'elapsed':round(time.time()-start,1)}),flush=True)
    checkpoint()
    x=pd.concat([pd.read_parquet(p) for p in sorted(ck.glob('batch_*.parquet'))],ignore_index=True).sort_values(['signal_date','ts_code']);x['label_status']='UNMATURED_EXIT_AFTER_20261105';x.to_parquet(DEST/'late_unmatured_features.parquet',index=False,compression='zstd')
    feat={str(d):{'rows':len(g),'pool_status':g.pool_status.value_counts().to_dict(),'feature_observed':{k:int(g[k].notna().sum()) for k in c.FEATURES}} for d,g in x.groupby('signal_date')}
    report={'status':'PASS','date_scope':'20261029..20261105, all target and non-target source rows, outcomes UNMATURED','counts':coverage,'stocks':len(groups),'rows':len(x),'by_date':feat,'late_ohlcv_sha256':c.sha(DEST/'new_dates_ohlcv_features_source.parquet'),'late_features_sha256':c.sha(DEST/'late_unmatured_features.parquet'),'wall_seconds':time.time()-start,'basis':'same 11/05 panel generation; prior stock tail from existing checkpoint; no full panel history rescan'}
    dump('LATE_FEATURE_RECEIPT.json',report);print(json.dumps({'stage':'LATE_FEATURES_SAVED','rows':len(x),'by_date':{k:v['pool_status'] for k,v in feat.items()},'wall_seconds':report['wall_seconds']},ensure_ascii=False),flush=True)

def label_new():
    x=pd.read_parquet(RUN/'features_pre_oos.parquet');x=x[(x.signal_date>c.TRAIN)&(x.signal_date<=c.X_END)&x.pool_status.eq('TARGET')].copy()
    p=pd.read_parquet(RUN/'raw_prefix_20240101_20261028.parquet',columns=['ts_code','trade_date','open','high','low','close','volume']);p=p[p.trade_date>=20261019]
    late=pd.read_parquet(DEST/'new_dates_ohlcv_features_source.parquet',columns=['ts_code','trade_date','open','high','low','close','volume']);p=pd.concat([p,late],ignore_index=True);p['valid']=t.valid_price(p)
    dmap={d:(SESSIONS[i+1],SESSIONS[i+6]) for i,d in enumerate(SESSIONS) if i+6<len(SESSIONS)}
    labels=x[['ts_code','signal_date','event_group']].copy();labels['entry_date']=labels.signal_date.map(lambda x:dmap[x][0]);labels['exit_date']=labels.signal_date.map(lambda x:dmap[x][1]);assert labels.exit_date.le(c.ASOF).all()
    for side in ['entry','exit']:
        k=p[['ts_code','trade_date','open','volume','valid']].rename(columns={'trade_date':side+'_date','open':side+'_open','volume':side+'_volume','valid':side+'_valid'})
        labels=labels.merge(k,on=['ts_code',side+'_date'],how='left',validate='many_to_one')
    good=labels.entry_valid.fillna(False).to_numpy(dtype=np.bool_)&labels.exit_valid.fillna(False).to_numpy(dtype=np.bool_);labels['label_status']=np.where(good,'KNOWN','UNKNOWN_PRICE_OR_VOLUME');labels['ret_t5_pct']=np.nan;labels.loc[good,'ret_t5_pct']=(labels.loc[good,'exit_open']/labels.loc[good,'entry_open']-1)*100
    if labels.duplicated(['ts_code','signal_date']).any():raise ValueError('FINAL_DUPLICATE')
    labels.to_parquet(DEST/'new_matured_label_overlay.parquet',index=False,compression='zstd');return x,labels

def fit():
    c.bindings();t.rt.install_compat();lock=json.loads((RUN/'SCORES_LOCK.json').read_text());model=t.rt.load(RUN/'oos_continued_model.pkl',lock['model_sha256']);x,labels=label_new()
    fit=x.merge(labels[['ts_code','signal_date','exit_date','label_status','ret_t5_pct']],on=['ts_code','signal_date'],validate='one_to_one');fit=fit[fit.label_status.eq('KNOWN')].copy().reset_index(drop=True)
    y=(fit.groupby('signal_date').ret_t5_pct.rank(pct=True)-.5).to_numpy(float);fit['hard_rank_target']=y
    if len(fit)<10 or (fit.exit_date>c.ASOF).any() or fit.signal_date.le(c.TRAIN).any():raise ValueError('FINAL_MATURITY_OR_DUPLICATE_INVALID')
    fit.to_parquet(DEST/'fit_rows.parquet',index=False,compression='zstd');print(json.dumps({'stage':'FINAL_TRAIN_COHORT','fit_rows':len(fit),'stocks':int(fit.ts_code.nunique()),'by_date':fit.signal_date.value_counts().sort_index().to_dict(),'test_period_absorbed':True},ensure_ascii=False),flush=True)
    before={'ridge':model.ridge_.coef_.copy(),'rff':model.rff_.coef_.copy(),'trees':len(model.gbdt_.trees_),'med':model.prep_.medians_.copy(),'mean':model.prep_.means_.copy(),'std':model.prep_.stds_.copy()}
    with threadpool_limits(limits=1):
        xx=model.prep_.transform(fit);model.ridge_.continue_fit(xx,y,lr=.004,epochs=6);model.rff_.continue_fit(xx,y,lr=.004,epochs=4);model.gbdt_.continue_fit(xx,y,n_extra_trees=10,sample_weight=np.ones(len(y)))
    delta={'ridge_l2':float(np.linalg.norm(model.ridge_.coef_-before['ridge'])),'rff_l2':float(np.linalg.norm(model.rff_.coef_-before['rff'])),'trees_before':before['trees'],'trees_after':len(model.gbdt_.trees_),'preprocessor_frozen':bool(np.array_equal(model.prep_.medians_,before['med']) and np.array_equal(model.prep_.means_,before['mean']) and np.array_equal(model.prep_.stds_,before['std']))}
    if delta['ridge_l2']<=0 or delta['rff_l2']<=0 or delta['trees_after']!=delta['trees_before']+10 or not delta['preprocessor_frozen']:raise ValueError('FINAL_WEIGHT_UPDATE_INVALID')
    z,obs=t.structural(model,fit);old_uni=json.loads((RUN/'uniform_posterior.json').read_text());ua,ub,ulam,utau=t.posterior_update(old_uni['alpha'],np.asarray(old_uni['beta']),z,y,model.tau_intercept,model.tau_slope,1.)
    changes=[]
    for tc,idx in fit.groupby('ts_code',sort=True).indices.items():
        obj=model.stock_posteriors_.get(str(tc))
        if obj is None:continue
        oa=float(obj['alpha_post']);ob=np.asarray(obj['beta_post'],dtype=float).copy();bars=int(obj.get('total_bars',0));low=.25 if bars<60 else (.60 if len(idx)<6 else 1.);na,nb,lam,tau=t.posterior_update(oa,ob,z[idx],y[idx],model.tau_intercept,model.tau_slope,low)
        obj['alpha_post']=na;obj['beta_post']=nb;obj['dominant_tactics']=model._classify_dominant_tactic(nb)
        q={'ts_code':str(tc),'fit_rows':len(idx),'alpha_before':oa,'alpha_after':na,'low_multiplier':low,'lambda':lam,'tau':tau}
        for j in range(12):q[f'beta{j:02d}_before']=float(ob[j]);q[f'beta{j:02d}_after']=float(nb[j]);q[f'z{j:02d}_observed_rows']=int(obs[idx,j].sum())
        changes.append(q)
    model._build_fast_lookup_tables();pd.DataFrame(changes).to_parquet(DEST/'posterior_changes.parquet',index=False,compression='zstd');dump('uniform_posterior.json',{'alpha':ua,'beta':ub.tolist(),'prior_alpha':old_uni['alpha'],'prior_beta':old_uni['beta'],'lambda':ulam,'tau':utau,'observed_rows_by_dimension':obs.sum(axis=0).tolist()})
    modelpath=DEST/'final_refit_model.pkl';t.save(model,modelpath)
    late=pd.read_parquet(DEST/'late_unmatured_features.parquet');eligible=late[late.pool_status.eq('TARGET')].copy().reset_index(drop=True)
    if len(eligible):
        with threadpool_limits(limits=1):base,z2,ob2,alpha,beta,ps,us,src=t.score_parts(model,eligible,(ua,ub))
        eligible['backbone_score']=base;eligible['score_personal']=ps;eligible['score_uniform']=us;eligible['posterior_source']=src;eligible['personal_alpha']=alpha;eligible['personal_effect']=(z2*beta).sum(axis=1)
        for j in range(12):eligible[f'z{j:02d}_observed']=ob2[:,j]
    eligible.to_parquet(DEST/'unmatured_target_scores.parquet',index=False,compression='zstd')
    result={'status':'FINAL_REFIT_SAVED_TEST_PERIOD_CONSUMED_NOT_NEW_OOS_VALIDATED','parent_oos_model_sha256':lock['model_sha256'],'model_sha256':c.sha(modelpath),'fit_rows':len(fit),'fit_stocks':int(fit.ts_code.nunique()),'target_rows_before_maturity_check':len(labels),'unknown_maturity_or_price':int(labels.label_status.ne('KNOWN').sum()),'fit_dates':{str(k):int(v) for k,v in fit.signal_date.value_counts().sort_index().items()},'fit_exit_max':int(fit.exit_date.max()),'updated_stocks':len(changes),'parameter_delta':delta,'late_target_scores':len(eligible),'late_scored_by_date':{str(k):int(v) for k,v in eligible.signal_date.value_counts().sort_index().items()},'source_features_sha256':c.sha(DEST/'late_unmatured_features.parquet'),'matured_overlay_sha256':c.sha(DEST/'new_matured_label_overlay.parquet'),'fit_rows_sha256':c.sha(DEST/'fit_rows.parquet'),'scores_sha256':c.sha(DEST/'unmatured_target_scores.parquet'),'posterior_sha256':c.sha(DEST/'posterior_changes.parquet'),'pit_certified':False,'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    dump('FINAL_FIT_RECEIPT.json',result);print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['canary','project','fit']);a=p.parse_args();{'canary':canary,'project':full,'fit':fit}[a.stage]()
