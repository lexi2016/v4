"""Refit same frozen estimators after excluding unknown original-basis stocks.

This reads only the existing derived event/label projection and its observed
session proxy. It does not read, reproject or recompute the source panel.
"""
import json, os
from argparse import Namespace
import pandas as pd
import pipeline

BASE=pipeline.OUT; contract_path=BASE/'EXPERIMENT_CONTRACT_R3.json'; cfg=json.loads(contract_path.read_text())
src=BASE/'full/events_features_labels.parquet';overlay_path=BASE/'full/event_basis_overlay.parquet'
assert pipeline.sha(src)==cfg['input']['source_events_sha256']
assert pipeline.sha(overlay_path)==cfg['input']['source_overlay_sha256']
events=pd.read_parquet(src);overlay=pd.read_parquet(overlay_path)
assert len(events)==len(overlay) and not overlay.duplicated(['ts_code','trade_date']).any()
paired=events[['ts_code','trade_date']].merge(overlay,on=['ts_code','trade_date'],how='left',validate='one_to_one')
assert not paired['source_basis_class'].isna().any()
excluded=events.ts_code.isin(cfg['input']['excluded_retained_history_codes'])
assert excluded.equals(paired.source_basis_class.eq('RETAINED_ORIGINAL_BASIS_ASOF'))
assert int(excluded.sum())==cfg['input']['excluded_event_count']
assert int((excluded&events.y10.ge(0)).sum())==cfg['input']['excluded_known_y10_count']
out=BASE/'r3/full';out.mkdir(parents=True,exist_ok=True)
excluded_details=events.loc[excluded,['ts_code','trade_date','anchor_date','event_group','y10','label10_status']].merge(
    overlay.loc[excluded,['ts_code','trade_date','source_basis_asof','source_basis_identity_status']],
    on=['ts_code','trade_date'],validate='one_to_one')
excluded_details['exclusion_reason']='RETAINED_ORIGINAL_BASIS_IDENTITY_NOT_BOUND'
pipeline.write_parquet_atomic(excluded_details,out/'excluded_events.parquet')
selected=events.loc[~excluded].copy();pipeline.write_parquet_atomic(selected,out/'events_features_labels.parquet')
target=out/'observed_a_sessions.parquet';source=BASE/'full/observed_a_sessions.parquet'
if not target.exists():os.link(source,target)
assert pipeline.sha(source)==pipeline.sha(target)
summary={'scope':'A_HISTORY_EXCLUDING_SEVEN_RETAINED_ORIGINAL_BASIS_STOCKS_NOT_ALL_A',
    'source_event_sha256':pipeline.sha(src),'source_overlay_sha256':pipeline.sha(overlay_path),
    'excluded_symbols':cfg['input']['excluded_retained_history_codes'],'excluded_events':int(excluded.sum()),
    'excluded_known_y10':int((excluded&events.y10.ge(0)).sum()),'selected_events':len(selected),
    'selected_known_y10':int(selected.y10.ge(0).sum()),'selected_unknown_y10':int(selected.y10.lt(0).sum()),
    'selected_events_sha256':pipeline.sha(out/'events_features_labels.parquet'),
    'excluded_events_sha256':pipeline.sha(out/'excluded_events.parquet'),
    'session_sha256':pipeline.sha(target),'session_scope':'SAME_ALL_A_OBSERVED_PANEL_PROXY_UNCERTIFIED',
    'source_panel_reread':False,'feature_or_label_recompute':False}
pipeline.atomic_json(out/'DATA_SUMMARY.json',summary);print(json.dumps(summary,ensure_ascii=False),flush=True)
pipeline.OUT=BASE/'r3';pipeline.CONTRACT_PATH=contract_path;pipeline.CONTRACT=cfg
pipeline.fit(Namespace(canary=False,threads=12))
