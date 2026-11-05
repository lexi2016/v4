"""Fresh-process restricted model load and locked scores/slots readback."""
import json,sys
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
import common as c
import train_score as t

def main():
    a=json.loads((t.OUT/'SCORES_LOCK.json').read_text())
    for path,key in [('oos_continued_model.pkl','model_sha256'),('oos_scores_before_y.parquet','scores_sha256'),('selected_slots_before_y.parquet','selected_slots_sha256'),('uniform_posterior.json','uniform_sha256')]:
        if c.sha(t.OUT/path)!=a[key]:raise ValueError('FROZEN_HASH_MISMATCH:'+path)
    t.rt.install_compat();m=t.rt.load(t.OUT/'oos_continued_model.pkl',a['model_sha256']);old=t.rt.load(c.PARENT,c.PARENT_SHA);x=pd.read_parquet(t.OUT/'oos_scores_before_y.parquet');u=json.loads((t.OUT/'uniform_posterior.json').read_text())
    with threadpool_limits(limits=1):
        base,z,obs,alpha,beta,ps,us,_=t.score_parts(m,x,(u['alpha'],np.asarray(u['beta'])));oldp=old.predict(x)
    errs={'personal':float(np.max(np.abs(ps-x.score_personal))),'uniform':float(np.max(np.abs(us-x.score_uniform))),'parent':float(np.max(np.abs(oldp-x.score_parent_original)))}
    if max(errs.values())>1e-11:raise ValueError('FRESH_PROCESS_SCORE_MISMATCH')
    slots=pd.read_parquet(t.OUT/'selected_slots_before_y.parquet')
    for (date,arm),g in slots.groupby(['signal_date','arm']):
        expect=x[x.signal_date.eq(date)].sort_values(['score_'+arm,'ts_code'],ascending=[False,True],kind='stable').head(10).ts_code.tolist()
        if g.sort_values('rank').ts_code.tolist()!=expect:raise ValueError('LOCKED_TOP_SELECTION_MISMATCH')
    result={'status':'PASS','fresh_process_python':sys.executable,'max_abs_score_error':errs,'model_sha256':a['model_sha256'],'scores_sha256':a['scores_sha256'],'selected_slots_sha256':a['selected_slots_sha256'],'score_rows':len(x),'slot_rows':len(slots),'test_y_opened':False}
    t.writej(t.OUT/'FRESH_PROCESS_PARITY.json',result);print(json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
