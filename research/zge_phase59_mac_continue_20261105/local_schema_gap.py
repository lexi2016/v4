"""Compare frozen feature-order names with V4 panel metadata, not semantics."""
import json
from pathlib import Path
import runtime as r

meta=Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/pullback_model_design_20261104/PANEL_METADATA_SNAPSHOT.json')
panel=json.loads(meta.read_text())['selector'];order=r.MODEL/'feature_order_v3_1.json';features=json.loads(order.read_text());names=set(panel['columns'])
same=[x for x in features if x in names];absent=[x for x in features if x not in names]
result={'status':'METADATA_NAME_COMPARISON_NOT_SEMANTIC_BINDING','local_asof':20261104,'local_generation':'e3ff25234adf18d8f29805a1107b36d61416b7bba3af8f3da9e63f17ee42fe09',
 'feature_order_sha256':r.sha(order),'panel_metadata_sha256':r.sha(meta),'panel_column_count':len(panel['columns']),'required_feature_count':len(features),
 'same_name_only_count':len(same),'same_name_only_not_formula_or_basis_bound':same,'exact_name_absent_count':len(absent),'exact_name_absent':absent,
 'semantically_certified_count':0,'note':'4 shared names are NOT verified equivalence; absent names may have producers/aliases that require exact semantics. No 11/04 87D feature rows generated.',
 'locally_bound_label_inputs':['ts_code','trade_date','open','volume','price_valid derived from full OHLC in R4 cache','observed_a_sessions'],
 'scope':'Local new labels on already-existing <=20261015 cloud feature keys only; no claim of 11/04 feature adaptation','PIT':'CANNOT_CONFIRM'}
(r.OUT/'LOCAL_1104_FEATURE_GAP.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'same_name_only':len(same),'absent_exact_name':len(absent),'semantic_certified':0}))
