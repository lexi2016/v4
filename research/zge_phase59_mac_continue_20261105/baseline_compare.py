"""Compare frozen package reference and local compatibility predictions."""
import json
import numpy as np
import pandas as pd
import runtime as r

ref=r.OUT/'baseline_reference.parquet';new=r.OUT/'baseline_compat.parquet'
a=pd.read_parquet(ref);b=pd.read_parquet(new)
assert list(a.columns)==list(b.columns) and len(a)==len(b)==2500
pd.testing.assert_frame_equal(a[['sample_row_id','ts_code','signal_date']],b[['sample_row_id','ts_code','signal_date']],check_exact=True)
cols=[x for x in a.columns if x not in ('sample_row_id','ts_code','signal_date')]
delta={c:float(np.max(np.abs(a[c].to_numpy()-b[c].to_numpy()))) for c in cols}
assert all(x<=1e-12 for x in delta.values())
receipt={'status':'PASS_REFERENCE_VS_COMPAT_SAME_SAMPLE','max_abs_difference':delta,'rows':len(a),'sample_only':True,
 'reference_path':str(ref),'reference_sha256':r.sha(ref),'compat_path':str(new),'compat_sha256':r.sha(new),
 'same_output_bytes':r.sha(ref)==r.sha(new),'model_fit':'NOT_RUN'}
(r.OUT/'BASELINE_PARITY.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps(receipt,ensure_ascii=False))
