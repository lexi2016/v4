"""Fresh-process readback of post-evaluation refit; outputs are unvalidated scores."""
import json,sys
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
import common as c
import train_score as t
import final_refit as f

def main():
    receipt=json.loads((f.DEST/'FINAL_FIT_RECEIPT.json').read_text());t.rt.install_compat();m=t.rt.load(f.DEST/'final_refit_model.pkl',receipt['model_sha256']);u=json.loads((f.DEST/'uniform_posterior.json').read_text());x=pd.read_parquet(f.DEST/'unmatured_target_scores.parquet')
    if len(x):
        with threadpool_limits(limits=1):_,_,_,_,_,p,s,_=t.score_parts(m,x,(u['alpha'],np.asarray(u['beta'])))
        errors={'personal':float(np.max(np.abs(p-x.score_personal))),'uniform':float(np.max(np.abs(s-x.score_uniform)))}
    else:errors={'personal':0.,'uniform':0.}
    if max(errors.values())>1e-11 or c.sha(f.DEST/'unmatured_target_scores.parquet')!=receipt['scores_sha256']:raise ValueError('FINAL_FRESH_PROCESS_MISMATCH')
    out={'status':'PASS','python':sys.executable,'model_sha256':receipt['model_sha256'],'unmatured_scores_sha256':receipt['scores_sha256'],'rows':len(x),'max_abs_error':errors,'validation':'LOAD_PREDICT_PARITY_ONLY; TEST_PERIOD_CONSUMED; NOT NEW OOS'}
    t.writej(f.DEST/'FRESH_PROCESS_PARITY.json',out);print(json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
