"""Annotate retained historical basis without altering trained samples or models."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from pipeline import OUT, sha, atomic_json, write_parquet_atomic

snapshot=OUT.parent/'PANEL_METADATA_SNAPSHOT.json';q=json.loads(json.loads(snapshot.read_text())['selector']['metadata']['a_share_qfq_contract_v1'])
mapping=q['retained_history_asof'];codes=set(q['retained_history_codes'])
mixed=json.loads((OUT/'mixed_cache/MIXED_INPUT_REPORT.json').read_text())
assert codes==set(mapping)==set(mixed['symbols'])
ev=pd.read_parquet(OUT/'full/events_features_labels.parquet');retained=ev.ts_code.isin(codes)
overlay=ev[['ts_code','trade_date']].copy()
overlay['source_basis_class']=np.where(retained,'RETAINED_ORIGINAL_BASIS_ASOF','GENERATION_DECLARED_A_MARKET_BASIS')
overlay['source_basis_asof']=ev.ts_code.map(mapping).fillna(20261104).astype('int64')
overlay['source_basis_identity_status']=np.where(retained,'CANNOT_CONFIRM_ORIGINAL_BASIS_IDENTITY','PRODUCER_DECLARED_NOT_PIT_CERTIFIED')
path=OUT/'full/event_basis_overlay.parquet';write_parquet_atomic(overlay,path)
pred=pd.read_parquet(OUT/'full/predictions.parquet');fold_counts=pred.loc[pred.ts_code.isin(codes)].groupby('fold').size().to_dict()
valid=0;invalid=0
for p in (OUT/'full/parts').glob('prices_*.parquet'):
    df=pd.read_parquet(p,columns=['price_valid']);valid+=int(df.price_valid.sum());invalid+=int((~df.price_valid).sum())
stats={}
for sym in sorted(codes):
    e=ev.loc[ev.ts_code.eq(sym)];stats[sym]={'original_asof':mapping[sym],'source_rows':mixed['symbols'][sym]['rows'],
        'event_count':len(e),'known_R10':int(e.y10.ge(0).sum()),'basis_identity':'CANNOT_CONFIRM_ORIGINAL_BASIS_IDENTITY'}
report={'scope':'PROVENANCE_ANNOTATION_ONLY_FITTED_SAMPLES_UNCHANGED','retention_semantics':q['history_retention_semantics'],
    'retained_source_rows':sum(x['rows'] for x in mixed['symbols'].values()),'retained_symbols':stats,'retained_event_count':int(retained.sum()),
    'retained_known_R10':int((retained&ev.y10.ge(0)).sum()),'retained_test_rows_by_fold':{str(k):int(v) for k,v in fold_counts.items()},
    'signal_period_valid_price_rows':valid,'signal_period_invalid_price_rows':invalid,
    'other_rows_basis':'PRODUCER_DECLARED_QFQ_ASOF_20261104_QFQ_EVENT_VOLUME_RAW_TURNOVER_NOT_PIT_CERTIFIED',
    'retained_basis':'RETAINED_ORIGINAL_BASIS_ASOF_PER_SYMBOL_EXACT_ORIGINAL_IDENTITY_CANNOT_CONFIRM',
    'overlay_path':str(path),'overlay_sha256':sha(path),'overlay_rows':len(overlay),
    'join_key':['ts_code','trade_date'],'training_and_metrics_rerun':False,
    'source_snapshot_path':str(snapshot),'source_snapshot_sha256':sha(snapshot)}
atomic_json(OUT/'full/PROVENANCE_REPORT.json',report);print(json.dumps(report,ensure_ascii=False))
