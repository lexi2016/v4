"""Fit only matured train labels, then lock pre-label test scores and slots."""
import json,os,pickle,resource,sys,time
from pathlib import Path
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
import common as c

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'zge_phase59_mac_continue_20261105'))
import runtime as rt
OUT=c.ROOT/'run'
DEPS=[['kb_personal_vol_quantile_z'],['J','kb_personal_j_quantile_z'],['kb_white_yellow_bowl_score'],['digested_big_green_rebuild_flag'],['undigested_big_green_veto_flag'],['day1_high_j_pullback_flag'],['jcb_accumulation_intensity'],['tactic_pb1_shallow_white_score'],['tactic_pb2_yellow_bowl_b1_score'],['tactic_pb3_keyk_low_spring_score'],['tactic_b2_yang_confirm_score'],['mkt_ew_ret_5d','p53_jcb_rs_5d_excess']]

def writej(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def save(m,p):
    with p.open('xb') as f:pickle.dump(m,f,protocol=4);f.flush();os.fsync(f.fileno())

def valid_price(x):
    o,h,l,cl,v=(pd.to_numeric(x[z],errors='coerce').to_numpy(float) for z in ('open','high','low','close','volume'))
    return np.isfinite(o)&np.isfinite(h)&np.isfinite(l)&np.isfinite(cl)&np.isfinite(v)&(o>0)&(h>0)&(l>0)&(cl>0)&(v>0)&(h+1e-7>=l)&(h+1e-7>=o)&(h+1e-7>=cl)&(l<=o+1e-7)&(l<=cl+1e-7)

def train_labels(x,prices):
    left=x[x.signal_date.eq(c.TRAIN)&x.pool_status.eq('TARGET')].copy();out=left[['ts_code','signal_date','event_group']].copy()
    assert c.TRAIN_END<min(c.TEST)
    for date,prefix in [(20261019,'entry'),(20261026,'exit')]:
        p=prices[prices.trade_date.eq(date)].copy();p[prefix+'_valid']=valid_price(p)
        p=p[['ts_code','open','volume',prefix+'_valid']].rename(columns={'open':prefix+'_open','volume':prefix+'_volume'})
        out=out.merge(p,on='ts_code',how='left',validate='one_to_one')
    ok=out.entry_valid.fillna(False).to_numpy(dtype=np.bool_)&out.exit_valid.fillna(False).to_numpy(dtype=np.bool_)
    out['label_status']=np.where(ok,'KNOWN','UNKNOWN_PRICE_OR_VOLUME');out['ret_t5_pct']=np.nan
    out.loc[ok,'ret_t5_pct']=(out.loc[ok,'exit_open']/out.loc[ok,'entry_open']-1)*100
    out['label_end']=c.TRAIN_END;return left,out

def structural(model,df):
    z=model.build_structural_design_matrix_12d(df).astype(float);obs=np.ones((len(df),12),dtype=np.bool_)
    for i,deps in enumerate(DEPS):
        for name in deps:
            a=pd.to_numeric(df[name],errors='coerce').to_numpy(float) if name in df else np.full(len(df),np.nan)
            obs[:,i]&=np.isfinite(a)
    z[~obs]=0.0
    if not np.isfinite(z).all():raise ValueError('NONFINITE_OBSERVED_STRUCTURAL_X')
    return z,obs

def posterior_update(old_a,old_b,z,y,taui,taus,low):
    n=len(y);lam=n/(n+taui)*low;a=float(np.clip(lam*float(np.mean(y))+(1-lam)*old_a,-.025,.025));tau=taus/max(.15,low)
    b=np.linalg.solve(z.T@z+tau*np.eye(12),z.T@(y-a)+tau*old_b)
    b[3]=np.clip(b[3],.002,.032);b[4]=np.clip(b[4],-.048,-.010);b[5]=np.clip(b[5],-.038,-.006);b=np.clip(b,-.048,.038)
    # A dimension with no observed source is unchanged, not an imputed observation.
    b[~(np.any(z!=0,axis=0))]=old_b[~(np.any(z!=0,axis=0))]
    return a,b,float(lam),float(tau)

def score_parts(model,df,uniform):
    z,obs=structural(model,df);base=model.predict_backbone(df);aa=[];bb=[];source=[]
    for tc in df.ts_code.astype(str):
        o=model.stock_posteriors_.get(tc)
        if o is None:aa.append(uniform[0]);bb.append(uniform[1]);source.append('UNIFORM_NO_STOCK_PRIOR')
        else:aa.append(float(o['alpha_post']));bb.append(np.asarray(o['beta_post'],dtype=float));source.append('STOCK_POSTERIOR')
    a=np.asarray(aa);b=np.asarray(bb);score=base+model.adaptive_scale*(a+(z*b).sum(axis=1))
    uniscore=base+model.adaptive_scale*(uniform[0]+z@uniform[1])
    if not (np.isfinite(score).all() and np.isfinite(uniscore).all()):raise ValueError('PREDICT_NONFINITE')
    return base,z,obs,a,b,score,uniscore,source

def main():
    start=time.time();c.bindings();rt.install_compat();parent=rt.load(c.PARENT,c.PARENT_SHA);original=rt.load(c.PARENT,c.PARENT_SHA)
    if abs(parent.adaptive_scale-.42)>1e-12:raise ValueError('SCALE_CHANGED')
    x=pd.read_parquet(OUT/'features_pre_oos.parquet');prices=pd.read_parquet(OUT/'raw_prefix_20240101_20261028.parquet');prices=prices[prices.trade_date.isin([20261019,20261026])]
    tr,labels=train_labels(x,prices);labels.to_parquet(OUT/'train_labels.parquet',index=False,compression='zstd')
    fit=tr.merge(labels[['ts_code','signal_date','label_status','ret_t5_pct','label_end']],on=['ts_code','signal_date'],validate='one_to_one');fit=fit[fit.label_status.eq('KNOWN')].reset_index(drop=True)
    if len(fit)<10:raise ValueError('TOO_FEW_MATURE_TRAIN_TARGETS '+str(len(fit)))
    y=(fit.ret_t5_pct.rank(pct=True)-.5).to_numpy(float);fit['hard_rank_target']=y
    fit.to_parquet(OUT/'train_fit_rows.parquet',index=False,compression='zstd')
    print(json.dumps({'stage':'TRAIN_COHORT','target_rows':len(tr),'known_matured_rows':len(fit),'stocks':fit.ts_code.nunique(),'exit':c.TRAIN_END},ensure_ascii=False),flush=True)
    before={'ridge':parent.ridge_.coef_.copy(),'rff':parent.rff_.coef_.copy(),'trees':len(parent.gbdt_.trees_),'med':parent.prep_.medians_.copy(),'mean':parent.prep_.means_.copy(),'std':parent.prep_.stds_.copy()}
    with threadpool_limits(limits=1):
        xx=parent.prep_.transform(fit);parent.ridge_.continue_fit(xx,y,lr=.004,epochs=6);parent.rff_.continue_fit(xx,y,lr=.004,epochs=4);parent.gbdt_.continue_fit(xx,y,n_extra_trees=10,sample_weight=np.ones(len(y)))
    delta={'ridge_l2':float(np.linalg.norm(parent.ridge_.coef_-before['ridge'])),'rff_l2':float(np.linalg.norm(parent.rff_.coef_-before['rff'])),'trees_before':before['trees'],'trees_after':len(parent.gbdt_.trees_),'preprocessor_frozen':bool(np.array_equal(parent.prep_.medians_,before['med']) and np.array_equal(parent.prep_.means_,before['mean']) and np.array_equal(parent.prep_.stds_,before['std']))}
    if delta['ridge_l2']<=0 or delta['rff_l2']<=0 or delta['trees_after']!=delta['trees_before']+10 or not delta['preprocessor_frozen']:raise ValueError('FIT_DID_NOT_UPDATE_AS_REQUIRED')
    z,obs=structural(parent,fit);u0=float(parent.global_prior_intercept_);ub=np.asarray(parent.global_prior_slopes_,dtype=float).copy();ua,ubn,ulam,utau=posterior_update(u0,ub,z,y,parent.tau_intercept,parent.tau_slope,1.)
    updates=[]
    for tc,idx in fit.groupby('ts_code',sort=True).indices.items():
        obj=parent.stock_posteriors_.get(str(tc))
        if obj is None:continue
        oa=float(obj['alpha_post']);ob=np.asarray(obj['beta_post'],dtype=float).copy();bars=int(obj.get('total_bars',0));low=.25 if bars<60 else (.60 if len(idx)<6 else 1.)
        na,nb,lam,tau=posterior_update(oa,ob,z[idx],y[idx],parent.tau_intercept,parent.tau_slope,low)
        obj['alpha_post']=na;obj['beta_post']=nb;obj['dominant_tactics']=parent._classify_dominant_tactic(nb)
        row={'ts_code':str(tc),'n':len(idx),'prior_bars':bars,'low_sample_multiplier':low,'lambda':lam,'tau':tau,'alpha_before':oa,'alpha_after':na}
        for j in range(12):row[f'beta{j:02d}_before']=float(ob[j]);row[f'beta{j:02d}_after']=float(nb[j]);row[f'z{j:02d}_observed_rows']=int(obs[idx,j].sum())
        updates.append(row)
    parent._build_fast_lookup_tables();upd=pd.DataFrame(updates);upd.to_parquet(OUT/'posterior_changes.parquet',index=False,compression='zstd')
    uniform=(ua,ubn);writej(OUT/'uniform_posterior.json',{'alpha':ua,'beta':ubn.tolist(),'alpha_prior':u0,'beta_prior':ub.tolist(),'lambda':ulam,'tau':utau,'train_count':len(fit),'observed_rows_by_dimension':obs.sum(axis=0).tolist()})
    modelpath=OUT/'oos_continued_model.pkl';save(parent,modelpath)
    groupids=set(fit.event_group.dropna());test=x[x.signal_date.isin(c.TEST)&x.pool_status.eq('TARGET')].copy();test['same_train_event_group']=test.event_group.isin(groupids)
    exclusions={str(d):{'target_pool_before_exclusion':len(g),'same_train_event_group':int(g.same_train_event_group.sum()),'remaining':int((~g.same_train_event_group).sum())} for d,g in test.groupby('signal_date')}
    test=test[~test.same_train_event_group].reset_index(drop=True)
    if test.empty:raise ValueError('NO_ELIGIBLE_HOLDOUT_POOL')
    with threadpool_limits(limits=1):
        base,z,ob,alpha,beta,pers,uni,which=score_parts(parent,test,uniform);parent_score=original.predict(test)
    test['backbone_score']=base;test['personal_alpha']=alpha;test['personal_effect']=(z*beta).sum(axis=1);test['posterior_source']=which
    test['score_parent_original']=parent_score;test['score_uniform']=uni;test['score_personal']=pers
    for j in range(12):test[f'z{j:02d}_observed']=ob[:,j];test[f'z{j:02d}']=z[:,j];test[f'beta{j:02d}']=beta[:,j]
    test.to_parquet(OUT/'oos_scores_before_y.parquet',index=False,compression='zstd')
    slots=[]
    for d,g in test.groupby('signal_date',sort=True):
        for arm in ['parent_original','uniform','personal']:
            ranked=g.sort_values(['score_'+arm,'ts_code'],ascending=[False,True],kind='stable').head(10)
            for rank,(_,row) in enumerate(ranked.iterrows(),1):slots.append({'signal_date':int(d),'arm':arm,'rank':rank,'ts_code':row.ts_code,'event_group':row.event_group,'score':float(row['score_'+arm])})
    slots=pd.DataFrame(slots);slots.to_parquet(OUT/'selected_slots_before_y.parquet',index=False,compression='zstd')
    report={'status':'FITTED_AND_SCORES_LOCKED_BEFORE_TEST_Y','train_target_rows':len(tr),'train_known_rows':len(fit),'train_unknown_rows':len(tr)-len(fit),'train_stocks':int(fit.ts_code.nunique()),'posterior_updated_stocks':len(upd),'no_stock_prior_train_rows':int(len(fit)-len(upd)),'train_signal':c.TRAIN,'train_exit':c.TRAIN_END,'test_signals':list(c.TEST),'same_event_group_exclusions':exclusions,'test_pool_rows':len(test),'score_formula':'same backbone + 0.42*(alpha+sum(observed_Z*beta)); missing Z omitted','unseen_stock':'uniform fallback','uniform_prior':'global parent posterior updated on same mature training ranks','delta':delta,'posterior_observed_dimensions':obs.sum(axis=0).tolist(),'personal_input_observation_by_date':{str(d):{f'z{j:02d}':int(g[f'z{j:02d}_observed'].sum()) for j in range(12)} for d,g in test.groupby('signal_date')},'model_path':str(modelpath),'model_sha256':c.sha(modelpath),'training_rows_sha256':c.sha(OUT/'train_fit_rows.parquet'),'scores_sha256':c.sha(OUT/'oos_scores_before_y.parquet'),'selected_slots_sha256':c.sha(OUT/'selected_slots_before_y.parquet'),'uniform_sha256':c.sha(OUT/'uniform_posterior.json'),'parent_sha256':c.PARENT_SHA,'wall_seconds':time.time()-start,'peak_rss':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'pit_certified':False,'calibration':'UNCALIBRATED_SCORE','test_outcomes_opened':False}
    writej(OUT/'SCORES_LOCK.json',report);print(json.dumps({'stage':'SCORES_LOCKED',**{k:report[k] for k in ['train_known_rows','train_stocks','test_pool_rows','same_event_group_exclusions','model_sha256','scores_sha256','selected_slots_sha256']}},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
