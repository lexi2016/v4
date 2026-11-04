"""Materialize and verify one known invalid-prefix stock, reusing the R4 worker."""
import json
import pandas as pd
import pipeline as p
import r4_features as r

symbol='600256.SH';source=pd.read_parquet(p.OUT/'r3/full/events_features_labels.parquet')
ev=source.loc[source.ts_code.eq(symbol),['ts_code','trade_date','anchor_date']+r.EDIT].copy()
result=r.worker((symbol,r.TARGET['target_symbols'][symbol],ev,p.sha(r.__file__)))
assert result['tainted_events']>0 and result['events']>0
dest=p.OUT/'r4/corrections'/f'{symbol}.parquet';z=pd.read_parquet(dest)
assert z.loc[z.source_prefix_tainted,r.SOURCE_FEATURES+p.PERSONAL].isna().all().all()
assert z.loc[z.invalid_anchor_path,r.ANCHOR_FEATURES].isna().all().all()
out={'status':'PASS','case':result,'feature_mask':'PASS','anchor_path_mask':'PASS','source_data_reread':'TARGET_SYMBOL_ONLY','checkpoint_reusable':True}
p.atomic_json(p.OUT/'r4/CANARY.json',out);print(json.dumps(out,ensure_ascii=False))
